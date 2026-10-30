"""Offline tests for the owned, origin-pinned HTTPX adapter."""
import asyncio
import json
import logging
from decimal import Decimal

import httpx
import pytest

from app import httpx_transport
from app.httpx_transport import ASSESSMENT_PATH, HttpxAsyncTransport
from app.provider_safety import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    ProviderBudgetConfig,
    ProviderCallGate,
    ProviderSafetyError,
    bounded_provider_call,
    serialize_provider_request,
)
from provider_test_support import bounded_transport_call as _bounded_transport_call

ORIGIN = "https://provider.invalid"
ENDPOINT = ORIGIN + ASSESSMENT_PATH
_CURRENT_HANDLER = None


@pytest.fixture(autouse=True)
def _install_offline_transport(monkeypatch):
    def factory(**_kwargs):
        return httpx.MockTransport(_CURRENT_HANDLER or (lambda _request: httpx.Response(500)))
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", factory)


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, started=None, cancelled=None):
        self.chunks = list(chunks)
        self.started = started
        self.cancelled = cancelled
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.started is not None:
                self.started.set()
            yield chunk
        if self.started is not None and self.cancelled is not None:
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    async def aclose(self):
        self.closed = True


def _gate(max_requests=1):
    return ProviderCallGate(ProviderBudgetConfig(
        enabled=True,
        max_requests=max_requests,
        max_estimated_cost_usd="5.00",
        conservative_cost_per_request_usd="0.01",
    ))


def _payload():
    return serialize_provider_request([], "CHECKLIST_UNAVAILABLE")


def _adapter(handler):
    global _CURRENT_HANDLER
    _CURRENT_HANDLER = handler
    return HttpxAsyncTransport(ENDPOINT)


def _run(handler, *, timeout=2.0, gate=None):
    return asyncio.run(_bounded_transport_call(
        _adapter(handler), _payload(), gate or _gate(), timeout_seconds=timeout,
    ))


def test_httpx_transport_sends_exact_payload_and_reads_streamed_response():
    seen = {}
    stream = ChunkStream([b'[', b']'])

    def handler(request):
        seen["body"] = request.read()
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, headers={"content-length": "2"}, stream=stream)

    assert _run(handler) == []
    assert seen["body"] == bytes(_payload())
    assert len(seen["body"]) <= MAX_REQUEST_BYTES
    assert seen["headers"]["accept-encoding"] == "identity"
    assert "authorization" not in seen["headers"]
    assert "cookie" not in seen["headers"]
    assert stream.closed


@pytest.mark.parametrize("chunks", [
    [b"x" * 1024, b"x" * 1024, b"x" * 1024, b"x" * 1024, b"x"],
    [b"x" * (MAX_RESPONSE_BYTES + 1)],
])
def test_httpx_transport_rejects_oversized_streamed_body(chunks):
    stream = ChunkStream(chunks)
    with pytest.raises(ProviderSafetyError) as error:
        _run(lambda _request: httpx.Response(200, stream=stream))
    assert error.value.code == "response_too_large"
    assert stream.closed


@pytest.mark.parametrize("headers,expected", [
    ([(b"x-canary", b"v")] * 65, "response_headers_too_large"),
    ([(b"x-canary", b"v" * (16 * 1024))], "response_headers_too_large"),
    ([(b"content-length", b"not-a-number")], "malformed_response_headers"),
    ([(b"content-length", b"1"), (b"content-length", b"1")], "malformed_response_headers"),
])
def test_httpx_transport_rejects_excessive_or_invalid_headers(headers, expected):
    stream = ChunkStream([b"[]"])
    with pytest.raises(ProviderSafetyError) as error:
        _run(lambda _request: httpx.Response(200, headers=headers, stream=stream))
    assert error.value.code == expected
    assert stream.closed


def test_httpx_transport_timeout_cancels_body_read_and_closes_stream():
    started, cancelled = asyncio.Event(), asyncio.Event()
    stream = ChunkStream([], started=started, cancelled=cancelled)
    with pytest.raises(ProviderSafetyError) as error:
        _run(lambda _request: httpx.Response(200, stream=stream), timeout=0.02)
    assert error.value.code == "timeout"
    assert stream.closed
    assert started.is_set() and cancelled.is_set()


def test_httpx_stream_read_timeout_is_a_controlled_timeout():
    class TimeoutStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadTimeout("SYNTHETIC_READ_TIMEOUT_CANARY")
            yield b""  # pragma: no cover

        async def aclose(self):
            return None

    with pytest.raises(ProviderSafetyError) as error:
        _run(lambda _request: httpx.Response(200, stream=TimeoutStream()))
    assert error.value.code == "timeout"
    assert "SYNTHETIC_READ_TIMEOUT_CANARY" not in str(error.value)


def test_httpx_transport_sanitizes_exception_and_performs_one_attempt(caplog):
    canary = "SYNTHETIC_HTTPX_EXCEPTION_CANARY"
    calls = []

    def handler(_request):
        calls.append(True)
        raise httpx.ConnectError(canary)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ProviderSafetyError) as error:
            _run(handler)
    assert error.value.code == "provider_failure"
    assert canary not in str(error.value)
    assert canary not in caplog.text
    assert calls == [True]


def test_quota_is_reserved_before_callback_and_failed_attempt_is_not_refunded():
    gate = _gate()
    calls = []

    def handler(_request):
        calls.append(gate.request_count)
        raise httpx.ConnectError("offline synthetic failure")

    with pytest.raises(ProviderSafetyError):
        _run(handler, gate=gate)
    assert calls == [1]
    assert gate.request_count == 1
    assert gate.reserved_estimated_cost_usd == Decimal("0.01")


def test_malformed_json_is_controlled():
    with pytest.raises(ProviderSafetyError) as error:
        _run(lambda _request: httpx.Response(200, stream=ChunkStream([b"not-json"])))
    assert error.value.code == "malformed_response"


def test_transport_single_flight_rejects_overlap_and_releases_slot():
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        class WaitingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                entered.set()
                await release.wait()
                yield b'[]'

            async def aclose(self):
                return None

        adapter = _adapter(lambda _request: (calls.append(True) or httpx.Response(200, stream=WaitingStream())))
        gate = _gate(max_requests=2)
        first = asyncio.create_task(_bounded_transport_call(adapter, _payload(), gate))
        await entered.wait()
        with pytest.raises(ProviderSafetyError) as rejected:
            await _bounded_transport_call(adapter, _payload(), gate)
        assert rejected.value.code == "concurrent_request"
        assert calls == [True]
        assert gate.request_count == 1
        release.set()
        assert await first == []
        assert gate.request_count == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("endpoint", [
    "http://provider.invalid/v1/assess",
    "ftp://provider.invalid/v1/assess",
    "https:///v1/assess",
    "https://user:pass@provider.invalid/v1/assess",
    "https://provider.invalid/v1/assess?api_key=SYNTHETIC_CANARY",
    "https://provider.invalid/v1/assess#SYNTHETIC_CANARY",
    "https://provider.invalid/v1/assess?",
    "https://provider.invalid/v1/assess#",
    "https://@provider.invalid/v1/assess",
    "https://provider.invalid/other",
    "https://other.invalid/v1/assess",
    "https://provider.invalid/v1%2fassess",
])
def test_endpoint_origin_and_path_are_pinned_before_transport(endpoint):
    calls = []
    mock = httpx.MockTransport(lambda _request: (calls.append(True) or httpx.Response(200)))
    with pytest.raises(ProviderSafetyError) as error:
        HttpxAsyncTransport(endpoint)
    assert error.value.code == "invalid_transport"
    assert calls == []


def test_origin_is_trusted_and_cannot_be_selected_by_endpoint_caller():
    for endpoint in ("https://other.invalid/v1/assess", "https://provider.invalid.evil/v1/assess",
                     "https://user:pass@provider.invalid/v1/assess"):
        with pytest.raises(ProviderSafetyError):
            HttpxAsyncTransport(endpoint)


def test_reassigning_public_origin_reference_does_not_change_admission(monkeypatch):
    monkeypatch.setattr(httpx_transport, "APPROVED_PROVIDER_ORIGIN", "https://attacker.invalid")

    with pytest.raises(ProviderSafetyError) as error:
        HttpxAsyncTransport("https://attacker.invalid" + ASSESSMENT_PATH)
    assert error.value.code == "invalid_transport"

    adapter = HttpxAsyncTransport(ENDPOINT)
    assert adapter._endpoint == ENDPOINT


def test_approved_placeholder_and_assessment_path_are_fixed():
    assert httpx_transport.APPROVED_PROVIDER_ORIGIN == ORIGIN
    assert ASSESSMENT_PATH == "/v1/assess"
    assert HttpxAsyncTransport(ENDPOINT)._endpoint == ENDPOINT


def test_transport_configuration_is_immutable_and_does_not_accept_client():
    adapter = _adapter(lambda _request: httpx.Response(200, stream=ChunkStream([b"[]"])))
    with pytest.raises(AttributeError):
        adapter._endpoint = "https://attacker.invalid/v1/assess"
    with pytest.raises(AttributeError):
        adapter._mock_transport_for_tests = None

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
    try:
        with pytest.raises(TypeError):
            HttpxAsyncTransport(ENDPOINT, client=client)
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize("unsafe_options", [
    {"auth": ("user", "pass")},
    {"headers": {"authorization": "Bearer SYNTHETIC_CANARY"}},
    {"cookies": {"session": "SYNTHETIC_CANARY"}},
    {"follow_redirects": True},
    {"trust_env": True},
    {"event_hooks": {"request": [lambda _request: None]}},
    {"mounts": {"all://": httpx.MockTransport(lambda _request: httpx.Response(200))}},
    {"proxy": "http://proxy.invalid"},
    {"verify": False},
])
def test_untrusted_client_configuration_cannot_enter_transport(unsafe_options):
    options = {"trust_env": False, **unsafe_options}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200)), **options)
    try:
        with pytest.raises(TypeError):
            HttpxAsyncTransport(ENDPOINT, client=client)
    finally:
        asyncio.run(client.aclose())


def test_owned_production_client_sets_explicit_no_proxy_verified_no_retry(monkeypatch):
    observed = {}
    handler_calls = []

    def factory(**kwargs):
        observed.update(kwargs)
        return httpx.MockTransport(lambda request: (handler_calls.append(request) or httpx.Response(200, stream=ChunkStream([b"[]"])) ))

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", factory)
    monkeypatch.setenv("HTTPS_PROXY", "http://SYNTHETIC_PROXY_CANARY.invalid")
    adapter = HttpxAsyncTransport(ENDPOINT)
    assert asyncio.run(_bounded_transport_call(adapter, _payload(), _gate())) == []
    assert observed == {"retries": 0, "trust_env": False, "verify": True}
    assert len(handler_calls) == 1


def test_redirect_is_not_followed_and_authentication_is_not_supported():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://redirect.invalid/collect"})

    with pytest.raises(ProviderSafetyError) as error:
        _run(handler)
    assert error.value.code == "provider_failure"
    assert len(calls) == 1
    assert calls[0].url == httpx.URL(ENDPOINT)
    assert "authorization" not in calls[0].headers
    with pytest.raises(TypeError):
        HttpxAsyncTransport(ENDPOINT, auth=("user", "password"))


def test_approved_endpoint_details_are_not_logged(caplog):
    endpoint_canary = "endpoint-canary-synthetic.invalid"
    with caplog.at_level(logging.INFO), pytest.raises(ProviderSafetyError):
        HttpxAsyncTransport("https://" + endpoint_canary + ASSESSMENT_PATH)
    assert endpoint_canary not in caplog.text


def test_secret_canary_does_not_enter_logs_or_manifest(caplog):
    from app.experiment_manifest import AttemptMetadata, ExperimentRunManifest

    canary = "SYNTHETIC_CREDENTIAL_CANARY_7F2A"
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ProviderSafetyError):
            _run(lambda _request: (_ for _ in ()).throw(httpx.ConnectError(canary)))
    assert canary not in caplog.text
    logging.getLogger("httpx").info("%s", canary)
    logging.getLogger("httpcore.connection").debug("%s", canary)
    assert canary not in caplog.text

    digest = "a" * 64
    manifest = ExperimentRunManifest(
        run_id="synthetic-run", dataset_sha256=digest, evaluator_version="3.20.0",
        prompt_version="prompt-v1", prompt_sha256=digest,
        serializer_version="serializer-v1", serializer_sha256=digest,
    )
    manifest.add_attempt(AttemptMetadata(case_id="synthetic-case", request_count=1,
                                         error_category="provider_failure"))
    assert canary not in json.dumps(manifest.to_dict())
    with pytest.raises(ValueError):
        ExperimentRunManifest(
            run_id="synthetic-run", dataset_sha256=digest, evaluator_version="3.20.0",
            prompt_version="prompt-v1", prompt_sha256=digest,
            serializer_version="serializer-v1", serializer_sha256=digest,
            model_name=canary,
        )
    with pytest.raises(ValueError):
        ExperimentRunManifest(
            run_id="synthetic-run", dataset_sha256=digest, evaluator_version="3.20.0",
            prompt_version="prompt-v1", prompt_sha256=digest,
            serializer_version="serializer-v1", serializer_sha256=digest,
            model_name="sk-live-FAKEKEYCANARY123456",
        )
    for field in ("run_id", "evaluator_version", "prompt_version", "serializer_version",
                  "code_revision", "model_name", "model_version"):
        kwargs = dict(run_id="synthetic-run", dataset_sha256=digest, evaluator_version="3.20.0",
                      prompt_version="prompt-v1", prompt_sha256=digest,
                      serializer_version="serializer-v1", serializer_sha256=digest)
        kwargs[field] = "https://manifest-canary.invalid/path"
        with pytest.raises(ValueError):
            ExperimentRunManifest(**kwargs)
    with pytest.raises(ValueError):
        AttemptMetadata(case_id="https://manifest-canary.invalid", request_count=1)
    with pytest.raises(ValueError):
        AttemptMetadata(case_id="provider.example.com", request_count=1)
    for host_literal in (
        "10.0.0.1", "127.0.0.1", "2001:db8::1", "[2001:db8::1]",
        "localhost", "LOCALHOST", "localhost.localdomain", "db.internal",
        "127.1", "0177.0.0.1", "0x7f.1", "0x7f000001", "2130706433",
    ):
        with pytest.raises(ValueError):
            AttemptMetadata(case_id=host_literal, request_count=1)
    with pytest.raises(ValueError):
        AttemptMetadata(case_id=123, request_count=1)
    with pytest.raises(ValueError):
        ExperimentRunManifest(
            run_id="synthetic-run", dataset_sha256=digest, evaluator_version="3.20.0",
            prompt_version="prompt-v1", prompt_sha256=digest,
            serializer_version="serializer-v1", serializer_sha256=digest,
            model_name=123,
        )
    manifest.model_name = canary
    with pytest.raises(ValueError):
        manifest.to_dict()


@pytest.mark.parametrize("identifier", [
    "server", "localhost-evil", "server-db", "api", "mail.example", "https://example.invalid/x",
    "127.0.0.1", "0177.0.0.1", "0x7f000001", "2130706433", "0300.0000.0000.0001",
    "localhost.", "server.", "[::1]", "2001:db8::1", "0x7f.1",
])
def test_metadata_identifiers_reject_hostnames_urls_and_ambiguous_ip_forms(identifier):
    from app.experiment_manifest import AttemptMetadata
    with pytest.raises(ValueError):
        AttemptMetadata(case_id=identifier, request_count=1)


def test_metadata_version_fields_allow_documented_version_strings():
    from app.experiment_manifest import ExperimentRunManifest
    manifest = ExperimentRunManifest(
        run_id="run-123", dataset_sha256="a" * 64, code_revision=None,
        prompt_version="3.20.0", prompt_sha256="b" * 64,
        serializer_version="3.20.0", serializer_sha256="c" * 64,
        evaluator_version="3.20.0",
    )
    assert manifest.to_dict()["prompt_version"] == "3.20.0"


def test_metadata_version_fields_reject_ip_shaped_values_but_allow_non_host_ids():
    from app.experiment_manifest import ExperimentRunManifest
    base = dict(run_id="run-123", dataset_sha256="a" * 64, code_revision=None,
                prompt_version="3.20.0", prompt_sha256="b" * 64,
                serializer_version="serializer-v1", serializer_sha256="c" * 64,
                evaluator_version="3.20.0")
    assert ExperimentRunManifest(**base).to_dict()["serializer_version"] == "serializer-v1"
    for field in ("prompt_version", "serializer_version", "evaluator_version"):
        invalid = {**base, field: "127.0.0.1"}
        with pytest.raises(ValueError, match="Invalid metadata version"):
            ExperimentRunManifest(**invalid)
