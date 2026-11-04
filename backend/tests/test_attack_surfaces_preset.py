"""Eighth probe batch: preset binding and proposal budget under hostile input.

The preset is what makes a question map to a hypothesis, so it is the one place where a
client can try to *choose* the verdict's frame. And every claim has a bounded proposal list,
so a corpus large enough to exceed it must be refused, not silently truncated.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx
import pytest

from app import store
from app.main import app

CHECKLIST_Q = "Why was the checklist unavailable during handover?"
PRESET_Q = "Did checklist availability contribute to missing handover information?"


def call(method: str, path: str, *, json_body=None):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json_body)

    return asyncio.run(send())


@pytest.fixture()
def db(monkeypatch):
    path = store.DATA_DIR / f".preset-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()
    return path


def test_a_preset_with_a_mismatched_question_is_refused(db):
    response = call(
        "POST",
        "/api/investigations",
        json_body={"question": "Why was the team short staffed?", "preset_id": "checklist_access"},
    )
    assert response.status_code == 422, response.text


def test_an_unknown_preset_is_a_client_error_not_a_crash(db):
    response = call("POST", "/api/investigations", json_body={"question": CHECKLIST_Q, "preset_id": "NOT_A_PRESET"})
    assert 400 <= response.status_code < 500, response.status_code


def test_a_preset_cannot_be_smuggled_as_a_non_string(db):
    response = call("POST", "/api/investigations", json_body={"question": CHECKLIST_Q, "preset_id": 7})
    assert 400 <= response.status_code < 500, response.status_code


def test_the_matching_preset_returns_exactly_one_claim(db):
    response = call(
        "POST",
        "/api/investigations",
        json_body={"question": PRESET_Q, "preset_id": "checklist_access"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["preset_id"] == "checklist_access"
    assert len(body["claims"]) == 1
    assert body["claims"][0]["hypothesis_id"] == "CHECKLIST_UNAVAILABLE"


def test_a_corpus_over_the_proposal_budget_is_refused_with_a_reason(db):
    """44 records are one past the measured ceiling; the API must say so rather than
    silently assessing a truncated corpus."""
    import sqlite3

    connection = sqlite3.connect(db)
    try:
        for index in range(44):
            connection.execute(
                "INSERT OR REPLACE INTO records(id,timestamp,department,text,tags_json,restricted,source_group)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    f"BULK-{index}",
                    "2026-05-0%dT09:00:00+00:00" % (index % 9 + 1),
                    "Front Office",
                    "The checklist binder was missing at handover, note %d." % index,
                    "[]",
                    0,
                    f"BULK-{index}",
                ),
            )
        connection.commit()
    finally:
        connection.close()

    response = call("POST", "/api/investigations", json_body={"question": CHECKLIST_Q})

    assert response.status_code == 413, response.status_code
    assert "proposal" in response.text.lower() or "budget" in response.text.lower()
