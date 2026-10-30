"""API behavior with an isolated, disposable prototype-local SQLite file."""
import gc
import asyncio
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

import pytest
import httpx

from app import main as main_module, store
from app.engine import AssessmentEngine, ProviderError
from app.main import app
from app.models import HYPOTHESES


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
        assert response.json() == {"detail": "Local prototype database is not initialized. See hackathon/README.md."}
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

