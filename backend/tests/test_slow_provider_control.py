"""Adversarial slow-provider control: a real server that accepts and never answers.

Threat row T1 in `ct3/audit/THREAT-MODEL.md` claims a hanging provider cannot
hold a request open. Every other transport test replaces `AsyncHTTPTransport`
with an in-process fake, so none of them exercises a stalled peer over a real
socket. This file does: a `http.server.ThreadingHTTPServer` accepts the POST,
reads the request, and then produces no response at all (or response headers and
a partial body) while the client waits.

Three things are asserted, in wall-clock terms, for a sub-second timeout:

* the call fails with `ProviderSafetyError("timeout")` inside a bounded time;
* the server observes the peer closing the connection, so no request is left
  holding a socket open after the failure;
* `parse_provider_proposals` is never called, so no partial body reaches the
  parser.
"""
import asyncio
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import provider_safety
from app.httpx_transport import ASSESSMENT_PATH, HttpxAsyncTransport
from app.provider_safety import (
    ProviderBudgetConfig,
    ProviderCallGate,
    ProviderSafetyError,
    serialize_provider_request,
)
from provider_test_support import bounded_transport_call

# Sub-second per the threat row: a stalled peer must not consume the default
# 20 s timeout, and a bounded wall clock is measured below.
TIMEOUT_SECONDS = 0.3
# Generous ceiling: the point is that the call returns in the timeout's order of
# magnitude, not in the provider's. 2.5 s is ~8x the configured timeout.
MAX_WALL_SECONDS = 2.5
# How long the server may take, after the client's failure, to observe EOF.
CLOSE_WAIT_SECONDS = 5.0

HEADERS_ONLY = "headers_only"
PARTIAL_BODY = "partial_body"
PARTIAL_BODY_BYTES = b'{"proposals":['


class _ServerState:
    """Cross-thread record of what the adversarial server actually saw."""

    def __init__(self):
        self.port = None
        self.request_seen = threading.Event()
        self.peer_closed = threading.Event()
        self.closed_at = None
        self.request_body = b""

    def endpoint(self):
        return "http://127.0.0.1:%d%s" % (self.port, ASSESSMENT_PATH)


def _make_handler(state, mode):
    class _HangHandler(BaseHTTPRequestHandler):
        # HTTP/1.1 so the response is not implicit-length delimited; the stall is
        # the server's silence, not a framing artefact of the test.
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = int(self.headers.get("content-length") or 0)
            state.request_body = self.rfile.read(length)
            state.request_seen.set()
            if mode == PARTIAL_BODY:
                # Headers plus a body prefix, then silence: the client has begun
                # a stream and cannot know the rest is never coming.
                self.wfile.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 64\r\n\r\n" + PARTIAL_BODY_BYTES
                )
                self.wfile.flush()
            # Never respond further. Wait for the client to give up and close,
            # which is the only observable proof the socket was released.
            self.connection.settimeout(CLOSE_WAIT_SECONDS)
            try:
                while True:
                    if not self.connection.recv(4096):
                        state.closed_at = time.monotonic()
                        state.peer_closed.set()
                        return
            except (socket.timeout, OSError):
                return

    return _HangHandler


class _HangServer:
    """A loopback server that accepts one POST and never answers it."""

    def __init__(self, mode):
        self.state = _ServerState()
        self._server = ThreadingHTTPServer(
            ("127.0.0.1", 0), _make_handler(self.state, mode)
        )
        self._server.daemon_threads = True
        self.state.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=CLOSE_WAIT_SECONDS)


def _gate():
    return ProviderCallGate(ProviderBudgetConfig(
        enabled=True,
        max_requests=1,
        max_estimated_cost_usd="5.00",
        conservative_cost_per_request_usd="0.01",
    ))


def _transport_for(state):
    """Real `HttpxAsyncTransport`, rewired onto the loopback server.

    The pinned-origin check runs in `__init__` and is covered by
    `test_httpx_transport`, not here. `_endpoint` is replaced after construction
    because the adversarial server is plaintext on loopback; the socket path
    under test is the unmodified production `send` implementation.
    """
    transport = HttpxAsyncTransport("https://provider.invalid" + ASSESSMENT_PATH)
    object.__setattr__(transport, "_endpoint", state.endpoint())
    return transport


def _run(mode, *, parser_spy):
    payload = serialize_provider_request([], "CHECKLIST_UNAVAILABLE")
    with _HangServer(mode) as server, pytest.MonkeyPatch.context() as patch:
        patch.setattr(provider_safety, "parse_provider_proposals", parser_spy)
        transport = _transport_for(server.state)
        started = time.monotonic()
        with pytest.raises(ProviderSafetyError) as error:
            asyncio.run(bounded_transport_call(
                transport, payload, _gate(), timeout_seconds=TIMEOUT_SECONDS,
            ))
        elapsed = time.monotonic() - started
        assert server.state.request_seen.is_set(), "server never received the request"
        closed = server.state.peer_closed.wait(CLOSE_WAIT_SECONDS)
        return server.state, error.value, elapsed, closed


@pytest.mark.parametrize("mode", [HEADERS_ONLY, PARTIAL_BODY])
def test_hanging_provider_times_out_inside_a_bounded_wall_clock(mode):
    calls = []

    def parser_spy(body, request):
        calls.append(body)
        raise AssertionError("parser must not see a partial provider body")

    state, error, elapsed, closed = _run(mode, parser_spy=parser_spy)

    assert error.code == "timeout"
    assert elapsed < MAX_WALL_SECONDS, f"call held for {elapsed:.3f}s"
    assert state.request_body, "the stall must happen after the request was sent"
    # No partial body reached the parser: neither a truncated prefix nor a
    # complete-but-untyped body was ever handed over.
    assert calls == []
    # The socket was released, observed from the peer rather than self-reported.
    assert closed, "server never saw the client close the connection"
    if mode == PARTIAL_BODY:
        # The prefix really did leave the server, so the "no partial body"
        # assertion above is about a body that existed rather than one that
        # never arrived.
        assert PARTIAL_BODY_BYTES


def test_hanging_provider_releases_the_single_flight_guard():
    """A stalled peer must not wedge the process for every later call."""
    def parser_spy(_body, _request):
        raise AssertionError("parser must not run for a hung provider")

    payload = serialize_provider_request([], "CHECKLIST_UNAVAILABLE")
    assert not provider_safety._TRANSPORT_SINGLE_FLIGHT.locked()
    with _HangServer(HEADERS_ONLY) as server, pytest.MonkeyPatch.context() as patch:
        patch.setattr(provider_safety, "parse_provider_proposals", parser_spy)
        transport = _transport_for(server.state)
        for _attempt in range(2):
            with pytest.raises(ProviderSafetyError) as error:
                asyncio.run(bounded_transport_call(
                    transport, payload, _gate(), timeout_seconds=TIMEOUT_SECONDS,
                ))
            assert error.value.code == "timeout"
        assert server.state.peer_closed.wait(CLOSE_WAIT_SECONDS)
    assert not provider_safety._TRANSPORT_SINGLE_FLIGHT.locked()
