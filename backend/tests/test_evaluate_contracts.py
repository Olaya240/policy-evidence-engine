"""Contract tests for the offline evaluation harness in `app/evaluate.py`.

These pin properties the harness states about itself rather than particular
counts: where an error category comes from, that a failure stays counted, that
the reported accuracy is the one the reported rows support, that the persisted
database is not touched, and that the frozen evaluation instant is normalised
and actually used.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from app import evaluate, store
from app.engine import AssessmentEngine, ProviderError
from app.evaluate import DATASET_PATH, EVALUATION_AS_OF, EvaluationDateTime, run_evaluation
from app.experiment_control import ExperimentControlError
from app.models import Record


def _cases() -> list[dict]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]


def _eligible(cases: list[dict]) -> list[dict]:
    return [case for case in cases if not case.get("expected_rejection_code")]


def _row(result: dict, case_id: str) -> dict:
    return next(row for row in result["cases"] if row["id"] == case_id)


def _attempt(result: dict, case_id: str) -> dict:
    return next(a for a in result["metrics"]["experiment_manifest"]["attempts"] if a["case_id"] == case_id)


def test_provider_error_category_is_read_from_the_code_attribute():
    # The base class message is fixed and carries no category, so a category
    # taken from `str(exc)` could never equal a code. Only `.code` can.
    sentinel = "synthetic_code_probe_7f31"
    error = ProviderError(sentinel)
    assert error.code == sentinel
    assert sentinel not in str(error)

    case_id = "supportive-direct"
    result = run_evaluation(
        guarded=False,
        failure_injector=lambda case: error if case["id"] == case_id else None,
    )

    row = _row(result, case_id)
    assert row["observed"] == "provider_error"
    assert row["error_category"] == sentinel
    rate = result["metrics"]["provider_error_rate"]
    assert rate["categories"] == [sentinel]
    assert rate["case_ids"] == [case_id]
    # The manifest normalises codes outside its allowlist, which happens only
    # after the raw code was read from `.code`.
    assert _attempt(result, case_id)["error_category"] == "unexpected_exception"
    # The exception message is not reused as a category anywhere in the payload.
    assert str(error) not in json.dumps(result)


def test_experiment_control_error_category_is_read_from_the_code_attribute():
    case_id = "contradictory-direct"
    control_error = ExperimentControlError("single_flight_limit")
    assert control_error.code == "single_flight_limit"
    assert "single_flight_limit" not in str(control_error)

    result = run_evaluation(
        guarded=False,
        failure_injector=lambda case: control_error if case["id"] == case_id else None,
    )

    row = _row(result, case_id)
    assert row["observed"] == "provider_error"
    assert row["error_category"] == "single_flight_limit"
    assert result["metrics"]["provider_error_rate"]["categories"] == ["single_flight_limit"]
    assert _attempt(result, case_id)["error_category"] == "single_flight_limit"


def test_provider_failure_is_counted_in_every_bucket_it_belongs_to():
    cases = _cases()
    eligible = _eligible(cases)
    failed_id = "supportive-direct"
    clean = run_evaluation(guarded=False)
    injected = run_evaluation(
        guarded=False,
        failure_injector=lambda case: ProviderError("provider_failure") if case["id"] == failed_id else None,
    )
    clean_metrics, metrics = clean["metrics"], injected["metrics"]

    # The gold denominators are frozen before provider work, so a failure cannot
    # shrink them.
    assert metrics["expected_denominators"] == clean_metrics["expected_denominators"]
    rate = metrics["provider_error_rate"]
    assert (rate["numerator"], rate["denominator"]) == (1, len(eligible))
    assert rate["rate"] == round(1 / len(eligible), 4)
    assert rate["case_ids"] == [failed_id]

    # The failed case keeps a report row, so it cannot disappear from the output.
    assert len(injected["cases"]) == len(clean["cases"]) == len(cases)
    case = next(item for item in cases if item["id"] == failed_id)
    assert _row(injected, failed_id)["expected_stances"] == case["expected_stances"]
    assert _row(injected, failed_id)["expected_status"] == case["expected_status"]

    # Its gold slots score as wrong instead of being dropped. Pin the fixture's
    # clean run first, otherwise the subtraction below could be vacuous.
    clean_row = _row(clean, failed_id)
    stance_slots_in_clean = sum(
        observed == expected
        for observed, expected in zip(clean_row["observed_stances"], clean_row["expected_stances"])
    )
    assert stance_slots_in_clean == 1
    assert clean_row["observed_status"] == clean_row["expected_status"]
    assert metrics["stance_accuracy"]["numerator"] == clean_metrics["stance_accuracy"]["numerator"] - stance_slots_in_clean
    assert metrics["status_accuracy"]["numerator"] == clean_metrics["status_accuracy"]["numerator"] - 1
    assert metrics["exact_quote_validity"]["numerator"] == clean_metrics["exact_quote_validity"]["numerator"] - 1

    # And it is never reported as a valid abstention or an empty assessment.
    assert metrics["valid_abstention_rate"]["numerator"] == clean_metrics["valid_abstention_rate"]["numerator"]
    assert failed_id not in metrics["valid_abstention_rate"]["case_ids"]

    # The failed attempt still consumed exactly one reserved provider request.
    assert metrics["assessment_calls"] == clean_metrics["assessment_calls"]
    assert len(metrics["experiment_manifest"]["attempts"]) == len(eligible)


def test_reported_accuracy_is_recomputable_from_the_reported_rows():
    cases = {case["id"]: case for case in _cases()}
    contract_ids = {case_id for case_id, case in cases.items() if case.get("expected_rejection_code")}
    result = run_evaluation()  # shipped default: guarded
    assert result["semantic_guard"] is True

    rows = result["cases"]
    scored = [row for row in rows if "expected_stances" in row]
    # Contract cases are local validator checks and own no model slots.
    assert {row["id"] for row in rows} - {row["id"] for row in scored} == contract_ids
    assert [row["id"] for row in scored] == [case["id"] for case in _eligible(list(cases.values()))]

    stance_numerator = sum(
        observed == expected
        for row in scored
        for observed, expected in zip(row["observed_stances"], row["expected_stances"])
    )
    stance_denominator = sum(len(row["expected_stances"]) for row in scored)
    status_numerator = sum(row["observed_status"] == row["expected_status"] for row in scored)

    stance = result["metrics"]["stance_accuracy"]
    assert (stance["numerator"], stance["denominator"]) == (stance_numerator, stance_denominator)
    assert stance["rate"] == round(stance_numerator / stance_denominator, 4)
    status = result["metrics"]["status_accuracy"]
    assert (status["numerator"], status["denominator"]) == (status_numerator, len(scored))
    assert result["metrics"]["expected_denominators"]["stance_labels"] == stance_denominator
    assert result["metrics"]["expected_denominators"]["status_labels"] == len(scored)
    assert result["metrics"]["expected_denominators"]["eligible_cases"] == len(scored)

    # The per-mode split is the same arithmetic on the same rows.
    by_mode = stance["by_provider_mode"]
    assert set(by_mode) == {cases[row["id"]]["provider_mode"] for row in scored}
    for mode, reported in by_mode.items():
        mode_rows = [row for row in scored if cases[row["id"]]["provider_mode"] == mode]
        numerator = sum(
            observed == expected
            for row in mode_rows
            for observed, expected in zip(row["observed_stances"], row["expected_stances"])
        )
        denominator = sum(len(row["expected_stances"]) for row in mode_rows)
        assert (reported["numerator"], reported["denominator"]) == (numerator, denominator)
        assert reported["rate"] == round(numerator / denominator, 4)


def test_evaluation_does_not_touch_the_configured_persisted_database(monkeypatch):
    sentinel = store.validate_database_path(store.DATA_DIR / f".contract-sentinel-{uuid4().hex}.sqlite3")
    assert not sentinel.exists()
    monkeypatch.setenv("HACKATHON_DB_PATH", str(sentinel))
    try:
        store.initialize_database()
        before_bytes = sentinel.read_bytes()
        before_records = [record.id for record in store.list_records()]
        # A zero-byte or empty database would make the comparison below vacuous.
        assert len(before_bytes) > 0
        assert before_records
        before_leftovers = {path.name for path in store.DATA_DIR.glob(".phase37-eval-*")}

        result = run_evaluation(guarded=False)

        # The configured database survives byte-for-byte, with its rows intact.
        assert sentinel.exists()
        assert sentinel.read_bytes() == before_bytes
        assert [record.id for record in store.list_records()] == before_records
        # The harness restores the caller's path and removes its disposable one.
        assert os.environ["HACKATHON_DB_PATH"] == str(sentinel)
        assert {path.name for path in store.DATA_DIR.glob(".phase37-eval-*")} == before_leftovers
        recomputation = result["metrics"]["deterministic_recomputation_history_consistency"]
        assert recomputation["disposable_database_removed"] is True
        assert recomputation["total"] > 0
        assert recomputation["passed"] == recomputation["total"]
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            candidate = sentinel.with_name(sentinel.name + suffix)
            if candidate.exists():
                candidate.unlink()


def test_evaluation_instant_is_normalised_at_construction_and_honoured_by_the_engine():
    # Construction site: aware and offset zero, so no later `astimezone` has to
    # guess the intended offset.
    assert EVALUATION_AS_OF.tzinfo is timezone.utc
    assert EVALUATION_AS_OF.utcoffset() == timedelta(0)
    assert EVALUATION_AS_OF.isoformat() == "2026-10-27T12:00:00+00:00"

    # `now()` normalises the same instant on both the naive and aware paths.
    assert EvaluationDateTime.now().tzinfo is None
    assert EvaluationDateTime.now() == EVALUATION_AS_OF.replace(tzinfo=None)
    plus_five = timezone(timedelta(hours=5))
    assert EvaluationDateTime.now(plus_five) == EVALUATION_AS_OF
    assert EvaluationDateTime.now(plus_five).utcoffset() == timedelta(hours=5)

    case = _eligible(_cases())[0]
    records = [Record.model_validate(item) for item in case["records"]]

    def assess():
        provider = evaluate._fixture_provider(
            case["id"], case["hypothesis_id"], case["provider_mode"], case.get("fixture_output")
        )
        return AssessmentEngine(provider, semantic_guard=False).assess_hypothesis(records, case["hypothesis_id"])

    # Honoured: the engine the harness builds stamps the frozen instant, not the
    # wall clock (the constant is fixed at 2026-10-27T12:00:00Z).
    with patch("app.engine.datetime", EvaluationDateTime):
        frozen = assess()
    assert frozen["explanation_trace"]["generated_at"] == "2026-10-27T12:00:00Z"

    # The patch is what freezes it: without it the same engine stamps the wall
    # clock, so the frozen assertion above is not satisfied by default behaviour.
    unstamped = assess()
    stamped = datetime.fromisoformat(unstamped["explanation_trace"]["generated_at"].replace("Z", "+00:00"))
    assert abs((stamped - datetime.now(timezone.utc)).total_seconds()) < 60
