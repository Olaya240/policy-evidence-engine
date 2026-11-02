"""Contract of the process-local experiment run controller (slice 16).

Real call site: `app/evaluate.py` builds one controller per evaluation run with
`max_requests=len(eligible_cases), single_flight=True` (line 153), calls
`execute(case["id"], assess_target)` per case (line 203), reads
`run_controller.request_count` while building attempt metadata (lines 220, 232)
and the `assessment_calls` counter (line 309), and maps
`ExperimentControlError.code` onto `error_category` (line 208). Default cost
arguments mean a run reserves `Decimal("0")` per request.

Pinned here: every branch of the public surface -- constructor validation,
registry/signature conflict, the two read-only properties, and each of
`execute`'s rejections (`invalid_attempt`, `single_flight_limit`,
`request_limit`, `estimated_budget_exceeded`) with its ordering relative to the
callback.

Note on `estimated_budget_exceeded`: the constructor already refuses
`per_request * max_requests > ceiling`, and `request_limit` is checked before
the projected cost is compared, so that branch is a defensive re-check against
the immutable shared signature and is not reachable through the public
constructor. The tests below pin the reachable behaviour: oversubscription is
refused at construction, and exhausting a legal run reports `request_limit`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from uuid import uuid4

import pytest

from app.experiment_control import ExperimentControlError, ExperimentRunController
from app.provider_safety import (
    MAX_CONFIGURABLE_ESTIMATED_BUDGET_USD,
    MAX_EXPERIMENT_REQUESTS,
)


def controller(run_id: str | None = None, **kwargs) -> ExperimentRunController:
    """Every test gets a fresh run ID: the registry is process-global and permanent."""
    return ExperimentRunController(run_id=run_id or uuid4().hex, **kwargs)


def code_of(exc: pytest.ExceptionInfo) -> str:
    return exc.value.code


# --- ExperimentControlError -------------------------------------------------


def test_error_exposes_its_code_and_a_fixed_message_that_does_not_leak_it():
    error = ExperimentControlError("request_limit")
    assert error.code == "request_limit"
    assert str(error) == "Experiment request was not authorized"
    assert "request_limit" not in str(error)
    assert isinstance(error, RuntimeError)


def test_error_message_is_identical_for_different_codes():
    assert str(ExperimentControlError("invalid_budget")) == str(
        ExperimentControlError("run_configuration_conflict")
    )


# --- constructor: max_requests ---------------------------------------------


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, "3", None,
                                   MAX_EXPERIMENT_REQUESTS + 1, 10**9])
def test_invalid_max_requests_is_rejected(value):
    with pytest.raises(ExperimentControlError) as exc:
        controller(max_requests=value)
    assert code_of(exc) == "invalid_budget"


def test_max_requests_boundaries_are_accepted():
    assert controller(max_requests=1).request_count == 0
    assert controller(max_requests=MAX_EXPERIMENT_REQUESTS).request_count == 0


# --- constructor: single_flight --------------------------------------------


@pytest.mark.parametrize("value", [1, 0, "true", None, Decimal("1")])
def test_non_bool_single_flight_is_rejected(value):
    with pytest.raises(ExperimentControlError) as exc:
        controller(single_flight=value)
    assert code_of(exc) == "invalid_budget"


# --- constructor: money ----------------------------------------------------


@pytest.mark.parametrize("value", [0, "0", -1, "-0.01", "NaN", "Infinity", "-Infinity",
                                   True, False, "abc", None, "", object()])
def test_invalid_cost_ceiling_is_rejected(value):
    with pytest.raises(ExperimentControlError) as exc:
        controller(estimated_cost_ceiling_usd=value)
    assert code_of(exc) == "invalid_budget"


def test_cost_ceiling_above_the_configurable_cap_is_rejected():
    with pytest.raises(ExperimentControlError) as exc:
        controller(estimated_cost_ceiling_usd=MAX_CONFIGURABLE_ESTIMATED_BUDGET_USD + Decimal("0.01"))
    assert code_of(exc) == "invalid_budget"


def test_cost_ceiling_at_the_configurable_cap_is_accepted():
    assert controller(estimated_cost_ceiling_usd=MAX_CONFIGURABLE_ESTIMATED_BUDGET_USD).estimated_cost_reserved_usd == Decimal("0")


def test_per_request_cost_may_be_zero():
    assert controller(estimated_cost_per_request_usd=0).estimated_cost_reserved_usd == Decimal("0")


@pytest.mark.parametrize("value", [-1, "-0.01", "NaN", True, "abc", None])
def test_invalid_per_request_cost_is_rejected(value):
    with pytest.raises(ExperimentControlError) as exc:
        controller(estimated_cost_per_request_usd=value)
    assert code_of(exc) == "invalid_budget"


def test_oversubscription_of_the_ceiling_is_refused_at_construction():
    with pytest.raises(ExperimentControlError) as exc:
        controller(max_requests=2, estimated_cost_ceiling_usd="1.00",
                   estimated_cost_per_request_usd="0.51")
    assert code_of(exc) == "invalid_budget"


def test_per_request_cost_exactly_filling_the_ceiling_is_accepted():
    run = controller(max_requests=2, estimated_cost_ceiling_usd="1.00",
                     estimated_cost_per_request_usd="0.50", single_flight=False)
    assert run.execute("case-a", lambda: "ok") == "ok"
    assert run.estimated_cost_reserved_usd == Decimal("0.50")


# --- constructor: run id ---------------------------------------------------


@pytest.mark.parametrize("value", ["   ", 123, 1.5, ("tuple",), "a" * 129, object()])
def test_invalid_run_id_is_rejected(value):
    with pytest.raises(ExperimentControlError) as exc:
        ExperimentRunController(run_id=value)
    assert code_of(exc) == "invalid_run_id"


def test_run_id_at_the_length_boundary_is_accepted():
    assert ExperimentRunController(run_id="a" * 128).run_id == "a" * 128


@pytest.mark.parametrize("value", [None, ""])
def test_absent_run_id_is_generated_as_a_hex_uuid(value):
    run = ExperimentRunController(run_id=value)
    assert isinstance(run.run_id, str)
    assert len(run.run_id) == 32
    assert run.run_id == run.run_id.strip()


def test_generated_run_ids_are_distinct():
    assert ExperimentRunController().run_id != ExperimentRunController().run_id


# --- registry: signature sharing and conflict ------------------------------


def test_same_run_id_with_a_different_max_requests_conflicts():
    run_id = uuid4().hex
    controller(run_id, max_requests=2, single_flight=False)
    with pytest.raises(ExperimentControlError) as exc:
        controller(run_id, max_requests=3, single_flight=False)
    assert code_of(exc) == "run_configuration_conflict"


def test_same_run_id_with_a_different_ceiling_conflicts():
    run_id = uuid4().hex
    controller(run_id, estimated_cost_ceiling_usd="1.00", single_flight=False)
    with pytest.raises(ExperimentControlError) as exc:
        controller(run_id, estimated_cost_ceiling_usd="2.00", single_flight=False)
    assert code_of(exc) == "run_configuration_conflict"


def test_same_run_id_with_a_different_per_request_cost_conflicts():
    run_id = uuid4().hex
    controller(run_id, estimated_cost_per_request_usd="0.10", single_flight=False)
    with pytest.raises(ExperimentControlError) as exc:
        controller(run_id, estimated_cost_per_request_usd="0.20", single_flight=False)
    assert code_of(exc) == "run_configuration_conflict"


def test_same_run_id_with_a_different_single_flight_conflicts():
    run_id = uuid4().hex
    controller(run_id, single_flight=False)
    with pytest.raises(ExperimentControlError) as exc:
        controller(run_id, single_flight=True)
    assert code_of(exc) == "run_configuration_conflict"


def test_equal_budgets_written_differently_do_not_conflict():
    """The signature holds Decimals, so "5.0" and "5.00" are the same run."""
    run_id = uuid4().hex
    controller(run_id, estimated_cost_ceiling_usd="5.00", single_flight=False)
    assert controller(run_id, estimated_cost_ceiling_usd="5.0",
                      single_flight=False).run_id == run_id
    assert controller(run_id, estimated_cost_ceiling_usd=5,
                      single_flight=False).run_id == run_id


def test_same_run_id_shares_one_ledger_across_instances():
    run_id = uuid4().hex
    first = controller(run_id, max_requests=3, estimated_cost_ceiling_usd="3.00",
                       estimated_cost_per_request_usd="0.25", single_flight=False)
    second = controller(run_id, max_requests=3, estimated_cost_ceiling_usd="3.00",
                        estimated_cost_per_request_usd="0.25", single_flight=False)

    assert first.execute("case-a", lambda: "a") == "a"
    assert second.execute("case-b", lambda: "b") == "b"
    assert first.request_count == second.request_count == 2
    assert first.estimated_cost_reserved_usd == second.estimated_cost_reserved_usd == Decimal("0.50")

    assert first.execute("case-c", lambda: "c") == "c"
    with pytest.raises(ExperimentControlError) as exc:
        second.execute("case-d", lambda: "d")
    assert code_of(exc) == "request_limit"
    assert first.request_count == 3


# --- read-only properties ---------------------------------------------------


def test_properties_start_at_zero_with_the_documented_types():
    run = controller()
    assert run.request_count == 0
    assert isinstance(run.request_count, int)
    assert run.estimated_cost_reserved_usd == Decimal("0")
    assert isinstance(run.estimated_cost_reserved_usd, Decimal)


# --- execute: invalid_attempt ----------------------------------------------


@pytest.mark.parametrize("case_id, attempt", [
    ("", lambda: "ok"),
    ("   ", lambda: "ok"),
    (5, lambda: "ok"),
    (None, lambda: "ok"),
    ("case-a", "not callable"),
    ("case-a", None),
])
def test_malformed_arguments_are_rejected_without_reserving_quota(case_id, attempt):
    run = controller(max_requests=2, estimated_cost_per_request_usd="0.10", single_flight=False)
    with pytest.raises(ExperimentControlError) as exc:
        run.execute(case_id, attempt)
    assert code_of(exc) == "invalid_attempt"
    assert run.request_count == 0
    assert run.estimated_cost_reserved_usd == Decimal("0")


def test_invalid_case_id_is_reported_before_an_uncallable_attempt():
    run = controller()
    with pytest.raises(ExperimentControlError) as exc:
        run.execute("", "not callable")
    assert code_of(exc) == "invalid_attempt"
    assert run.request_count == 0


# --- execute: happy path ---------------------------------------------------


@pytest.mark.parametrize("value", ["ok", 0, None, {"claim": 1}, [1, 2]])
def test_execute_returns_the_callback_value_unchanged(value):
    run = controller()
    assert run.execute("case-a", lambda: value) == value
    assert run.request_count == 1


def test_execute_reserves_before_the_callback_can_observe_the_count():
    run = controller(estimated_cost_per_request_usd="0.10")
    seen: list[int] = []

    def attempt():
        seen.append(run.request_count)
        return "ok"

    run.execute("case-a", attempt)
    assert seen == [1]
    assert run.estimated_cost_reserved_usd == Decimal("0.10")


# --- execute: request_limit ------------------------------------------------


def test_request_limit_fires_at_the_cap_and_before_the_callback_runs():
    run = controller(max_requests=2, single_flight=False)
    calls: list[str] = []

    def attempt(name):
        def run_attempt():
            calls.append(name)
            return name
        return run_attempt

    assert run.execute("case-a", attempt("a")) == "a"
    assert run.execute("case-b", attempt("b")) == "b"
    with pytest.raises(ExperimentControlError) as exc:
        run.execute("case-c", attempt("c"))
    assert code_of(exc) == "request_limit"
    assert calls == ["a", "b"]
    assert run.request_count == 2


def test_max_requests_of_one_permits_exactly_one_attempt():
    run = controller(max_requests=1, single_flight=False)
    assert run.execute("case-a", lambda: "ok") == "ok"
    with pytest.raises(ExperimentControlError) as exc:
        run.execute("case-b", lambda: "ok")
    assert code_of(exc) == "request_limit"


def test_request_limit_is_shared_by_every_controller_with_the_run_id():
    run_id = uuid4().hex
    instances = [controller(run_id, max_requests=3, single_flight=False) for _ in range(3)]
    outcomes = []
    for index in range(5):
        instance = instances[index % 3]
        try:
            instance.execute(f"case-{index}", lambda: True)
            outcomes.append("ok")
        except ExperimentControlError as exc:
            outcomes.append(exc.code)
    assert outcomes == ["ok", "ok", "ok", "request_limit", "request_limit"]
    assert instances[0].request_count == 3


# --- execute: failure accounting -------------------------------------------


def test_failed_callback_consumes_request_and_cost_quota():
    run = controller(max_requests=2, estimated_cost_per_request_usd="0.10", single_flight=False)

    def explode():
        raise RuntimeError("controlled failure")

    with pytest.raises(RuntimeError, match="controlled failure"):
        run.execute("case-a", explode)

    assert run.request_count == 1
    assert run.estimated_cost_reserved_usd == Decimal("0.10")


def test_failed_attempt_is_never_retried_or_refunded():
    run = controller(max_requests=1, single_flight=False)
    calls: list[str] = []

    def explode():
        calls.append("called")
        raise ValueError("controlled failure")

    with pytest.raises(ValueError):
        run.execute("case-a", explode)
    with pytest.raises(ExperimentControlError) as exc:
        run.execute("case-a", lambda: "retry")
    assert code_of(exc) == "request_limit"
    assert calls == ["called"]


@pytest.mark.parametrize("error", [RuntimeError, ValueError, TimeoutError,
                                   ExperimentControlError])
def test_callback_exceptions_propagate_unchanged(error):
    run = controller()
    raised = error("boom") if error is not ExperimentControlError else ExperimentControlError("request_limit")
    with pytest.raises(error) as exc:
        run.execute("case-a", lambda: (_ for _ in ()).throw(raised))
    assert exc.value is raised


def test_failed_callback_releases_the_single_flight_slot():
    run = controller(single_flight=True)

    def explode():
        raise RuntimeError("controlled failure")

    with pytest.raises(RuntimeError):
        run.execute("case-a", explode)
    # If the finally-block had not decremented `active`, this would be refused.
    assert run.execute("case-b", lambda: "ok") == "ok"
    assert run.request_count == 2


# --- execute: single_flight_limit ------------------------------------------


def test_nested_attempt_on_the_same_controller_hits_single_flight():
    run = controller(single_flight=True)

    def outer():
        with pytest.raises(ExperimentControlError) as exc:
            run.execute("inner", lambda: "inner")
        assert code_of(exc) == "single_flight_limit"
        return "outer"

    assert run.execute("outer", outer) == "outer"
    # The refused nested call reserved nothing.
    assert run.request_count == 1


def test_single_flight_blocks_a_second_thread_until_the_first_returns():
    run = controller(single_flight=True)
    entered, release = Event(), Event()

    def slow():
        entered.set()
        assert release.wait(timeout=10)
        return "slow"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run.execute, "case-a", slow)
        assert entered.wait(timeout=10)
        with pytest.raises(ExperimentControlError) as exc:
            run.execute("case-b", lambda: "must not run")
        assert code_of(exc) == "single_flight_limit"
        release.set()
        assert future.result(timeout=10) == "slow"

    assert run.request_count == 1
    assert run.execute("case-c", lambda: "ok") == "ok"


def test_single_flight_disabled_allows_two_in_flight_attempts():
    run = controller(max_requests=2, single_flight=False)
    entered, release = Event(), Event()
    seen: list[int] = []

    def slow():
        seen.append(run.request_count)
        entered.set()
        assert release.wait(timeout=10)
        return "slow"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run.execute, "case-a", slow)
        assert entered.wait(timeout=10)
        # The second reservation is allowed while the first is still running.
        assert run.execute("case-b", lambda: "fast") == "fast"
        release.set()
        assert future.result(timeout=10) == "slow"

    assert seen == [1]
    assert run.request_count == 2


# --- budget ----------------------------------------------------------------


def test_budget_breach_on_a_legal_run_surfaces_as_request_limit():
    """Price the run so the cap and the ceiling are reached at the same attempt."""
    run = controller(max_requests=3, estimated_cost_ceiling_usd="0.30",
                     estimated_cost_per_request_usd="0.10", single_flight=False)
    for index in range(3):
        assert run.execute(f"case-{index}", lambda: "ok") == "ok"
    with pytest.raises(ExperimentControlError) as exc:
        run.execute("case-3", lambda: "must not run")
    assert code_of(exc) == "request_limit"
    assert run.estimated_cost_reserved_usd == Decimal("0.30")


def test_cost_reservation_stays_exact_decimal_at_the_ceiling():
    run = controller(max_requests=3, estimated_cost_ceiling_usd="0.30",
                     estimated_cost_per_request_usd="0.10", single_flight=False)
    run.execute("case-a", lambda: "ok")
    run.execute("case-b", lambda: "ok")
    run.execute("case-c", lambda: "ok")
    assert run.estimated_cost_reserved_usd == Decimal("0.30")
    assert str(run.estimated_cost_reserved_usd) == "0.30"


def test_zero_per_request_cost_never_grows_the_reservation():
    run = controller(max_requests=2, single_flight=False)
    run.execute("case-a", lambda: "ok")
    run.execute("case-b", lambda: "ok")
    assert run.estimated_cost_reserved_usd == Decimal("0")


def test_default_cost_arguments_match_the_evaluate_call_site():
    """`app/evaluate.py` passes only max_requests and single_flight."""
    run = controller(max_requests=17, single_flight=True)
    assert run.estimated_cost_reserved_usd == Decimal("0")
    assert run.execute("case-a", lambda: 1) == 1
    assert run.estimated_cost_reserved_usd == Decimal("0")
