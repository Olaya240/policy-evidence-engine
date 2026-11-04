"""Fourth probe batch: restricted-data disclosure and resource exhaustion.

The corpus contains one restricted record whose text is a canary
(`RESTRICTED_CANARY_DO_NOT_DISCLOSE_8f2b1d`). Every endpoint the API exposes is a
chance to leak it, and the challenge endpoint is the sharpest: it validates a quote
against a record's text, so a 200/422 difference is a substring oracle over text the
client is not allowed to read.
"""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

import httpx
import pytest

from app import store
from app.main import app

CANARY = "RESTRICTED_CANARY_DO_NOT_DISCLOSE_8f2b1d"
RESTRICTED_ID = "CANARY-RESTRICTED-001"
QUESTION = "Why was the checklist unavailable during handover?"


def call(method: str, path: str, *, json_body=None):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json_body)

    return asyncio.run(send())


@pytest.fixture()
def db(monkeypatch):
    path = store.DATA_DIR / f".canary-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()
    return path


# 1. The canary must not appear in any body the API returns, including the full
#    investigation snapshot and its history, which carry evidence quotes.
def test_the_restricted_canary_appears_in_no_response_body(db):
    bodies = []
    records = call("GET", "/api/records")
    bodies.append(records.text)
    assert RESTRICTED_ID not in records.text

    created = call("POST", "/api/investigations", json_body={"question": QUESTION})
    assert created.status_code == 201
    bodies.append(created.text)
    investigation_id = created.json()["id"]

    fetched = call("GET", f"/api/investigations/{investigation_id}")
    bodies.append(fetched.text)
    history = call("GET", f"/api/investigations/{investigation_id}/history")
    bodies.append(history.text)
    bodies.append(call("GET", "/api/health").text)

    leaked = [body for body in bodies if CANARY in body]
    assert leaked == [], f"restricted canary leaked in {len(leaked)} response(s)"


# 2. The challenge endpoint refuses a restricted record before it compares the
#    quote, so it cannot be used as a substring oracle over hidden text.
def test_challenging_a_restricted_record_is_404_not_a_quote_oracle(db):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION})
    investigation = created.json()
    claim_id = investigation["claims"][0]["id"]

    prefix = CANARY[:6]  # a true substring: 200/422 would both be a leak
    probe = call(
        "POST",
        f"/api/investigations/{investigation['id']}/claims/{claim_id}/challenge",
        json_body={"source_record_id": RESTRICTED_ID, "quote": prefix, "reason": "restricted probe"},
    )

    assert probe.status_code == 404
    assert CANARY not in probe.text

    # And a non-substring must not be distinguishable either: same status.
    miss = call(
        "POST",
        f"/api/investigations/{investigation['id']}/claims/{claim_id}/challenge",
        json_body={"source_record_id": RESTRICTED_ID, "quote": "definitely absent", "reason": "restricted probe"},
    )
    assert miss.status_code == probe.status_code == 404


# 3. A very large question is a validation failure, not a crash or a hang.
def test_a_large_question_is_refused_within_a_second(db):
    started = time.perf_counter()
    response = call("POST", "/api/investigations", json_body={"question": "x" * 200_000})
    elapsed = time.perf_counter() - started

    assert response.status_code in {422, 413}, response.status_code
    assert elapsed < 1.0, f"{elapsed:.2f}s"


# 4. A pathological record text must not trigger regex backtracking in the cue
#    guard. 20 000 repetitions of a negation-adjacent token is the shape that
#    blows up a careless `\s+(\w+\s+)*` pattern.
def test_a_pathological_record_text_is_assessed_in_linear_time(db):
    from app.decision_table import decide_evidence
    from app.engine import AssessmentEngine
    from app.models import Evidence, EvidenceReviewState, Record, Stance
    from datetime import datetime, timezone

    clock = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    hostile = Record(
        id="R1",
        timestamp=clock,
        department="Front Office",
        text=("not " * 2_000) + "the checklist binder was missing at the handover.",
        tags=[],
        source_group=None,
    )
    engine = AssessmentEngine(clock=lambda: clock)

    started = time.perf_counter()
    engine.assess_hypothesis([hostile], "CHECKLIST_UNAVAILABLE")
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"guard took {elapsed:.2f}s on an 8 KB record"

    # A stance decision over a long quote is the other regex path.
    evidence = Evidence(
        source_record_id="R1",
        timestamp=clock,
        quote=("no " * 5_000) + "checklist",
        stance=Stance.SUPPORTS,
        review_state=EvidenceReviewState.ACCEPTED,
        rationale="probe",
        department="Front Office",
        source_group="ops-team",
    )
    started = time.perf_counter()
    decide_evidence([evidence])
    assert time.perf_counter() - started < 1.0


# 5. The same input assessed twice must produce identical output: a verdict that
#    changes between identical calls cannot be reviewed.
def test_assessment_is_deterministic_across_identical_calls(db):
    records = store.list_records()
    from app.engine import AssessmentEngine

    first = AssessmentEngine(clock=lambda: __import__("datetime").datetime(2026, 6, 1, tzinfo=__import__("datetime").timezone.utc)).investigate(records)
    second = AssessmentEngine(clock=lambda: __import__("datetime").datetime(2026, 6, 1, tzinfo=__import__("datetime").timezone.utc)).investigate(records)

    assert first == second


# 6. A record too large for the bounded provider request must not be reported as
#    "provider unavailable": the provider is fine, the corpus is over budget, and
#    the client cannot tell the two apart from a 503.
def test_an_oversized_record_reports_a_corpus_problem_not_provider_outage(db):
    from datetime import datetime, timezone

    clock = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    store.add_record(  # noqa: hasattr-check below
        id="OVERSIZED-1",
        timestamp=clock.isoformat(),
        department="Front Office",
        text=("not " * 5_000) + "the checklist binder was missing.",
        tags=[],
        restricted=False,
        source_group="OVERSIZED-1",
    ) if hasattr(store, "add_record") else _insert_oversized(db, clock)

    response = call("POST", "/api/investigations", json_body={"question": QUESTION})

    assert response.status_code == 413, response.status_code
    detail = response.text.lower()
    assert "unavailable" not in detail and "invalid output" not in detail
    assert "corpus" in detail


def _insert_oversized(db, clock):
    import sqlite3
    import json as json_module

    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "INSERT OR REPLACE INTO records(id,timestamp,department,text,tags_json,restricted,source_group)"
            " VALUES(?,?,?,?,?,?,?)",
            ("OVERSIZED-1", clock.isoformat(), "Front Office",
             ("not " * 5_000) + "the checklist binder was missing.", json_module.dumps([]), 0, "OVERSIZED-1"),
        )
        connection.commit()
    finally:
        connection.close()
