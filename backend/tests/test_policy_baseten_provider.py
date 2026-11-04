"""Offline-only policy Baseten adapter and Policy Demo integration tests."""
import json
import asyncio
import threading
from decimal import Decimal

import pytest
import httpx
from fastapi.testclient import TestClient

from app.provider_safety import ProviderBudgetConfig
from policy_baseten_provider import (
    BasetenPolicyProposalAdapter,
    BasetenPolicyHttpxTransport,
    POLICY_BASETEN_CHAT_COMPLETIONS_ENDPOINT,
    POLICY_BASETEN_MODEL_ID,
    POLICY_KEY_ENV,
    POLICY_MAX_COST_ENV,
    POLICY_MAX_REQUESTS_ENV,
    POLICY_PER_REQUEST_COST_ENV,
    POLICY_PROVIDER_ENV,
    PolicyProviderError,
    build_policy_provider_from_environment,
)
import policy_demo_api
from policy_demo_api import app
from policy_evidence_demo import (
    build_scenario_reviewer_challenge,
    recompute_investigation_after_challenge,
    run_initial_evidence_investigation,
    build_hotel_scheduling_policy_pair,
    build_initial_proposal_payload,
)
from policy_proposal_contract import build_proposal_request


MODEL = POLICY_BASETEN_MODEL_ID
SYNTHETIC_KEY = "SYNTHETIC_POLICY_BASETEN_KEY_NEVER_REAL"


def _budget(max_requests=1):
    return ProviderBudgetConfig(
        enabled=True,
        max_requests=max_requests,
        max_estimated_cost_usd=Decimal("0.20"),
        conservative_cost_per_request_usd=Decimal("0.10"),
    )


def _completion(pair, model=MODEL, response=None):
    request = build_proposal_request(pair)
    response = response or build_initial_proposal_payload(pair, request["request_id"])
    return json.dumps({
        "id": "test-request-1",
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(response),
        }}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }, separators=(",", ":")).encode()


class OfflineTransport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def complete(self, body, *, timeout_seconds):
        self.calls.append((body, timeout_seconds))
        if self.error:
            raise self.error
        return self.response


class AsyncMockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request):
        return self.handler(request)


class AsyncBytes(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body

    async def aclose(self):
        return None


def _http_response(status, body):
    return httpx.Response(status, stream=AsyncBytes(body))


def _adapter(pair, transport, max_requests=1):
    return BasetenPolicyProposalAdapter(transport, _budget(max_requests))


def test_policy_request_contains_only_canonical_pair_context_and_metadata():
    pair = build_hotel_scheduling_policy_pair()
    transport = OfflineTransport(_completion(pair))
    provider = _adapter(pair, transport)
    raw, attribution = provider.generate(pair, build_proposal_request(pair))
    body = json.loads(transport.calls[0][0])
    assert set(body) == {"model", "max_tokens", "messages"}
    assert body["model"] == MODEL
    assert body["max_tokens"] == 8192
    assert len(body["messages"]) == 2
    user_envelope = json.loads(body["messages"][1]["content"])
    assert user_envelope == build_proposal_request(pair)
    assert transport.calls[0][1] == 90.0
    assert attribution == {"provider": "baseten", "model": MODEL,
                           "request_id": "test-request-1",
                           "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}
    assert raw["request_id"] == user_envelope["request_id"]


def test_real_transport_is_pinned_and_sends_exact_model_bearer_and_body(monkeypatch):
    pair = build_hotel_scheduling_policy_pair()
    response_body = _completion(pair)
    captured = []

    def handler(request):
        captured.append(request)
        return _http_response(200, response_body)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(handler))
    transport = BasetenPolicyHttpxTransport(SYNTHETIC_KEY)
    result = transport.complete(b'{"model":"test"}', timeout_seconds=2.0)

    assert result == response_body
    assert str(captured[0].url) == POLICY_BASETEN_CHAT_COMPLETIONS_ENDPOINT
    assert captured[0].headers["authorization"] == f"Bearer {SYNTHETIC_KEY}"
    assert captured[0].content == b'{"model":"test"}'
    assert POLICY_BASETEN_CHAT_COMPLETIONS_ENDPOINT == "https://inference.baseten.co/v1/chat/completions"
    assert MODEL == "meta-models/muse-spark-open-1026"
    assert SYNTHETIC_KEY not in repr(transport)


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("synthetic"), httpx.ConnectError("synthetic")])
def test_httpx_transport_sanitizes_timeout_and_network_errors(monkeypatch, failure):
    def handler(_request):
        raise failure

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(handler))
    transport = BasetenPolicyHttpxTransport(SYNTHETIC_KEY)
    with pytest.raises(PolicyProviderError) as caught:
        transport.complete(b"{}", timeout_seconds=2.0)
    assert caught.value.code == "provider_failure"
    assert SYNTHETIC_KEY not in str(caught.value)


def test_httpx_transport_rejects_non_success_and_oversized_response(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(
        lambda _request: _http_response(401, b"unauthorized")
    ))
    with pytest.raises(PolicyProviderError):
        BasetenPolicyHttpxTransport(SYNTHETIC_KEY).complete(b"{}", timeout_seconds=2.0)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(
        lambda _request: _http_response(200, b"x" * 64_001)
    ))
    with pytest.raises(PolicyProviderError) as oversized:
        BasetenPolicyHttpxTransport(SYNTHETIC_KEY).complete(b"{}", timeout_seconds=2.0)
    assert oversized.value.code == "invalid_response"


def test_valid_proposal_is_locally_cited_and_core_stays_human_review_only():
    pair = build_hotel_scheduling_policy_pair()
    provider = _adapter(pair, OfflineTransport(_completion(pair)))
    result = run_initial_evidence_investigation(pair, provider)
    assert result["provider_attribution"]["provider"] == "baseten"
    assert result["human_review_required"] is True
    assert result["semantic_support"] == "NOT_VERIFIED"
    assert all(item["verified_locally"] for item in result["provenance_details"])
    assert result["official_policy_mutated"] is False


@pytest.mark.parametrize("bad_citation", ["unknown_source", "unsupported_quote"])
def test_invalid_or_unknown_citations_are_rejected_by_local_contract(bad_citation):
    pair = build_hotel_scheduling_policy_pair()
    request = build_proposal_request(pair)
    bad_response = build_initial_proposal_payload(pair, request["request_id"])
    hint = bad_response["candidates"][0]["citation_hints"][0]
    if bad_citation == "unknown_source":
        hint["passage_id"] = "p999999-deadbeefdeadbeef"
    else:
        hint["quote"] = "A fabricated policy quotation absent from the source."
    transport = OfflineTransport(_completion(pair, response=bad_response))
    with pytest.raises(Exception):
        run_initial_evidence_investigation(pair, _adapter(pair, transport))


def test_model_mismatch_and_malformed_chat_completion_are_rejected():
    pair = build_hotel_scheduling_policy_pair()
    request = build_proposal_request(pair)
    wrong_model = OfflineTransport(_completion(pair, model="unverified/model"))
    with pytest.raises(PolicyProviderError) as mismatch:
        _adapter(pair, wrong_model).generate(pair, request)
    assert mismatch.value.code == "invalid_response"

    malformed = OfflineTransport(b'{"choices":[] }')
    with pytest.raises(PolicyProviderError) as invalid:
        _adapter(pair, malformed).generate(pair, request)
    assert invalid.value.code == "invalid_response"


def test_abstention_is_preserved_and_recomputation_uses_validated_initial_proposal():
    pair = build_hotel_scheduling_policy_pair()
    request = build_proposal_request(pair)
    abstention = {"schema_version": 1, "request_id": request["request_id"], "candidates": [{
        "proposed_relation": "INCONCLUSIVE", "reasoning": "Insufficient source evidence; abstain.",
        "citation_hints": [], "uncertainty_reasons": ["missing_evidence", "semantic_support_unverified"],
        "abstain": True,
    }]}
    initial = run_initial_evidence_investigation(
        pair, _adapter(pair, OfflineTransport(_completion(pair, response=abstention)))
    )
    assert initial["proposed_relation"] == "INCONCLUSIVE"
    assert initial["human_review_required"] is True
    challenge = build_scenario_reviewer_challenge(pair, initial, "HOUSEKEEPING")
    recomputed = recompute_investigation_after_challenge(pair, initial, challenge)
    assert recomputed["recomputed_core_result"]["classification"] == "INCONCLUSIVE"
    assert recomputed["provider_attribution"]["provider"] == "baseten"
    assert recomputed["recomputation_provider"] == "local_policy_engine"


def test_budget_exhaustion_prevents_second_transport_call():
    pair = build_hotel_scheduling_policy_pair()
    transport = OfflineTransport(_completion(pair))
    provider = _adapter(pair, transport, max_requests=1)
    request = build_proposal_request(pair)
    provider.generate(pair, request)
    with pytest.raises(PolicyProviderError) as error:
        provider.generate(pair, request)
    assert error.value.code == "budget_exhausted"
    assert len(transport.calls) == 1


@pytest.mark.parametrize("failure", [TimeoutError("offline timeout"), OSError("offline network error")])
def test_timeout_and_network_failures_are_sanitized(failure):
    pair = build_hotel_scheduling_policy_pair()
    provider = _adapter(pair, OfflineTransport(error=failure))
    with pytest.raises(PolicyProviderError) as error:
        provider.generate(pair, build_proposal_request(pair))
    assert error.value.code == "provider_failure"
    assert "offline" not in str(error.value)


def test_baseten_transport_failure_does_not_fall_back():
    pair = build_hotel_scheduling_policy_pair()
    provider = BasetenPolicyProposalAdapter(BasetenPolicyHttpxTransport(SYNTHETIC_KEY), _budget())
    with pytest.raises(PolicyProviderError) as error:
        run_initial_evidence_investigation(pair, provider)
    assert error.value.code == "provider_failure"


def test_policy_demo_explicit_baseten_selection_returns_error_without_synthetic_fallback(monkeypatch):
    monkeypatch.setattr(policy_demo_api, "_policy_provider_initialized", False)
    monkeypatch.setattr(policy_demo_api, "_policy_provider", None)
    monkeypatch.setattr(policy_demo_api, "_policy_provider_failure_code", None)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "synthetic-test-presence-only")
    monkeypatch.setenv("POLICY_DEMO_BASETEN_MAX_REQUESTS", "1")
    monkeypatch.setenv("POLICY_DEMO_BASETEN_MAX_ESTIMATED_COST_USD", "0.10")
    monkeypatch.setenv("POLICY_DEMO_BASETEN_CONSERVATIVE_COST_PER_REQUEST_USD", "0.10")
    sent = []

    def offline_failure(request):
        sent.append(request)
        raise httpx.ConnectError("synthetic offline failure")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(offline_failure))
    client = TestClient(app)
    response = client.get("/demo-api/scenario?id=scheduling")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "provider_failure"
    assert "proposed_relation" not in response.json()
    assert "synthetic-test-presence-only" not in response.text
    exhausted = client.get("/demo-api/scenario?id=scheduling")
    assert exhausted.status_code == 429
    assert exhausted.json()["detail"]["error"] == "budget_exhausted"
    assert len(sent) == 1


def test_async_challenge_reuses_bound_baseten_proposal_without_second_transport_call(monkeypatch):
    from policy_demo_session import InMemoryDemoSessionManager

    pair = build_hotel_scheduling_policy_pair()
    transport = OfflineTransport(_completion(pair))
    provider = _adapter(pair, transport, max_requests=2)
    manager = InMemoryDemoSessionManager()
    monkeypatch.setattr(policy_demo_api, "default_session_manager", manager)
    monkeypatch.setattr(policy_demo_api, "_get_policy_provider", lambda: provider)

    route_loop_threads = []
    original_recompute = policy_demo_api._recompute_bound_challenge

    def verify_worker_thread(*args, **kwargs):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        route_loop_threads.append(threading.get_ident())
        return original_recompute(*args, **kwargs)

    monkeypatch.setattr(policy_demo_api, "_recompute_bound_challenge", verify_worker_thread)
    client = TestClient(app)
    scenario_response = client.get("/demo-api/scenario?id=scheduling")
    assert scenario_response.status_code == 200
    displayed = scenario_response.json()
    assert len(transport.calls) == 1

    session_response = client.post("/demo-api/session/new", json={
        "scenario_id": "scheduling", "proposal_id": displayed["proposal_id"],
    })
    assert session_response.status_code == 200
    session = session_response.json()
    challenge_response = client.post("/demo-api/challenge", json={
        "scenario_id": "scheduling", "department_id": "HOUSEKEEPING",
        "session_id": session["session_id"], "proposal_id": displayed["proposal_id"],
    })

    assert challenge_response.status_code == 200
    result = challenge_response.json()
    assert result["proposal_id"] == displayed["proposal_id"]
    assert result["provider_attribution"] == displayed["provider_attribution"]
    assert result["recomputed_proposal"]["proposed_relation"] == "INCONCLUSIVE"
    assert len(transport.calls) == 1
    assert len(route_loop_threads) == 1
    history = client.get(f"/demo-api/session/{session['session_id']}/history").json()
    assert history["events"][0]["proposal_id"] == displayed["proposal_id"]
    assert history["events"][0]["initial_relation"] == displayed["proposed_relation"]


def test_async_challenge_errors_are_sanitized_and_wrong_proposal_is_not_retried(monkeypatch):
    from policy_demo_session import InMemoryDemoSessionManager

    pair = build_hotel_scheduling_policy_pair()
    transport = OfflineTransport(_completion(pair))
    provider = _adapter(pair, transport, max_requests=2)
    monkeypatch.setattr(policy_demo_api, "default_session_manager", InMemoryDemoSessionManager())
    monkeypatch.setattr(policy_demo_api, "_get_policy_provider", lambda: provider)
    client = TestClient(app)

    displayed = client.get("/demo-api/scenario?id=scheduling").json()
    session = client.post("/demo-api/session/new", json={
        "scenario_id": "scheduling", "proposal_id": displayed["proposal_id"],
    }).json()
    response = client.post("/demo-api/challenge", json={
        "scenario_id": "scheduling", "department_id": "HOUSEKEEPING",
        "session_id": session["session_id"], "proposal_id": "d" * 32,
    })
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "proposal_mismatch"
    assert "SYNTHETIC_POLICY_BASETEN_KEY_NEVER_REAL" not in response.text
    assert len(transport.calls) == 1


def test_scenario_provider_failure_is_sanitized_and_does_not_fall_back(monkeypatch):
    from policy_demo_session import InMemoryDemoSessionManager

    pair = build_hotel_scheduling_policy_pair()
    provider = _adapter(pair, OfflineTransport(error=OSError("private response body")))
    monkeypatch.setattr(policy_demo_api, "default_session_manager", InMemoryDemoSessionManager())
    monkeypatch.setattr(policy_demo_api, "_get_policy_provider", lambda: provider)
    response = TestClient(app).get("/demo-api/scenario?id=scheduling")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "provider_failure"
    assert "private response body" not in response.text


def test_environment_activation_without_required_settings_fails_closed():
    with pytest.raises(PolicyProviderError) as caught:
        build_policy_provider_from_environment({"POLICY_DEMO_PROVIDER": "baseten"})
    assert caught.value.code == "provider_unavailable"


def test_baseten_provider_selection_and_model_pinning():
    env = {
        POLICY_PROVIDER_ENV: "baseten",
        POLICY_KEY_ENV: SYNTHETIC_KEY,
        POLICY_MAX_REQUESTS_ENV: "2",
        POLICY_MAX_COST_ENV: "0.50",
        POLICY_PER_REQUEST_COST_ENV: "0.10",
    }
    provider = build_policy_provider_from_environment(env)
    assert isinstance(provider, BasetenPolicyProposalAdapter)
    assert provider.provider_id == "baseten"
    assert provider.model_id == "meta-models/muse-spark-open-1026"
    assert POLICY_BASETEN_MODEL_ID == "meta-models/muse-spark-open-1026"
    assert POLICY_BASETEN_CHAT_COMPLETIONS_ENDPOINT == "https://inference.baseten.co/v1/chat/completions"


def test_synthetic_default_and_unknown_provider_failure():
    assert build_policy_provider_from_environment({}) is None
    assert build_policy_provider_from_environment({POLICY_PROVIDER_ENV: "synthetic"}) is None
    assert build_policy_provider_from_environment({POLICY_PROVIDER_ENV: "  SYNTHETIC  "}) is None
    with pytest.raises(PolicyProviderError) as caught:
        build_policy_provider_from_environment({POLICY_PROVIDER_ENV: "unsupported_provider"})
    assert caught.value.code == "provider_unavailable"


@pytest.mark.parametrize("invalid_key", ["", "   ", " leading_space", "trailing_space ", "control\nchar", "del\x7f"])
def test_baseten_invalid_api_key_fails_closed(invalid_key):
    env = {
        POLICY_PROVIDER_ENV: "baseten",
        POLICY_KEY_ENV: invalid_key,
        POLICY_MAX_REQUESTS_ENV: "1",
        POLICY_MAX_COST_ENV: "0.20",
        POLICY_PER_REQUEST_COST_ENV: "0.10",
    }
    with pytest.raises(PolicyProviderError) as caught:
        build_policy_provider_from_environment(env)
    assert caught.value.code == "provider_unavailable"
    if invalid_key:
        assert invalid_key not in str(caught.value)


@pytest.mark.parametrize("bad_budget", [
    {"POLICY_DEMO_BASETEN_MAX_REQUESTS": "0"},
    {"POLICY_DEMO_BASETEN_MAX_REQUESTS": "18"},
    {"POLICY_DEMO_BASETEN_MAX_REQUESTS": "not_an_int"},
    {"POLICY_DEMO_BASETEN_MAX_ESTIMATED_COST_USD": "0.00"},
    {"POLICY_DEMO_BASETEN_MAX_ESTIMATED_COST_USD": "-1.00"},
    {"POLICY_DEMO_BASETEN_MAX_ESTIMATED_COST_USD": "5.01"},
    {"POLICY_DEMO_BASETEN_MAX_ESTIMATED_COST_USD": "$1.00"},
    {"POLICY_DEMO_BASETEN_CONSERVATIVE_COST_PER_REQUEST_USD": "0.00"},
    {"POLICY_DEMO_BASETEN_CONSERVATIVE_COST_PER_REQUEST_USD": "-0.50"},
    # Multiplicative cost exceeds ceiling: 5 * 0.50 = 2.50 > 1.00
    {
        "POLICY_DEMO_BASETEN_MAX_REQUESTS": "5",
        "POLICY_DEMO_BASETEN_MAX_ESTIMATED_COST_USD": "1.00",
        "POLICY_DEMO_BASETEN_CONSERVATIVE_COST_PER_REQUEST_USD": "0.50",
    },
])
def test_baseten_invalid_budget_fails_closed(bad_budget):
    env = {
        POLICY_PROVIDER_ENV: "baseten",
        POLICY_KEY_ENV: SYNTHETIC_KEY,
        POLICY_MAX_REQUESTS_ENV: "1",
        POLICY_MAX_COST_ENV: "0.20",
        POLICY_PER_REQUEST_COST_ENV: "0.10",
    }
    env.update(bad_budget)
    with pytest.raises(PolicyProviderError) as caught:
        build_policy_provider_from_environment(env)
    assert caught.value.code == "provider_unavailable"


def _status_request():
    from starlette.requests import Request
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/demo-api/provider-status",
        "raw_path": b"/demo-api/provider-status",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 43210),
        "server": ("127.0.0.1", 8083),
    }
    return Request(scope)


def test_baseten_provider_status_reporting(monkeypatch):
    monkeypatch.setattr(policy_demo_api, "_policy_provider_initialized", False)
    monkeypatch.setattr(policy_demo_api, "_policy_provider", None)
    monkeypatch.setattr(policy_demo_api, "_policy_provider_failure_code", None)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "baseten-sentinel-key")

    uninitialized = policy_demo_api.provider_status(_status_request())
    assert uninitialized == {
        "configured_provider": "baseten",
        "provider_id": None,
        "model_id": "meta-models/muse-spark-open-1026",
        "provider_state": "not_initialized",
        "authorized_request_attempts": 0,
        "counter_semantics": "budget reservations before transport; not confirmed HTTP deliveries",
    }
    assert "baseten-sentinel-key" not in repr(uninitialized)

    # Initialized and ready
    provider = BasetenPolicyProposalAdapter(OfflineTransport(), _budget(max_requests=2))
    monkeypatch.setattr(policy_demo_api, "_policy_provider_initialized", True)
    monkeypatch.setattr(policy_demo_api, "_policy_provider", provider)

    ready = policy_demo_api.provider_status(_status_request())
    assert ready["configured_provider"] == "baseten"
    assert ready["provider_id"] == "baseten"
    assert ready["model_id"] == "meta-models/muse-spark-open-1026"
    assert ready["provider_state"] == "ready"
    assert ready["authorized_request_attempts"] == 0

    # Initialization failure
    monkeypatch.setattr(policy_demo_api, "_policy_provider", None)
    monkeypatch.setattr(policy_demo_api, "_policy_provider_failure_code", "provider_unavailable")

    unavailable = policy_demo_api.provider_status(_status_request())
    assert unavailable["configured_provider"] == "baseten"
    assert unavailable["provider_id"] is None
    assert unavailable["model_id"] == "meta-models/muse-spark-open-1026"
    assert unavailable["provider_state"] == "unavailable"
    assert unavailable["authorized_request_attempts"] == 0
