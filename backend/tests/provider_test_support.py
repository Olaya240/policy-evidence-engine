"""Explicit pytest-only seam for exercising bounded calls without network I/O."""
from contextvars import ContextVar
from unittest.mock import patch

from app.httpx_transport import ASSESSMENT_PATH, HttpxAsyncTransport
from app.provider_safety import (
    BoundedTransportProvider,
    MandatoryProviderBoundary,
    MAX_REQUEST_TIMEOUT_SECONDS,
)

_FAKE_TRANSPORT = ContextVar("provider_test_fake_transport", default=None)


async def _dispatch_fake_send(_adapter, payload, *, timeout_seconds):
    transport = _FAKE_TRANSPORT.get()
    if transport is None:
        raise AssertionError("test fake transport was not installed")
    return await transport.send(payload, timeout_seconds=timeout_seconds)


async def bounded_transport_call(transport, request, gate, *, timeout_seconds=MAX_REQUEST_TIMEOUT_SECONDS):
    """Run the application wrapper with its exact adapter and a pytest-local send seam."""
    if type(transport) is HttpxAsyncTransport:
        adapter = transport
        test_patch = None
    else:
        adapter = HttpxAsyncTransport("https://provider.invalid" + ASSESSMENT_PATH)
        test_patch = patch.object(HttpxAsyncTransport, "send", _dispatch_fake_send)

    provider = BoundedTransportProvider(adapter, gate)
    boundary = MandatoryProviderBoundary(provider)
    token = _FAKE_TRANSPORT.set(transport if test_patch is not None else None)
    try:
        if test_patch is None:
            return await provider._assess_async(request, boundary, timeout_seconds=timeout_seconds)
        with test_patch:
            return await provider._assess_async(request, boundary, timeout_seconds=timeout_seconds)
    finally:
        _FAKE_TRANSPORT.reset(token)
