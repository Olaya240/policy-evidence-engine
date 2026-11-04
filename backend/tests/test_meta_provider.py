"""Offline-only coverage for the pinned Meta Muse Spark provider."""
import json
from decimal import Decimal

import httpx
import pytest

from app import main
from app.httpx_transport import META_CHAT_COMPLETIONS_ENDPOINT, MetaMuseSparkTransport
from app.mock_provider import MockProvider, SEED_RECORDS
from app.provider_activation import ProviderActivationError, create_meta_assessment_engine
from app.provider_safety import (MandatoryProviderBoundary, MetaMuseSparkAdapter,
    ProviderBudgetConfig, ProviderCallGate, ProviderSafetyError, serialize_provider_request)

KEY = "SYNTHETIC_META_KEY_NEVER_REAL"
RECORD = SEED_RECORDS[0]
PROPOSAL = {"source_record_id": RECORD.id, "quote": RECORD.text[:40],
            "stance": "NEUTRAL", "rationale": "Synthetic offline test proposal."}


def gate():
    return ProviderCallGate(ProviderBudgetConfig(enabled=True, max_requests=1,
        max_estimated_cost_usd=Decimal("0.10"),
        conservative_cost_per_request_usd=Decimal("0.10")))


def request():
    return serialize_provider_request([RECORD], "TIME_PRESSURE")


def completion(content=None, model=MetaMuseSparkAdapter.MODEL_ID):
    return json.dumps({"id": "synthetic", "object": "chat.completion", "created": 1,
        "model": model, "choices": [{"index": 0, "message": {"role": "assistant",
        "content": json.dumps([PROPOSAL] if content is None else content)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        separators=(",", ":")).encode()


class Body(httpx.AsyncByteStream):
    def __init__(self, body): self.body = body
    async def __aiter__(self): yield self.body
    async def aclose(self): pass


def engine(monkeypatch, *, status=200, body=None, error=None, captured=None):
    def handler(req):
        if captured is not None: captured.append(req)
        if error: raise error
        return httpx.Response(status, stream=Body(completion() if body is None else body))
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handler))
    return create_meta_assessment_engine(key_source=lambda: KEY,
        budget_config=ProviderBudgetConfig(enabled=True, max_requests=1,
          max_estimated_cost_usd="0.10", conservative_cost_per_request_usd="0.10"))


def test_meta_request_is_pinned_and_bearer_key_is_not_exposed(monkeypatch):
    seen = []
    eng = engine(monkeypatch, captured=seen)
    assert eng.provider_boundary.assess([RECORD], "TIME_PRESSURE") == [PROPOSAL]
    req = seen[0]
    assert str(req.url) == META_CHAT_COMPLETIONS_ENDPOINT
    assert req.headers["authorization"] == f"Bearer {KEY}"
    data = json.loads(req.content)
    assert data["model"] == "muse-spark-1.3"
    assert "authorization" not in repr(eng.provider)
    assert KEY not in repr(eng.provider) + repr(eng.provider._transport)


@pytest.mark.parametrize(("status", "code"), [(401, "authentication_failed"),
    (403, "authentication_failed"), (429, "rate_limited"), (500, "provider_server_error"),
    (503, "provider_server_error")])
def test_meta_http_errors_are_sanitized_and_not_mock_fallback(monkeypatch, status, code):
    eng = engine(monkeypatch, status=status)
    with pytest.raises(ProviderSafetyError) as error:
        eng.provider_boundary.assess([RECORD], "TIME_PRESSURE")
    assert error.value.code == code
    assert type(eng.provider) is MetaMuseSparkAdapter


def test_empty_malformed_and_wrong_model_responses_fail_closed(monkeypatch):
    for body in (completion([]), b"not-json", completion(model="other-model")):
        eng = engine(monkeypatch, body=body)
        with pytest.raises(ProviderSafetyError):
            eng.provider_boundary.assess([RECORD], "TIME_PRESSURE")


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("synthetic"), httpx.ConnectError("synthetic")])
def test_meta_timeout_and_network_errors_are_sanitized(monkeypatch, error):
    eng = engine(monkeypatch, error=error)
    with pytest.raises(ProviderSafetyError) as caught:
        eng.provider_boundary.assess([RECORD], "TIME_PRESSURE")
    assert caught.value.code in {"timeout", "provider_failure"}
    assert KEY not in str(caught.value)


def _meta_env(**updates):
    env = {"ENABLE_META": "1", "MODEL_API_KEY": KEY, "META_MAX_REQUESTS": "1",
           "META_MAX_ESTIMATED_COST_USD": "0.10",
           "META_CONSERVATIVE_COST_PER_REQUEST_USD": "0.10"}
    env.update(updates)
    return env


def test_meta_activation_requires_key_and_complete_budget_and_mock_is_default():
    assert type(main.build_engine_from_environment({}).provider) is MockProvider
    no_key = _meta_env()
    del no_key["MODEL_API_KEY"]
    assert type(main.build_engine_from_environment(no_key).provider) is MockProvider
    assert type(main.build_engine_from_environment(_meta_env(MODEL_API_KEY="")).provider) is MockProvider
    assert type(main.build_engine_from_environment(_meta_env().copy()).provider) is MetaMuseSparkAdapter
    with pytest.raises(ProviderActivationError):
        create_meta_assessment_engine(key_source=lambda: KEY, budget_config=None)


def test_both_remote_provider_flags_fail_closed_to_mock():
    assert type(main.build_engine_from_environment(_meta_env(ENABLE_BASETEN="1")).provider) is MockProvider
