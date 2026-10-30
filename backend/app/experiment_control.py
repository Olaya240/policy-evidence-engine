"""Process-local run accounting for deterministic evaluation and fake providers only.

This module is not used by the runtime provider path and cannot enable a transport.
Its estimated cost is a local reservation estimate, not a provider billing limit.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import Callable, TypeVar
from uuid import uuid4

from .provider_safety import MAX_CONFIGURABLE_ESTIMATED_BUDGET_USD, MAX_EXPERIMENT_REQUESTS

T = TypeVar("T")


class ExperimentControlError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__("Experiment request was not authorized")


def _money(value: Decimal | str | int | float, *, allow_zero: bool) -> Decimal:
    if isinstance(value, bool):
        raise ExperimentControlError("invalid_budget")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ExperimentControlError("invalid_budget") from None
    if not amount.is_finite() or amount < 0 or (amount == 0 and not allow_zero):
        raise ExperimentControlError("invalid_budget")
    return amount


@dataclass
class _RunLedger:
    signature: tuple
    lock: Lock
    requests: int = 0
    estimated_cost: Decimal = Decimal("0")
    active: int = 0


_registry_lock = Lock()
_run_ledgers: dict[str, _RunLedger] = {}


class ExperimentRunController:
    """Atomically reserve attempts across controller instances sharing a run ID.

    Failed callback attempts consume request and estimated-cost quota. The optional
    single-flight check is independent of the run-wide request cap.
    """

    __slots__ = ("run_id", "_ledger", "_max_requests", "_cost_per_request", "_single_flight")

    def __init__(
        self,
        *,
        run_id: str | None = None,
        max_requests: int = MAX_EXPERIMENT_REQUESTS,
        estimated_cost_ceiling_usd: Decimal | str | int | float = "5.00",
        estimated_cost_per_request_usd: Decimal | str | int | float = "0",
        single_flight: bool = True,
    ):
        if isinstance(max_requests, bool) or not isinstance(max_requests, int) or not 1 <= max_requests <= MAX_EXPERIMENT_REQUESTS:
            raise ExperimentControlError("invalid_budget")
        if not isinstance(single_flight, bool):
            raise ExperimentControlError("invalid_budget")
        ceiling = _money(estimated_cost_ceiling_usd, allow_zero=False)
        per_request = _money(estimated_cost_per_request_usd, allow_zero=True)
        if ceiling > MAX_CONFIGURABLE_ESTIMATED_BUDGET_USD or per_request * max_requests > ceiling:
            raise ExperimentControlError("invalid_budget")
        chosen_id = run_id or uuid4().hex
        if not isinstance(chosen_id, str) or not chosen_id.strip() or len(chosen_id) > 128:
            raise ExperimentControlError("invalid_run_id")
        signature = (max_requests, ceiling, per_request, single_flight)
        with _registry_lock:
            ledger = _run_ledgers.get(chosen_id)
            if ledger is None:
                ledger = _RunLedger(signature=signature, lock=Lock())
                _run_ledgers[chosen_id] = ledger
            elif ledger.signature != signature:
                raise ExperimentControlError("run_configuration_conflict")
        self.run_id = chosen_id
        self._ledger = ledger
        self._max_requests = max_requests
        self._cost_per_request = per_request
        self._single_flight = single_flight

    @property
    def request_count(self) -> int:
        with self._ledger.lock:
            return self._ledger.requests

    @property
    def estimated_cost_reserved_usd(self) -> Decimal:
        with self._ledger.lock:
            return self._ledger.estimated_cost

    def execute(self, case_id: str, attempt: Callable[[], T]) -> T:
        """Reserve before callback execution; never retry or refund a failed attempt."""
        if not isinstance(case_id, str) or not case_id.strip() or not callable(attempt):
            raise ExperimentControlError("invalid_attempt")
        with self._ledger.lock:
            if self._single_flight and self._ledger.active:
                raise ExperimentControlError("single_flight_limit")
            if self._ledger.requests >= self._max_requests:
                raise ExperimentControlError("request_limit")
            projected = self._ledger.estimated_cost + self._cost_per_request
            # Re-check against the immutable signature in the shared ledger.
            ceiling = self._ledger.signature[1]
            if projected > ceiling:
                raise ExperimentControlError("estimated_budget_exceeded")
            self._ledger.requests += 1
            self._ledger.estimated_cost = projected
            self._ledger.active += 1
        try:
            return attempt()
        finally:
            with self._ledger.lock:
                self._ledger.active -= 1
