"""Slice 19-20 audit: experiment manifest shape and API route contracts.

Manifest claims under test: which fields it records, that a manifest can describe
a run that never happened, and that the module writes no file at all.

Route claims under test: status code of every route, preset/question coupling,
`_derive_preset_id` refusing to guess, ascending history order, and the absence of
any restricted record identifier from every response body.
"""
import ast
import asyncio
import gc
import hashlib
import json
import time
import types
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app import experiment_manifest, main as main_module, store
from app.engine import AssessmentError, ProviderError
from app.experiment_manifest import AttemptMetadata, ExperimentRunManifest, sha256_hex
from app.main import _derive_preset_id, app
from app.mock_provider import SEED_RECORDS
from app.models import (HYPOTHESES, INVESTIGATION_PRESET_HYPOTHESES,
                        INVESTIGATION_PRESET_QUESTIONS, InvestigationPreset)

RESTRICTED_RECORDS = [record for record in SEED_RECORDS if record.restricted]
RESTRICTED_IDS = [record.id for record in RESTRICTED_RECORDS]
RESTRICTED_TEXTS = [record.text for record in RESTRICTED_RECORDS]

_DIGEST = "a" * 64


class InProcessClient:
    """Synchronous helper over HTTPX ASGITransport, without Starlette TestClient."""

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
    """Initialized disposable database inside the only writable directory."""
    db_path = store.DATA_DIR / f".test-s1920-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    try:
        store.initialize_database()
        with InProcessClient(app) as test_client:
            yield test_client
    finally:
        _remove_sqlite_files(db_path)


@pytest.fixture
def uninitialized_client(monkeypatch):
    """Configured database path that was never initialized."""
    db_path = store.DATA_DIR / f".test-s1920-missing-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    try:
        with InProcessClient(app) as test_client:
            yield test_client
    finally:
        _remove_sqlite_files(db_path)


@pytest.fixture
def invalid_path_client(monkeypatch):
    """Configured path outside the permitted data directory."""
    monkeypatch.setenv("HACKATHON_DB_PATH", "/tmp/test-s1920-outside.sqlite3")
    with InProcessClient(app) as test_client:
        yield test_client


def _manifest_kwargs(**overrides):
    kwargs = dict(
        run_id="run-0001",
        dataset_sha256=_DIGEST,
        evaluator_version="3.16.0",
        prompt_version="local-instructions-v1",
        prompt_sha256="b" * 64,
        serializer_version="allowlist-json-v1",
        serializer_sha256="c" * 64,
        code_revision="rev-1",
        model_name="synthetic-model",
        model_version="2026-10-01",
        temperature=0.0,
        seed=7,
    )
    kwargs.update(overrides)
    return kwargs


def _assert_no_restricted_content(payload) -> None:
    body = json.dumps(payload)
    for restricted_id in RESTRICTED_IDS:
        assert restricted_id not in body
    for restricted_text in RESTRICTED_TEXTS:
        assert restricted_text not in body


# --------------------------------------------------------------------------- #
# Slice 19: experiment manifest
# --------------------------------------------------------------------------- #

_MANIFEST_KEYS = {
    "schema_version", "run_id", "dataset_sha256", "code_revision", "prompt_version",
    "prompt_sha256", "serializer_version", "serializer_sha256", "model_name",
    "model_version", "decoding", "evaluator_version", "attempts",
}
_ATTEMPT_KEYS = {
    "case_id", "request_count", "latency_ms", "input_tokens", "output_tokens",
    "error_category",
}


def test_manifest_serializes_exactly_the_declared_metadata_fields():
    manifest = ExperimentRunManifest(**_manifest_kwargs())
    manifest.add_attempt(AttemptMetadata(case_id="case-1", request_count=1, latency_ms=12,
                                         input_tokens=3, output_tokens=4))

    data = manifest.to_dict()

    assert set(data) == _MANIFEST_KEYS
    assert data["schema_version"] == "1"
    assert data["decoding"] == {"temperature": 0.0, "seed": 7}
    assert data["attempts"] == [{
        "case_id": "case-1", "request_count": 1, "latency_ms": 12,
        "input_tokens": 3, "output_tokens": 4, "error_category": None,
    }]
    assert set(data["attempts"][0]) == _ATTEMPT_KEYS
    # The docstring's promise: no prompt, response, proposal, or record text.
    for forbidden_key in ("prompt", "response", "messages", "proposal", "rationale",
                          "text", "quote", "records", "payload"):
        assert forbidden_key not in data
    serialized = json.dumps(data)
    for restricted_text in RESTRICTED_TEXTS:
        assert restricted_text not in serialized


def test_manifest_constructor_rejects_text_carrying_keywords():
    # Extra keyword arguments are refused by dataclass construction, so the field
    # set cannot be widened by a caller that wants to attach a prompt or output.
    with pytest.raises(TypeError):
        ExperimentRunManifest(**_manifest_kwargs(), prompt_text="system prompt")
    with pytest.raises(TypeError):
        ExperimentRunManifest(**_manifest_kwargs(), provider_response="body")


def test_manifest_accepts_an_attempt_for_a_case_that_never_executed():
    manifest = ExperimentRunManifest(**_manifest_kwargs())
    manifest.add_attempt(AttemptMetadata(case_id="case-that-never-ran", request_count=97))

    assert manifest.to_dict()["attempts"][0]["case_id"] == "case-that-never-ran"
    assert manifest.to_dict()["attempts"][0]["request_count"] == 97


def test_manifest_with_no_attempts_still_serializes_a_complete_run_record():
    data = ExperimentRunManifest(**_manifest_kwargs(run_id="declared-only")).to_dict()

    assert data["run_id"] == "declared-only"
    assert data["attempts"] == []
    assert set(data) == _MANIFEST_KEYS


def test_attempts_written_outside_add_attempt_cannot_be_serialised():
    """This test used to pin the opposite: attempts could be replaced after the
    fact and still serialise, so a manifest could describe a run that never
    happened. The manifest is now fingerprinted when attempts are added and
    re-checked on serialisation."""
    manifest = ExperimentRunManifest(**_manifest_kwargs())
    manifest.add_attempt(AttemptMetadata(case_id="case-1", request_count=1))

    manifest.attempts = [AttemptMetadata(case_id="injected-after-the-fact", request_count=5)]

    with pytest.raises(ValueError):
        manifest.to_dict()


def test_a_sealed_manifest_refuses_further_attempts_and_requires_one():
    empty = ExperimentRunManifest(**_manifest_kwargs())
    with pytest.raises(ValueError):
        empty.seal()

    manifest = ExperimentRunManifest(**_manifest_kwargs())
    manifest.add_attempt(AttemptMetadata(case_id="case-1", request_count=1))
    manifest.seal()

    with pytest.raises(ValueError):
        manifest.add_attempt(AttemptMetadata(case_id="case-2", request_count=1))
    assert len(manifest.to_dict()["attempts"]) == 1


def test_manifest_echoes_caller_supplied_identifiers_and_digests_verbatim():
    # Nothing derives these from an executed artifact; the caller's values are the
    # record, so a manifest can describe a different experiment than the one run.
    kwargs = _manifest_kwargs(run_id="declared-run", dataset_sha256="d" * 64,
                              evaluator_version="99.0.0", code_revision="unused-rev")
    data = ExperimentRunManifest(**kwargs).to_dict()

    assert data["run_id"] == "declared-run"
    assert data["dataset_sha256"] == "d" * 64
    assert data["evaluator_version"] == "99.0.0"
    assert data["code_revision"] == "unused-rev"


def test_sha256_hex_hashes_only_the_bytes_it_is_given():
    assert sha256_hex(b"synthetic") == hashlib.sha256(b"synthetic").hexdigest()
    assert sha256_hex(b"synthetic") == sha256_hex(b"synthetic")
    assert sha256_hex(b"synthetic") != sha256_hex(b"synthetic ")


def test_manifest_module_contains_no_file_io_and_no_path_imports():
    source = Path(experiment_manifest.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = {alias.name.split(".")[0]
                for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0]
                 for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert imported.isdisjoint({"os", "pathlib", "io", "shutil", "tempfile",
                                "subprocess", "socket"})
    assert [node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "open"] == []


# --------------------------------------------------------------------------- #
# Slice 20: route status codes
# --------------------------------------------------------------------------- #

_VALID_QUESTION = "Did time pressure contribute to recurring handover omissions?"
_VALID_CHALLENGE = {
    "reason": "Human reviewer disputed the recorded evidence.",
    "source_record_id": "OPS-101",
    "quote": "checklist binder was missing",
}


def test_health_reports_ok_when_database_is_not_initialized(uninitialized_client):
    response = uninitialized_client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "prototype": True,
        "synthetic_data_only": True,
        "database_initialized": False,
        "database_available": False,
        "authentication": False,
        "human_review_required": True,
    }


def test_health_reports_ok_when_database_is_initialized(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database_initialized"] is True
    assert body["database_available"] is True
    assert body["authentication"] is False


def test_health_reports_degraded_for_a_corrupt_database(client, monkeypatch):
    db_path = store.database_path()
    db_path.write_bytes(b"not a sqlite database at all")

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["database_initialized"] is True
    assert body["database_available"] is False
    assert body["status"] == "degraded"


def test_records_returns_503_from_the_handler_for_a_corrupt_database(client):
    db_path = store.database_path()
    db_path.write_bytes(b"not a sqlite database at all")

    response = client.get("/api/records")

    assert response.status_code == 503
    assert response.json()["detail"] == "Local prototype database is unavailable."


def test_health_reports_misconfigured_when_the_path_is_rejected(invalid_path_client):
    # A path outside the permitted directory makes `database_path()` raise, which
    # makes every data route 503. Health must not call that "ok": it used to, and
    # the signal disagreed with the availability it describes.
    response = invalid_path_client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["database_initialized"] is False
    assert body["database_available"] is False
    assert body["status"] == "misconfigured"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/records", None),
        ("POST", "/api/investigations", {"question": _VALID_QUESTION}),
        ("GET", "/api/investigations/any-id", None),
        ("POST", "/api/investigations/any-id/claims/TIME_PRESSURE/challenge", _VALID_CHALLENGE),
        ("GET", "/api/investigations/any-id/history", None),
    ],
    ids=["records", "create", "read", "challenge", "history"],
)
def test_every_data_route_returns_503_when_database_is_not_initialized(
    uninitialized_client, method, path, body,
):
    response = uninitialized_client.request(method, path, json=body)

    assert response.status_code == 503
    assert "not initialized" in response.json()["detail"]


def test_records_returns_200_and_never_lists_restricted_records(client):
    response = client.get("/api/records")

    assert response.status_code == 200
    body = response.json()
    assert body, "seed records expected"
    returned_ids = {record["id"] for record in body}
    for restricted_id in RESTRICTED_IDS:
        assert restricted_id not in returned_ids
    assert all(record["restricted"] is False for record in body)
    _assert_no_restricted_content(body)


def test_create_investigation_with_matching_preset_returns_201_and_one_claim(client):
    preset_id = InvestigationPreset.CHECKLIST_ACCESS
    question = INVESTIGATION_PRESET_QUESTIONS[preset_id]

    response = client.post("/api/investigations",
                           json={"question": question, "preset_id": preset_id.value})

    assert response.status_code == 201
    body = response.json()
    assert body["question"] == question
    assert body["preset_id"] == preset_id.value
    assert [claim["id"] for claim in body["claims"]] == [
        INVESTIGATION_PRESET_HYPOTHESES[preset_id]
    ]
    assert body["claims"][0]["hypothesis_id"] == INVESTIGATION_PRESET_HYPOTHESES[preset_id]
    _assert_no_restricted_content(body)


def test_create_investigation_rejects_a_question_that_does_not_match_the_preset(client):
    response = client.post(
        "/api/investigations",
        json={"question": "Did something else happen entirely?",
              "preset_id": InvestigationPreset.CHECKLIST_ACCESS.value},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Question does not match the selected investigation preset."
    )


def test_create_investigation_rejects_an_unknown_preset_value(client):
    response = client.post(
        "/api/investigations",
        json={"question": _VALID_QUESTION, "preset_id": "not_a_preset"},
    )

    assert response.status_code == 422


def test_create_investigation_rejects_extra_fields(client):
    response = client.post(
        "/api/investigations",
        json={"question": _VALID_QUESTION, "hypotheses": ["TIME_PRESSURE"]},
    )

    assert response.status_code == 422


def test_create_investigation_without_a_preset_returns_201_and_all_hypotheses(client):
    response = client.post("/api/investigations", json={"question": _VALID_QUESTION})

    assert response.status_code == 201
    body = response.json()
    assert body["preset_id"] is None
    assert [claim["id"] for claim in body["claims"]] == [item.id for item in HYPOTHESES]
    _assert_no_restricted_content(body)


def test_get_investigation_returns_200_for_a_created_id_and_404_otherwise(client):
    created = client.post("/api/investigations", json={"question": _VALID_QUESTION}).json()

    found = client.get(f"/api/investigations/{created['id']}")
    missing = client.get("/api/investigations/does-not-exist")

    assert found.status_code == 200
    assert found.json()["id"] == created["id"]
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Investigation not found"


def test_get_investigation_treats_the_stored_preset_identifier_as_untrusted(
    monkeypatch, uninitialized_client,
):
    preset_id = InvestigationPreset.DESK_COVERAGE
    hypothesis_id = INVESTIGATION_PRESET_HYPOTHESES[preset_id]
    stored = {
        "id": "investigation-stored",
        "question": INVESTIGATION_PRESET_QUESTIONS[preset_id],
        "preset_id": InvestigationPreset.PROPERTY_SYSTEM.value,
        "created_at": "2026-10-31T10:00:00+00:00",
        "version": 1,
        "claims": [{
            "id": hypothesis_id, "hypothesis_id": hypothesis_id, "status": "INSUFFICIENT",
            "confidence": 0.0, "uncertainty": "none", "summary": "stored",
            "evidence": [], "conflicts": [], "missing_evidence": [], "dependencies": [],
            "version": 1,
        }],
    }
    monkeypatch.setattr(main_module, "require_database", lambda: None)
    monkeypatch.setattr(store, "get_investigation", lambda _id: stored)

    response = uninitialized_client.get("/api/investigations/investigation-stored")

    assert response.status_code == 200
    assert response.json()["preset_id"] == preset_id.value


def test_create_investigation_returns_503_when_the_provider_fails(client, monkeypatch):
    def fail(_records):
        raise ProviderError("provider_failure")

    # The engine is sealed against attribute replacement, so the module-level
    # reference is swapped instead.
    monkeypatch.setattr(main_module, "engine", types.SimpleNamespace(investigate=fail))

    response = client.post("/api/investigations", json={"question": _VALID_QUESTION})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Assessment provider is unavailable or returned invalid output."
    )


def _first_evidence_target(investigation: dict) -> tuple[str, str, str]:
    for claim in investigation["claims"]:
        for evidence in claim["evidence"]:
            quote = evidence["quote"]
            if len(quote.strip()) >= 3:
                return claim["id"], evidence["source_record_id"], quote[:max(3, min(24, len(quote)))]
    raise AssertionError("expected at least one evidence row")


def _created_investigation(client) -> dict:
    response = client.post(
        "/api/investigations",
        json={"question": INVESTIGATION_PRESET_QUESTIONS[InvestigationPreset.CHECKLIST_ACCESS],
              "preset_id": InvestigationPreset.CHECKLIST_ACCESS.value},
    )
    assert response.status_code == 201
    return response.json()


def test_challenge_returns_200_and_history_is_ordered_by_ascending_version(client):
    created = _created_investigation(client)
    claim_id, record_id, quote = _first_evidence_target(created)

    challenged = client.post(
        f"/api/investigations/{created['id']}/claims/{claim_id}/challenge",
        json={"reason": "Human reviewer disputed the recorded evidence.",
              "source_record_id": record_id, "quote": quote},
    )

    assert challenged.status_code == 200
    body = challenged.json()
    assert body["reason"] == "Human reviewer disputed the recorded evidence."
    assert body["recomputed_claim_ids"] == [claim_id]
    assert set(body["before"]) == {claim_id}
    assert set(body["after"]) == {claim_id}

    history = client.get(f"/api/investigations/{created['id']}/history")

    assert history.status_code == 200
    entries = history.json()
    assert [entry["version"] for entry in entries] == [1, 2]
    assert [entry["event"] for entry in entries] == ["CREATED", "CHALLENGE"]
    assert entries[0]["created_at"] <= entries[1]["created_at"]
    _assert_no_restricted_content(body)
    _assert_no_restricted_content(entries)


def test_challenge_returns_404_for_a_restricted_record_identifier(client):
    created = _created_investigation(client)
    claim_id = created["claims"][0]["id"]

    response = client.post(
        f"/api/investigations/{created['id']}/claims/{claim_id}/challenge",
        json={"reason": "Attempt to challenge from a restricted row.",
              "source_record_id": RESTRICTED_IDS[0], "quote": RESTRICTED_TEXTS[0][:20]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Source record not found"
    _assert_no_restricted_content(response.json())


def test_challenge_returns_404_for_an_unknown_source_record(client):
    created = _created_investigation(client)
    claim_id = created["claims"][0]["id"]

    response = client.post(
        f"/api/investigations/{created['id']}/claims/{claim_id}/challenge",
        json={"reason": "Unknown source record reference.",
              "source_record_id": "NO-SUCH-RECORD", "quote": "checklist"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Source record not found"


def test_challenge_returns_422_for_a_quote_that_is_not_an_exact_substring(client):
    created = _created_investigation(client)
    claim_id = created["claims"][0]["id"]

    response = client.post(
        f"/api/investigations/{created['id']}/claims/{claim_id}/challenge",
        json={"reason": "Quote was paraphrased rather than quoted.",
              "source_record_id": "OPS-101", "quote": "checklist binder was absent"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Challenge quote must be an exact source substring"


def test_challenge_returns_404_for_unknown_investigation_or_claim(client):
    created = _created_investigation(client)
    claim_id = created["claims"][0]["id"]

    unknown_investigation = client.post(
        "/api/investigations/no-such-investigation/claims/TIME_PRESSURE/challenge",
        json=_VALID_CHALLENGE,
    )
    unknown_claim = client.post(
        f"/api/investigations/{created['id']}/claims/NO_SUCH_CLAIM/challenge",
        json=_VALID_CHALLENGE,
    )

    assert unknown_investigation.status_code == 404
    assert unknown_investigation.json()["detail"] == "Investigation or claim not found"
    assert unknown_claim.status_code == 404
    assert unknown_claim.json()["detail"] == "Investigation or claim not found"


def test_challenge_returns_409_when_the_snapshot_became_stale(client, monkeypatch):
    created = _created_investigation(client)
    claim_id, record_id, quote = _first_evidence_target(created)

    def stale(*_args, **_kwargs):
        raise store.StaleRevision("snapshot changed")

    monkeypatch.setattr(store, "apply_challenge", stale)

    response = client.post(
        f"/api/investigations/{created['id']}/claims/{claim_id}/challenge",
        json={"reason": "Concurrent edit arrived during recomputation.",
              "source_record_id": record_id, "quote": quote},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Investigation changed during challenge computation; reload and retry."
    )


def test_challenge_returns_422_when_recomputation_is_rejected(client, monkeypatch):
    created = _created_investigation(client)
    claim_id, record_id, quote = _first_evidence_target(created)

    def reject(*_args, **_kwargs):
        raise AssessmentError("This source is not an assessed dependency for the selected claim",
                              code="invalid_source")

    monkeypatch.setattr(main_module, "engine", types.SimpleNamespace(challenge=reject))

    response = client.post(
        f"/api/investigations/{created['id']}/claims/{claim_id}/challenge",
        json={"reason": "Source is not an assessed dependency.",
              "source_record_id": record_id, "quote": quote},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "This source is not an assessed dependency for the selected claim"
    )


def test_history_returns_404_for_an_unknown_investigation(client):
    response = client.get("/api/investigations/does-not-exist/history")

    assert response.status_code == 404
    assert response.json()["detail"] == "Investigation not found"


# --------------------------------------------------------------------------- #
# Slice 20: _derive_preset_id refuses to guess
# --------------------------------------------------------------------------- #

_CHECKLIST_PRESET = InvestigationPreset.CHECKLIST_ACCESS
_CHECKLIST_QUESTION = INVESTIGATION_PRESET_QUESTIONS[_CHECKLIST_PRESET]
_CHECKLIST_HYPOTHESIS = INVESTIGATION_PRESET_HYPOTHESES[_CHECKLIST_PRESET]


def _claim(hypothesis_id, claim_id=None):
    return {"id": claim_id or hypothesis_id, "hypothesis_id": hypothesis_id}


def test_derive_preset_id_accepts_only_canonical_question_plus_matching_single_claim():
    assert _derive_preset_id({
        "question": _CHECKLIST_QUESTION,
        "claims": [_claim(_CHECKLIST_HYPOTHESIS)],
    }) is _CHECKLIST_PRESET


@pytest.mark.parametrize(
    "investigation",
    [
        {"question": _CHECKLIST_QUESTION, "claims": []},
        {"question": _CHECKLIST_QUESTION, "claims": [
            _claim(_CHECKLIST_HYPOTHESIS), _claim("TIME_PRESSURE")]},
        {"question": _CHECKLIST_QUESTION, "claims": [_claim("TIME_PRESSURE")]},
        {"question": _CHECKLIST_QUESTION, "claims": [
            {"id": _CHECKLIST_HYPOTHESIS, "hypothesis_id": "TIME_PRESSURE"}]},
        {"question": _CHECKLIST_QUESTION, "claims": [
            {"id": "TIME_PRESSURE", "hypothesis_id": _CHECKLIST_HYPOTHESIS}]},
        {"question": _CHECKLIST_QUESTION + " Please confirm.", "claims": [
            _claim(_CHECKLIST_HYPOTHESIS)]},
        {"question": _CHECKLIST_QUESTION.lower(), "claims": [_claim(_CHECKLIST_HYPOTHESIS)]},
        {"question": "Did checklist availability contribute to missing handover information",
         "claims": [_claim(_CHECKLIST_HYPOTHESIS)]},
        {"question": None, "claims": [_claim(_CHECKLIST_HYPOTHESIS)]},
        {"question": _CHECKLIST_QUESTION, "claims": {"0": _claim(_CHECKLIST_HYPOTHESIS)}},
        {"question": _CHECKLIST_QUESTION, "claims": "not-a-list"},
        {"question": _CHECKLIST_QUESTION, "claims": ["not-a-dict"]},
        {"claims": [_claim(_CHECKLIST_HYPOTHESIS)]},
        {},
    ],
    ids=[
        "no-claims", "two-claims", "wrong-hypothesis", "mismatched-hypothesis-id",
        "mismatched-claim-id", "question-suffix", "question-lowercased",
        "question-missing-terminator", "question-none", "claims-dict", "claims-string",
        "claim-not-dict", "question-absent", "empty",
    ],
)
def test_derive_preset_id_refuses_every_non_exact_shape(investigation):
    assert _derive_preset_id(investigation) is None


def test_derive_preset_id_ignores_a_stored_preset_identifier():
    # A stored `preset_id` is never the source of truth; a mismatched stored value
    # must not suppress the canonical derivation, and a matching one cannot be
    # supplied for a shape that fails the checks.
    derived_with_foreign_stored_value = _derive_preset_id({
        "question": _CHECKLIST_QUESTION,
        "preset_id": InvestigationPreset.HANDOVER_OMISSIONS.value,
        "claims": [_claim(_CHECKLIST_HYPOTHESIS)],
    })
    derived_from_stored_value_only = _derive_preset_id({
        "question": "A question that is not a preset question.",
        "preset_id": _CHECKLIST_PRESET.value,
        "claims": [_claim(_CHECKLIST_HYPOTHESIS)],
    })

    assert derived_with_foreign_stored_value is _CHECKLIST_PRESET
    assert derived_from_stored_value_only is None


@pytest.mark.parametrize("preset_id", list(InvestigationPreset))
def test_created_preset_investigations_round_trip_to_their_preset(client, preset_id):
    response = client.post("/api/investigations", json={
        "question": INVESTIGATION_PRESET_QUESTIONS[preset_id],
        "preset_id": preset_id.value,
    })

    assert response.status_code == 201
    body = response.json()
    assert body["preset_id"] == preset_id.value
    assert [claim["id"] for claim in body["claims"]] == [
        INVESTIGATION_PRESET_HYPOTHESES[preset_id]
    ]


def test_no_route_response_in_a_full_flow_contains_a_restricted_record_id(client):
    responses = [client.get("/api/records")]

    created = _created_investigation(client)
    responses.append(client.get(f"/api/investigations/{created['id']}"))

    claim_id, record_id, quote = _first_evidence_target(created)
    responses.append(client.post(
        f"/api/investigations/{created['id']}/claims/{claim_id}/challenge",
        json={"reason": "Full-flow challenge for leak check.",
              "source_record_id": record_id, "quote": quote},
    ))
    responses.append(client.get(f"/api/investigations/{created['id']}/history"))
    responses.append(client.get("/api/health"))

    for response in responses:
        assert 200 <= response.status_code < 300, response.text
        _assert_no_restricted_content(response.json())
