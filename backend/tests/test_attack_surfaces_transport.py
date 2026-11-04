"""Fifth probe batch: transport-level oddities and concurrency.

Everything here is legal HTTP that a client can send without touching the schema:
non-standard JSON literals, duplicate keys, deep nesting, the wrong content type, and
simultaneous writers. The question in each case is whether the API answers with a
bounded status or falls over.
"""

from __future__ import annotations

import json
import threading
from uuid import uuid4

import httpx
import pytest

from app import store
from app.main import app

QUESTION = "Why was the checklist unavailable during handover?"


def post_raw(body: bytes, content_type: str = "application/json"):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post("/api/investigations", content=body, headers={"content-type": content_type})

    return _run(send)


def _run(send):
    import asyncio

    return asyncio.run(send())


@pytest.fixture()
def db(monkeypatch):
    path = store.DATA_DIR / f".transport-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()
    return path


# 1. Non-standard literals are rejected as validation errors, never as 500s.
@pytest.mark.parametrize("body", [
    b'{"question": NaN}',
    b'{"question": Infinity}',
    b'{"question": -Infinity}',
    b'{"question": [1, 2, 3]}',
    b'{"question": {"nested": true}}',
    b'{"question": 12345}',
    b'{}',
    b'[]',
    b'null',
])
def test_non_standard_or_wrong_typed_bodies_are_4xx(db, body):
    response = post_raw(body)
    assert 400 <= response.status_code < 500, response.status_code


# 2. A duplicated key is resolved deterministically and never by accident of ordering:
#    Python's decoder keeps the last one, so the surviving question is the last value.
def test_a_duplicated_key_keeps_the_last_value(db):
    body = json.dumps({"question": QUESTION, "question": QUESTION + " (second)"}).encode()
    response = post_raw(body)

    assert response.status_code == 201, response.status_code
    assert response.json()["question"].endswith("(second)")


# 3. Deeply nested JSON must not exhaust the parser stack.
def test_deeply_nested_json_is_refused_not_crashed(db):
    body = b'{"question": ' + b"[" * 5_000 + b'"x"' + b"]" * 5_000 + b"}"
    response = post_raw(body)
    assert 400 <= response.status_code < 500, response.status_code


# 4. A body sent with a non-JSON content type is a client error, not a 500.
def test_a_wrong_content_type_is_a_client_error(db):
    response = post_raw(json.dumps({"question": QUESTION}).encode(), content_type="text/plain")
    assert 400 <= response.status_code < 500, response.status_code


# 5. Bidi overrides and NULs inside the question are either refused or stored
#    verbatim; what must not happen is a crash, or silent rewriting that makes the
#    stored question differ from the one the verdict was computed over.
def test_bidi_and_nul_in_the_question_are_handled_consistently(db):
    hostile = QUESTION + "\u202e" + "\x00" + "suffix"
    response = post_raw(json.dumps({"question": hostile}).encode())

    assert response.status_code in {201, 422}, response.status_code
    if response.status_code == 201:
        assert response.json()["question"] == hostile


# 6. Concurrent writers: several requests at once against one SQLite file must all
#    answer, and the store must not be left locked.
def test_concurrent_writes_all_answer(db):
    results: list[int] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(post_raw(json.dumps({"question": QUESTION}).encode()).status_code)
        except BaseException as exc:  # noqa: BLE001 - recorded, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == [], errors
    assert len(results) == 6
    assert set(results) <= {201, 409, 503}, results


# 7. Two simultaneous challenges on one claim must not lose an update. If both read
#    version N and both write N+1, the history can show two challenges while the
#    claim version advanced once — two reviewers, one decision silently dropped.
def test_concurrent_challenges_do_not_lose_an_update(db):
    created = post_raw(json.dumps({"question": QUESTION}).encode()).json()
    investigation_id = created["id"]
    claim = created["claims"][0]
    # The challenge endpoint only accepts a record the claim already depends on.
    dependency = claim["evidence"][0]
    record_id = dependency["source_record_id"]
    quote = dependency["quote"]

    body = json.dumps({"source_record_id": record_id, "quote": quote, "reason": "concurrent probe"})

    statuses: list[int] = []

    def send():
        statuses.append(_run_challenge(investigation_id, claim["id"], body.encode()))

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    history = _run_get(f"/api/investigations/{investigation_id}/history")
    current = _run_get(f"/api/investigations/{investigation_id}")
    versions = [entry["version"] for entry in history.json()]

    # Either both writes landed on distinct versions, or the loser was refused with
    # 409. What must never happen is two successes sharing one version.
    assert set(statuses) <= {200, 409}, statuses
    assert len(set(versions)) == len(versions), f"duplicate version in history: {versions}"
    successes = [s for s in statuses if s == 200]
    assert successes, f"no challenge was accepted: {statuses}"  # a vacuous pass proves nothing
    assert len(successes) == len(versions) - 1, (statuses, versions)
    assert current.json()["claims"][0]["version"] == max(versions)


def _run_challenge(investigation_id: str, claim_id: str, body: bytes) -> int:
    import asyncio

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                f"/api/investigations/{investigation_id}/claims/{claim_id}/challenge",
                content=body,
                headers={"content-type": "application/json"},
            )

    return asyncio.run(go()).status_code


def _run_get(path: str):
    import asyncio

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)

    return asyncio.run(go())


# 8. A flood must not blind the health signal. The limiter keyed every path on one
#    bucket, so after 600 requests a client's own `/api/health` returned 429 — the
#    probe was rate limited at exactly the moment an operator needs it.
def test_a_flooded_client_can_still_read_health(db):
    from app import main as main_module

    main_module.rate_limiter.reset()
    # Exhaust whatever key the ASGI transport reports for this client.
    for key in ("127.0.0.1", "testclient", "unknown"):
        for _ in range(600):
            main_module.rate_limiter.check(key)

    refused = post_raw(json.dumps({"question": QUESTION}).encode())
    assert refused.status_code == 429, refused.status_code

    health = _run_get("/api/health")
    assert health.status_code == 200, health.status_code
    assert health.json()["status"] in {"ok", "degraded", "misconfigured"}
