"""What a client can and cannot see of the guard's new surface, over ASGI.

Two things were added to the assessment layer this revision:

* the reason code ``ATTRIBUTED_DENIAL`` on an assessment the guard withholds, and
* the truth interval ``truth_lower`` / ``truth_upper`` on a decided verdict.

These tests assert what the HTTP app actually ships, not what the domain layer
computes. Drift observed while writing them is recorded in
``ct3/audit/API-REASON-CODES.md``. The contract asserted here is the *current*
one, so a later change that promotes either item into a typed field will fail
these tests and must update that artifact with the new shape.

The client fixture reuses ``InProcessClient`` from ``test_api.py``; it is the same
HTTPX-over-ASGITransport path the rest of the API tests use. The suite-wide
``conftest.py`` contributes the autouse rate-limiter reset and no client: the
limiter is process-global, so its buckets are drained between cases.
"""
import json
import logging
import sqlite3
from uuid import uuid4

import pytest

from test_api import InProcessClient, _remove_sqlite_files

from app import store
from app.decision_table import decide
from app.main import app

# The mock provider attaches a record to the CHECKLIST_UNAVAILABLE hypothesis by
# keyword. "No one could confirm ..." additionally trips the guard's
# third-party-attribution reading, which is what produces ATTRIBUTED_DENIAL.
DENIAL_TEXT = "No one could confirm that the checklist was unavailable during the night handover."
DENIAL_QUOTE = "Night checklist binder was missing from the desk"
OPS_101_QUOTE = (
    "Night checklist binder was missing from the desk; "
    "we wrote room 412's late arrival on a loose note."
)

REASON_CODES_UNDER_AUDIT = {"ATTRIBUTED_DENIAL"}
INTERVAL_FIELDS = {"truth_lower", "truth_upper", "truth_interval", "interval_status"}


@pytest.fixture
def client(monkeypatch):
    db_path = store.DATA_DIR / f".test-reason-codes-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    try:
        store.initialize_database()
        with InProcessClient(app) as test_client:
            test_client.app.state.test_database_path = db_path
            yield test_client
    finally:
        _remove_sqlite_files(db_path)


def _ingest_denial_record(client):
    response = client.post(
        "/api/records/ingest",
        json={"text": DENIAL_TEXT, "department": "Front Office", "source_group": "API-REASON-CODES"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_investigation(client):
    response = client.post(
        "/api/investigations",
        json={
            "question": "Did checklist availability contribute to missing handover information?",
            "preset_id": "checklist_access",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _guard_decisions(claim):
    return claim["explanation_trace"]["semantic_guard"]["decisions"]


def _decision_for(claim, record_id):
    matches = [d for d in _guard_decisions(claim) if d["source_record_id"] == record_id]
    assert len(matches) == 1, matches
    return matches[0]


def _all_key_paths(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{prefix}/{key}"
            yield from _all_key_paths(child, f"{prefix}/{key}")
    elif isinstance(value, list) and value:
        yield from _all_key_paths(value[0], f"{prefix}[]")


def test_attributed_denial_reason_code_reaches_the_client(client):
    """The new reason code is in the response, at one path, and nothing else names it."""
    record_id = _ingest_denial_record(client)
    claim = _create_investigation(client)["claims"][0]

    decision = _decision_for(claim, record_id)
    assert decision["reason_code"] == "ATTRIBUTED_DENIAL"
    assert decision["semantic_relation"] is None
    assert decision["review_state"] == "UNVERIFIED"
    assert decision["guard_enabled"] is True
    assert decision["decision_source"] == "ASSESSMENT_REVIEW"

    # The reason is not promoted: no evidence entry carries a reason code, so a
    # client reading only claims[].evidence[] cannot tell a withheld assessment
    # from one the guard simply had no cue for.
    evidence = next(e for e in claim["evidence"] if e["source_record_id"] == record_id)
    assert "reason_code" not in evidence
    assert evidence["review_state"] == "UNVERIFIED"
    assert evidence["stance"] == "NEUTRAL"
    assert evidence["semantic_relation"] is None


def test_reason_code_survives_the_read_round_trip(client):
    """A stored claim returns the same reason code, field for field."""
    record_id = _ingest_denial_record(client)
    created = _create_investigation(client)

    fetched = client.get(f"/api/investigations/{created['id']}")
    assert fetched.status_code == 200, fetched.text
    stored_claim = fetched.json()["claims"][0]
    created_claim = created["claims"][0]

    assert _guard_decisions(stored_claim) == _guard_decisions(created_claim)
    assert _decision_for(stored_claim, record_id)["reason_code"] == "ATTRIBUTED_DENIAL"


def test_reason_code_does_not_match_the_guard_s_own_cue_list(client):
    """Drift: the cue list says SUPPORTS while the reason code says the reading was refused."""
    record_id = _ingest_denial_record(client)
    claim = _create_investigation(client)["claims"][0]

    decision = _decision_for(claim, record_id)
    assert decision["reason_code"] == "ATTRIBUTED_DENIAL"
    assert decision["cue_ids"] == ["CHECKLIST_UNAVAILABLE.SUPPORTS.checklist_was_unavailable"]
    assert decision["semantic_relation"] is None

    # The human-readable field the client does get says only that cues "did not
    # verify its direction", which is not what happened: a cue fired and was
    # overridden by attribution. Only the trace carries the actual reason.
    evidence = next(e for e in claim["evidence"] if e["source_record_id"] == record_id)
    assert "ATTRIBUTED_DENIAL" not in evidence["rationale"]
    assert "attributed" not in evidence["rationale"].lower()


def test_openapi_cannot_describe_the_reason_code(client):
    """A generated client has no way to discover the reason code from the schema."""
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    document = spec.text
    for emitted in ("reason_code", "ATTRIBUTED_DENIAL", "semantic_guard", "cue_ids"):
        assert emitted not in document

    schema = spec.json()["components"]["schemas"]
    trace_schema = schema["Claim"]["properties"]["explanation_trace"]
    objects = [part for part in trace_schema["anyOf"] if part.get("type") == "object"]
    assert objects and objects[0]["additionalProperties"] is True
    for field in ("reason_code",) + tuple(INTERVAL_FIELDS):
        assert field not in schema["Evidence"]["properties"]
        assert field not in schema["Claim"]["properties"]


def test_truth_interval_is_computed_but_never_serialised(client):
    """The interval exists in the decision layer and is dropped at the API boundary."""
    _ingest_denial_record(client)
    created = _create_investigation(client)

    # The domain verdict does carry it, so this is a boundary loss, not a gap in
    # the rule: the engine holds these numbers while building the response.
    verdict = decide(2, 1)
    assert isinstance(verdict.truth_lower, float)
    assert isinstance(verdict.truth_upper, float)
    assert 0.0 <= verdict.truth_lower <= verdict.truth_upper <= 1.0

    fetched = client.get(f"/api/investigations/{created['id']}").json()
    paths = list(_all_key_paths(fetched))
    leaked = [p for p in paths if any(field in p for field in INTERVAL_FIELDS)]
    assert leaked == []
    assert "truth" not in json.dumps(fetched).lower()

    claim = fetched["claims"][0]
    for field in INTERVAL_FIELDS:
        assert field not in claim
    # uncertainty is prose, not a pair of bounds, so it cannot stand in for the interval.
    assert isinstance(claim["uncertainty"], str)
    assert isinstance(claim["confidence"], float)


def test_unknown_claim_and_investigation_are_not_found_without_internals(client):
    created = _create_investigation(client)

    missing_claim = client.post(
        f"/api/investigations/{created['id']}/claims/DOES_NOT_EXIST/challenge",
        json={"source_record_id": "OPS-101", "quote": DENIAL_QUOTE, "reason": "probe the error shape"},
    )
    assert missing_claim.status_code == 404
    assert missing_claim.json() == {"detail": "Investigation or claim not found"}

    missing_investigation = client.get("/api/investigations/DOES_NOT_EXIST")
    assert missing_investigation.status_code == 404
    assert missing_investigation.json() == {"detail": "Investigation not found"}


def test_unknown_source_record_and_bad_quote_are_rejected_with_a_reason(client):
    created = _create_investigation(client)
    claim_id = created["claims"][0]["id"]
    path = f"/api/investigations/{created['id']}/claims/{claim_id}/challenge"

    unknown_record = client.post(
        path,
        json={"source_record_id": "OPS-999", "quote": DENIAL_QUOTE, "reason": "probe the error shape"},
    )
    assert unknown_record.status_code == 404
    assert unknown_record.json() == {"detail": "Source record not found"}

    bad_quote = client.post(
        path,
        json={"source_record_id": "OPS-101", "quote": "text that is not there", "reason": "probe the error shape"},
    )
    assert bad_quote.status_code == 422
    assert bad_quote.json() == {"detail": "Challenge quote must be an exact source substring"}
    for body in (unknown_record.text, bad_quote.text):
        assert "Traceback" not in body
        assert "sqlite" not in body.lower()


def test_corrupt_stored_row_is_a_bounded_503_and_the_row_goes_to_the_log(client, caplog):
    created = _create_investigation(client)
    claim_id = created["claims"][0]["id"]
    db_path = client.app.state.test_database_path

    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE claim_versions SET claim_json = ? WHERE investigation_id = ?",
        ("{not json", created["id"]),
    )
    connection.commit()
    connection.close()

    with caplog.at_level(logging.WARNING):
        response = client.get(f"/api/investigations/{created['id']}")

    assert response.status_code == 503
    assert response.json() == {"detail": "Local prototype database is unavailable."}
    # The caller learns "the store is unreadable" and nothing more: no table, no
    # row id, no column name, no stored value.
    for internal in ("claim_versions", claim_id, "claim_json", "not json", "Traceback"):
        assert internal not in response.text
    # The operator channel is where the coordinates land.
    assert "claim_versions" in caplog.text
    assert claim_id in caplog.text


def test_disputed_evidence_is_visible_on_the_claim_and_in_history(client):
    created = _create_investigation(client)
    claim = created["claims"][0]
    claim_id = claim["id"]

    challenged = client.post(
        f"/api/investigations/{created['id']}/claims/{claim_id}/challenge",
        json={"source_record_id": "OPS-101", "quote": OPS_101_QUOTE, "reason": "probe the disputed verdict"},
    )
    assert challenged.status_code == 200, challenged.text
    body = challenged.json()
    assert sorted(body) == ["after", "before", "reason", "recomputed_claim_ids", "version"]
    assert body["before"][claim["hypothesis_id"]]["status"] == "PARTIAL"

    after = client.get(f"/api/investigations/{created['id']}").json()
    updated = next(c for c in after["claims"] if c["id"] == claim_id)
    assert updated["status"] == "PARTIAL"
    assert updated["version"] == 2
    disputed = [e for e in updated["evidence"] if e["disputed"]]
    assert [e["source_record_id"] for e in disputed] == ["OPS-101"]

    history = client.get(f"/api/investigations/{created['id']}/history")
    assert history.status_code == 200
    events = [(entry["version"], entry["event"]) for entry in history.json()]
    assert events == [(1, "CREATED"), (2, "CHALLENGE")]

    # Drift: nothing on the claim says it was demoted. A caller that renders
    # status and confidence alone cannot tell this PARTIAL from one that was never
    # challenged; the dispute is only in evidence[].disputed and the history feed.
    assert "disput" not in updated["summary"].lower()
    assert "disput" not in updated["uncertainty"].lower()
