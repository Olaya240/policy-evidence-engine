"""Wiring tests: `app.main` builds its engine through the activation factory.

The seam in `app.provider_activation` only matters if something calls it. These
tests cover the composition root in `app.main`:

1. The default is the mock provider, wrapped by the mandatory boundary, and no
   configuration is required to keep it that way.
2. A requested activation that is missing its key is refused — the process keeps
   the mock and says why, instead of silently ignoring the request.
3. Any activation failure leaves the mock provider in place.
4. The explicit flag *and* a key *and* a budget do reach the live adapter, still
   behind `MandatoryProviderBoundary`, so the wiring is a path and not a decoy.
"""
import logging
import pathlib

from app import main as main_module
from app import provider_activation as activation
from app.mock_provider import MockProvider
from app.provider_activation import ProviderActivationError
from app.provider_safety import (
    BasetenMuseSparkOpenAdapter,
    MandatoryProviderBoundary,
    ProviderSafetyError,
)

_SYNTHETIC_KEY = "SYNTHETIC_WIRING_KEY_NEVER_REAL"
_MAIN_SOURCE = pathlib.Path(main_module.__file__).read_text(encoding="utf-8")


def _activated_environ(**overrides):
    environ = {
        main_module.ACTIVATE_BASETEN_ENV_VAR: "1",
        main_module.BASETEN_API_KEY_ENV_VAR: _SYNTHETIC_KEY,
        main_module.BASETEN_MAX_REQUESTS_ENV_VAR: "1",
        main_module.BASETEN_MAX_ESTIMATED_COST_ENV_VAR: "0.10",
        main_module.BASETEN_CONSERVATIVE_COST_ENV_VAR: "0.10",
    }
    environ.update(overrides)
    return environ


def _assert_bound_mock(engine) -> None:
    assert type(engine.provider) is MockProvider
    assert type(engine.provider_boundary) is MandatoryProviderBoundary
    assert engine.provider_boundary._provider is engine.provider
    assert not hasattr(engine.provider, "_transport")


class _SealedKeyMapping(dict):
    """A mapping whose key value cannot be fetched, so only presence is observable."""

    def __getitem__(self, key):
        if key == main_module.BASETEN_API_KEY_ENV_VAR:
            raise AssertionError("the key value was read on the inactive path")
        return super().__getitem__(key)


def test_default_environment_builds_a_bound_mock_engine(caplog):
    caplog.set_level(logging.DEBUG)

    engine = main_module.build_engine_from_environment({})

    _assert_bound_mock(engine)
    assert [r for r in caplog.records if r.name == "app.main"] == []


def test_process_engine_defaults_to_the_mock_reached_through_the_factory():
    engine = main_module.engine
    _assert_bound_mock(engine)
    # The defect was a direct constructor call here: one caller of the factory
    # replaces it, and nothing else in the module builds an engine by hand.
    assert "engine = build_engine_from_environment(os.environ)" in _MAIN_SOURCE
    assert "AssessmentEngine()" not in _MAIN_SOURCE


def test_flag_without_key_is_refused_and_keeps_the_mock(monkeypatch, caplog):
    seen = {}
    real_factory = main_module.create_assessment_engine

    def recording_factory(**kwargs):
        seen.update(kwargs)
        return real_factory(**kwargs)

    monkeypatch.setattr(main_module, "create_assessment_engine", recording_factory)
    caplog.set_level(logging.WARNING)
    environ = _activated_environ()
    del environ[main_module.BASETEN_API_KEY_ENV_VAR]

    engine = main_module.build_engine_from_environment(environ)

    _assert_bound_mock(engine)
    # Activation was requested, so the refusal is the factory's, not a silently
    # skipped branch.
    assert seen["activate_baseten"] is True
    assert seen["key_source"] is None
    assert any("key_source_required" in r.getMessage() for r in caplog.records)


def test_key_without_flag_is_reported_and_never_fetched(caplog):
    caplog.set_level(logging.WARNING)
    environ = _SealedKeyMapping(_activated_environ())
    del environ[main_module.ACTIVATE_BASETEN_ENV_VAR]

    engine = main_module.build_engine_from_environment(environ)

    _assert_bound_mock(engine)
    messages = [r.getMessage() for r in caplog.records]
    assert any("ENABLE_BASETEN is not enabled" in message for message in messages)
    assert all(_SYNTHETIC_KEY not in message for message in messages)


def test_unrecognised_flag_value_stays_off(caplog):
    caplog.set_level(logging.WARNING)
    environ = _activated_environ(**{main_module.ACTIVATE_BASETEN_ENV_VAR: "maybe"})

    engine = main_module.build_engine_from_environment(environ)

    _assert_bound_mock(engine)
    assert any(
        "not a recognised activation value" in record.getMessage()
        for record in caplog.records
    )


def test_incomplete_budget_refuses_and_keeps_the_mock(caplog):
    caplog.set_level(logging.WARNING)
    environ = _activated_environ()
    del environ[main_module.BASETEN_CONSERVATIVE_COST_ENV_VAR]

    engine = main_module.build_engine_from_environment(environ)

    _assert_bound_mock(engine)
    assert any("enabled_budget_required" in r.getMessage() for r in caplog.records)


def test_failed_activation_leaves_the_mock_provider(monkeypatch, caplog):
    def rejecting(key):
        raise ProviderSafetyError("invalid_transport")

    monkeypatch.setattr(activation, "BasetenMuseSparkOpenTransport", rejecting)
    caplog.set_level(logging.WARNING)
    original_engine = main_module.engine

    engine = main_module.build_engine_from_environment(_activated_environ())

    _assert_bound_mock(engine)
    assert any("activation_failed" in r.getMessage() for r in caplog.records)
    # The process engine is untouched, so a failed build cannot half-swap it.
    assert main_module.engine is original_engine
    _assert_bound_mock(main_module.engine)


def test_unexpected_factory_failure_leaves_the_mock_provider(monkeypatch, caplog):
    real_factory = main_module.create_assessment_engine

    def exploding_factory(**kwargs):
        if kwargs.get("activate_baseten"):
            raise RuntimeError("synthetic wiring failure")
        return real_factory(**kwargs)

    monkeypatch.setattr(main_module, "create_assessment_engine", exploding_factory)
    caplog.set_level(logging.WARNING)

    engine = main_module.build_engine_from_environment(_activated_environ())

    _assert_bound_mock(engine)
    assert any(
        "failed unexpectedly" in record.getMessage() for record in caplog.records
    )
    assert all(_SYNTHETIC_KEY not in record.getMessage() for record in caplog.records)


def test_explicit_flag_key_and_budget_activate_behind_the_boundary():
    engine = main_module.build_engine_from_environment(_activated_environ())

    adapter = engine.provider
    assert type(adapter) is BasetenMuseSparkOpenAdapter
    assert type(engine.provider_boundary) is MandatoryProviderBoundary
    assert engine.provider_boundary._provider is adapter
    assert adapter._boundary is engine.provider_boundary
    assert adapter._transport._boundary is engine.provider_boundary
    assert adapter._gate.config.enabled is True
    assert adapter._gate.config.max_requests == 1


def test_refused_activation_does_not_echo_the_key(monkeypatch, caplog):
    from app.provider_activation import create_assessment_engine

    def refusing(**kwargs):
        if kwargs.get("activate_baseten"):
            raise ProviderActivationError("key_unavailable")
        return create_assessment_engine(**kwargs)

    monkeypatch.setattr(main_module, "create_assessment_engine", refusing)
    caplog.set_level(logging.DEBUG)

    engine = main_module.build_engine_from_environment(_activated_environ())

    _assert_bound_mock(engine)
    assert any("key_unavailable" in r.getMessage() for r in caplog.records)
    assert all(_SYNTHETIC_KEY not in r.getMessage() for r in caplog.records)
    assert all(_SYNTHETIC_KEY not in repr(r.args) for r in caplog.records)
