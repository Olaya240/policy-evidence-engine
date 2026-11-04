"""Offline-only tests for explicit, default-off provider activation."""
import asyncio
import hmac
import logging

import httpx
import pytest

from app import main as main_module
from app.engine import ProviderError
from app.httpx_transport import (
    BASETEN_CHAT_COMPLETIONS_ENDPOINT,
    BasetenMuseSparkOpenTransport,
)
from app.mock_provider import MockProvider, SEED_RECORDS
from app.provider_activation import (
    BASETEN_API_KEY_ENV_VAR,
    ProviderActivationError,
    create_assessment_engine,
)
from app.provider_safety import (
    BasetenMuseSparkOpenAdapter,
    ProviderBudgetConfig,
)

_SYNTHETIC_KEY = "SYNTHETIC_ACTIVATION_KEY_NEVER_REAL"


def _budget():
    return ProviderBudgetConfig(
        enabled=True,
        max_requests=1,
        max_estimated_cost_usd="0.10",
        conservative_cost_per_request_usd="0.10",
    )


def _assert_secret_absent(value: str, synthetic_key: str) -> None:
    if synthetic_key in value:
        raise AssertionError("redaction assertion failed")


def _assert_header_matches(value: str, synthetic_key: str) -> None:
    expected = "Bearer " + synthetic_key
    if not hmac.compare_digest(value, expected):
        raise AssertionError("authorization header did not match the synthetic test value")


def test_inactive_factory_uses_mock_and_never_calls_key_source():
    calls = []

    def forbidden_source():
        calls.append("called")
        raise AssertionError("inactive path consulted the key source")

    engine = create_assessment_engine(key_source=forbidden_source)

    assert type(engine.provider) is MockProvider
    assert engine.provider_boundary._provider is engine.provider
    assert calls == []


def test_false_activation_does_not_consult_key_source_even_with_other_options():
    calls = []
    engine = create_assessment_engine(
        activate_baseten=False,
        key_source=lambda: calls.append("called"),
        budget_config=_budget(),
    )

    assert type(engine.provider) is MockProvider
    assert calls == []


def test_activation_requires_key_source_and_enabled_budget_before_key_lookup():
    calls = []
    with pytest.raises(ProviderActivationError) as missing_source:
        create_assessment_engine(activate_baseten=True, budget_config=_budget())
    assert missing_source.value.code == "key_source_required"

    with pytest.raises(ProviderActivationError) as missing_budget:
        create_assessment_engine(
            activate_baseten=True,
            key_source=lambda: calls.append("called"),
        )
    assert missing_budget.value.code == "enabled_budget_required"
    assert calls == []

    invalid_budget = ProviderBudgetConfig(
        enabled=True,
        max_requests=18,
        max_estimated_cost_usd="0.10",
        conservative_cost_per_request_usd="0.01",
    )
    with pytest.raises(ProviderActivationError) as invalid:
        create_assessment_engine(
            activate_baseten=True,
            key_source=lambda: calls.append("called"),
            budget_config=invalid_budget,
        )
    assert invalid.value.code == "invalid_budget"
    assert calls == []


@pytest.mark.parametrize("key", [None, "", "   ", "\tbad", "bad\nkey"])
def test_explicit_activation_rejects_missing_or_invalid_synthetic_key(key):
    with pytest.raises(ProviderActivationError) as error:
        create_assessment_engine(
            activate_baseten=True,
            key_source=lambda: key,
            budget_config=_budget(),
        )
    assert error.value.code == "invalid_key"
    assert str(error.value) == "Baseten provider activation could not be safely configured"


def test_enabled_gate_and_exact_adapter_types_exist_only_on_explicit_factory_path():
    engine = create_assessment_engine(
        activate_baseten=True,
        key_source=lambda: _SYNTHETIC_KEY,
        budget_config=_budget(),
    )

    assert type(engine.provider) is BasetenMuseSparkOpenAdapter
    assert type(engine.provider._transport) is BasetenMuseSparkOpenTransport
    assert engine.provider._gate.config.enabled is True
    assert engine.provider._boundary is engine.provider_boundary
    assert engine.provider_boundary._provider is engine.provider


def test_factory_does_not_offer_endpoint_model_or_transport_overrides():
    import inspect

    parameters = set(inspect.signature(create_assessment_engine).parameters)
    assert not {"endpoint", "model", "transport"} & parameters
    assert BASETEN_CHAT_COMPLETIONS_ENDPOINT == "https://inference.baseten.co/v1/chat/completions"
    assert BasetenMuseSparkOpenAdapter.MODEL_SLUG == "meta-models/muse-spark-open-1026"
    assert BASETEN_API_KEY_ENV_VAR == "BASETEN_API_KEY"


def test_normal_application_module_keeps_mock_default():
    assert type(main_module.engine.provider) is MockProvider
    assert main_module.engine.provider_boundary._provider is main_module.engine.provider


def test_provider_failure_does_not_fallback_and_redacts_synthetic_key(
    monkeypatch, caplog,
):
    sent = []

    def response_handler(request):
        sent.append(request)
        return httpx.Response(401, content=_SYNTHETIC_KEY.encode("ascii"), request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncHTTPTransport",
        lambda **_kwargs: httpx.MockTransport(response_handler),
    )
    caplog.set_level(logging.DEBUG)
    engine = create_assessment_engine(
        activate_baseten=True,
        key_source=lambda: _SYNTHETIC_KEY,
        budget_config=_budget(),
    )
    transport = engine.provider._transport

    with pytest.raises(ProviderError) as failure:
        engine.assess_hypothesis([SEED_RECORDS[0]], "CHECKLIST_UNAVAILABLE")

    assert len(sent) == 1
    authorization = sent[0].headers["authorization"]
    _assert_header_matches(authorization, _SYNTHETIC_KEY)
    assert type(engine.provider) is BasetenMuseSparkOpenAdapter
    assert engine.provider is engine.provider_boundary._provider
    _assert_secret_absent(repr(transport), _SYNTHETIC_KEY)
    _assert_secret_absent(repr(engine.provider), _SYNTHETIC_KEY)
    _assert_secret_absent(repr(engine), _SYNTHETIC_KEY)
    _assert_secret_absent(str(failure.value), _SYNTHETIC_KEY)
    _assert_secret_absent(caplog.text, _SYNTHETIC_KEY)

    response = asyncio.run(main_module.provider_error_handler(None, failure.value))
    _assert_secret_absent(response.body.decode("utf-8"), _SYNTHETIC_KEY)


def test_key_source_failure_is_sanitized_without_fallback():
    def failing_source():
        raise RuntimeError(_SYNTHETIC_KEY)

    with pytest.raises(ProviderActivationError) as error:
        create_assessment_engine(
            activate_baseten=True,
            key_source=failing_source,
            budget_config=_budget(),
        )

    assert error.value.code == "key_unavailable"
    assert error.value.__context__ is None
    _assert_secret_absent(str(error.value), _SYNTHETIC_KEY)

