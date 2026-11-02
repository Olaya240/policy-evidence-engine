"""Eleventh probe batch: can an identifier address a claim outside its investigation?

Every route is `/api/investigations/{iid}/claims/{cid}/challenge`. If the store resolves
`cid` alone, then two investigations can be made to write into each other, and the URL's
scope is decorative.
"""

from __future__ import annotations

import asyncio
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
    path = store.DATA_DIR / f".scope-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()
    return path


def two_investigations():
    first = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    second = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    return first, second


def test_a_claim_id_cannot_be_addressed_through_another_investigation(db):
    first, second = two_investigations()
    dependency = first["claims"][0]["evidence"][0]

    response = call(
        "POST",
        f"/api/investigations/{second['id']}/claims/{first['claims'][0]['id']}/challenge",
        json_body={
            "source_record_id": dependency["source_record_id"],
            "quote": dependency["quote"],
            "reason": "cross-scope probe",
        },
    )
    # Claim ids are hypothesis ids, so the same id exists in both investigations: the
    # path's investigation decides the target, and only that one may move.
    assert response.status_code == 200, response.text

    after_first = call("GET", f"/api/investigations/{first['id']}").json()
    after_second = call("GET", f"/api/investigations/{second['id']}").json()
    assert after_first["claims"][0]["version"] == first["claims"][0]["version"]
    assert after_second["claims"][0]["version"] == first["claims"][0]["version"] + 1


@pytest.mark.parametrize("bad_id", [
    "..",
    "%2e%2e%2frecords",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "'; DROP TABLE records; --",
    "%00",
    "0" * 300,
])
def test_identifier_path_traversal_and_injection_are_refused(db, bad_id):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    response = call("GET", f"/api/investigations/{bad_id}")

    assert response.status_code in {404, 422}, response.status_code
    assert "Traceback" not in response.text
    assert "sqlite" not in response.text.lower()
    # The corpus is intact afterwards.
    assert call("GET", "/api/records").status_code == 200


def test_history_of_an_unknown_investigation_is_404_not_empty(db):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION}).json()
    other = "0" * 32
    assert other != created["id"]
    response = call("GET", f"/api/investigations/{other}/history")
    assert response.status_code == 404, response.status_code
