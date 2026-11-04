"""Threat row H8: the API refuses a caller that exceeds the volume bound.

The limiter is a module attribute, so this test swaps in a one-token bucket rather
than flooding the default 600/minute. If the middleware is removed or stops
consulting the limiter, these tests fail.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import main as main_module
from app.main import app
from app.rate_limit import TokenBucketRateLimiter


def request(method: str, path: str):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path)

    return asyncio.run(send())


@pytest.fixture()
def one_token(monkeypatch):
    monkeypatch.setattr(main_module, "rate_limiter", TokenBucketRateLimiter(limit=1, window_seconds=60.0))


def test_the_second_call_in_a_window_is_refused_with_retry_after(one_token):
    first = request("GET", "/api/records")
    second = request("GET", "/api/records")

    assert first.status_code != 429
    assert second.status_code == 429
    assert second.json() == {"detail": "Too many requests; retry later."}
    assert int(second.headers["Retry-After"]) >= 1


def test_a_refusal_does_not_reach_the_route(one_token):
    """A limited caller must not be able to make the route do work."""
    # A path with no route at all: if the refusal came after routing, this would be
    # a 404 rather than a 429.
    request("GET", "/api/not-a-route")
    refused = request("GET", "/api/not-a-route")

    assert refused.status_code == 429


def test_health_stays_available_when_the_bucket_is_empty(one_token):
    """The probe must answer during the flood it is meant to describe."""
    assert request("GET", "/api/records").status_code != 429
    assert request("GET", "/api/records").status_code == 429

    health = request("GET", "/api/health")
    assert health.status_code == 200
    assert health.json()["status"] in {"ok", "degraded", "misconfigured"}


def test_the_limit_is_per_client_not_global(monkeypatch):
    limiter = TokenBucketRateLimiter(limit=2, window_seconds=60.0)
    monkeypatch.setattr(main_module, "rate_limiter", limiter)

    assert limiter.check("client-a").allowed
    assert limiter.check("client-a").allowed
    assert not limiter.check("client-a").allowed
    assert limiter.check("client-b").allowed
