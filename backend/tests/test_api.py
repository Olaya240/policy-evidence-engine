"""API behavior with an isolated, disposable prototype-local SQLite file."""
import gc
import asyncio
from copy import deepcopy
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

import pytest
import httpx
from fastapi.exceptions import ResponseValidationError

from app import main as main_module, store
from app.engine import AssessmentEngine, ProviderError
from app.main import app
from app.mock_provider import MockProvider
from app.models import (HYPOTHESES, INVESTIGATION_PRESET_HYPOTHESES,
                        INVESTIGATION_PRESET_QUESTIONS, InvestigationPreset,
                        Record)


class InProcessClient:
    """Synchronous test helper over HTTPX ASGITransport, without Starlette TestClient."""

    def __init__(self, application):
        self.app = application

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def request(self, method, path, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)


def _remove_sqlite_files(db_path: Path) -> None:
    gc.collect()
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = Path(str(db_path) + suffix)
        for _ in range(10):
            if not path.exists():
                break
            try:
                path.unlink()
                break
            except PermissionError:
                gc.collect()
                time.sleep(0.05)


@pytest.fixture
def client(monkeypatch):
    db_path = store.DATA_DIR / f".test-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    try:
        store.initialize_database()
        with InProcessClient(app) as test_client:
            test_client.app.state.test_database_path = db_path
            yield test_client
    finally:
        _remove_sqlite_files(db_path)


@pytest.fixture
def mocked_read_client(monkeypatch):
    """Exercise API response validation without opening or creating a database."""
    monkeypatch.setattr(main_module, "require_database", lambda: None)
    with InProcessClient(app) as test_client:
        yield test_client


_MISSING_REVIEW_STATE = object()


def _investigation_with_review_state(review_state=_MISSING_REVIEW_STATE):
    evidence = {
        "source_record_id": "LEGACY-API",
        "timestamp": "2026-10-31T10:00:00+00:00",
        "quote": "The checklist was unavailable.",
        "stance": "SUPPORTS",
        "rationale": "stored legacy evidence",
        "stale": False,
        "department": "Front Office",
        "source_group": "LEGACY-API",
        "disputed": False,
    }
    if review_state is not _MISSING_REVIEW_STATE:
        evidence["review_state"] = review_state
    return {
        "id": "investigation-legacy",
        "question": "Review this stored synthetic investigation.",
        "created_at": "2026-10-31T10:00:00+00:00",
        "version": 7,
        "claims": [{
            "id": "CHECKLIST_UNAVAILABLE",
            "hypothesis_id": "CHECKLIST_UNAVAILABLE",
            "status": "SUPPORTED",
            "confidence": 0.68,
            "uncertainty": "Previously stored claim status.",
            "summary": "Previously stored claim summary.",
            "evidence": [evidence],
            "conflicts": [],
            "missing_evidence": [],
            "dependencies": ["LEGACY-API"],
            "version": 3,
        }],
    }


@pytest.mark.parametrize(
    "stored_state,expected_state",
    [
        (_MISSING_REVIEW_STATE, "UNVERIFIED"),
        ("ACCEPTED", "ACCEPTED"),
        ("UNVERIFIED", "UNVERIFIED"),
    ],
    ids=["missing-state-normalized", "explicit-accepted-preserved", "explicit-unverified-preserved"],
)
def test_get_investigation_normalizes_only_missing_review_state_without_mutating_store_result(
    mocked_read_client, monkeypatch, stored_state, expected_state,
):
    original = _investigation_with_review_state(stored_state)
    original_before = deepcopy(original)
    monkeypatch.setattr(store, "get_investigation", lambda _investigation_id: original)

    response = mocked_read_client.get("/api/investigations/investigation-legacy")

    assert response.status_code == 200
    returned = response.json()
    evidence = returned["claims"][0]["evidence"][0]
    assert evidence["review_state"] == expected_state
    assert returned["preset_id"] is None
    assert returned["claims"][0]["status"] == "SUPPORTED"
    assert returned["claims"][0]["explanation_trace"] is None
    assert original == original_before


def test_legacy_history_snapshots_are_marked_trace_unavailable_without_mutation(
    mocked_read_client, monkeypatch,
):
    claim = _investigation_with_review_state()["claims"][0]
    original = [{
        "version": 2,
        "created_at": "2026-10-31T10:00:00+00:00",
        "event": "CHALLENGE",
        "before": {"CHECKLIST_UNAVAILABLE": claim},
        "after": {"CHECKLIST_UNAVAILABLE": claim},
        "recomputed_claim_ids": ["CHECKLIST_UNAVAILABLE"],
    }]
    original_before = deepcopy(original)
    monkeypatch.setattr(store, "get_history", lambda _investigation_id: original)

    response = mocked_read_client.get("/api/investigations/investigation-legacy/history")

    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["before"]["CHECKLIST_UNAVAILABLE"]["explanation_trace"] is None
    assert entry["after"]["CHECKLIST_UNAVAILABLE"]["explanation_trace"] is None
    assert original == original_before


@pytest.mark.parametrize("stored_preset_id", [None, "property_system"])
def test_get_investigation_derives_preset_from_question_and_claim_not_stored_identifier(
    mocked_read_client, monkeypatch, stored_preset_id,
):
    preset_id = InvestigationPreset.CHECKLIST_ACCESS
    expected_hypothesis = INVESTIGATION_PRESET_HYPOTHESES[preset_id]
    original = _investigation_with_review_state()
    original.update(
        question=INVESTIGATION_PRESET_QUESTIONS[preset_id],
        preset_id=stored_preset_id,
        claims=[{
            **original["claims"][0],
            "id": expected_hypothesis,
            "hypothesis_id": expected_hypothesis,
        }],
    )
    monkeypatch.setattr(store, "get_investigation", lambda _investigation_id: original)

    response = mocked_read_client.get("/api/investigations/investigation-legacy")

    assert response.status_code == 200
    assert response.json()["preset_id"] == preset_id.value
    assert original["preset_id"] == stored_preset_id


def test_get_investigation_does_not_infer_preset_from_canonical_question_with_mismatched_claim(
    mocked_read_client, monkeypatch,
):
    preset_id = InvestigationPreset.CHECKLIST_ACCESS
    original = _investigation_with_review_state()
    original["question"] = INVESTIGATION_PRESET_QUESTIONS[preset_id]
    original["claims"][0]["id"] = "TRAINING_GAP"
    original["claims"][0]["hypothesis_id"] = "TRAINING_GAP"
    monkeypatch.setattr(store, "get_investigation", lambda _investigation_id: original)

    response = mocked_read_client.get("/api/investigations/investigation-legacy")

    assert response.status_code == 200
    assert response.json()["preset_id"] is None
    assert response.json()["claims"][0]["hypothesis_id"] == "TRAINING_GAP"


def test_get_investigation_invalid_review_state_is_rejected_not_normalized(
    mocked_read_client, monkeypatch,
):
    original = _investigation_with_review_state("INVALID")
    original_before = deepcopy(original)
    monkeypatch.setattr(store, "get_investigation", lambda _investigation_id: original)

    with pytest.raises(ResponseValidationError):
        mocked_read_client.get("/api/investigations/investigation-legacy")

    assert original == original_before


def test_create_investigation_response_preserves_engine_review_states_without_database(
    mocked_read_client, monkeypatch,
):
    source = Record(
        id="NEW-API",
        timestamp="2026-10-31T10:00:00+00:00",
        department="Front Office",
        text="The checklist was unavailable during handover. A desk lamp was replaced before dinner.",
        tags=[],
        restricted=False,
    )
    proposals = [
        {
            "source_record_id": source.id,
            "quote": "The checklist was unavailable during handover.",
            "stance": "SUPPORTS",
            "rationale": "matching phrase cue",
        },
        {
            "source_record_id": source.id,
            "quote": "A desk lamp was replaced before dinner.",
            "stance": "SUPPORTS",
            "rationale": "no matching phrase cue",
        },
    ]
    provider = MockProvider(assessment_overrides={
        "CHECKLIST_UNAVAILABLE": proposals,
        **{hypothesis.id: [] for hypothesis in HYPOTHESES
           if hypothesis.id != "CHECKLIST_UNAVAILABLE"},
    })
    monkeypatch.setattr(main_module, "engine", AssessmentEngine(provider))
    monkeypatch.setattr(store, "list_records_with_report", lambda **_: ([source], ()))
    monkeypatch.setattr(
        store,
        "create_investigation",
        lambda question, claims: {
            "id": "new-investigation",
            "question": question,
            "created_at": "2026-10-31T10:00:00+00:00",
            "version": 1,
            "claims": claims,
        },
    )

    response = mocked_read_client.post(
        "/api/investigations",
        json={"question": "Review these synthetic handover evidence cues."},
    )

    assert response.status_code == 201
    claim = next(
        item for item in response.json()["claims"]
        if item["id"] == "CHECKLIST_UNAVAILABLE"
    )
    assert [item["review_state"] for item in claim["evidence"]] == [
        "ACCEPTED", "UNVERIFIED",
    ]


@pytest.mark.parametrize("preset_id", list(InvestigationPreset))
def test_selected_preset_assesses_only_its_mapped_hypothesis_without_database(
    mocked_read_client, monkeypatch, preset_id,
):
    from app.mock_provider import SEED_RECORDS

    question = INVESTIGATION_PRESET_QUESTIONS[preset_id]
    hypothesis_id = INVESTIGATION_PRESET_HYPOTHESES[preset_id]
    provider = MockProvider()
    monkeypatch.setattr(main_module, "engine", AssessmentEngine(provider))
    monkeypatch.setattr(store, "list_records_with_report", lambda **_: (SEED_RECORDS, ()))
    persisted = {}

    def capture_create(selected_question, claims):
        persisted["question"] = selected_question
        persisted["claims"] = claims
        return {
            "id": "preset-investigation",
            "question": selected_question,
            "created_at": "2026-10-31T10:00:00+00:00",
            "version": 1,
            "claims": claims,
        }

    monkeypatch.setattr(store, "create_investigation", capture_create)
    response = mocked_read_client.post(
        "/api/investigations",
        json={"question": question, "preset_id": preset_id.value},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["question"] == question
    assert [claim["hypothesis_id"] for claim in body["claims"]] == [hypothesis_id]
    assert persisted["question"] == question
    assert [claim["id"] for claim in persisted["claims"]] == [hypothesis_id]
    assert provider.assessment_history == (hypothesis_id,)


@pytest.mark.parametrize(
    "request_body",
    [
        {"question": "Did checklist availability contribute to missing handover information?",
         "preset_id": "CLIENT_DEFINED_HYPOTHESIS"},
        {"question": "A mismatched question for this preset.",
         "preset_id": InvestigationPreset.CHECKLIST_ACCESS.value},
        {"question": "Did checklist availability contribute to missing handover information?",
         "hypothesis_id": "CLIENT_DEFINED_HYPOTHESIS"},
    ],
    ids=["unknown-preset-rejected", "question-preset-mismatch-rejected", "client-hypothesis-rejected"],
)
def test_selected_preset_validation_rejects_unknown_or_inconsistent_selection(
    mocked_read_client, monkeypatch, request_body,
):
    accessed_records = []
    monkeypatch.setattr(store, "list_records_with_report", lambda **_: (accessed_records.append(True) or [], ()))
    monkeypatch.setattr(store, "create_investigation", lambda *_args: pytest.fail("must not persist invalid selection"))

    response = mocked_read_client.post("/api/investigations", json=request_body)

    assert response.status_code == 422
    assert accessed_records == []


@pytest.mark.parametrize(
    "preset_id,source_record_id,quote",
    [
        (InvestigationPreset.HANDOVER_OMISSIONS, "OPS-107", "shift had enough time"),
        (InvestigationPreset.CHECKLIST_ACCESS, "OPS-101", "Night checklist binder was missing"),
        (InvestigationPreset.DESK_COVERAGE, "OPS-105", "Two agents covered the desk"),
        (InvestigationPreset.PROPERTY_SYSTEM, "OPS-106", "property system timed out"),
    ],
    ids=["handover-omissions", "checklist-access", "desk-coverage", "property-system"],
)
def test_each_preset_identity_survives_challenge_retrieval_and_history(
    client, monkeypatch, preset_id, source_record_id, quote,
):
    question = INVESTIGATION_PRESET_QUESTIONS[preset_id]
    hypothesis_id = INVESTIGATION_PRESET_HYPOTHESES[preset_id]
    provider = MockProvider()
    monkeypatch.setattr(main_module, "engine", AssessmentEngine(provider))

    created = client.post(
        "/api/investigations",
        json={"question": question, "preset_id": preset_id.value},
    )
    assert created.status_code == 201, created.text
    created_body = created.json()
    assert created_body["question"] == question
    assert created_body["preset_id"] == preset_id.value
    assert [claim["hypothesis_id"] for claim in created_body["claims"]] == [hypothesis_id]
    initial_trace = created_body["claims"][0]["explanation_trace"]
    assert initial_trace["trace_schema_version"] == "1.0"
    assert initial_trace["confidence_kind"] == "SIGNED_EVIDENCE_MARGIN_NOT_CALIBRATED_PROBABILITY"
    assert provider.assessment_history == (hypothesis_id,)

    challenge = client.post(
        f"/api/investigations/{created_body['id']}/claims/{hypothesis_id}/challenge",
        json={
            "reason": "Please review the selected synthetic source wording.",
            "source_record_id": source_record_id,
            "quote": quote,
        },
    )
    assert challenge.status_code == 200, challenge.text
    assert challenge.json()["recomputed_claim_ids"] == [hypothesis_id]
    assert set(challenge.json()["before"]) == {hypothesis_id}
    assert set(challenge.json()["after"]) == {hypothesis_id}
    assert challenge.json()["after"][hypothesis_id]["version"] == 2
    assert challenge.json()["before"][hypothesis_id]["explanation_trace"] == initial_trace
    assert challenge.json()["after"][hypothesis_id]["explanation_trace"]["trace_schema_version"] == "1.0"
    assert challenge.json()["after"][hypothesis_id]["explanation_trace"] != initial_trace
    assert any(
        item["source_record_id"] == source_record_id and item["disputed"]
        for item in challenge.json()["after"][hypothesis_id]["evidence"]
    )

    retrieved = client.get(f"/api/investigations/{created_body['id']}")
    assert retrieved.status_code == 200
    retrieved_body = retrieved.json()
    assert retrieved_body["question"] == question
    assert retrieved_body["preset_id"] == preset_id.value
    assert retrieved_body["claims"][0]["explanation_trace"] == challenge.json()["after"][hypothesis_id]["explanation_trace"]
    assert [(claim["id"], claim["hypothesis_id"]) for claim in retrieved_body["claims"]] == [
        (hypothesis_id, hypothesis_id),
    ]
    history = client.get(f"/api/investigations/{created_body['id']}/history")
    assert history.status_code == 200
    assert history.json()[1]["recomputed_claim_ids"] == [hypothesis_id]
    assert list(history.json()[1]["before"]) == [hypothesis_id]
    assert list(history.json()[1]["after"]) == [hypothesis_id]
    assert history.json()[1]["before"][hypothesis_id]["explanation_trace"] == initial_trace
    assert history.json()[1]["after"][hypothesis_id]["explanation_trace"] == retrieved_body["claims"][0]["explanation_trace"]


def test_legacy_question_only_investigation_without_canonical_question_has_no_preset_id(client):
    question = "Review recurring handover omissions in this synthetic week."
    created = client.post("/api/investigations", json={"question": question})

    assert created.status_code == 201, created.text
    created_body = created.json()
    assert created_body["preset_id"] is None
    assert len(created_body["claims"]) == len(HYPOTHESES)

    retrieved = client.get(f"/api/investigations/{created_body['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["preset_id"] is None


def test_legacy_question_only_canonical_question_does_not_infer_preset_from_question_alone(client):
    question = INVESTIGATION_PRESET_QUESTIONS[InvestigationPreset.CHECKLIST_ACCESS]
    created = client.post("/api/investigations", json={"question": question})

    assert created.status_code == 201, created.text
    created_body = created.json()
    assert len(created_body["claims"]) == len(HYPOTHESES)
    assert created_body["preset_id"] is None

    retrieved = client.get(f"/api/investigations/{created_body['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["preset_id"] is None


def test_health_reports_synthetic_and_not_authenticated(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["synthetic_data_only"] is True
    assert response.json()["authentication"] is False


def test_records_list_is_synthetic_and_hides_restricted_canary(client):
    response = client.get("/api/records")
    assert response.status_code == 200
    body = response.text
    assert "OPS-101" in body
    assert "CANARY-RESTRICTED-001" not in body
    assert "RESTRICTED_CANARY_DO_NOT_DISCLOSE" not in body


def test_canary_is_absent_from_all_investigation_and_challenge_responses(client):
    canary = "RESTRICTED_CANARY_DO_NOT_DISCLOSE_8f2b1d"
    create = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."})
    assert create.status_code == 201
    assert canary not in create.text
    investigation_id = create.json()["id"]

    current = client.get(f"/api/investigations/{investigation_id}")
    assert current.status_code == 200 and canary not in current.text
    # There is no record-by-ID endpoint; challenge lookup must not reveal a restricted record.
    denied = client.post(f"/api/investigations/{investigation_id}/claims/CHECKLIST_UNAVAILABLE/challenge", json={"reason": "Review this restricted record.", "source_record_id": "CANARY-RESTRICTED-001", "quote": canary})
    assert denied.status_code == 404 and canary not in denied.text and "CANARY-RESTRICTED-001" not in denied.text

    challenge = client.post(f"/api/investigations/{investigation_id}/claims/CHECKLIST_UNAVAILABLE/challenge", json={"reason": "  Please review whether the binder record is reliable.  ", "source_record_id": "OPS-101", "quote": "binder was missing"})
    assert challenge.status_code == 200 and canary not in challenge.text
    assert challenge.json()["reason"] == "Please review whether the binder record is reliable."
    history = client.get(f"/api/investigations/{investigation_id}/history")
    assert history.status_code == 200 and canary not in history.text
    assert client.get("/api/health").status_code == 200


def test_uninitialized_database_returns_controlled_error_without_creating_file(monkeypatch):
    db_path = store.DATA_DIR / f".test-uninitialized-{uuid4().hex}.sqlite3"
    assert not db_path.exists()
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    try:
        with InProcessClient(app) as test_client:
            response = test_client.get("/api/records")
        assert response.status_code == 503
        assert response.json() == {"detail": "Local prototype database is not initialized. Run `PYTHONPATH=backend python -m app.store init` from the repository root (see README.md)."}
        assert not db_path.exists()
    finally:
        _remove_sqlite_files(db_path)


def test_corrupt_database_returns_sanitized_controlled_error(client):
    db_path = client.app.state.test_database_path
    db_path.write_bytes(b"not a sqlite database")
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "degraded" and health.json()["database_available"] is False
    response = client.get("/api/records")
    assert response.status_code == 503
    assert response.json() == {"detail": "Local prototype database is unavailable."}
    assert str(db_path) not in response.text and "sqlite" not in response.text.lower()


def test_write_failure_is_sanitized_and_transaction_rolls_back(client):
    db_path = client.app.state.test_database_path
    db = sqlite3.connect(db_path)
    try:
        db.execute("CREATE TRIGGER reject_test_investigation BEFORE INSERT ON investigations BEGIN SELECT RAISE(ABORT, 'synthetic trigger failure'); END;")
        db.commit()
    finally:
        db.close()
    response = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."})
    assert response.status_code == 503
    assert response.json() == {"detail": "Local prototype database is unavailable."}
    assert str(db_path) not in response.text and "trigger" not in response.text.lower() and "insert" not in response.text.lower()
    db = sqlite3.connect(db_path)
    try:
        assert db.execute("SELECT count(*) FROM investigations").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM history").fetchone()[0] == 0
    finally:
        db.close()


def test_investigation_create_and_retrieve_has_five_claims(client):
    created = client.post("/api/investigations", json={"question": "Why do handover notes keep missing open guest requests?"})
    assert created.status_code == 201
    investigation_id = created.json()["id"]
    assert len(created.json()["claims"]) == 5
    fetched = client.get(f"/api/investigations/{investigation_id}")
    assert fetched.status_code == 200
    assert fetched.json()["version"] == 1


def test_provider_failure_does_not_persist_or_leak_provider_error(client, monkeypatch):
    marker = "RESTRICTED_CANARY_DO_NOT_DISCLOSE_8f2b1d"
    from app.mock_provider import MockProvider
    provider = MockProvider(failure_message=marker)
    monkeypatch.setattr(main_module, "engine", AssessmentEngine(provider))
    response = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."})
    assert response.status_code == 503
    assert response.json() == {"detail": "Assessment provider is unavailable or returned invalid output."}
    assert marker not in response.text
    db_path = client.app.state.test_database_path
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT count(*) FROM investigations").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM history").fetchone()[0] == 0


def test_malformed_provider_response_during_challenge_leaves_snapshot_and_history_unchanged(client, monkeypatch):
    from app.mock_provider import SEED_RECORDS

    source = next(record for record in SEED_RECORDS if record.id == "OPS-101")

    from app.mock_provider import MockProvider
    provider = MockProvider(assessment_sequences={
        "CHECKLIST_UNAVAILABLE": [
            [{"source_record_id": source.id, "quote": "binder", "stance": "SUPPORTS", "rationale": "synthetic proposal"}],
            {"unexpected": "not a proposal list"},
        ],
        **{hypothesis.id: [[]] for hypothesis in HYPOTHESES if hypothesis.id != "CHECKLIST_UNAVAILABLE"},
    })
    monkeypatch.setattr(main_module, "engine", AssessmentEngine(provider))
    created_response = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."})
    assert created_response.status_code == 201
    investigation_id = created_response.json()["id"]
    before = client.get(f"/api/investigations/{investigation_id}").json()
    history_before = client.get(f"/api/investigations/{investigation_id}/history").json()

    response = client.post(
        f"/api/investigations/{investigation_id}/claims/CHECKLIST_UNAVAILABLE/challenge",
        json={"reason": "Review the complete synthetic source wording.", "source_record_id": source.id, "quote": "Night checklist binder was missing"},
    )
    assert provider.assessment_history.count("CHECKLIST_UNAVAILABLE") == 2
    assert response.status_code == 503
    assert response.json() == {"detail": "Assessment provider is unavailable or returned invalid output."}
    assert client.get(f"/api/investigations/{investigation_id}").json() == before
    assert client.get(f"/api/investigations/{investigation_id}/history").json() == history_before


def test_malformed_provider_output_preserves_claims_revision_and_history(client, monkeypatch):
    from app.mock_provider import SEED_RECORDS

    source = next(record for record in SEED_RECORDS if record.id == "OPS-101")

    from app.mock_provider import MockProvider
    provider = MockProvider(assessment_sequences={
        "CHECKLIST_UNAVAILABLE": [
            [{"source_record_id": source.id, "quote": "binder", "stance": "SUPPORTS", "rationale": "synthetic proposal"}],
            {"unexpected": "not a proposal list"},
        ],
        **{hypothesis.id: [[]] for hypothesis in HYPOTHESES if hypothesis.id != "CHECKLIST_UNAVAILABLE"},
    })
    monkeypatch.setattr(main_module, "engine", AssessmentEngine(provider))

    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."})
    assert created.status_code == 201
    investigation_id = created.json()["id"]
    before = client.get(f"/api/investigations/{investigation_id}").json()
    history_before = client.get(f"/api/investigations/{investigation_id}/history").json()

    response = client.post(
        f"/api/investigations/{investigation_id}/claims/CHECKLIST_UNAVAILABLE/challenge",
        json={"reason": "Review the complete synthetic source wording.", "source_record_id": source.id, "quote": "Night checklist binder was missing from the desk"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Assessment provider is unavailable or returned invalid output."}
    assert provider.assessment_history.count("CHECKLIST_UNAVAILABLE") == 2
    assert client.get(f"/api/investigations/{investigation_id}").json() == before
    assert client.get(f"/api/investigations/{investigation_id}/history").json() == history_before


@pytest.mark.parametrize("provider_code", ["provider_failure", "malformed_output"])
def test_challenge_recompute_failure_rolls_back_all_persisted_versions(client, monkeypatch, provider_code):
    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."}).json()
    investigation_id = created["id"]
    before = client.get(f"/api/investigations/{investigation_id}").json()
    history_before = client.get(f"/api/investigations/{investigation_id}/history").json()

    class FailingChallengeEngine:
        def challenge(self, claim, records, record_id, quote):
            raise ProviderError(provider_code)

    monkeypatch.setattr(main_module, "engine", FailingChallengeEngine())
    response = client.post(
        f"/api/investigations/{investigation_id}/claims/CHECKLIST_UNAVAILABLE/challenge",
        json={"reason": "Review this source safely.", "source_record_id": "OPS-101", "quote": "binder was missing"},
    )
    assert response.status_code == 503
    assert "private details" not in response.text
    assert client.get(f"/api/investigations/{investigation_id}").json() == before
    assert client.get(f"/api/investigations/{investigation_id}/history").json() == history_before


def test_challenge_recompute_runs_outside_write_transaction_and_rejects_stale_revision(client, monkeypatch):
    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."}).json()
    investigation_id = created["id"]
    real_engine = AssessmentEngine()
    observed = {}

    class RacingEngine:
        winner_committed = False

        def challenge(self, claim, records, record_id, quote):
            # This write lock would fail to acquire if the route still called
            # provider/recompute code from inside apply_challenge's transaction.
            with store.connect(write=True):
                pass
            stale_result = real_engine.challenge(claim, records, record_id, quote)
            if not self.winner_committed:
                self.winner_committed = True
                snapshot = store.get_challenge_snapshot(investigation_id, "CHECKLIST_UNAVAILABLE", record_id)
                winning_results = {
                    cid: real_engine.challenge(item, records, record_id, quote)
                    for cid, item in snapshot["claims"].items()
                }
                observed["winner"] = store.apply_challenge(
                    investigation_id, "CHECKLIST_UNAVAILABLE", "Concurrent winning challenge.",
                    record_id, quote, expected_revision=snapshot["revision"],
                    expected_claims=snapshot["claims"], revised_claims=winning_results,
                )
            return stale_result

    monkeypatch.setattr(main_module, "engine", RacingEngine())
    response = client.post(
        f"/api/investigations/{investigation_id}/claims/CHECKLIST_UNAVAILABLE/challenge",
        json={"reason": "Review this source safely.", "source_record_id": "OPS-101", "quote": "binder was missing"},
    )
    assert response.status_code == 409
    assert "reload and retry" in response.json()["detail"]
    assert observed["winner"]["version"] == 2
    current = client.get(f"/api/investigations/{investigation_id}").json()
    history = client.get(f"/api/investigations/{investigation_id}/history").json()
    assert current["version"] == 2
    current_by_id = {claim["id"]: claim for claim in current["claims"]}
    assert {cid: current_by_id[cid] for cid in observed["winner"]["after"]} == observed["winner"]["after"]
    initial_by_id = {claim["id"]: claim for claim in created["claims"]}
    assert all(current_by_id[cid] == claim for cid, claim in initial_by_id.items() if cid not in observed["winner"]["after"])
    assert [entry["version"] for entry in history] == [1, 2]
    assert history[1]["reason"] == "Concurrent winning challenge."
    assert history[1]["after"] == observed["winner"]["after"]


def test_challenge_database_write_failure_rolls_back_claims_revision_and_history(client):
    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."}).json()
    investigation_id = created["id"]
    before = client.get(f"/api/investigations/{investigation_id}").json()
    history_before = client.get(f"/api/investigations/{investigation_id}/history").json()
    db_path = client.app.state.test_database_path
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TRIGGER reject_challenge_history BEFORE INSERT ON history
            WHEN NEW.version=2 BEGIN SELECT RAISE(ABORT, 'simulated disposable-db write failure'); END""")

    response = client.post(
        f"/api/investigations/{investigation_id}/claims/CHECKLIST_UNAVAILABLE/challenge",
        json={"reason": "Review this source safely.", "source_record_id": "OPS-101", "quote": "binder was missing"},
    )
    assert response.status_code == 503
    assert "simulated disposable-db write failure" not in response.text
    assert client.get(f"/api/investigations/{investigation_id}").json() == before
    assert client.get(f"/api/investigations/{investigation_id}/history").json() == history_before


@pytest.mark.parametrize("question", ["", "short", "       ", "x" * 501])
def test_invalid_investigation_questions_return_validation_error(client, question):
    assert client.post("/api/investigations", json={"question": question}).status_code == 422


def test_missing_and_malformed_investigation_bodies_return_validation_error(client):
    assert client.post("/api/investigations", json={}).status_code == 422
    response = client.post("/api/investigations", content="{malformed", headers={"Content-Type": "application/json"})
    assert response.status_code == 422


def test_unknown_investigation_and_source_ids_are_rejected(client):
    assert client.get("/api/investigations/not-a-uuid").status_code == 404
    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."}).json()
    response = client.post(f"/api/investigations/{created['id']}/claims/CHECKLIST_UNAVAILABLE/challenge", json={"reason": "Check a source that should not be present.", "source_record_id": "NO-SUCH-ID", "quote": "some text"})
    assert response.status_code == 404


def test_invalid_challenge_quote_returns_422(client):
    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."}).json()
    response = client.post(f"/api/investigations/{created['id']}/claims/CHECKLIST_UNAVAILABLE/challenge", json={"reason": "This is not the source wording.", "source_record_id": "OPS-101", "quote": "fabricated source wording"})
    assert response.status_code == 422


@pytest.mark.parametrize("reason", ["", "        ", " \t \n "])
def test_blank_challenge_reasons_return_422(client, reason):
    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."}).json()
    response = client.post(f"/api/investigations/{created['id']}/claims/CHECKLIST_UNAVAILABLE/challenge", json={"reason": reason, "source_record_id": "OPS-101", "quote": "binder was missing"})
    assert response.status_code == 422


def test_challenge_appends_history_and_keeps_unaffected_claim_versions(client):
    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."}).json()
    inv_id = created["id"]
    before = {claim["id"]: claim for claim in created["claims"]}
    target_claim = "CHECKLIST_UNAVAILABLE"
    source_record_id = "OPS-101"
    expected_affected = {cid for cid, claim in before.items() if source_record_id in {item["source_record_id"] for item in claim["evidence"]}}
    expected_affected.add(target_claim)
    assert expected_affected == {"CHECKLIST_UNAVAILABLE"}  # OPS-101 is only assessed against this hypothesis in MockProvider.

    result = client.post(f"/api/investigations/{inv_id}/claims/{target_claim}/challenge", json={"reason": "  Please review whether the binder record is reliable.  ", "source_record_id": source_record_id, "quote": "binder was missing"})
    assert result.status_code == 200, result.text
    assert result.json()["version"] == 2
    assert set(result.json()["recomputed_claim_ids"]) == expected_affected
    current = client.get(f"/api/investigations/{inv_id}").json()
    current_by_id = {claim["id"]: claim for claim in current["claims"]}
    assert current_by_id[target_claim]["version"] == 2
    assert current_by_id["CHECKLIST_UNAVAILABLE"]["status"] == "PARTIAL"
    assert current_by_id["CHECKLIST_UNAVAILABLE"]["evidence"]
    for claim_id in before:
        expected_version = before[claim_id]["version"] + (1 if claim_id in expected_affected else 0)
        assert current_by_id[claim_id]["version"] == expected_version
        if claim_id not in expected_affected:
            assert current_by_id[claim_id] == before[claim_id]
    history = client.get(f"/api/investigations/{inv_id}/history").json()
    assert [entry["version"] for entry in history] == [1, 2]
    assert history[1]["reason"] == "Please review whether the binder record is reliable."
    assert set(history[1]["recomputed_claim_ids"]) == expected_affected
    assert set(history[1]["before"]) == expected_affected
    assert set(history[1]["after"]) == expected_affected
    for claim_id in expected_affected:
        assert history[1]["before"][claim_id] == before[claim_id]
        assert history[1]["after"][claim_id] == current_by_id[claim_id]
        assert history[1]["before"][claim_id]["version"] == 1
        assert history[1]["after"][claim_id]["version"] == 2
    assert all(claim_id not in history[1]["before"] for claim_id in before if claim_id not in expected_affected)


def test_second_assessed_dependency_can_be_challenged_after_first_and_history_advances(client):
    created = client.post(
        "/api/investigations",
        json={"question": "Review recurring handover omissions in this synthetic week."},
    )
    assert created.status_code == 201, created.text
    investigation_id = created.json()["id"]
    claim_id = "CHECKLIST_UNAVAILABLE"
    initial_claim = next(item for item in created.json()["claims"] if item["id"] == claim_id)
    assert {item["source_record_id"] for item in initial_claim["evidence"]} >= {"OPS-101", "OPS-102"}

    first = client.post(
        f"/api/investigations/{investigation_id}/claims/{claim_id}/challenge",
        json={"reason": "Review the first assessed checklist source.",
              "source_record_id": "OPS-101", "quote": "binder was missing"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 2

    second = client.post(
        f"/api/investigations/{investigation_id}/claims/{claim_id}/challenge",
        json={"reason": "Review the second assessed checklist source.",
              "source_record_id": "OPS-102", "quote": "checklist opened normally"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 3
    expected_second_affected = {"CHECKLIST_UNAVAILABLE", "PMS_SYSTEM_ISSUE"}
    assert set(second.json()["recomputed_claim_ids"]) == expected_second_affected

    current = client.get(f"/api/investigations/{investigation_id}").json()
    current_claim = next(item for item in current["claims"] if item["id"] == claim_id)
    assert current["version"] == 3
    assert current_claim["version"] == 3
    pms_claim = next(item for item in current["claims"] if item["id"] == "PMS_SYSTEM_ISSUE")
    assert pms_claim["version"] == 2
    assert {item["source_record_id"] for item in current_claim["evidence"]
            if item["disputed"]} >= {"OPS-101", "OPS-102"}

    history = client.get(f"/api/investigations/{investigation_id}/history").json()
    assert [event["version"] for event in history] == [1, 2, 3]
    assert history[1]["after"][claim_id]["version"] == 2
    assert history[2]["before"][claim_id]["version"] == 2
    assert history[2]["after"][claim_id] == current_claim
    assert set(history[2]["before"]) == expected_second_affected
    assert set(history[2]["after"]) == expected_second_affected


def test_unrelated_source_after_prior_dispute_is_rejected_without_persistence_changes(client):
    created = client.post(
        "/api/investigations",
        json={"question": "Review recurring handover omissions in this synthetic week."},
    )
    assert created.status_code == 201, created.text
    investigation_id = created.json()["id"]
    claim_id = "CHECKLIST_UNAVAILABLE"

    first = client.post(
        f"/api/investigations/{investigation_id}/claims/{claim_id}/challenge",
        json={"reason": "Establish the first legitimate dispute.",
              "source_record_id": "OPS-101", "quote": "binder was missing"},
    )
    assert first.status_code == 200, first.text
    before_rejected_request = client.get(f"/api/investigations/{investigation_id}").json()
    history_before = client.get(f"/api/investigations/{investigation_id}/history").json()

    rejected = client.post(
        f"/api/investigations/{investigation_id}/claims/{claim_id}/challenge",
        json={"reason": "Try an unrelated lamp maintenance record.",
              "source_record_id": "OPS-111", "quote": "guest called about a lamp"},
    )

    assert rejected.status_code == 422
    assert "not an assessed dependency" in rejected.json()["detail"]
    assert client.get(f"/api/investigations/{investigation_id}").json() == before_rejected_request
    assert client.get(f"/api/investigations/{investigation_id}/history").json() == history_before


def test_invalid_quote_after_prior_dispute_leaves_investigation_unchanged(client):
    created = client.post(
        "/api/investigations",
        json={"question": "Review recurring handover omissions in this synthetic week."},
    )
    assert created.status_code == 201, created.text
    investigation_id = created.json()["id"]
    claim_id = "CHECKLIST_UNAVAILABLE"

    first = client.post(
        f"/api/investigations/{investigation_id}/claims/{claim_id}/challenge",
        json={"reason": "Establish the first legitimate dispute.",
              "source_record_id": "OPS-101", "quote": "binder was missing"},
    )
    assert first.status_code == 200, first.text
    before_rejected_request = client.get(f"/api/investigations/{investigation_id}").json()
    history_before = client.get(f"/api/investigations/{investigation_id}/history").json()

    rejected = client.post(
        f"/api/investigations/{investigation_id}/claims/{claim_id}/challenge",
        json={"reason": "Use invalid wording for a known source.",
              "source_record_id": "OPS-102", "quote": "fabricated checklist wording"},
    )

    assert rejected.status_code == 422
    assert "exact source substring" in rejected.json()["detail"]
    assert client.get(f"/api/investigations/{investigation_id}").json() == before_rejected_request
    assert client.get(f"/api/investigations/{investigation_id}/history").json() == history_before


def test_challenge_recomputes_claim_with_only_unverified_source_dependency_and_records_history(
    client, monkeypatch,
):
    from app.mock_provider import MockProvider, SEED_RECORDS

    source = next(record for record in SEED_RECORDS if record.id == "OPS-101")
    quote = "Night checklist binder was missing"
    provider = MockProvider(assessment_overrides={
        "CHECKLIST_UNAVAILABLE": [{
            "source_record_id": source.id,
            "quote": quote,
            "stance": "SUPPORTS",
            "rationale": "Accepted checklist availability cue.",
        }],
        "TRAINING_GAP": [{
            "source_record_id": source.id,
            "quote": quote,
            "stance": "SUPPORTS",
            "rationale": "No training cue is present in this quote.",
        }],
        **{
            hypothesis.id: []
            for hypothesis in HYPOTHESES
            if hypothesis.id not in {"CHECKLIST_UNAVAILABLE", "TRAINING_GAP"}
        },
    })
    monkeypatch.setattr(main_module, "engine", AssessmentEngine(provider))

    created = client.post(
        "/api/investigations",
        json={"question": "Review the synthetic checklist and training evidence."},
    )
    assert created.status_code == 201, created.text
    investigation_id = created.json()["id"]
    before = {claim["id"]: claim for claim in created.json()["claims"]}
    target_id = "CHECKLIST_UNAVAILABLE"
    related_id = "TRAINING_GAP"
    related_before = before[related_id]

    target_evidence = before[target_id]["evidence"][0]
    related_evidence = related_before["evidence"][0]
    assert target_evidence["review_state"] == "ACCEPTED"
    assert related_evidence["review_state"] == "UNVERIFIED"
    assert related_before["dependencies"] == [source.id]
    assert related_before["status"] == "INSUFFICIENT"
    assert related_before["confidence"] == 0.0

    response = client.post(
        f"/api/investigations/{investigation_id}/claims/{target_id}/challenge",
        json={
            "reason": "Reassess every claim linked to this synthetic source.",
            "source_record_id": source.id,
            "quote": quote,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    expected_ids = {target_id, related_id}
    assert set(result["recomputed_claim_ids"]) == expected_ids
    assert set(result["before"]) == expected_ids
    assert set(result["after"]) == expected_ids

    related_after = result["after"][related_id]
    assert related_after["status"] == related_before["status"]
    assert related_after["confidence"] == related_before["confidence"]
    assert related_after["evidence"][0]["review_state"] == "UNVERIFIED"
    assert related_after["evidence"][0]["disputed"] is True
    assert result["before"][related_id] == related_before
    assert result["before"][related_id]["evidence"][0]["review_state"] == "UNVERIFIED"

    # The accepted dependency continues to be selected and retains its state.
    assert result["before"][target_id]["evidence"][0]["review_state"] == "ACCEPTED"
    assert result["after"][target_id]["evidence"][0]["review_state"] == "ACCEPTED"

    history = client.get(f"/api/investigations/{investigation_id}/history")
    assert history.status_code == 200
    challenge_event = history.json()[1]
    assert set(challenge_event["recomputed_claim_ids"]) == expected_ids
    assert set(challenge_event["before"]) == expected_ids
    assert set(challenge_event["after"]) == expected_ids
    assert challenge_event["before"][related_id]["evidence"][0]["review_state"] == "UNVERIFIED"
    assert challenge_event["after"][related_id]["evidence"][0]["review_state"] == "UNVERIFIED"


def test_challenge_added_unverified_proposal_persists_review_state_in_response_and_history(client, monkeypatch):
    from app.mock_provider import MockProvider, SEED_RECORDS

    source = next(record for record in SEED_RECORDS if record.id == "OPS-101")
    proposal = {"source_record_id": source.id, "quote": "Night checklist binder was missing", "stance": "CONTRADICTS", "rationale": "synthetic proposal"}
    provider = MockProvider(assessment_sequences={
        "CHECKLIST_UNAVAILABLE": [[], [proposal]],
        **{hypothesis.id: [[]] for hypothesis in HYPOTHESES if hypothesis.id != "CHECKLIST_UNAVAILABLE"},
    })
    monkeypatch.setattr(main_module, "engine", AssessmentEngine(provider))
    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."})
    assert created.status_code == 201
    investigation_id = created.json()["id"]
    response = client.post(
        f"/api/investigations/{investigation_id}/claims/CHECKLIST_UNAVAILABLE/challenge",
        json={"reason": "Review whether this synthetic source supports the claim.", "source_record_id": source.id,
              "quote": "Night checklist binder was missing"},
    )
    assert response.status_code == 200, response.text
    after = response.json()["after"]["CHECKLIST_UNAVAILABLE"]
    evidence = after["evidence"][0]
    assert evidence["review_state"] == "UNVERIFIED"
    assert evidence["proposed_stance"] == "CONTRADICTS"
    assert evidence["semantic_relation"] == "SUPPORTS"
    assert evidence["disputed"] is True
    assert after["status"] == "INSUFFICIENT"
    persisted = client.get(f"/api/investigations/{investigation_id}").json()
    stored = next(c for c in persisted["claims"] if c["id"] == "CHECKLIST_UNAVAILABLE")
    assert stored == after
    history = client.get(f"/api/investigations/{investigation_id}/history").json()
    assert history[1]["after"]["CHECKLIST_UNAVAILABLE"] == after


def test_unknown_claim_is_rejected(client):
    created = client.post("/api/investigations", json={"question": "Review recurring handover omissions in this synthetic week."}).json()
    response = client.post(f"/api/investigations/{created['id']}/claims/UNKNOWN/challenge", json={"reason": "Review this claim now.", "source_record_id": "OPS-101", "quote": "binder was missing"})
    assert response.status_code == 404

