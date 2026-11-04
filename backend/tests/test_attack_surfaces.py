"""Attack-surface probes that assert fail-closed behaviour, not features.

Each test either passes (the surface is closed) or fails with the exact status the
probe observed, which is the finding. Nothing here is aspirational: where the
current answer is merely *acceptable* rather than ideal, the test asserts the
acceptable bound and the report says why.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app import main as main_module, store
from app.main import app
from app.rate_limit import TokenBucketRateLimiter

QUESTION = "Why was the checklist unavailable during handover?"


def call(method: str, path: str, *, content: bytes | None = None, headers=None, json_body=None):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            if content is not None:
                return await client.request(method, path, content=content, headers=headers or {})
            return await client.request(method, path, json=json_body, headers=headers or {})

    return asyncio.run(send())


@pytest.fixture()
def db(monkeypatch):
    path = store.DATA_DIR / f".attack-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()
    return path


# 1. A lone surrogate is legal in a JSON escape and illegal in UTF-8/SQLite.
def test_a_lone_surrogate_in_the_question_is_refused_not_a_500(db):
    body = b'{"question": "\\ud800' + QUESTION.encode() + b'", "preset_id": null}'
    response = call("POST", "/api/investigations", content=body,
                    headers={"content-type": "application/json"})

    assert response.status_code in (400, 422), response.text


# 2. NaN/Infinity are accepted by Python's json but are not JSON.
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_refused(db, literal):
    body = ('{"question": "%s", "preset_id": %s}' % (QUESTION, literal)).encode()
    response = call("POST", "/api/investigations", content=body,
                    headers={"content-type": "application/json"})

    assert response.status_code in (400, 422), response.text


# 3. Duplicate keys: the last one wins in every JSON parser, so the risk is not
# corruption but a second interpretation of the same body by a proxy.
def test_duplicate_keys_resolve_deterministically(db):
    body = ('{"question": "%s", "question": "x", "preset_id": null}' % QUESTION).encode()
    response = call("POST", "/api/investigations", content=body,
                    headers={"content-type": "application/json"})

    # Last-wins means "x" — too short, so 422. The point is that it is not 201.
    assert response.status_code == 422, response.text


# 4. A JSON body with a non-JSON content type must not be silently parsed.
def test_a_json_body_with_a_text_content_type_is_not_parsed(db):
    response = call("POST", "/api/investigations",
                    content=json.dumps({"question": QUESTION, "preset_id": None}).encode(),
                    headers={"content-type": "text/plain"})

    assert response.status_code == 422, response.text


# 5. Path parameters: traversal and SQL metacharacters reach the store query.
@pytest.mark.parametrize("hostile", [
    "../../etc/passwd",
    "..%2f..%2fetc%2fpasswd",
    "' OR 1=1 --",
    "'; DROP TABLE investigations; --",
    "%00",
])
def test_hostile_investigation_ids_are_not_found(db, hostile):
    response = call("GET", f"/api/investigations/{hostile}")

    assert response.status_code in (404, 400), response.text
    # The table must still be there.
    assert call("GET", "/api/records").status_code == 200


# 6. The challenge route's record id goes into a query too.
def test_a_sql_metacharacter_record_id_is_a_404_not_a_database_error(db):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION, "preset_id": None})
    assert created.status_code == 201, created.text
    body = created.json()

    response = call(
        "POST",
        f"/api/investigations/{body['id']}/claims/{body['claims'][0]['id']}/challenge",
        json_body={"source_record_id": "'; DROP TABLE records; --", "quote": "abc",
                   "reason": "the binder was present"},
    )

    assert response.status_code == 404, response.text
    assert call("GET", "/api/records").status_code == 200


# 7. Rate limiting must key on the transport peer, not a header the client controls.
def test_forwarded_for_headers_cannot_buy_a_fresh_bucket(monkeypatch, db):
    limiter = TokenBucketRateLimiter(limit=1, window_seconds=60.0)
    monkeypatch.setattr(main_module, "rate_limiter", limiter)

    # /api/health is exempt from the limiter, so a metered route is the probe here.
    first = call("GET", "/api/records", headers={"x-forwarded-for": "203.0.113.9"})
    second = call("GET", "/api/records", headers={"x-forwarded-for": "198.51.100.7"})

    assert first.status_code == 200
    assert second.status_code == 429, "a spoofed header bought a second bucket"


# 8. A hostile client cannot grow the limiter's key map without bound.
def test_the_limiter_key_map_is_capped():
    limiter = TokenBucketRateLimiter(limit=1, window_seconds=60.0)

    for index in range(5_000):
        limiter.check(f"10.0.{index // 256}.{index % 256}")

    assert len(limiter._buckets) <= 1_024  # the cap the module declares


# 9. Two sequential challenges are legal — each reads the revision the last one
# wrote. The race to test is two writers holding the SAME snapshot.
def test_two_sequential_challenges_both_commit_and_bump_the_version(db):
    created = call("POST", "/api/investigations", json_body={"question": QUESTION, "preset_id": None})
    body = created.json()
    url = f"/api/investigations/{body['id']}/claims/{body['claims'][0]['id']}/challenge"

    first = call("POST", url, json_body={"source_record_id": "OPS-101", "quote": "binder",
                                         "reason": "the binder was present"})
    second = call("POST", url, json_body={"source_record_id": "OPS-101", "quote": "binder",
                                          "reason": "the binder was present"})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["version"] == first.json()["version"] + 1


def test_two_threads_holding_one_snapshot_produce_exactly_one_winner(db):
    import threading

    created = call("POST", "/api/investigations", json_body={"question": QUESTION, "preset_id": None})
    body = created.json()
    investigation_id = body["id"]
    claim_id = body["claims"][0]["id"]

    snapshot = store.get_challenge_snapshot(investigation_id, claim_id, "OPS-101")
    assert snapshot is not None

    barrier = threading.Barrier(2)
    results = []

    def attempt():
        barrier.wait()
        try:
            store.apply_challenge(
                investigation_id, claim_id, "the binder was present", "OPS-101", "binder",
                expected_revision=snapshot["revision"],
                expected_claims=snapshot["claims"],
                revised_claims=dict(snapshot["claims"]),
            )
            results.append("committed")
        except store.StaleRevision:
            results.append("stale")
        except Exception as exc:  # noqa: BLE001 - the probe records what happened
            results.append(type(exc).__name__)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["committed", "stale"], results
