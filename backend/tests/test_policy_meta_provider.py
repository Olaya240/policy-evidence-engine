"""Offline-only tests for the policy-specific Meta proposal provider."""
import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

import policy_demo_api
from app.provider_safety import ProviderBudgetConfig
from policy_baseten_provider import (
    MAX_POLICY_PROVIDER_TIMEOUT_SECONDS,
    MetaPolicyHttpxTransport,
    MetaPolicyProposalAdapter,
    POLICY_META_CHAT_COMPLETIONS_ENDPOINT,
    POLICY_META_KEY_ENV,
    POLICY_META_MAX_COST_ENV,
    POLICY_META_MAX_REQUESTS_ENV,
    POLICY_META_MODEL_ID,
    POLICY_META_PER_REQUEST_COST_ENV,
    POLICY_PROVIDER_ENV,
    PolicyProviderError,
    build_policy_provider_from_environment,
)
from policy_evidence_demo import build_hotel_scheduling_policy_pair, build_initial_proposal_payload
from policy_proposal_contract import build_proposal_request


TEST_KEY = "offline-test-key-only"


def _budget(max_requests=1):
    return ProviderBudgetConfig(
        enabled=True,
        max_requests=max_requests,
        max_estimated_cost_usd=Decimal("0.20"),
        conservative_cost_per_request_usd=Decimal("0.10"),
    )


def _completion(pair, *, model=POLICY_META_MODEL_ID, proposal=None, content=None, **outer):
    request = build_proposal_request(pair)
    proposal = proposal if proposal is not None else build_initial_proposal_payload(pair, request["request_id"])
    if content is None:
        content = json.dumps(proposal, separators=(",", ":"))
    response = {
        "id": "meta-offline-request-1",
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": content,
        }}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
    }
    response.update(outer)
    return json.dumps(response, separators=(",", ":")).encode()


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


def test_synthetic_is_default_and_meta_is_explicitly_opt_in_without_network():
    assert build_policy_provider_from_environment({}) is None
    env = {
        POLICY_PROVIDER_ENV: "meta",
        POLICY_META_KEY_ENV: TEST_KEY,
        POLICY_META_MAX_REQUESTS_ENV: "1",
        POLICY_META_MAX_COST_ENV: "0.10",
        POLICY_META_PER_REQUEST_COST_ENV: "0.10",
    }
    provider = build_policy_provider_from_environment(env)
    assert isinstance(provider, MetaPolicyProposalAdapter)
    assert provider.provider_id == "meta"
    assert provider.model_id == "muse-spark-1.3"


def test_meta_request_is_policy_specific_bounded_and_model_pinned():
    pair = build_hotel_scheduling_policy_pair()
    transport = OfflineTransport(_completion(pair))
    provider = MetaPolicyProposalAdapter(transport, _budget())
    proposal, attribution = provider.generate(pair, build_proposal_request(pair))
    body = json.loads(transport.calls[0][0])
    assert set(body) == {"model", "max_tokens", "messages"}
    assert body["model"] == "muse-spark-1.3"
    assert body["max_tokens"] == 8192
    assert len(body["messages"]) == 2
    sent_context = json.loads(body["messages"][1]["content"])
    assert sent_context == build_proposal_request(pair)
    assert not {"session_id", "challenge", "proposal_id"}.intersection(sent_context)
    assert transport.calls[0][1] == MAX_POLICY_PROVIDER_TIMEOUT_SECONDS
    assert proposal["request_id"] == sent_context["request_id"]
    assert attribution == {
        "provider": "meta", "model": "muse-spark-1.3",
        "request_id": "meta-offline-request-1",
        "usage": {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
    }


@pytest.mark.parametrize("raw", [
    b"not-json",
    b'{"model":"wrong","choices":[]}',
    b'{"model":"muse-spark-1.3","choices":[]}',
    b'{"model":"muse-spark-1.3","choices":[{"finish_reason":"length","message":{"role":"assistant","content":"{}"}}]}',
    b'{"model":"muse-spark-1.3","choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"not-json"}}]}',
])
def test_invalid_completion_shapes_are_rejected(raw):
    pair = build_hotel_scheduling_policy_pair()
    provider = MetaPolicyProposalAdapter(OfflineTransport(raw), _budget())
    with pytest.raises(PolicyProviderError) as caught:
        provider.generate(pair, build_proposal_request(pair))
    assert caught.value.code == "invalid_response"


@pytest.mark.parametrize("citation_mutation", ["unknown_id", "fabricated_quote"])
def test_meta_citations_are_validated_against_local_policy_evidence(citation_mutation):
    from policy_evidence_demo import run_initial_evidence_investigation

    pair = build_hotel_scheduling_policy_pair()
    request = build_proposal_request(pair)
    proposal = build_initial_proposal_payload(pair, request["request_id"])
    hint = proposal["candidates"][0]["citation_hints"][0]
    if citation_mutation == "unknown_id":
        hint["passage_id"] = "unknown-policy-passage"
    else:
        hint["quote"] = "This fabricated sentence is not in the supplied policy."
    provider = MetaPolicyProposalAdapter(OfflineTransport(_completion(pair, proposal=proposal)), _budget())
    with pytest.raises(Exception):
        run_initial_evidence_investigation(pair, provider)


@pytest.mark.parametrize("bad_content", ["{}", "null", "[]"])
def test_missing_or_malformed_proposal_is_rejected_by_policy_normalizer(bad_content):
    from policy_evidence_demo import run_initial_evidence_investigation

    pair = build_hotel_scheduling_policy_pair()
    provider = MetaPolicyProposalAdapter(
        OfflineTransport(_completion(pair, content=bad_content)), _budget(),
    )
    with pytest.raises(Exception):
        run_initial_evidence_investigation(pair, provider)


def test_meta_abstention_is_preserved_and_challenge_is_local():
    from policy_evidence_demo import (
        build_scenario_reviewer_challenge,
        recompute_investigation_after_challenge,
        run_initial_evidence_investigation,
    )

    pair = build_hotel_scheduling_policy_pair()
    request = build_proposal_request(pair)
    abstention = {"schema_version": 1, "request_id": request["request_id"], "candidates": [{
        "proposed_relation": "INCONCLUSIVE", "reasoning": "Evidence is insufficient; abstain.",
        "citation_hints": [], "uncertainty_reasons": ["missing_evidence", "semantic_support_unverified"],
        "abstain": True,
    }]}
    transport = OfflineTransport(_completion(pair, proposal=abstention))
    initial = run_initial_evidence_investigation(pair, MetaPolicyProposalAdapter(transport, _budget()))
    challenge = build_scenario_reviewer_challenge(pair, initial, "HOUSEKEEPING")
    recomputed = recompute_investigation_after_challenge(pair, initial, challenge)
    assert initial["provider_attribution"]["provider"] == "meta"
    assert initial["proposed_relation"] == "INCONCLUSIVE"
    assert initial["human_review_required"] is True
    assert recomputed["provider_attribution"] == initial["provider_attribution"]
    assert recomputed["recomputation_provider"] == "local_policy_engine"
    assert len(transport.calls) == 1


def test_budget_exhaustion_and_provider_failures_are_sanitized_without_retry():
    pair = build_hotel_scheduling_policy_pair()
    transport = OfflineTransport(_completion(pair))
    provider = MetaPolicyProposalAdapter(transport, _budget(max_requests=1))
    request = build_proposal_request(pair)
    provider.generate(pair, request)
    with pytest.raises(PolicyProviderError) as exhausted:
        provider.generate(pair, request)
    assert exhausted.value.code == "budget_exhausted"
    assert len(transport.calls) == 1

    for error in (TimeoutError("offline timeout diagnostic"), OSError("offline network diagnostic")):
        failing = MetaPolicyProposalAdapter(OfflineTransport(error=error), _budget())
        with pytest.raises(PolicyProviderError) as failed:
            failing.generate(pair, request)
        assert failed.value.code == "provider_failure"
        assert "diagnostic" not in str(failed.value)


def test_meta_http_transport_uses_fixed_url_bearer_and_supplied_body_only(monkeypatch):
    captured = []
    response_body = b'{"model":"muse-spark-1.3","choices":[]}'
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(
        lambda request: (captured.append(request) or _http_response(200, response_body))
    ))
    transport = MetaPolicyHttpxTransport(TEST_KEY)
    body = b'{"model":"muse-spark-1.3","messages":[]}'
    assert transport.complete(body, timeout_seconds=2.0) == response_body
    assert str(captured[0].url) == POLICY_META_CHAT_COMPLETIONS_ENDPOINT
    assert captured[0].headers["authorization"] == f"Bearer {TEST_KEY}"
    assert captured[0].content == body
    assert TEST_KEY not in repr(transport)


def test_meta_http_transport_sanitizes_timeout_network_and_http_errors(monkeypatch):
    for failure in (httpx.ReadTimeout("offline timeout"), httpx.ConnectError("offline network")):
        monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(
            lambda _request, error=failure: (_ for _ in ()).throw(error)
        ))
        with pytest.raises(PolicyProviderError) as caught:
            MetaPolicyHttpxTransport(TEST_KEY).complete(b"{}", timeout_seconds=2.0)
        assert caught.value.code == "provider_failure"
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(
        lambda _request: _http_response(503, b"provider detail withheld")
    ))
    with pytest.raises(PolicyProviderError) as caught:
        MetaPolicyHttpxTransport(TEST_KEY).complete(b"{}", timeout_seconds=2.0)
    assert caught.value.code == "provider_failure"
    assert "withheld" not in str(caught.value)


def test_policy_api_meta_attribution_and_challenge_make_one_mocked_provider_call(monkeypatch):
    from policy_demo_session import InMemoryDemoSessionManager

    pair = build_hotel_scheduling_policy_pair()
    requests = []
    completion = _completion(pair)

    def handler(request):
        requests.append(request)
        return _http_response(200, completion)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(handler))
    monkeypatch.setattr(policy_demo_api, "_policy_provider_initialized", False)
    monkeypatch.setattr(policy_demo_api, "_policy_provider", None)
    monkeypatch.setattr(policy_demo_api, "_policy_provider_failure_code", None)
    monkeypatch.setattr(policy_demo_api, "default_session_manager", InMemoryDemoSessionManager())
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")
    monkeypatch.setenv("MODEL_API_KEY", TEST_KEY)
    monkeypatch.setenv("META_MAX_REQUESTS", "1")
    monkeypatch.setenv("META_MAX_ESTIMATED_COST_USD", "0.10")
    monkeypatch.setenv("META_CONSERVATIVE_COST_PER_REQUEST_USD", "0.10")

    with TestClient(policy_demo_api.app) as client:
        scenario_response = client.get("/demo-api/scenario?id=scheduling")
        assert scenario_response.status_code == 200
        scenario = scenario_response.json()
        assert scenario["provider_attribution"]["provider"] == "meta"
        assert scenario["provider_attribution"]["model"] == "muse-spark-1.3"
        assert all(item["verified_locally"] for item in scenario["provenance_details"])
        session = client.post("/demo-api/session/new", json={
            "scenario_id": "scheduling", "proposal_id": scenario["proposal_id"],
        }).json()
        challenge = client.post("/demo-api/challenge", json={
            "scenario_id": "scheduling", "department_id": "HOUSEKEEPING",
            "session_id": session["session_id"], "proposal_id": scenario["proposal_id"],
        })
        assert challenge.status_code == 200
        result = challenge.json()
        assert result["provider_attribution"] == scenario["provider_attribution"]
        assert result["recomputation_provider"] == "local_policy_engine"
        assert len(requests) == 1
        assert requests[0].headers["authorization"] == f"Bearer {TEST_KEY}"


def test_api_meta_failure_is_visible_and_never_falls_back_to_synthetic(monkeypatch):
    monkeypatch.setattr(policy_demo_api, "_policy_provider_initialized", False)
    monkeypatch.setattr(policy_demo_api, "_policy_provider", None)
    monkeypatch.setattr(policy_demo_api, "_policy_provider_failure_code", None)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")
    monkeypatch.setenv("MODEL_API_KEY", TEST_KEY)
    monkeypatch.setenv("META_MAX_REQUESTS", "1")
    monkeypatch.setenv("META_MAX_ESTIMATED_COST_USD", "0.10")
    monkeypatch.setenv("META_CONSERVATIVE_COST_PER_REQUEST_USD", "0.10")
    calls = []

    def fail(request):
        calls.append(request)
        raise httpx.ConnectError("offline network diagnostic")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: AsyncMockTransport(fail))
    response = TestClient(policy_demo_api.app).get("/demo-api/scenario?id=scheduling")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "provider_failure"
    assert "proposed_relation" not in response.json()
    assert TEST_KEY not in response.text
    assert "offline network diagnostic" not in response.text
    assert len(calls) == 1

