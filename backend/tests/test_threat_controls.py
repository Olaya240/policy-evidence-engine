"""Threat -> control -> test.

Each test here corresponds to a row of `ct3/audit/THREAT-MODEL.md` and is written so
that removing the named control makes it fail. Nothing asserts a posture the code does
not have: where the control is absent (no authentication, by declaration), the test
asserts the *declaration* instead of inventing a protection.
"""

from __future__ import annotations

import asyncio
import gc
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app import main as main_module, store
from app.engine import ProviderError
from app.main import app
from app.mock_provider import SEED_RECORDS

RESTRICTED = [record for record in SEED_RECORDS if record.restricted]
ALLOWED_ORIGIN = "http://localhost:5174"
QUESTION = "Why was the checklist unavailable during handover?"


class Client:
    def request(self, method, path, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)


def _cleanup(db_path: Path) -> None:
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


@pytest.fixture()
def client(monkeypatch):
    db_path = store.DATA_DIR / f".threat-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    store.initialize_database()
    try:
        yield Client()
    finally:
        _cleanup(db_path)


def test_cors_admits_the_local_ui_and_refuses_any_other_origin(client):
    """Control: CORS allowlist. Removing the middleware or widening it fails this."""
    allowed = client.request(
        "OPTIONS", "/api/investigations",
        headers={"Origin": ALLOWED_ORIGIN,
                 "Access-Control-Request-Method": "POST"},
    )
    foreign = client.request(
        "OPTIONS", "/api/investigations",
        headers={"Origin": "https://attacker.example",
                 "Access-Control-Request-Method": "POST"},
    )

    assert allowed.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert foreign.headers.get("access-control-allow-origin") is None
    assert allowed.headers.get("access-control-allow-credentials") is None


def test_no_restricted_text_leaves_through_the_records_endpoint(client):
    """Control: the restriction filter in store.list_records/visible_records."""
    body = client.get("/api/records").text

    assert RESTRICTED, "the seed corpus must contain a restricted record"
    for record in RESTRICTED:
        assert record.text not in body
        assert record.id not in body


def test_a_restricted_record_is_indistinguishable_from_an_absent_one(client):
    """Control: 404 for both, so the route is not an existence oracle."""
    restricted = RESTRICTED[0]
    created = client.post("/api/investigations", json={"question": QUESTION, "preset_id": None})
    assert created.status_code == 201
    investigation_id = created.json()["id"]
    claim_id = created.json()["claims"][0]["id"]

    restricted_response = client.post(
        f"/api/investigations/{investigation_id}/claims/{claim_id}/challenge",
        json={"source_record_id": restricted.id, "quote": "abc", "reason": "the binder was present"},
    )
    absent_response = client.post(
        f"/api/investigations/{investigation_id}/claims/{claim_id}/challenge",
        json={"source_record_id": "NO-SUCH-RECORD", "quote": "abc", "reason": "the binder was present"},
    )

    assert restricted_response.status_code == absent_response.status_code == 404
    assert restricted_response.json() == absent_response.json()


def test_a_provider_fault_never_echoes_record_text(client, monkeypatch):
    """Control: the ProviderError handler returns a fixed body."""
    def explode(*_args, **_kwargs):
        raise ProviderError("provider_failure")

    monkeypatch.setattr(type(main_module.engine), "investigate", explode)

    response = client.post("/api/investigations", json={"question": QUESTION, "preset_id": None})

    assert response.status_code == 503
    body = response.text
    for record in SEED_RECORDS:
        assert record.text not in body


def test_an_uninitialised_database_is_a_503_not_a_500(monkeypatch):
    """Control: require_database and the DatabaseUnavailable handler."""
    missing = store.DATA_DIR / f".missing-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(missing))

    response = Client().get("/api/records")

    assert response.status_code == 503


def test_a_malformed_request_is_refused_before_the_engine_sees_it(client):
    """Control: Pydantic validation (forbid extras, bounded strings)."""
    oversized = client.post(
        "/api/investigations",
        json={"question": "q" * 100_000, "preset_id": None},
    )
    unknown_field = client.post(
        "/api/investigations",
        json={"question": "q", "preset_id": None, "records": ["OPS-101"]},
    )

    assert oversized.status_code == 422
    assert unknown_field.status_code == 422


def test_the_health_endpoint_declares_the_posture_it_has(client):
    """No authentication exists; the endpoint must say so rather than imply it."""
    body = client.get("/api/health").json()

    assert body["authentication"] is False
    assert body["synthetic_data_only"] is True
    assert body["human_review_required"] is True
    assert body["status"] == "ok"
