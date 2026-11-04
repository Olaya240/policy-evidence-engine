"""Slice-20 contracts: `app/provider_activation.py` stays inert, explicit, and single-purpose.

Pins, each read out of the module before being asserted here:

1. The gate is disabled by default: `activate_baseten: bool = False`, and the
   default call returns `AssessmentEngine(provider=MockProvider())`.
2. Activation is explicit and single-purpose: exactly three keyword-only inputs
   (`activate_baseten`, `key_source`, `budget_config`), no endpoint/model/
   transport/budget overrides, and construction performs no HTTP work.
3. An activated provider is still wrapped by `MandatoryProviderBoundary`, and the
   transport refuses direct use (`mandatory_boundary_required`).
4. No environment variable enables the network provider: the module imports no
   `os`, never reads `os.environ`/`getenv`, and the exported
   `BASETEN_API_KEY_ENV_VAR` name appears exactly once — as a string literal that
   nothing consults. The explicit flag is necessary *and* not sufficient.
5. Activation failure raises instead of returning a partially-wired engine, so
   the process engine (`app.main.engine`) is still the bound mock.

Silent paths named by these tests (behaviour is pinned, not corrected — this
slice owns no `app/` file):

- **S1 not-activated silence.** A caller who supplies a working `key_source` and
  an enabled budget but omits `activate_baseten=True` gets a mock engine with no
  error, no warning, and no log record. Only `type(engine.provider)` reveals it.
- **S2 collapsed construction cause.** `except Exception: pass` around transport/
  adapter/engine construction discards the discriminating safety code: an
  `invalid_transport` from the transport is reported as `activation_failed` with
  `__context__ is None`.
- **S3 misclassified gate cause.** The same swallow around `ProviderCallGate`
  reports any non-budget failure as `invalid_budget`, so an unrelated defect
  looks like a budget misconfiguration.
- **S4 silent key-source failure.** A key source that raises is reported only as
  `key_unavailable`; the cause (and the fact that no key was obtained) is
  deliberately not chained or logged.
- **S5 unread env-var constant.** `BASETEN_API_KEY_ENV_VAR` is exported but never
  read, so an operator who exports `BASETEN_API_KEY` sees no effect and no
  diagnostic.
"""
import asyncio
import inspect
import logging
import pathlib
import types

import httpx
import pytest

from app import main as main_module
from app import provider_activation as activation
from app.httpx_transport import BasetenMuseSparkOpenTransport
from app.mock_provider import MockProvider
from app.provider_activation import (
    BASETEN_API_KEY_ENV_VAR,
    ProviderActivationError,
    create_assessment_engine,
)
from app.provider_safety import (
    BasetenMuseSparkOpenAdapter,
    MandatoryProviderBoundary,
    ProviderBudgetConfig,
    ProviderSafetyError,
)

_KEY = "SYNTHETIC_SLICE20_KEY_NEVER_REAL"
_MODULE_SOURCE = pathlib.Path(activation.__file__).read_text(encoding="utf-8")


def _budget(*, enabled=True, max_requests=1, ceiling="0.10", per_request="0.10"):
    return ProviderBudgetConfig(
        enabled=enabled,
        max_requests=max_requests,
        max_estimated_cost_usd=ceiling,
        conservative_cost_per_request_usd=per_request,
    )


def test_default_call_is_disabled_and_returns_a_bound_mock_engine():
    """Pin 1: the gate is off unless the caller asks for it, by literal default."""
    parameter = inspect.signature(create_assessment_engine).parameters["activate_baseten"]
    assert parameter.default is False

    engine = create_assessment_engine()

    assert type(engine.provider) is MockProvider
    assert type(engine.provider_boundary) is MandatoryProviderBoundary
    assert engine.provider_boundary._provider is engine.provider
    # No gate and no transport exist on the default engine at all, so "disabled
    # by default" is structural rather than a flag someone could flip at runtime.
    assert not hasattr(engine.provider, "_gate")
    assert not hasattr(engine.provider, "_transport")


def test_factory_exposes_exactly_three_keyword_only_inputs():
    """Pin 2: single purpose — no endpoint, model, transport, or budget overrides."""
    signature = inspect.signature(create_assessment_engine)
    assert set(signature.parameters) == {"activate_baseten", "key_source", "budget_config"}
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


@pytest.mark.parametrize("value", [1, 0, "yes", "False", None, object()])
def test_activation_flag_must_be_exactly_bool(value):
    """Pin 2: a truthy *or falsy* non-bool never silently chooses the mock path."""
    calls = []

    with pytest.raises(ProviderActivationError) as error:
        create_assessment_engine(
            activate_baseten=value,
            key_source=lambda: calls.append("called"),
            budget_config=_budget(),
        )

    assert error.value.code == "invalid_activation"
    assert calls == []


def test_budget_must_be_exact_type_with_enabled_literally_true():
    """Pin 2: a truthy `enabled` (1) or a duck-typed config cannot enable the gate."""
    calls = []
    truthy = ProviderBudgetConfig(
        enabled=1,
        max_requests=1,
        max_estimated_cost_usd="0.10",
        conservative_cost_per_request_usd="0.10",
    )
    duck = types.SimpleNamespace(
        enabled=True,
        max_requests=1,
        max_estimated_cost_usd="0.10",
        conservative_cost_per_request_usd="0.10",
    )

    for candidate in (truthy, duck, _budget(enabled=False)):
        with pytest.raises(ProviderActivationError) as error:
            create_assessment_engine(
                activate_baseten=True,
                key_source=lambda: calls.append("called") or _KEY,
                budget_config=candidate,
            )
        assert error.value.code == "enabled_budget_required"

    # Budget is validated before any key source is consulted.
    assert calls == []


def test_activation_constructs_the_transport_without_any_http_client():
    """Pin 2: activation wires objects; it performs no network work."""
    opened = []

    def refuse(**_kwargs):
        opened.append("client")
        raise AssertionError("activation constructed an HTTP client")

    original = httpx.AsyncHTTPTransport
    httpx.AsyncHTTPTransport = refuse
    try:
        engine = create_assessment_engine(
            activate_baseten=True,
            key_source=lambda: _KEY,
            budget_config=_budget(),
        )
    finally:
        httpx.AsyncHTTPTransport = original

    assert type(engine.provider) is BasetenMuseSparkOpenAdapter
    assert type(engine.provider._transport) is BasetenMuseSparkOpenTransport
    assert opened == []


def test_activated_provider_remains_wrapped_by_the_mandatory_boundary():
    """Pin 3: the live adapter is reachable only through the boundary."""
    engine = create_assessment_engine(
        activate_baseten=True,
        key_source=lambda: _KEY,
        budget_config=_budget(),
    )
    adapter = engine.provider

    assert type(adapter) is BasetenMuseSparkOpenAdapter
    assert type(engine.provider_boundary) is MandatoryProviderBoundary
    assert engine.provider_boundary._provider is adapter
    assert adapter._boundary is engine.provider_boundary
    assert adapter._transport._boundary is engine.provider_boundary
    assert adapter._gate.config.enabled is True
    assert adapter._gate.config.max_requests == 1

    with pytest.raises(ProviderSafetyError) as refused:
        asyncio.run(adapter._transport.send(b"{}", timeout_seconds=1.0))
    assert refused.value.code == "mandatory_boundary_required"


def test_environment_variable_cannot_enable_the_network_provider(monkeypatch):
    """Pin 4 / silence S5: exporting the key name changes nothing, flag or not."""
    for name in (BASETEN_API_KEY_ENV_VAR, "BASETEN_ENABLED", "ENABLE_BASETEN"):
        monkeypatch.setenv(name, _KEY if name == BASETEN_API_KEY_ENV_VAR else "1")

    default_engine = create_assessment_engine()
    assert type(default_engine.provider) is MockProvider
    assert not hasattr(default_engine.provider, "_transport")

    # The explicit flag is necessary but not sufficient: the environment is not
    # consulted as a key fallback either.
    with pytest.raises(ProviderActivationError) as missing_source:
        create_assessment_engine(activate_baseten=True, budget_config=_budget())
    assert missing_source.value.code == "key_source_required"

    # Ordering: the key source is validated before the budget, so the error code
    # names the first missing input rather than the last.
    with pytest.raises(ProviderActivationError) as no_budget:
        create_assessment_engine(activate_baseten=True)
    assert no_budget.value.code == "key_source_required"

    with pytest.raises(ProviderActivationError) as missing_budget:
        create_assessment_engine(activate_baseten=True, key_source=lambda: _KEY)
    assert missing_budget.value.code == "enabled_budget_required"


def test_module_has_no_environment_or_secret_store_lookup_path():
    """Pin 4 / silence S5: the env-var name exists once, as an unread literal."""
    assert "import os" not in _MODULE_SOURCE
    assert "os.environ" not in _MODULE_SOURCE
    assert "getenv" not in _MODULE_SOURCE
    assert _MODULE_SOURCE.count('"BASETEN_API_KEY"') == 1
    assert 'BASETEN_API_KEY_ENV_VAR = "BASETEN_API_KEY"' in _MODULE_SOURCE


def test_activation_failure_leaves_the_process_engine_on_the_mock_provider(monkeypatch):
    """Pin 5 / silence S2: a failed build raises; nothing is returned or swapped in."""
    original_engine = main_module.engine
    seen = []

    def rejecting(key):
        seen.append(key)
        raise ProviderSafetyError("invalid_transport")

    monkeypatch.setattr(activation, "BasetenMuseSparkOpenTransport", rejecting)

    with pytest.raises(ProviderActivationError) as error:
        create_assessment_engine(
            activate_baseten=True,
            key_source=lambda: _KEY,
            budget_config=_budget(),
        )

    # S2: the discriminating code is collapsed, and the cause is not chained.
    assert error.value.code == "activation_failed"
    assert error.value.__context__ is None
    assert error.value.__cause__ is None
    assert _KEY not in str(error.value)
    assert seen == [_KEY], "the transport was attempted once, with the supplied key"

    assert main_module.engine is original_engine
    assert type(main_module.engine.provider) is MockProvider
    assert type(main_module.engine.provider_boundary) is MandatoryProviderBoundary
    assert main_module.engine.provider_boundary._provider is main_module.engine.provider


def test_key_source_failure_does_not_fall_back_to_mock_or_chain_the_cause():
    """Pin 5 / silence S4: no engine is handed back, and the cause stays out."""
    original_engine = main_module.engine

    def failing_source():
        raise RuntimeError(_KEY)

    with pytest.raises(ProviderActivationError) as error:
        create_assessment_engine(
            activate_baseten=True,
            key_source=failing_source,
            budget_config=_budget(),
        )

    assert error.value.code == "key_unavailable"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert _KEY not in str(error.value)
    assert _KEY not in repr(error.value)
    assert main_module.engine is original_engine
    assert type(main_module.engine.provider) is MockProvider


def test_gate_construction_failure_is_reported_as_a_budget_problem(monkeypatch):
    """Silence S3: any gate failure is labelled `invalid_budget`, cause dropped."""
    calls = []

    def rejecting(_config):
        raise ValueError("synthetic non-budget failure")

    monkeypatch.setattr(activation, "ProviderCallGate", rejecting)

    with pytest.raises(ProviderActivationError) as error:
        create_assessment_engine(
            activate_baseten=True,
            key_source=lambda: calls.append("called") or _KEY,
            budget_config=_budget(),
        )

    assert error.value.code == "invalid_budget"
    assert error.value.__context__ is None
    assert error.value.__cause__ is None
    # The key source is never consulted when the budget cannot be built.
    assert calls == []


def test_omitted_flag_is_silent_about_the_options_it_ignored(caplog):
    """Silence S1: a real key source plus an enabled budget still yields a mock."""
    calls = []
    caplog.set_level(logging.DEBUG)

    engine = create_assessment_engine(
        key_source=lambda: calls.append("called") or _KEY,
        budget_config=_budget(),
    )

    assert type(engine.provider) is MockProvider
    assert type(engine.provider_boundary._provider) is MockProvider
    assert calls == [], "the inactive path must not touch the key source"
    emitted = [r for r in caplog.records if r.name.startswith("app.provider_activation")]
    assert emitted == [], "not-activating is silent: no log record, so no warning"
