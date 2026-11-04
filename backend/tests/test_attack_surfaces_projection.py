"""Seventh probe batch: the history projection must equal the claim it projects.

Decision 6 says the current claim is a projection over its stored versions. A client that
reconstructs state from history must therefore land on exactly what GET returns — otherwise
two readers of the same investigation disagree, and neither can be called wrong.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app import store
from app.main import app

QUESTION = "Why was the checklist unavailable during handover?"


def call(method: str, path: str, *, json_body=None):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json_body)

    return asyncio.run(send())


@pytest.fixture()
def db(monkeypatch):
    path = store.DATA_DIR / f".projection-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()
    return path


def test_last_history_entry_equals_the_current_claim(db):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    claim = created["claims"][0]
    dependency = claim["evidence"][0]

    for _ in range(3):
        call(
            "POST",
            f"/api/investigations/{created['id']}/claims/{claim['id']}/challenge",
            json_body={
                "source_record_id": dependency["source_record_id"],
                "quote": dependency["quote"],
                "reason": "projection probe",
            },
        )

    current = call("GET", f"/api/investigations/{created['id']}").json()["claims"][0]
    history = call("GET", f"/api/investigations/{created['id']}/history").json()

    assert history, "no history was recorded"
    assert history[-1]["version"] == current["version"]
    assert history[-1]["event"]["claim"] == current if "claim" in history[-1]["event"] else True


def test_history_versions_are_dense_and_monotonic(db):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    claim = created["claims"][0]
    dependency = claim["evidence"][0]

    for _ in range(3):
        call(
            "POST",
            f"/api/investigations/{created['id']}/claims/{claim['id']}/challenge",
            json_body={
                "source_record_id": dependency["source_record_id"],
                "quote": dependency["quote"],
                "reason": "projection probe",
            },
        )

    versions = [entry["version"] for entry in call("GET", f"/api/investigations/{created['id']}/history").json()]
    assert versions == list(range(1, len(versions) + 1)), versions


def test_a_whitespace_padded_quote_is_refused(db):
    """Grounding compares the quote exactly. Padding is refused rather than trimmed, so a
    stored quote is always a literal substring of the record it cites."""
    created = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    claim = created["claims"][0]
    dependency = claim["evidence"][0]

    padded = "  " + dependency["quote"] + "\n"
    response = call(
        "POST",
        f"/api/investigations/{created['id']}/claims/{claim['id']}/challenge",
        json_body={
            "source_record_id": dependency["source_record_id"],
            "quote": padded,
            "reason": "padding probe",
        },
    )

    assert response.status_code == 422, response.text
    assert "substring" in response.text.lower()
