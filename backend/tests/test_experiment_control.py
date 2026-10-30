from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from app.experiment_control import ExperimentControlError, ExperimentRunController
from app.experiment_manifest import AttemptMetadata, ExperimentRunManifest


def controller(run_id=None, **kwargs):
    return ExperimentRunController(run_id=run_id or uuid4().hex, **kwargs)


def test_failed_attempt_consumes_shared_run_quota_and_duplicate_id_shares_state():
    run_id = uuid4().hex
    first = controller(run_id, max_requests=2, single_flight=False)
    second = controller(run_id, max_requests=2, single_flight=False)

    with pytest.raises(RuntimeError):
        first.execute("case-a", lambda: (_ for _ in ()).throw(RuntimeError("controlled test failure")))
    assert second.request_count == 1
    assert second.execute("case-b", lambda: "ok") == "ok"
    assert first.request_count == 2
    with pytest.raises(ExperimentControlError, match="authorized") as exc:
        first.execute("case-c", lambda: "must not run")
    assert exc.value.code == "request_limit"
    with pytest.raises(ExperimentControlError) as conflict:
        controller(run_id, max_requests=3, single_flight=False)
    assert conflict.value.code == "run_configuration_conflict"


def test_concurrent_reservations_never_exceed_run_request_cap():
    gate = controller(max_requests=7, single_flight=False)

    def attempt(index):
        try:
            gate.execute(f"case-{index}", lambda: True)
            return True
        except ExperimentControlError as exc:
            assert exc.code == "request_limit"
            return False

    with ThreadPoolExecutor(max_workers=24) as pool:
        accepted = list(pool.map(attempt, range(80)))
    assert sum(accepted) == 7
    assert gate.request_count == 7


def test_single_flight_is_enforced_separately_from_total_request_count():
    gate = controller(max_requests=3, single_flight=True)
    started, release = Event(), Event()

    def blocked():
        started.set()
        assert release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(gate.execute, "case-a", blocked)
        assert started.wait(timeout=5)
        with pytest.raises(ExperimentControlError) as exc:
            gate.execute("case-b", lambda: None)
        assert exc.value.code == "single_flight_limit"
        assert gate.request_count == 1
        release.set()
        first.result(timeout=5)
    assert gate.execute("case-c", lambda: "ok") == "ok"
    assert gate.request_count == 2


def test_cost_estimate_is_reserved_before_attempt_and_invalid_budget_fails_closed():
    gate = controller(max_requests=2, estimated_cost_ceiling_usd="0.02",
                      estimated_cost_per_request_usd="0.01", single_flight=False)
    assert gate.execute("case-a", lambda: True)
    assert str(gate.estimated_cost_reserved_usd) == "0.01"
    assert gate.execute("case-b", lambda: True)
    assert str(gate.estimated_cost_reserved_usd) == "0.02"
    with pytest.raises(ExperimentControlError) as over_budget:
        controller(max_requests=2, estimated_cost_ceiling_usd="0.01",
                   estimated_cost_per_request_usd="0.01")
    assert over_budget.value.code == "invalid_budget"
    with pytest.raises(ExperimentControlError) as invalid:
        controller(max_requests=18)
    assert invalid.value.code == "invalid_budget"


def test_manifest_contains_only_allowlisted_metadata():
    digest = "a" * 64
    manifest = ExperimentRunManifest(
        run_id="synthetic-run-1", dataset_sha256=digest,
        evaluator_version="3.16.0", prompt_version="prompt-v1", prompt_sha256=digest,
        serializer_version="serializer-v1", serializer_sha256=digest,
        model_name="future-model", model_version="2026-01", temperature=0,
    )
    manifest.add_attempt(AttemptMetadata(case_id="synthetic-case-1", request_count=1,
                                         latency_ms=12, input_tokens=10, output_tokens=8,
                                         error_category="timeout"))
    serialized = manifest.to_dict()
    assert serialized["attempts"][0]["error_category"] == "timeout"
    assert "prompt" not in serialized
    assert "response" not in serialized
    assert "record_text" not in serialized
    assert "api_key" not in serialized
    with pytest.raises(ValueError):
        AttemptMetadata(case_id="case", request_count=1, error_category="raw provider exception")
