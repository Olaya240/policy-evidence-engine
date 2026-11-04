"""Offline-only tests for the pinned Baseten Model API adapter prototype."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from decimal import Decimal
from threading import Barrier

import httpx
import pytest

from app import provider_safety
from app.engine import AssessmentEngine, ProviderError
from app.httpx_transport import (
    BASETEN_CHAT_COMPLETIONS_ENDPOINT,
    BasetenMuseSparkOpenTransport,
)
from app.models import Record
from app.provider_safety import (
    MAX_RESPONSE_BYTES,
    BasetenMuseSparkOpenAdapter,
    MandatoryProviderBoundary,
    ProviderBudgetConfig,
    ProviderCallGate,
    ProviderSafetyError,
    serialize_provider_request,
)
from app.mock_provider import SEED_RECORDS


class _AsyncBody(httpx.AsyncByteStream):
    def __init__(self, body: bytes):
        self._body = body

    async def __aiter__(self):
        yield self._body

    async def aclose(self):
        return None


def _gate(max_requests=1):
    return ProviderCallGate(ProviderBudgetConfig(
        enabled=True,
        max_requests=max_requests,
        max_estimated_cost_usd=Decimal("0.10") * max_requests,
        conservative_cost_per_request_usd=Decimal("0.10"),
    ))


def _dispatch_capability(transport, adapter, boundary, payload, timeout=1.0):
    return provider_safety._TransportDispatchAuthorization(
        transport, adapter, boundary, payload, timeout,
        _seal=provider_safety._TRANSPORT_DISPATCH_SEAL,
    )


class _TrackingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.inner = httpx.MockTransport(handler)
        self.closed = False
        self.calls = 0

    async def handle_async_request(self, request):
        self.calls += 1
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        self.closed = True
        await self.inner.aclose()


class _WaitingBody(httpx.AsyncByteStream):
    def __init__(self):
        self.started = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        self.started.set()
        await asyncio.Event().wait()
        yield b"[]"

    async def aclose(self):
        self.closed = True


def _response(content, *, extra_message=None, extra_top=None):
    message = {"role": "assistant", "content": content}
    if extra_message:
        message.update(extra_message)
    response = {
        "id": "chatcmpl-synthetic",
        "object": "chat.completion",
        "created": 1,
        "model": "meta-models/muse-spark-open-1026",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    }
    if extra_top:
        response.update(extra_top)
    return json.dumps(response, separators=(",", ":")).encode("utf-8")


def _engine_for(monkeypatch, response_body, *, status_code=200, gate=None, requests=None):
    def handler(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(status_code, stream=_AsyncBody(response_body))

    monkeypatch.setattr(
        httpx, "AsyncHTTPTransport",
        lambda **_kwargs: httpx.MockTransport(handler),
    )
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    provider = BasetenMuseSparkOpenAdapter(transport, gate)
    return AssessmentEngine(provider)


def test_baseten_request_pins_endpoint_and_model_and_allows_only_minimal_fields(monkeypatch):
    source = Record(
        id="SYN-1", timestamp=SEED_RECORDS[0].timestamp, department="Synthetic",
        text="Checklist binder was missing during handover.", tags=["PRIVATE_TAG"],
    )
    content = json.dumps([{
        "source_record_id": source.id,
        "quote": source.text,
        "stance": "SUPPORTS",
        "rationale": "The quoted text directly supports the hypothesis.",
    }], separators=(",", ":"))
    sent = []
    engine = _engine_for(monkeypatch, _response(content), gate=_gate(), requests=sent)

    claim = engine.assess_hypothesis([source], "CHECKLIST_UNAVAILABLE")

    assert BASETEN_CHAT_COMPLETIONS_ENDPOINT == "https://inference.baseten.co/v1/chat/completions"
    assert len(sent) == 1
    request = sent[0]
    assert str(request.url) == BASETEN_CHAT_COMPLETIONS_ENDPOINT
    assert request.method == "POST"
    assert request.headers["authorization"] == "Bearer SYNTHETIC_TEST_KEY_NEVER_SENT"
    wire = json.loads(request.content)
    assert set(wire) == {"model", "messages"}
    assert wire["model"] == "meta-models/muse-spark-open-1026"
    assert len(wire["messages"]) == 2
    assert all(set(message) == {"role", "content"} for message in wire["messages"])
    roles = [message["role"] for message in wire["messages"]]
    assert roles == ["developer", "user"]
    assert "system" not in roles
    user_input = json.loads(wire["messages"][1]["content"])
    assert user_input == {
        "hypothesis": {"id": "CHECKLIST_UNAVAILABLE", "label": "The handover checklist was unavailable"},
        "records": [{"id": source.id, "text": source.text}],
    }
    assert "PRIVATE_TAG" not in request.content.decode("utf-8")
    assert claim["status"] == "PARTIAL"
    assert claim["evidence"][0]["review_state"] == "ACCEPTED"


def test_baseten_constructor_has_no_endpoint_or_model_override_and_gate_is_disabled_by_default(monkeypatch):
    sends = []
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: httpx.MockTransport(
        lambda request: (sends.append(request), httpx.Response(200, stream=_AsyncBody(_response("[]"))))[1]
    ))
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    with pytest.raises(TypeError):
        BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT", endpoint="https://other.invalid")
    with pytest.raises(TypeError):
        BasetenMuseSparkOpenAdapter(transport, model="other-model")

    engine = AssessmentEngine(BasetenMuseSparkOpenAdapter(transport))
    with pytest.raises(ProviderError):
        engine.assess_hypothesis([], "CHECKLIST_UNAVAILABLE")
    assert sends == []


@pytest.mark.parametrize("body", [
    b'{"model":"m","choices":[],"unexpected":true}',
    b'{"model":"m","model":"other","choices":[]}',
    b'{"model":"m","choices":[],"usage":{"prompt_tokens":NaN}}',
    b'{"model":"m","choices":[]',
    b'{"model":"m","choices":[],"id":"\xed\xa0\x80"}',
    _response(""),
    _response("[]"),
    _response("[]", extra_message={"refusal": "synthetic policy refusal"}),
    _response("[]", extra_message={"tool_calls": []}),
    _response("[]", extra_top={"unexpected": True}),
])
def test_baseten_response_parser_fails_closed_on_unsupported_or_empty_shapes(body):
    request = serialize_provider_request([], "CHECKLIST_UNAVAILABLE")
    with pytest.raises(ProviderSafetyError):
        BasetenMuseSparkOpenAdapter._parse_response(body, request)


@pytest.mark.parametrize("controlled_field", [
    "review_state", "status", "confidence", "dependencies", "history",
])
def test_baseten_response_parser_rejects_proposals_with_engine_control_fields(controlled_field):
    request = serialize_provider_request(
        [Record(id="SYN", timestamp=SEED_RECORDS[0].timestamp, department="Synthetic",
                text="Checklist binder was missing.", tags=[])],
        "CHECKLIST_UNAVAILABLE",
    )
    proposal = {
        "source_record_id": "SYN",
        "quote": "Checklist binder was missing.",
        "stance": "SUPPORTS",
        "rationale": "synthetic",
    }
    proposal[controlled_field] = "provider-controlled"
    content = json.dumps([proposal], separators=(",", ":"))
    with pytest.raises(ProviderSafetyError) as error:
        BasetenMuseSparkOpenAdapter._parse_response(_response(content), request)
    assert error.value.code == "malformed_output"


def test_baseten_strict_inner_proposal_parser_rejects_duplicate_keys_and_nonstandard_constants():
    record = Record(id="SYN", timestamp=SEED_RECORDS[0].timestamp,
                    department="Synthetic", text="Checklist binder was missing.", tags=[])
    request = serialize_provider_request([record], "CHECKLIST_UNAVAILABLE")
    duplicate = ('[{"source_record_id":"SYN","source_record_id":"SYN",'
                 '"quote":"Checklist binder was missing.","stance":"SUPPORTS",'
                 '"rationale":"synthetic"}]')
    nonstandard = ('[{"source_record_id":"SYN","quote":"Checklist binder was missing.",'
                   '"stance":"SUPPORTS","rationale":NaN}]')
    for content in (duplicate, nonstandard):
        with pytest.raises(ProviderSafetyError) as error:
            BasetenMuseSparkOpenAdapter._parse_response(_response(content), request)
        assert error.value.code == "malformed_response"


def test_baseten_non_success_http_response_fails_closed_without_exposing_body(monkeypatch):
    canary = "SYNTHETIC_PROVIDER_ERROR_BODY"
    engine = _engine_for(monkeypatch, canary.encode("utf-8"), status_code=401, gate=_gate())
    with pytest.raises(ProviderError) as error:
        engine.assess_hypothesis([], "CHECKLIST_UNAVAILABLE")
    assert canary not in str(error.value)


def test_baseten_request_limit_is_reserved_and_not_refunded_after_failure(monkeypatch):
    sent = []
    engine = _engine_for(monkeypatch, b"not-json", gate=_gate(), requests=sent)
    with pytest.raises(ProviderError):
        engine.assess_hypothesis([], "CHECKLIST_UNAVAILABLE")
    assert len(sent) == 1
    with pytest.raises(ProviderError):
        engine.assess_hypothesis([], "CHECKLIST_UNAVAILABLE")
    assert len(sent) == 1


def test_baseten_oversized_response_is_rejected_without_network(monkeypatch):
    sent = []
    engine = _engine_for(monkeypatch, b"x" * (MAX_RESPONSE_BYTES + 1), gate=_gate(), requests=sent)
    with pytest.raises(ProviderError):
        engine.assess_hypothesis([], "CHECKLIST_UNAVAILABLE")
    assert len(sent) == 1


def test_baseten_adapter_is_exact_type_approved_and_bound_to_mandatory_boundary(monkeypatch):
    constructions = []

    def forbidden_transport(**kwargs):
        constructions.append(kwargs)
        raise AssertionError("direct send attempted HTTP transport construction")

    monkeypatch.setattr(
        httpx, "AsyncHTTPTransport", forbidden_transport,
    )
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    with pytest.raises(ProviderSafetyError) as direct_transport:
        asyncio.run(transport.send(b"{}", timeout_seconds=1.0))
    assert direct_transport.value.code == "mandatory_boundary_required"
    with pytest.raises(ProviderSafetyError) as direct_http:
        asyncio.run(transport._send_http(b"{}", timeout_seconds=1.0))
    assert direct_http.value.code == "mandatory_boundary_required"
    assert constructions == []

    class TransportSubclass(BasetenMuseSparkOpenTransport):
        pass

    with pytest.raises(ProviderSafetyError) as unsupported_transport:
        BasetenMuseSparkOpenAdapter(TransportSubclass("SYNTHETIC_TEST_KEY_NEVER_SENT"))
    assert unsupported_transport.value.code == "unsupported_transport"

    class AdapterSubclass(BasetenMuseSparkOpenAdapter):
        pass

    with pytest.raises(ProviderSafetyError) as unsupported_adapter:
        MandatoryProviderBoundary(AdapterSubclass(transport))
    assert unsupported_adapter.value.code == "unsupported_provider"

    adapter = BasetenMuseSparkOpenAdapter(transport)
    boundary = MandatoryProviderBoundary(adapter)
    with pytest.raises(ProviderSafetyError) as direct_adapter_dispatch:
        asyncio.run(transport._send_from_adapter(
            b"{}", adapter, boundary, timeout_seconds=1.0,
        ))
    assert direct_adapter_dispatch.value.code == "mandatory_boundary_required"
    assert constructions == []
    with pytest.raises(AttributeError):
        adapter._transport = object()


def test_dispatch_capability_rejects_mismatched_bindings_before_transport_construction(monkeypatch):
    constructions = []

    def forbidden_transport(**_kwargs):
        constructions.append(True)
        raise AssertionError("rejected capability constructed a transport")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden_transport)
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    adapter = BasetenMuseSparkOpenAdapter(transport, _gate())
    boundary = MandatoryProviderBoundary(adapter)
    payload = b"{}"
    authorization = _dispatch_capability(transport, adapter, boundary, payload)

    other_transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    other_adapter = BasetenMuseSparkOpenAdapter(other_transport, _gate())
    other_boundary = MandatoryProviderBoundary(other_adapter)
    same_value_distinct_object = bytes(bytearray(payload))
    assert same_value_distinct_object == payload
    assert same_value_distinct_object is not payload

    attempts = [
        lambda: other_transport._send_http(
            payload, timeout_seconds=1.0, _authorization=authorization,
        ),
        lambda: transport._send_from_adapter(
            payload, other_adapter, other_boundary, timeout_seconds=1.0,
            _authorization=authorization,
        ),
        lambda: transport._send_from_adapter(
            payload, adapter, other_boundary, timeout_seconds=1.0,
            _authorization=authorization,
        ),
        lambda: transport._send_http(
            same_value_distinct_object, timeout_seconds=1.0,
            _authorization=authorization,
        ),
        lambda: transport._send_http(
            b'{"different":true}', timeout_seconds=1.0,
            _authorization=authorization,
        ),
        lambda: transport._send_http(
            payload, timeout_seconds=2.0, _authorization=authorization,
        ),
    ]
    for attempt in attempts:
        with pytest.raises(ProviderSafetyError) as rejected:
            asyncio.run(attempt())
        assert rejected.value.code == "mandatory_boundary_required"

    assert authorization._consumed is False
    assert constructions == []


def test_dispatch_capability_is_single_use_and_replay_stops_before_transport(monkeypatch):
    transports = []
    sends = []

    def handler(request):
        sends.append(request)
        return httpx.Response(200, stream=_AsyncBody(b""))

    def transport_factory(**_kwargs):
        transport = _TrackingTransport(handler)
        transports.append(transport)
        return transport

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport_factory)
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    adapter = BasetenMuseSparkOpenAdapter(transport, _gate())
    boundary = MandatoryProviderBoundary(adapter)
    payload = b"{}"
    authorization = _dispatch_capability(transport, adapter, boundary, payload)

    async def consume_then_replay():
        response = await transport._send_http(
            payload, timeout_seconds=1.0, _authorization=authorization,
        )
        await response.aclose()
        with pytest.raises(ProviderSafetyError) as replay:
            await transport._send_http(
                payload, timeout_seconds=1.0, _authorization=authorization,
            )
        assert replay.value.code == "mandatory_boundary_required"

    asyncio.run(consume_then_replay())
    assert authorization._consumed is True
    assert len(transports) == len(sends) == 1
    assert transports[0].closed is True


def test_concurrent_cross_thread_reuse_of_one_capability_authorizes_one_send(monkeypatch):
    transports = []
    sends = []

    def handler(request):
        sends.append(request)
        return httpx.Response(200, stream=_AsyncBody(b""))

    def transport_factory(**_kwargs):
        transport = _TrackingTransport(handler)
        transports.append(transport)
        return transport

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport_factory)
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    adapter = BasetenMuseSparkOpenAdapter(transport, _gate())
    boundary = MandatoryProviderBoundary(adapter)
    payload = b"{}"
    authorization = _dispatch_capability(transport, adapter, boundary, payload)
    rendezvous = Barrier(2)

    def attempt():
        async def send_once():
            rendezvous.wait(timeout=5)
            try:
                response = await transport._send_http(
                    payload, timeout_seconds=1.0, _authorization=authorization,
                )
            except ProviderSafetyError as exc:
                return exc.code
            await response.aclose()
            return "sent"

        return asyncio.run(send_once())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: attempt(), range(2)))

    assert sorted(results) == ["mandatory_boundary_required", "sent"]
    assert len(transports) == len(sends) == 1
    assert transports[0].closed is True


def test_baseten_failure_releases_single_flight_and_keeps_quota_reserved(monkeypatch):
    transports = []
    calls = []
    source = Record(
        id="SYN-FAILURE-RETRY", timestamp=SEED_RECORDS[0].timestamp,
        department="Synthetic", text="Checklist binder was missing.", tags=[],
    )
    proposal_content = json.dumps([{
        "source_record_id": source.id,
        "quote": source.text,
        "stance": "SUPPORTS",
        "rationale": "synthetic retry proposal",
    }], separators=(",", ":"))

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("synthetic transport failure")
        return httpx.Response(200, stream=_AsyncBody(_response(proposal_content)))

    def transport_factory(**_kwargs):
        transport = _TrackingTransport(handler)
        transports.append(transport)
        return transport

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport_factory)
    gate = _gate(max_requests=2)
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    engine = AssessmentEngine(BasetenMuseSparkOpenAdapter(transport, gate))

    with pytest.raises(ProviderError):
        engine.assess_hypothesis([source], "CHECKLIST_UNAVAILABLE")
    assert gate.request_count == 1
    assert gate.reserved_estimated_cost_usd == Decimal("0.10")
    assert transports[0].closed is True

    claim = engine.assess_hypothesis([source], "CHECKLIST_UNAVAILABLE")
    assert claim["evidence"][0]["source_record_id"] == source.id
    assert gate.request_count == 2
    assert len(calls) == 2
    assert all(item.closed for item in transports)


def test_baseten_cancellation_closes_stream_and_transport_and_releases_single_flight(monkeypatch):
    transports = []
    waiting_body = _WaitingBody()
    calls = []
    source = Record(
        id="SYN-CANCEL-RETRY", timestamp=SEED_RECORDS[0].timestamp,
        department="Synthetic", text="Checklist binder was missing.", tags=[],
    )
    proposal_content = json.dumps([{
        "source_record_id": source.id,
        "quote": source.text,
        "stance": "SUPPORTS",
        "rationale": "synthetic retry proposal",
    }], separators=(",", ":"))

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, stream=waiting_body)
        return httpx.Response(200, stream=_AsyncBody(_response(proposal_content)))

    def transport_factory(**_kwargs):
        transport = _TrackingTransport(handler)
        transports.append(transport)
        return transport

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport_factory)
    gate = _gate(max_requests=2)
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    adapter = BasetenMuseSparkOpenAdapter(transport, gate)
    boundary = MandatoryProviderBoundary(adapter)
    request = serialize_provider_request([source], "CHECKLIST_UNAVAILABLE")

    async def exercise():
        first = asyncio.create_task(adapter._assess_async(request, boundary))
        await waiting_body.started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert waiting_body.closed is True
        assert transports[0].closed is True
        assert gate.request_count == 1
        assert gate.reserved_estimated_cost_usd == Decimal("0.10")

        result = await adapter._assess_async(request, boundary)
        assert result[0]["source_record_id"] == source.id

    asyncio.run(exercise())
    assert gate.request_count == 2
    assert len(calls) == 2
    assert all(item.closed for item in transports)


def test_baseten_async_client_construction_failure_closes_unowned_transport(monkeypatch):
    transports = []

    def transport_factory(**_kwargs):
        transport = _TrackingTransport(lambda _request: pytest.fail("request must not be sent"))
        transports.append(transport)
        return transport

    def failing_client_constructor(**_kwargs):
        raise RuntimeError("synthetic client construction failure")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport_factory)
    monkeypatch.setattr(httpx, "AsyncClient", failing_client_constructor)
    gate = _gate()
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    engine = AssessmentEngine(BasetenMuseSparkOpenAdapter(transport, gate))

    with pytest.raises(ProviderError) as error:
        engine.assess_hypothesis([], "CHECKLIST_UNAVAILABLE")

    assert error.value.code == "provider_failure"
    assert gate.request_count == 1
    assert len(transports) == 1
    assert transports[0].closed is True

