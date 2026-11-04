"""Sixth probe batch: storage integrity and grounding identity.

Two questions. First, what does the API do when a stored row is not what the writer
intended — the local SQLite file is the whole trust boundary here, and a half-written or
edited row must not become a stack trace. Second, does grounding bind a quote to *the
record the client named*, or merely to some record that happens to contain it?
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest

from app import store
from app.main import app

QUESTION = "Why was the checklist unavailable during handover?"


def call(method: str, path: str, *, json_body=None):
    async def send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json_body)

    return asyncio.run(send())


@pytest.fixture()
def db(monkeypatch):
    path = store.DATA_DIR / f".integrity-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()
    return path


# 1. A claim row whose JSON is truncated must surface as a bounded error that names
#    the row, never a traceback or a partially populated claim — and it must not
#    make a healthy investigation created afterwards unreadable.
@pytest.mark.parametrize("corrupt", ['{"id": "x", ', "not json at all", "[]", ""])
def test_a_corrupt_claim_row_does_not_produce_a_stack_trace(db, corrupt):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    investigation_id = created["id"]
    claim_id = created["claims"][0]["id"]

    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "UPDATE claim_versions SET claim_json=? WHERE investigation_id=? AND claim_id=?",
            (corrupt, investigation_id, claim_id),
        )
        connection.commit()
    finally:
        connection.close()

    response = call("GET", f"/api/investigations/{investigation_id}")

    # 503, not 500: the failure is a known unreadable row, reported as an outage of
    # the local store, with one fixed sentence and nothing of the stored text.
    assert response.status_code == 503, response.status_code
    body = response.text
    assert "Traceback" not in body
    assert "claim_versions" not in body
    assert "sqlite3" not in body.lower()

    # The client body cannot name the row, so the error must: table, row id, column.
    with pytest.raises(store.CorruptStoredRow) as error:
        store.get_investigation(investigation_id)
    assert error.value.table == "claim_versions"
    assert error.value.row_id == claim_id
    assert error.value.field == "claim_json"
    assert claim_id in str(error.value)

    # Localised: a fresh investigation, in the same table, is created and served.
    healthy = call("POST", "/api/investigations", json_body={"question": QUESTION})
    assert healthy.status_code == 201, healthy.status_code
    served = call("GET", f"/api/investigations/{healthy.json()['id']}")
    assert served.status_code == 200, served.status_code
    assert served.json()["claims"]


# 2. A record whose timestamp is not a timestamp is the same class of problem —
#    but here the read needs many rows, so the list degrades and reports the skip
#    instead of failing every record in the table.
def test_a_record_with_an_unparseable_timestamp_is_bounded(db):
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "INSERT OR REPLACE INTO records(id,timestamp,department,text,tags_json,restricted,source_group)"
            " VALUES(?,?,?,?,?,?,?)",
            ("BAD-TS", "yesterday-ish", "Front Office", "The checklist binder was missing.", "[]", 0, "BAD-TS"),
        )
        connection.commit()
    finally:
        connection.close()

    listed = call("GET", "/api/records")
    assert listed.status_code == 200, listed.status_code
    assert "BAD-TS" not in [record["id"] for record in listed.json()]
    assert "yesterday-ish" not in listed.text

    # The skip is reported, and it names the column to repair.
    records, skipped = store.list_records_with_report()
    assert [row.row_id for row in skipped] == ["BAD-TS"]
    assert skipped[0].table == "records"
    assert skipped[0].field == "timestamp"
    assert records

    # The write path still assesses the readable corpus.
    response = call("POST", "/api/investigations", json_body={"question": QUESTION})
    # A verdict is a claim about the whole corpus, so it is refused rather than
    # computed over a corpus that is quietly missing a row. The list still degrades
    # and reports; only the write path fails closed.
    assert response.status_code == 503, response.status_code
    assert "yesterday-ish" not in response.text
    assert "Traceback" not in response.text
    assert "fromisoformat" not in response.text


# 3. Grounding binds to the named record: a real quote from record A submitted under
#    record B's id must be refused, not accepted because some record contains it.
def test_a_quote_is_bound_to_the_record_that_was_named(db):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    claim = created["claims"][0]
    named = claim["evidence"][0]["source_record_id"]

    records = {record.id: record for record in store.list_records()}
    other = next(record.id for record in records.values() if record.id != named)
    foreign_quote = records[other].text[:60]

    response = call(
        "POST",
        f"/api/investigations/{created['id']}/claims/{claim['id']}/challenge",
        json_body={"source_record_id": named, "quote": foreign_quote, "reason": "cross-record probe"},
    )

    assert response.status_code == 422, response.status_code
    assert "quote" in response.text.lower()


# 4. The route-variant hole: an exempt path must be exempt only as itself. A trailing
#    slash or a doubled slash must not create a second unmetered route.
def test_only_the_exact_health_path_is_exempt(db):
    from app import main as main_module
    from app.rate_limit import TokenBucketRateLimiter

    original = main_module.rate_limiter
    main_module.rate_limiter = TokenBucketRateLimiter(limit=1, window_seconds=60.0)
    try:
        first = call("GET", "/api/health/")
        second = call("GET", "/api/health/")
        assert first.status_code != 429
        assert second.status_code in {404, 429}, second.status_code
    finally:
        main_module.rate_limiter = original
