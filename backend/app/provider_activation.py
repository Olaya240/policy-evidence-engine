"""Explicit, inert-by-default construction for the Baseten adapter prototype.

No environment lookup or secret-store access is implemented here; no
deployment secret manager has been identified. A future approved loader may be
supplied as ``key_source``; it is called only after explicit activation and a
valid budget.
"""
from collections.abc import Callable

from .engine import AssessmentEngine
from .httpx_transport import BasetenMuseSparkOpenTransport
from .httpx_transport import MetaMuseSparkTransport
from .mock_provider import MockProvider
from .provider_safety import (
    BasetenMuseSparkOpenAdapter,
    ProviderBudgetConfig,
    ProviderCallGate,
    MetaMuseSparkAdapter,
)

BASETEN_API_KEY_ENV_VAR = "BASETEN_API_KEY"


class ProviderActivationError(RuntimeError):
    """Fixed, sanitized error for explicit provider configuration failures."""

    def __init__(self, code: str):
        self.code = code
        super().__init__("Baseten provider activation could not be safely configured")


def create_assessment_engine(
    *,
    activate_baseten: bool = False,
    key_source: Callable[[], object] | None = None,
    budget_config: ProviderBudgetConfig | None = None,
) -> AssessmentEngine:
    """Return the mock engine unless Baseten activation is explicitly requested.

    This internal construction seam has no environment or secret-manager
    default. The caller must provide an approved key source and enabled budget
    configuration when activation is requested. Endpoint, model, transport,
    and provider types are fixed here.
    """
    if type(activate_baseten) is not bool:
        raise ProviderActivationError("invalid_activation")
    if not activate_baseten:
        # Inactive construction deliberately does not inspect either optional
        # argument and cannot accidentally consult a key source.
        return AssessmentEngine(provider=MockProvider())

    if not callable(key_source):
        raise ProviderActivationError("key_source_required")
    if (type(budget_config) is not ProviderBudgetConfig
            or budget_config.enabled is not True):
        raise ProviderActivationError("enabled_budget_required")

    # Validate the explicit budget before consulting a key source.
    gate = None
    try:
        gate = ProviderCallGate(budget_config)
    except Exception:
        pass
    if gate is None:
        raise ProviderActivationError("invalid_budget")

    key = None
    key_source_failed = False
    try:
        key = key_source()
    except Exception:
        key_source_failed = True
    if key_source_failed:
        raise ProviderActivationError("key_unavailable")

    if (type(key) is not str or not key or key.strip() != key
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in key)):
        raise ProviderActivationError("invalid_key")

    engine = None
    try:
        transport = BasetenMuseSparkOpenTransport(key)
        provider = BasetenMuseSparkOpenAdapter(transport, gate)
        engine = AssessmentEngine(provider=provider)
    except Exception:
        pass
    if engine is None:
        raise ProviderActivationError("activation_failed")
    return engine


def create_meta_assessment_engine(*, key_source: Callable[[], object],
                                  budget_config: ProviderBudgetConfig) -> AssessmentEngine:
    """Construct the fixed Meta adapter only with an explicit key source and budget."""
    if not callable(key_source):
        raise ProviderActivationError("key_source_required")
    if type(budget_config) is not ProviderBudgetConfig or budget_config.enabled is not True:
        raise ProviderActivationError("enabled_budget_required")
    try:
        gate = ProviderCallGate(budget_config)
    except Exception:
        raise ProviderActivationError("invalid_budget") from None
    try:
        key = key_source()
    except Exception:
        raise ProviderActivationError("key_unavailable") from None
    if (type(key) is not str or not key or key.strip() != key
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in key)):
        raise ProviderActivationError("invalid_key")
    try:
        return AssessmentEngine(provider=MetaMuseSparkAdapter(MetaMuseSparkTransport(key), gate))
    except Exception:
        raise ProviderActivationError("activation_failed") from None


__all__ = [
    "BASETEN_API_KEY_ENV_VAR",
    "ProviderActivationError",
    "create_assessment_engine",
    "create_meta_assessment_engine",
]
