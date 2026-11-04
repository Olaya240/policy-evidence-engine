"""Slice-3 regressions: the guards that had no test.

The audit (`ct3/audit/S03-coverage.md`) found three branches reached by nothing:
the single-flight refusal, the running-loop refusal, and the second-bind refusal.
All three are security guards, so an untested guard is indistinguishable from a
removed one.
"""

import asyncio
from decimal import Decimal

import pytest

from app.httpx_transport import ASSESSMENT_PATH, HttpxAsyncTransport
from app.provider_safety import (
    BoundedTransportProvider,
    MandatoryProviderBoundary,
    ProviderBudgetConfig,
    ProviderCallGate,
    ProviderSafetyError,
    serialize_provider_request,
)
from provider_test_support import bounded_transport_call


def _gate(max_requests=2):
    return ProviderCallGate(ProviderBudgetConfig(
        enabled=True,
        max_requests=max_requests,
        max_estimated_cost_usd=Decimal("0.10") * max_requests,
        conservative_cost_per_request_usd=Decimal("0.10"),
    ))


def _request():
    return serialize_provider_request([], "CHECKLIST_UNAVAILABLE")


def _provider(gate=None):
    adapter = HttpxAsyncTransport("https://provider.invalid" + ASSESSMENT_PATH)
    provider = BoundedTransportProvider(adapter, gate)
    boundary = MandatoryProviderBoundary(provider)
    return provider, boundary


def test_a_second_call_while_one_is_in_flight_is_refused():
    """`concurrent_request` is the only guard against overlapping in-process calls."""

    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()

        class ParkedTransport:
            async def send(self, payload, *, timeout_seconds):
                entered.set()
                await release.wait()

                class Response:
                    content_length = "2"

                    def __init__(self):
                        self.sent = False

                    async def read_chunk(self, n):
                        if self.sent:
                            return b""
                        self.sent = True
                        return b"[]"

                return Response()

        transport = ParkedTransport()
        first = asyncio.create_task(bounded_transport_call(transport, _request(), _gate()))
        await entered.wait()

        with pytest.raises(ProviderSafetyError) as refused:
            await bounded_transport_call(transport, _request(), _gate())
        assert refused.value.code == "concurrent_request"

        release.set()
        assert await first == []

    asyncio.run(exercise())


def test_the_synchronous_entry_refuses_inside_a_running_loop():
    """A nested loop would escape the boundary; the guard must fire, not hang."""
    provider, boundary = _provider()

    async def exercise():
        with pytest.raises(ProviderSafetyError) as refused:
            provider._assess_from_boundary(_request(), boundary)
        assert refused.value.code == "async_context_unsupported"

    asyncio.run(exercise())


def test_the_synchronous_entry_still_works_outside_a_loop():
    """Contrast case: the same call from synchronous code must not be refused."""
    provider, boundary = _provider(gate=_gate())

    class Response:
        content_length = "2"

        def __init__(self):
            self.sent = False

        async def read_chunk(self, n):
            if self.sent:
                return b""
            self.sent = True
            return b"[]"

    async def fake_send(_self, payload, *, timeout_seconds):
        return Response()

    original = HttpxAsyncTransport.send
    HttpxAsyncTransport.send = fake_send
    try:
        assert provider._assess_from_boundary(_request(), boundary) == []
    finally:
        HttpxAsyncTransport.send = original


def test_a_provider_cannot_be_bound_to_a_second_boundary():
    """Rebinding would let two boundaries share one provider, defeating the 1:1 rule."""
    provider, _boundary = _provider()

    with pytest.raises(ProviderSafetyError) as refused:
        MandatoryProviderBoundary(provider)
    assert refused.value.code == "mandatory_boundary_required"
