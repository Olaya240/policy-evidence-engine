"""Slice-2 regressions: response bounding, budget gate, dispatch authorisation.

Each test here corresponds to a property that slice 2 of the audit asserted and
that no test pinned before. They are deliberately shaped as invariants (a code
that must fire, an object that must not be accepted) rather than as snapshots.
"""

import asyncio

import pytest

from app import provider_safety as ps


class FakeResponse:
    def __init__(self, chunks, content_length=None, close_error=None, ignore_window=False):
        self._chunks = list(chunks)
        self.content_length = content_length
        self.close_error = close_error
        self.ignore_window = ignore_window
        self.closed = False

    async def read_chunk(self, n):
        if not self._chunks:
            return b""
        if self.ignore_window:
            return self._chunks.pop(0)
        data = self._chunks[0][:n]
        self._chunks[0] = self._chunks[0][n:]
        if not self._chunks[0]:
            self._chunks.pop(0)
        return data

    async def aclose(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def read(response):
    return asyncio.run(ps._read_bounded_response(response))


def test_a_non_bytes_chunk_is_its_own_error_not_a_size_verdict():
    response = FakeResponse([bytearray(b"{}")])
    with pytest.raises(ps.ProviderSafetyError) as raised:
        read(response)
    assert raised.value.code == "malformed_response_body"


def test_over_delivery_past_the_requested_window_is_refused():
    response = FakeResponse([b"a" * (ps.MAX_RESPONSE_READ_CHUNK_BYTES + 1)], ignore_window=True)
    with pytest.raises(ps.ProviderSafetyError) as raised:
        read(response)
    assert raised.value.code == "response_too_large"


def test_a_body_exactly_at_the_cap_is_accepted_and_one_byte_over_is_not():
    at_cap = FakeResponse([b"a" * ps.MAX_RESPONSE_BYTES])
    assert len(read(at_cap)) == ps.MAX_RESPONSE_BYTES

    over = FakeResponse([b"a" * ps.MAX_RESPONSE_BYTES, b"a"])
    with pytest.raises(ps.ProviderSafetyError) as raised:
        read(over)
    assert raised.value.code == "response_too_large"


def test_a_declared_length_above_the_cap_is_refused_before_any_read():
    response = FakeResponse([], content_length=str(ps.MAX_RESPONSE_BYTES + 1))
    with pytest.raises(ps.ProviderSafetyError) as raised:
        read(response)
    assert raised.value.code == "response_too_large"


@pytest.mark.parametrize("header", ["", " 42", "+42", "4_2", "٤٢", "42.0"])
def test_a_non_canonical_content_length_is_malformed(header):
    with pytest.raises(ps.ProviderSafetyError) as raised:
        read(FakeResponse([b"{}"], content_length=header))
    assert raised.value.code == "malformed_response_headers"


def test_a_close_failure_does_not_replace_the_safety_verdict():
    response = FakeResponse([bytearray(b"{}")], close_error=RuntimeError("socket gone"))
    with pytest.raises(ps.ProviderSafetyError) as raised:
        read(response)
    assert raised.value.code == "malformed_response_body"
    assert response.closed


def test_a_declared_length_that_disagrees_with_the_body_is_malformed():
    with pytest.raises(ps.ProviderSafetyError) as raised:
        read(FakeResponse([b"ab"], content_length="3"))
    assert raised.value.code == "malformed_response"


def test_the_gate_counts_attempts_and_refuses_past_the_limit():
    gate = ps.ProviderCallGate(
        ps.ProviderBudgetConfig(
            enabled=True,
            max_requests=2,
            max_estimated_cost_usd="0.20",
            conservative_cost_per_request_usd="0.10",
        )
    )
    gate.authorize_request()
    gate.authorize_request()
    with pytest.raises(ps.ProviderSafetyError) as raised:
        gate.authorize_request()
    assert raised.value.code == "request_limit"
    assert gate.request_count == 2


def test_an_unconfigured_gate_fails_closed_rather_than_being_unlimited():
    """`ProviderBudgetConfig()` is the kill switch, not an absent budget: a gate
    that was not explicitly enabled refuses every call."""
    gate = ps.ProviderCallGate()
    with pytest.raises(ps.ProviderSafetyError) as raised:
        gate.authorize_request()
    assert raised.value.code == "provider_disabled"
    assert gate.request_count == 0


# --------------------------------------------------------------------------
# Dispatch authorisation: minting needs no network, so single-use is testable
# --------------------------------------------------------------------------

def _minted(payload=b"{}", timeout=5.0):
    from app.httpx_transport import BasetenMuseSparkOpenTransport

    transport = BasetenMuseSparkOpenTransport(api_key="test-key-not-used")
    gate = ps.ProviderCallGate(ps.ProviderBudgetConfig(
        enabled=True, max_requests=2,
        max_estimated_cost_usd="0.20",
        conservative_cost_per_request_usd="0.10",
    ))
    adapter = ps.BasetenMuseSparkOpenAdapter(transport, gate)
    boundary = ps.MandatoryProviderBoundary(adapter)
    authorization = ps._TransportDispatchAuthorization(
        transport, adapter, boundary, payload, timeout,
        _seal=ps._TRANSPORT_DISPATCH_SEAL,
    )
    return transport, payload, timeout, authorization


def test_a_dispatch_authorization_is_consumable_exactly_once():
    transport, payload, timeout, authorization = _minted()
    consume = ps._consume_transport_dispatch_authorization

    assert ps._valid_transport_dispatch_authorization(authorization, transport, payload, timeout)
    assert consume(authorization, transport, payload, timeout) is True
    assert consume(authorization, transport, payload, timeout) is False
    assert ps._valid_transport_dispatch_authorization(authorization, transport, payload, timeout) is False


def test_an_authorization_does_not_transfer_to_an_equal_but_distinct_payload():
    transport, _payload, timeout, authorization = _minted(payload=b"{}")
    # Equal bytes, distinct object: the binding is by identity. Building it at
    # runtime defeats CPython's constant folding, which would otherwise hand back
    # the very same literal object and make this test pass for the wrong reason.
    other = bytes(bytearray(b"{}"))
    assert other == _payload and other is not _payload

    assert ps._consume_transport_dispatch_authorization(
        authorization, transport, other, timeout) is False


def test_an_authorization_is_bound_to_its_timeout():
    transport, payload, _timeout, authorization = _minted(timeout=5.0)
    assert ps._consume_transport_dispatch_authorization(
        authorization, transport, payload, 6.0) is False
