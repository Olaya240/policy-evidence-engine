"""Regression tests for the local synthetic gold-set evaluator."""
import json
import pytest

from app import evaluate
from app.evaluate import DATASET_PATH, run_evaluation
from app.engine import AssessmentEngine, ProviderError


def test_gold_dataset_has_independent_labels_and_required_evidence_cases():
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in dataset["cases"]}
    assert len(cases) == 21
    assert "before running the engine" in dataset["labeling_note"]
    assert all(case.get("explanation") for case in cases.values())
    assert cases["supportive-direct"]["expected_stances"] == ["SUPPORTS"]
    assert cases["contradictory-direct"]["expected_stances"] == ["CONTRADICTS"]
    assert cases["neutral-related-record"]["expected_stances"] == ["NEUTRAL"]
    irrelevant = cases["exact-quote-semantically-irrelevant"]
    assert irrelevant["fixture_output"][0]["quote"] in irrelevant["records"][0]["text"]
    assert irrelevant["fixture_output"][0]["stance"] == "SUPPORTS"
    assert irrelevant["expected_stances"] == ["NEUTRAL"]
    assert cases["stale-support"]["expected_status"] == "INSUFFICIENT"
    assert cases["conflicting-fresh-sources"]["expected_status"] == "PARTIAL"
    assert cases["empty-abstention"]["expected_status"] == "INSUFFICIENT"
    assert cases["unsupported-causation-overclaim"]["expected_rejection_code"] == "malformed_output"
    assert cases["malformed-provider-output"]["expected_rejection_code"] == "malformed_output"
    assert cases["unknown-source-id"]["expected_rejection_code"] == "invalid_source"
    assert cases["non-substring-quote"]["expected_rejection_code"] == "invalid_quote"
    assert cases["topic-only-no-support"]["expected_stances"] == ["NEUTRAL"]
    assert cases["neutral-as-contradiction"]["expected_stances"] == ["NEUTRAL"]
    assert cases["causal-rationale-sanitized"]["expected_status"] == "PARTIAL"
    # The original 11 expected labels stay explicitly fixed.
    assert cases["exact-quote-semantically-irrelevant"]["expected_status"] == "INSUFFICIENT"
    assert cases["conflicting-fresh-sources"]["expected_stances"] == ["SUPPORTS", "CONTRADICTS"]
    assert cases["paraphrased-checklist-support"]["expected_stances"] == ["SUPPORTS"]
    assert cases["negated-checklist-unavailable"]["expected_stances"] == ["CONTRADICTS"]
    assert cases["staffing-topic-neutral"]["expected_stances"] == ["NEUTRAL"]
    assert cases["alternative-wording-staffing-contradiction"]["expected_stances"] == ["CONTRADICTS"]
    assert cases["neutral-operational-observation"]["expected_stances"] == ["NEUTRAL"]
    assert cases["paraphrased-training-support"]["expected_stances"] == ["SUPPORTS"]
    assert cases["paraphrased-conflicting-sources"]["expected_stances"] == ["SUPPORTS", "CONTRADICTS"]


def test_evaluator_reports_actual_metrics_and_history_checks():
    baseline = run_evaluation(guarded=False)
    guarded = run_evaluation(guarded=True)
    assert baseline["case_count"] == guarded["case_count"] == 21
    baseline_metrics, metrics = baseline["metrics"], guarded["metrics"]
    assert baseline_metrics["stance_accuracy"] == {"numerator": 14, "denominator": 18, "rate": 0.7778,
        "by_provider_mode": {"adversarial_fixture": {"numerator": 8, "denominator": 12, "rate": 0.6667}, "mock": {"numerator": 6, "denominator": 6, "rate": 1.0}}}
    assert metrics["stance_accuracy"] == {"numerator": 6, "denominator": 18, "rate": 0.3333,
        "by_provider_mode": {"adversarial_fixture": {"numerator": 1, "denominator": 12, "rate": 0.0833}, "mock": {"numerator": 5, "denominator": 6, "rate": 0.8333}}}
    assert baseline_metrics["status_accuracy"] == {"numerator": 13, "denominator": 17, "rate": 0.7647}
    assert metrics["status_accuracy"] == {"numerator": 12, "denominator": 17, "rate": 0.7059}
    assert baseline_metrics["insufficient_evidence_rate"]["numerator"] == 4
    assert metrics["insufficient_evidence_rate"]["numerator"] == 13
    assert baseline_metrics["insufficient_evidence_rate"]["denominator"] == metrics["insufficient_evidence_rate"]["denominator"] == 17
    assert metrics["exact_quote_validity"] == {"numerator": 18, "denominator": 18, "rate": 1.0}
    assert metrics["invalid_source_rejection"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert metrics["invalid_quote_rejection"]["numerator"] == 1
    assert metrics["malformed_provider_output_rejection"]["numerator"] == 2
    assert metrics["unsupported_causation_rejection"]["numerator"] == 1
    assert baseline_metrics["invalid_proposal_rejection"] == metrics["invalid_proposal_rejection"] == {"numerator": 4, "denominator": 4, "rate": 1.0}
    assert baseline_metrics["false_support_rate"]["numerator"] == 3
    assert baseline_metrics["false_support_rate"]["denominator"] == metrics["false_support_rate"]["denominator"] == 11
    assert metrics["false_support_rate"]["numerator"] == 0
    assert baseline_metrics["false_abstention_false_neutral_rate"]["numerator"] == 0
    assert baseline_metrics["false_abstention_false_neutral_rate"]["denominator"] == metrics["false_abstention_false_neutral_rate"]["denominator"] == 12
    assert metrics["false_abstention_false_neutral_rate"]["numerator"] == 6
    assert set(metrics["false_abstention_false_neutral_rate"]["case_ids"]) == {
        "paraphrased-checklist-support", "negated-checklist-unavailable",
        "alternative-wording-staffing-contradiction", "paraphrased-training-support",
        "paraphrased-conflicting-sources",
    }
    for arm_metrics in (baseline_metrics, metrics):
        semantic = arm_metrics["semantic_mismatch_case_rate"]
        assert semantic["denominator"] == len(semantic["eligible_case_ids"]) == 10
        assert semantic["numerator"] == len(semantic["case_ids"])
        assert len(set(semantic["case_ids"])) == semantic["numerator"]
    assert metrics["semantic_mismatch_case_rate"]["numerator"] == 10
    assert metrics["semantic_mismatch_case_rate"]["denominator"] == 10
    assert metrics["false_abstention_false_neutral_rate"]["numerator"] == 6
    assert metrics["unverified_proposal_case_rate"]["numerator"] == 11
    assert metrics["unverified_proposal_case_rate"]["denominator"] == 17
    assert metrics["causal_rationale_sanitization"]["sanitized"] is True
    assert baseline_metrics["causal_rationale_sanitization"]["sanitized"] is False
    for result in (baseline, guarded):
        history = result["metrics"]["deterministic_recomputation_history_consistency"]
        assert history["passed"] == history["total"] == 7
        assert history["disposable_database_removed"] is True


def test_guard_retains_unverified_proposals_without_counting_them_as_neutral():
    result = run_evaluation(guarded=True)
    cases = {case["id"]: case for case in result["cases"]}
    for case_id in ("exact-quote-semantically-irrelevant", "topic-only-no-support", "neutral-as-contradiction", "staffing-topic-neutral"):
        case = cases[case_id]
        assert case["observed_stances"] == [None]
        assert case["observed_proposals"][0] in {"SUPPORTS", "CONTRADICTS"}
        assert case["observed_status"] == "INSUFFICIENT"
        assert case["guard_audit"][0]["review_state"] == "UNVERIFIED"
        assert case["guard_audit"][0]["proposed_stance"] == case["guard_audit"][0]["final_stance"]
    assert cases["stale-support"]["observed_stances"] == ["SUPPORTS"]
    assert cases["stale-support"]["observed_status"] == "INSUFFICIENT"
    assert cases["conflicting-fresh-sources"]["observed_stances"] == ["SUPPORTS", "CONTRADICTS"]
    assert cases["conflicting-fresh-sources"]["observed_status"] == "PARTIAL"
    assert cases["supportive-direct"]["observed_status"] == "PARTIAL"
    assert cases["causal-rationale-sanitized"]["observed_status"] == "PARTIAL"
    assert "caused" not in cases["causal-rationale-sanitized"]["guard_audit"][0]["rationale"].casefold()
    for case_id in ("paraphrased-checklist-support", "negated-checklist-unavailable",
                    "alternative-wording-staffing-contradiction", "paraphrased-training-support"):
        assert cases[case_id]["observed_stances"] == [None]
        assert cases[case_id]["guard_audit"][0]["review_state"] == "UNVERIFIED"
    assert cases["paraphrased-conflicting-sources"]["observed_stances"] == [None, None]
    assert all(item["review_state"] == "UNVERIFIED" for item in cases["paraphrased-conflicting-sources"]["guard_audit"])


def test_guarded_neutral_gold_proposals_require_explicit_neutral_review_and_keep_fixed_accounting():
    result = run_evaluation(guarded=True)
    cases = {case["id"]: case for case in result["cases"]}
    for case_id in ("neutral-related-record", "neutral-operational-observation"):
        case = cases[case_id]
        assert case["observed_proposals"] == ["NEUTRAL"]
        assert case["observed_stances"] == [None]
        assert case["guard_audit"][0]["review_state"] == "UNVERIFIED"
        assert case["observed_status"] == "INSUFFICIENT"
    metrics = result["metrics"]
    assert metrics["expected_denominators"]["stance_labels"] == 18
    assert metrics["expected_denominators"]["false_neutral_labels"] == 12
    assert metrics["false_abstention_false_neutral_rate"]["denominator"] == 12
    assert metrics["false_abstention_false_neutral_rate"]["numerator"] == 6


def test_evaluator_uses_one_target_assessment_for_each_eligible_case(monkeypatch):
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    eligible = [case for case in dataset["cases"] if not case.get("expected_rejection_code")]
    seen = []
    original_factory = evaluate._fixture_provider
    def counting_factory(case_id, hypothesis_id, provider_mode, fixture_output):
        provider = original_factory(case_id, hypothesis_id, provider_mode, fixture_output)
        seen.append((case_id, hypothesis_id, provider))
        return provider
    monkeypatch.setattr(evaluate, "_fixture_provider", counting_factory)
    monkeypatch.setattr(evaluate, "_evaluate_recomputation_history", lambda guarded: {"passed": 1, "total": 1})
    monkeypatch.setattr(AssessmentEngine, "investigate", lambda *args, **kwargs: pytest.fail("full investigation path called"))
    result = run_evaluation(guarded=False)

    assert len(seen) == len(eligible) + 4  # 17 assessment cases plus 4 local validator contracts
    assert all(provider.assessment_call_count == 1 and provider.assessment_history == (hypothesis_id,)
               for _case_id, hypothesis_id, provider in seen)
    assert all(case_id in {case["id"] for case in dataset["cases"]} for case_id, _hypothesis, _provider in seen)
    assert result["metrics"]["assessment_calls"] == {
        "numerator": 17, "denominator": 17, "exactly_one_per_eligible_case": True,
    }
    assert result["metrics"]["expected_denominators"] == {
        "eligible_cases": 17, "stance_labels": 18, "status_labels": 17,
        "exact_quote_slots": 18, "false_support_labels": 11,
        "false_neutral_labels": 12, "local_contract_cases": 4,
    }
    assert len(result["metrics"]["experiment_manifest"]["attempts"]) == 17


def test_provider_failures_keep_fixed_denominators_and_are_not_abstentions(monkeypatch):
    monkeypatch.setattr(evaluate, "_evaluate_recomputation_history", lambda guarded: {"passed": 1, "total": 1})

    def fail_two_cases(case):
        if case["id"] == "supportive-direct":
            return TimeoutError("synthetic timeout")
        if case["id"] == "empty-abstention":
            return RuntimeError("synthetic failure details must not be exposed")
        if case["id"] == "neutral-operational-observation":
            return ProviderError("provider_failure")
        return None

    result = run_evaluation(guarded=False, failure_injector=fail_two_cases)
    metrics = result["metrics"]
    assert metrics["provider_error_rate"] == {
        "numerator": 3, "denominator": 17, "rate": 0.1765,
        "categories": ["timeout", "unexpected_exception", "provider_failure"],
        "case_ids": ["supportive-direct", "empty-abstention", "neutral-operational-observation"],
        "note": "Failures count as incorrect in stance/status accuracy and are not valid abstentions.",
    }
    assert metrics["stance_accuracy"]["denominator"] == 18
    assert metrics["status_accuracy"]["denominator"] == 17
    assert metrics["valid_abstention_rate"]["denominator"] == 17
    assert metrics["valid_abstention_rate"]["numerator"] == 0
    assert metrics["assessment_calls"]["numerator"] == 17
    assert all("synthetic failure details" not in json.dumps(item) for item in result["cases"])
    by_id = {case["id"]: case for case in result["cases"]}
    assert by_id["supportive-direct"]["error_category"] == "timeout"
    assert by_id["empty-abstention"]["error_category"] == "unexpected_exception"


def test_semantic_metric_uses_frozen_case_units_and_separates_errors_from_abstentions(monkeypatch):
    monkeypatch.setattr(evaluate, "_evaluate_recomputation_history", lambda guarded: {"passed": 1, "total": 1})
    original_factory = evaluate._fixture_provider
    def abstaining_factory(case_id, hypothesis_id, provider_mode, fixture_output):
        if case_id == "paraphrased-training-support":
            return evaluate.MockProvider(assessment_overrides={hypothesis_id: []})
        return original_factory(case_id, hypothesis_id, provider_mode, fixture_output)
    monkeypatch.setattr(evaluate, "_fixture_provider", abstaining_factory)
    baseline = run_evaluation(guarded=False)
    baseline_semantic = baseline["metrics"]["semantic_mismatch_case_rate"]

    def fail_semantic_case(case):
        if case["id"] == "paraphrased-checklist-support":
            return ProviderError("malformed_output")
        return None

    failed = run_evaluation(guarded=False, failure_injector=fail_semantic_case)
    semantic = failed["metrics"]["semantic_mismatch_case_rate"]
    assert semantic["denominator"] == baseline_semantic["denominator"] == 10
    assert semantic["eligible_case_ids"] == baseline_semantic["eligible_case_ids"]
    assert semantic["numerator"] == len(semantic["case_ids"])
    assert len(set(semantic["case_ids"])) == semantic["numerator"]
    assert "paraphrased-checklist-support" in semantic["provider_error_case_ids"]
    assert "paraphrased-checklist-support" not in semantic["case_ids"]
    assert "paraphrased-checklist-support" not in semantic["valid_abstention_case_ids"]
    assert "paraphrased-training-support" in semantic["valid_abstention_case_ids"]
    assert "paraphrased-training-support" not in semantic["case_ids"]
    assert failed["metrics"]["provider_error_rate"]["case_ids"] == ["paraphrased-checklist-support"]
    assert "paraphrased-training-support" in failed["metrics"]["valid_abstention_rate"]["case_ids"]
