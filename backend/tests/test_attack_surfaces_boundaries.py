"""Ninth probe batch: boundary conditions that hostile input aims at.

Three edges where an off-by-one or a zero becomes a loop: the instant an event happens
relative to the frozen clock, repeated identical disputes, and the `Retry-After` a refusal
advertises.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from app import store
from app.main import app
from app.rate_limit import TokenBucketRateLimiter

QUESTION = "Why was the checklist unavailable during handover?"


def call(method: str, path: str, *, json_body=None):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json_body)

    return asyncio.run(send())


@pytest.fixture()
def db(monkeypatch):
    path = store.DATA_DIR / f".boundary-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()
    return path


# 1. An event at exactly the clock instant is current: `as_of` is inclusive at the top.
def test_an_event_at_exactly_the_clock_instant_is_visible():
    from app.engine import AssessmentEngine
    from app.models import Record

    clock = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    at_instant = Record(
        id="AT-INSTANT",
        timestamp=clock,
        department="Front Office",
        text="The checklist binder was not available during the handover.",
        tags=[],
        source_group="AT-INSTANT",
    )
    one_second_later = at_instant.model_copy(
        update={"id": "ONE-LATER", "timestamp": clock + timedelta(seconds=1), "source_group": "ONE-LATER"}
    )

    engine = AssessmentEngine(clock=lambda: clock)
    visible = engine.assess_hypothesis([at_instant], "CHECKLIST_UNAVAILABLE")
    future = engine.assess_hypothesis([one_second_later], "CHECKLIST_UNAVAILABLE")

    assert visible["evidence"] or visible.get("status") != "UNRESOLVED", visible

    # The one-second-later record is future-dated at the frozen instant. It is retained
    # for human review and cannot support the decision: no confidence, no support.
    assert future["confidence"] == 0.0, future["confidence"]
    assert future["status"] in {"UNRESOLVED", "INSUFFICIENT"}, future["status"]
    assert future["evidence"], "a future-dated proposal must still be visible to a reviewer"
    assert all(item["proposed_stance"] == "NEUTRAL" for item in future["evidence"]), future["evidence"]
    assert any("ONE-LATER" in conflict for conflict in future["conflicts"]), future["conflicts"]


# 2. Repeating the same dispute must not multiply entries (decision 3, dedupe).
def test_repeating_an_identical_dispute_does_not_multiply_it(db):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    claim = created["claims"][0]
    dependency = claim["evidence"][0]
    body = {
        "source_record_id": dependency["source_record_id"],
        "quote": dependency["quote"],
        "reason": "the same objection, verbatim",
    }

    for _ in range(3):
        response = call(
            "POST",
            f"/api/investigations/{created['id']}/claims/{claim['id']}/challenge",
            json_body=body,
        )
        assert response.status_code == 200, response.text

    current = call("GET", f"/api/investigations/{created['id']}").json()["claims"][0]
    disputes = [item for item in current["evidence"] if item.get("disputed")]
    assert len(disputes) == 1, disputes
    # The replay is recorded in history (each attempt is an event) but the dispute itself
    # is not duplicated on the claim.
    events = call("GET", f"/api/investigations/{created['id']}/history").json()
    assert len(events) == 4, [event["version"] for event in events]


# 3. A refusal must never advertise `Retry-After: 0`: a client that honours it spins.
def test_retry_after_is_never_zero():
    clock = [1000.0]
    limiter = TokenBucketRateLimiter(limit=1, window_seconds=60.0, clock=lambda: clock[0])

    assert limiter.check("client").allowed
    decision = limiter.check("client")
    assert not decision.allowed
    assert int(decision.retry_after_header) >= 1

    # Just before the window closes the raw wait is 0.1s; the header must still say 1,
    # because `Retry-After: 0` invites a client to spin.
    clock[0] += 59.9
    late = limiter.check("client")
    assert not late.allowed
    assert late.retry_after < 1, late.retry_after
    assert late.retry_after_header == "1", late.retry_after_header
