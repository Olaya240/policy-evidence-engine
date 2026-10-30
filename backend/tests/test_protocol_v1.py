"""Pure in-memory regression tests for the isolated protocol v1 module."""

from dataclasses import replace

import pytest
import evaluation.protocol_v1 as protocol_v1

from evaluation.protocol_fixtures import minimum_heldout_cohort, single_slot_dataset
from evaluation.protocol_v1 import (
    EmittedEvidence,
    EvaluationResult,
    FrozenSource,
    GoldCase,
    GoldDataset,
    GoldSlot,
    ProtocolInputError,
    RepeatedOccurrenceAdjudication,
    ScheduledAttempt,
    SubspanAdjudication,
    evaluate_protocol,
    score_contract_rejections,
    score_reviewer_agreement,
    validate_gold_dataset,
)


def _one_attempt(items, *, status="SUPPORTED", error_kind=None, inventory_known=True):
    return ScheduledAttempt("case-1", status, tuple(items) if inventory_known else None,
                            inventory_known, error_kind)


def _output(output_id="out-1", source="source-1", quote="The checklist was available.",
            stance="SUPPORTS", review_state="ACCEPTED", proposed_stance=None):
    return EmittedEvidence(output_id, source, quote, stance, review_state, proposed_stance)


def _repeated_quote_ambiguity(second_stance, first_stance="CONTRADICTS"):
    case_id = "ambiguous-case"
    quote = "Repeatable evidence."
    repeated_text = f"{quote} {quote}"
    first_start = repeated_text.index(quote)
    second_start = repeated_text.index(quote, first_start + 1)
    sources = [FrozenSource("repeated-source", repeated_text, "repeated-v1")]
    slots = [
        GoldSlot("first-slot", case_id, "hypothesis-1", first_stance, "repeated-source",
                 "repeated-v1", first_start, first_start + len(quote), True, True),
        GoldSlot("second-slot", case_id, "hypothesis-1", second_stance, "repeated-source",
                 "repeated-v1", second_start, second_start + len(quote), True, True),
    ]
    items = [_output("ambiguous-output", "repeated-source", quote, "SUPPORTS")]
    for index in range(20):
        source_id = f"neutral-source-{index}"
        text = f"Neutral evidence {index}."
        identity = f"neutral-v1-{index}"
        sources.append(FrozenSource(source_id, text, identity))
        slots.append(GoldSlot(
            f"neutral-slot-{index}", case_id, "hypothesis-1", "NEUTRAL", source_id,
            identity, 0, len(text), True, True,
        ))
        items.append(_output(f"neutral-output-{index}", source_id, text, "NEUTRAL"))
    status = "PARTIAL" if {first_stance, second_stance} == {"SUPPORTS", "CONTRADICTS"} else "SUPPORTED"
    case = GoldCase(case_id, "hypothesis-1", status, tuple(slots))
    dataset = GoldDataset("ambiguous-v1", tuple(sources), (case,))
    attempt = ScheduledAttempt(case_id, status, tuple(items))
    return dataset, attempt


def _conflict_fixture(*, include_eligible_support=True, decoy=None, status="PARTIAL"):
    case_id = "conflict-case"
    source_specs = [
        ("eligible-support-source", "Eligible support evidence.", "origin-a", True),
        ("eligible-contra-source", "Eligible contradiction evidence.", "origin-b", True),
    ]
    if decoy is not None:
        source_specs.append(("decoy-source", "Ineligible support evidence.",
                             decoy.get("origin", "origin-decoy"), decoy.get("origin_confirmed", True)))
    sources = [FrozenSource(source_id, text, f"{source_id}-v1", origin, confirmed)
               for source_id, text, origin, confirmed in source_specs]
    slots = [
        GoldSlot("eligible-support", case_id, "hypothesis-1", "SUPPORTS",
                 "eligible-support-source", "eligible-support-source-v1", 0,
                 len("Eligible support evidence."), True, True, "FRESH"),
        GoldSlot("eligible-contra", case_id, "hypothesis-1", "CONTRADICTS",
                 "eligible-contra-source", "eligible-contra-source-v1", 0,
                 len("Eligible contradiction evidence."), True, True, "FRESH"),
    ]
    items = []
    if include_eligible_support:
        items.append(_output("eligible-support-output", "eligible-support-source",
                             "Eligible support evidence.", "SUPPORTS"))
    items.append(_output("eligible-contra-output", "eligible-contra-source",
                         "Eligible contradiction evidence.", "CONTRADICTS"))
    if decoy is not None:
        slots.append(GoldSlot(
            "ineligible-support", case_id, "hypothesis-1", "SUPPORTS", "decoy-source",
            "decoy-source-v1", 0, len("Ineligible support evidence."),
            decoy.get("relevance", True), decoy.get("admissibility", True),
            decoy.get("freshness", "FRESH"),
        ))
        items.append(_output("decoy-support-output", "decoy-source",
                             "Ineligible support evidence.", "SUPPORTS"))
    case = GoldCase(case_id, "hypothesis-1", "PARTIAL", tuple(slots))
    dataset = GoldDataset("conflict-v1", tuple(sources), (case,))
    return dataset, ScheduledAttempt(case_id, status, tuple(items))


def _multi_pair_fixture(emitted_slots):
    case_id = "multi-pair-case"
    specifications = (
        ("support-a", "SUPPORTS", "source-support-a", "origin-a", "Support A evidence."),
        ("support-b", "SUPPORTS", "source-support-b", "origin-b", "Support B evidence."),
        ("contra-a", "CONTRADICTS", "source-contra-a", "origin-a", "Contradiction A evidence."),
        ("contra-b", "CONTRADICTS", "source-contra-b", "origin-b", "Contradiction B evidence."),
    )
    sources = tuple(FrozenSource(source_id, text, f"{source_id}-v1", origin, True)
                    for _, _, source_id, origin, text in specifications)
    slots = tuple(GoldSlot(
        slot_id, case_id, "hypothesis-1", stance, source_id, f"{source_id}-v1",
        0, len(text), True, True, "FRESH",
    ) for slot_id, stance, source_id, _, text in specifications)
    by_id = {slot_id: (stance, source_id, text)
             for slot_id, stance, source_id, _, text in specifications}
    items = tuple(
        _output(f"output-{slot_id}", source_id, text, stance)
        for slot_id in emitted_slots
        for stance, source_id, text in (by_id[slot_id],)
    )
    case = GoldCase(case_id, "hypothesis-1", "PARTIAL", slots)
    return GoldDataset("multi-pair-v1", sources, (case,)), ScheduledAttempt(
        case_id, "PARTIAL", items,
    )


def _ten_conflict_cases_with_ambiguity(mode):
    sources = []
    cases = []
    attempts = []

    def add_source_slot(case_id, slot_id, stance, source_id, origin, text,
                        start=0, relevance=True, admissibility=True, freshness="FRESH"):
        identity = f"{source_id}-v1"
        sources.append(FrozenSource(source_id, text, identity, origin, True))
        return GoldSlot(slot_id, case_id, "hypothesis-1", stance, source_id, identity,
                        start, start + len(text[start:]), relevance, admissibility, freshness)

    for index in range(10):
        case_id = f"conflict-{index}"
        slots = []
        items = []
        if index == 0 and mode == "changes":
            quote = "Repeated eligible support."
            repeated = f"{quote} {quote}"
            second_start = len(quote) + 1
            sources.append(FrozenSource("repeated-support", repeated, "repeated-v1",
                                        "support-origin", True))
            slots.extend((
                GoldSlot("support-eligible", case_id, "hypothesis-1", "SUPPORTS",
                         "repeated-support", "repeated-v1", 0, len(quote),
                         True, True, "FRESH"),
                GoldSlot("support-stale", case_id, "hypothesis-1", "SUPPORTS",
                         "repeated-support", "repeated-v1", second_start,
                         second_start + len(quote), True, True, "STALE"),
            ))
            items.append(_output("ambiguous-support", "repeated-support", quote, "SUPPORTS"))
            contra_text = "Eligible contradiction."
            slots.append(add_source_slot(case_id, "contra-eligible", "CONTRADICTS",
                                         "contra-source", "contra-origin", contra_text))
            items.append(_output("contra-output", "contra-source", contra_text, "CONTRADICTS"))
        elif index == 0 and mode == "unchanged":
            support_text = "Stable eligible support."
            contra_text = "Stable eligible contradiction."
            slots.append(add_source_slot(case_id, "support-stable", "SUPPORTS",
                                         "support-stable", "stable-support-origin", support_text))
            slots.append(add_source_slot(case_id, "contra-stable", "CONTRADICTS",
                                         "contra-stable", "stable-contra-origin", contra_text))
            items.extend((
                _output("support-stable-output", "support-stable", support_text, "SUPPORTS"),
                _output("contra-stable-output", "contra-stable", contra_text, "CONTRADICTS"),
            ))
            repeated_quote = "Other eligible support."
            repeated_text = f"{repeated_quote} {repeated_quote}"
            second_start = len(repeated_quote) + 1
            sources.append(FrozenSource("other-support", repeated_text, "other-support-v1",
                                        "other-support-origin", True))
            slots.extend((
                GoldSlot("other-support-1", case_id, "hypothesis-1", "SUPPORTS",
                         "other-support", "other-support-v1", 0, len(repeated_quote),
                         True, True, "FRESH"),
                GoldSlot("other-support-2", case_id, "hypothesis-1", "SUPPORTS",
                         "other-support", "other-support-v1", second_start,
                         second_start + len(repeated_quote), True, True, "FRESH"),
            ))
            items.append(_output("other-support-output", "other-support", repeated_quote, "SUPPORTS"))
        else:
            support_text = f"Support {index}."
            contra_text = f"Contradiction {index}."
            slots.extend((
                add_source_slot(case_id, f"support-{index}", "SUPPORTS", f"support-{index}",
                                f"support-origin-{index}", support_text),
                add_source_slot(case_id, f"contra-{index}", "CONTRADICTS", f"contra-{index}",
                                f"contra-origin-{index}", contra_text),
            ))
            items.extend((
                _output(f"support-output-{index}", f"support-{index}", support_text, "SUPPORTS"),
                _output(f"contra-output-{index}", f"contra-{index}", contra_text, "CONTRADICTS"),
            ))
        cases.append(GoldCase(case_id, "hypothesis-1", "PARTIAL", tuple(slots)))
        attempts.append(ScheduledAttempt(case_id, "PARTIAL", tuple(items)))

    return GoldDataset("ten-conflicts-v1", tuple(sources), tuple(cases)), tuple(attempts)


def _ten_conflict_cases_with_multi_pair_tie():
    """Build ten eligible cases; case zero has a tie that changes preservation."""
    sources = []
    cases = []
    attempts = []
    for index in range(10):
        case_id = f"tie-conflict-{index}"
        if index == 0:
            quote = "Repeated disputed evidence."
            repeated_text = f"{quote} {quote}"
            second_start = len(quote) + 1
            sources.extend((
                FrozenSource("repeated-source", repeated_text, "repeated-v1", "origin-x", True),
                FrozenSource("support-y-source", "Support from Y.", "support-y-v1", "origin-y", True),
                FrozenSource("contra-y-source", "Contradiction from Y.", "contra-y-v1", "origin-y", True),
            ))
            slots = (
                GoldSlot("support-x", case_id, "hypothesis-1", "SUPPORTS",
                         "repeated-source", "repeated-v1", 0, len(quote), True, True, "FRESH"),
                GoldSlot("contra-x", case_id, "hypothesis-1", "CONTRADICTS",
                         "repeated-source", "repeated-v1", second_start,
                         second_start + len(quote), True, True, "FRESH"),
                GoldSlot("support-y", case_id, "hypothesis-1", "SUPPORTS",
                         "support-y-source", "support-y-v1", 0, len("Support from Y."),
                         True, True, "FRESH"),
                GoldSlot("contra-y", case_id, "hypothesis-1", "CONTRADICTS",
                         "contra-y-source", "contra-y-v1", 0,
                         len("Contradiction from Y."), True, True, "FRESH"),
            )
            items = (
                _output("ambiguous-support", "repeated-source", quote, "SUPPORTS"),
                _output("ambiguous-contradiction", "repeated-source", quote, "CONTRADICTS"),
                _output("support-y-output", "support-y-source", "Support from Y.", "SUPPORTS"),
                _output("contra-y-output", "contra-y-source", "Contradiction from Y.", "CONTRADICTS"),
            )
        else:
            support_text = f"Support {index}."
            contra_text = f"Contradiction {index}."
            support_source = f"support-source-{index}"
            contra_source = f"contra-source-{index}"
            sources.extend((
                FrozenSource(support_source, support_text, f"{support_source}-v1",
                             f"support-origin-{index}", True),
                FrozenSource(contra_source, contra_text, f"{contra_source}-v1",
                             f"contra-origin-{index}", True),
            ))
            slots = (
                GoldSlot(f"support-{index}", case_id, "hypothesis-1", "SUPPORTS",
                         support_source, f"{support_source}-v1", 0, len(support_text),
                         True, True, "FRESH"),
                GoldSlot(f"contra-{index}", case_id, "hypothesis-1", "CONTRADICTS",
                         contra_source, f"{contra_source}-v1", 0, len(contra_text),
                         True, True, "FRESH"),
            )
            items = (
                _output(f"support-output-{index}", support_source, support_text, "SUPPORTS"),
                _output(f"contra-output-{index}", contra_source, contra_text, "CONTRADICTS"),
            )
        cases.append(GoldCase(case_id, "hypothesis-1", "PARTIAL", slots))
        attempts.append(ScheduledAttempt(case_id, "PARTIAL", items))
    return GoldDataset("ten-conflicts-with-tie-v1", tuple(sources), tuple(cases)), tuple(attempts)


def test_full_synthetic_cohort_meets_approved_sample_and_metric_boundaries():
    dataset, attempts = minimum_heldout_cohort()
    result = evaluate_protocol(dataset, attempts)

    assert result.verdict == "PASS"
    assert result.metrics["false_support"].numerator == 0
    assert result.metrics["support_recall"].rate == 1.0
    assert result.metrics["contradiction_recall"].rate == 1.0
    assert result.metrics["directional_coverage_support"].rate == 1.0
    assert result.metrics["directional_coverage_contradiction"].rate == 1.0
    assert result.metrics["status_accuracy"].denominator == 60
    assert result.metrics["status_accuracy"].numerator == 60
    assert result.metrics["conflict_preservation"].numerator == 10
    assert result.metrics["emitted_evidence_integrity"].rate == 1.0
    assert result.metrics["provider_error_rate"].numerator == 0
    assert result.sample_minima["support_slots"] == (20, 20, True)
    assert result.sample_minima["contradiction_slots"] == (20, 20, True)
    assert result.sample_minima["neutral_slots"] == (50, 20, True)
    assert "error_inclusive_missing_direction" not in result.metrics


def test_false_support_and_recall_threshold_boundaries_are_exact():
    dataset, attempts = minimum_heldout_cohort()
    changed = list(attempts)
    for index in range(10, 14):
        changed[index] = replace(changed[index], items=(replace(changed[index].items[0], stance="NEUTRAL"),))
    exact_recall = evaluate_protocol(dataset, tuple(changed))
    assert exact_recall.metrics["support_recall"].rate == 0.80
    assert exact_recall.metrics["support_recall"].state == "PASS"
    assert exact_recall.metrics["directional_coverage_support"].state == "PASS"

    neutral_case = next(case for case in dataset.cases if case.case_id == "heldout-30")
    first_neutral = neutral_case.slots[0]
    bad_attempts = list(attempts)
    target = next(i for i, attempt in enumerate(attempts) if attempt.case_id == neutral_case.case_id)
    bad_attempts[target] = replace(
        bad_attempts[target],
        items=(replace(bad_attempts[target].items[0], stance="SUPPORTS"),
               bad_attempts[target].items[1]),
    )
    false_support = evaluate_protocol(dataset, tuple(bad_attempts))
    assert first_neutral.expected_stance == "NEUTRAL"
    assert false_support.metrics["false_support"].numerator == 1
    assert false_support.metrics["false_support"].state == "FAIL"
    assert false_support.verdict == "FAIL"


def test_accepted_opposite_direction_fails_recall_but_is_not_false_neutral():
    dataset, attempts = minimum_heldout_cohort()
    changed = list(attempts)
    index = next(i for i, attempt in enumerate(attempts) if attempt.case_id == "heldout-10")
    changed[index] = replace(changed[index], items=(replace(changed[index].items[0], stance="CONTRADICTS"),))
    result = evaluate_protocol(dataset, tuple(changed))
    assert result.metrics["support_recall"].numerator == 19
    assert result.metrics["primary_false_neutral_rate"].numerator == 0
    assert result.metrics["primary_false_neutral_rate"].denominator == 40


def test_unverified_directional_proposal_without_accepted_stance_is_false_neutral():
    dataset = single_slot_dataset()
    unverified = _output(review_state="UNVERIFIED", proposed_stance="SUPPORTS")
    result = evaluate_protocol(dataset, (_one_attempt((unverified,)),))
    assert result.metrics["primary_false_neutral_rate"].numerator == 1
    assert result.metrics["unverified_slot_rate"].numerator == 1
    assert result.metrics["unverified_case_rate"].numerator == 1
    assert result.error_attempts == 0


def test_missing_and_duplicate_output_id_counts_are_item_level_and_error_is_attempt_level():
    dataset = single_slot_dataset()
    items = (
        _output(None),
        _output("dup"),
        _output("dup"),
        _output("dup"),
    )
    result = evaluate_protocol(dataset, (_one_attempt(items),))

    assert result.missing_id_items == 1
    assert result.duplicate_id_items == 3
    assert result.malformed_id_items == 0
    assert result.error_attempts == 1
    assert result.evaluation_error_attempts == 1
    assert result.provider_transport_error_attempts == 0
    assert result.metrics["provider_error_rate"].numerator == 1
    assert result.metrics["provider_error_rate"].denominator == 1
    assert result.metrics["status_accuracy"].numerator == 0
    assert result.metrics["status_accuracy"].denominator == 1
    assert result.metrics["support_recall"].numerator == 0
    assert result.metrics["emitted_evidence_integrity"].rate == 1.0


def test_duplicate_id_alone_counts_every_member_and_never_repairs_ids():
    dataset = single_slot_dataset()
    original = (_output("same"), _output("same"), _output("same"))
    result = evaluate_protocol(dataset, (_one_attempt(original),))
    assert result.duplicate_id_items == 3
    assert result.missing_id_items == 0
    assert result.error_attempts == 1
    assert all(item.output_id == "same" for item in original)


@pytest.mark.parametrize("output_id", ["x", "x" * 128, " ", "::/!? ID \t"])
def test_valid_opaque_output_ids_are_preserved_without_normalization(output_id):
    dataset = single_slot_dataset()
    item = _output(output_id)
    result = evaluate_protocol(dataset, (_one_attempt((item,)),))

    assert item.output_id == output_id
    assert result.malformed_id_items == 0
    assert result.error_attempts == 0
    assert result.metrics["support_recall"].numerator == 1


@pytest.mark.parametrize("bad_id", [
    "", "x" * 129, 17, True, b"bytes", [], {}, set(), (), 1.5,
], ids=["empty", "too-long", "integer", "boolean", "bytes", "list", "dict", "set", "tuple", "float"])
def test_malformed_and_unhashable_ids_are_scored_contract_errors_without_leaks(bad_id):
    dataset = single_slot_dataset()
    result = evaluate_protocol(dataset, (_one_attempt((_output(bad_id),)),))

    assert result.malformed_id_items == 1
    assert result.missing_id_items == 0
    assert result.duplicate_id_items == 0
    assert result.error_attempts == 1
    assert result.evaluation_error_attempts == 1
    assert result.metrics["provider_error_rate"].numerator == 1
    assert result.metrics["provider_error_rate"].denominator == 1
    assert result.metrics["status_accuracy"].numerator == 0
    assert result.metrics["status_accuracy"].denominator == 1
    assert result.metrics["support_recall"].numerator == 0
    assert result.metrics["support_recall"].denominator == 1


def test_malformed_id_value_is_not_exposed_in_result_or_diagnostic():
    dataset = single_slot_dataset()
    raw_id = "PRIVATE-ID-SENTINEL-" + ("x" * 129)
    result = evaluate_protocol(dataset, (_one_attempt((_output(raw_id),)),))

    assert result.malformed_id_items == 1
    assert raw_id not in repr(result)


def test_multiple_malformed_ids_count_items_but_error_attempt_once():
    dataset = single_slot_dataset()
    result = evaluate_protocol(dataset, (_one_attempt((
        _output(1), _output([]), _output("x" * 129),
    )),))

    assert result.malformed_id_items == 3
    assert result.error_attempts == 1
    assert result.metrics["provider_error_rate"].numerator == 1
    assert result.metrics["support_recall"].numerator == 0


def test_malformed_ids_cannot_be_mistaken_for_valid_unique_or_duplicate_ids():
    dataset = single_slot_dataset()
    result = evaluate_protocol(dataset, (_one_attempt((
        _output(7), _output(7), _output("7"), _output("7"),
    )),))

    assert result.malformed_id_items == 2
    assert result.duplicate_id_items == 2
    assert result.error_attempts == 1


def test_distinct_producer_ids_keep_repeated_emissions_parseable_and_stable():
    dataset = single_slot_dataset()
    repeated = (
        _output("producer-item-a"),
        _output("producer-item-b"),
    )
    result = evaluate_protocol(dataset, (_one_attempt(repeated),))

    assert tuple(item.output_id for item in repeated) == ("producer-item-a", "producer-item-b")
    assert result.error_attempts == 0
    assert result.metrics["support_recall"].numerator == 1
    assert result.metrics["extra_unmatched_output_rate"].numerator == 1


def test_fixture_ids_are_deterministic_across_reordered_equivalent_records():
    first_dataset, first_attempts = minimum_heldout_cohort()
    second_dataset, second_attempts = minimum_heldout_cohort()

    def ids_by_case(attempts):
        return {
            attempt.case_id: tuple(sorted(item.output_id for item in attempt.items))
            for attempt in attempts
        }

    first_ids = ids_by_case(first_attempts)
    reordered_dataset = replace(
        second_dataset,
        sources=tuple(reversed(second_dataset.sources)),
        cases=tuple(replace(case, slots=tuple(reversed(case.slots)))
                     for case in reversed(second_dataset.cases)),
    )
    reordered_attempts = tuple(
        replace(attempt, items=tuple(reversed(attempt.items)))
        for attempt in reversed(second_attempts)
    )
    reordered_ids = ids_by_case(reordered_attempts)
    assert first_ids == reordered_ids
    assert all(len({item.output_id for item in attempt.items}) == len(attempt.items)
               for attempt in first_attempts)
    assert first_dataset.version == reordered_dataset.version


def test_malformed_output_id_invalidates_conflict_scoring_without_changing_denominator():
    dataset, attempt = _conflict_fixture()
    bad_attempt = replace(attempt, items=(
        replace(attempt.items[0], output_id=[]), attempt.items[1],
    ))
    result = evaluate_protocol(dataset, (bad_attempt,))

    assert result.malformed_id_items == 1
    assert result.error_attempts == 1
    assert result.metrics["conflict_preservation"].numerator == 0
    assert result.metrics["conflict_preservation"].denominator == 1


def test_provider_and_evaluation_error_categories_are_separate_but_combined_once():
    dataset = single_slot_dataset()
    mixed = _one_attempt((_output(None),), error_kind="TRANSPORT_ERROR")
    result = evaluate_protocol(dataset, (mixed,))
    assert result.provider_transport_error_attempts == 1
    assert result.evaluation_error_attempts == 1
    assert result.error_attempts == 1


def test_unknown_inventory_is_inconclusive_and_zero_emissions_are_not_a_pass():
    dataset = single_slot_dataset()
    unknown = ScheduledAttempt("case-1", None, None, False, "EVALUATION_ERROR")
    unknown_result = evaluate_protocol(dataset, (unknown,))
    assert unknown_result.metrics["emitted_evidence_integrity"].state == "INCONCLUSIVE"
    assert unknown_result.metrics["status_accuracy"].numerator == 0
    assert unknown_result.metrics["status_accuracy"].denominator == 1

    empty = ScheduledAttempt("case-1", "SUPPORTED", (), True, None)
    empty_result = evaluate_protocol(dataset, (empty,))
    assert empty_result.metrics["emitted_evidence_integrity"].state == "N/A"
    assert empty_result.metrics["empty_output_rate"].numerator == 1
    assert empty_result.verdict == "INCONCLUSIVE"


def test_invalid_source_or_quote_fails_integrity_without_invalidating_other_valid_match():
    dataset = single_slot_dataset()
    items = (_output("bad-source", "not-in-dataset"), _output("valid"))
    result = evaluate_protocol(dataset, (_one_attempt(items),))
    assert result.error_attempts == 0
    assert result.metrics["emitted_evidence_integrity"].numerator == 1
    assert result.metrics["emitted_evidence_integrity"].denominator == 2
    assert result.metrics["support_recall"].numerator == 1


def test_invalid_quote_fails_integrity_without_invalidating_other_valid_match():
    dataset = single_slot_dataset()
    items = (
        _output("invalid-quote", quote="This quote is not in the frozen source."),
        _output("valid-quote"),
    )
    result = evaluate_protocol(dataset, (_one_attempt(items),))

    assert result.error_attempts == 0
    assert result.metrics["emitted_evidence_integrity"].numerator == 1
    assert result.metrics["emitted_evidence_integrity"].denominator == 2
    assert result.metrics["support_recall"].numerator == 1


def test_conflict_preservation_credits_both_eligible_opposing_directions():
    dataset, attempt = _conflict_fixture()
    result = evaluate_protocol(dataset, (attempt,))

    assert result.metrics["conflict_preservation"].denominator == 1
    assert result.metrics["conflict_preservation"].numerator == 1


def test_same_origin_opposing_slots_are_excluded_from_conflict_eligibility():
    case_id = "same-origin-conflict"
    sources = (
        FrozenSource("same-support-source", "Support evidence.", "same-support-v1", "same-origin", True),
        FrozenSource("same-contra-source", "Contradiction evidence.", "same-contra-v1", "same-origin", True),
    )
    slots = (
        GoldSlot("same-support", case_id, "hypothesis-1", "SUPPORTS",
                 "same-support-source", "same-support-v1", 0, len("Support evidence."),
                 True, True, "FRESH"),
        GoldSlot("same-contra", case_id, "hypothesis-1", "CONTRADICTS",
                 "same-contra-source", "same-contra-v1", 0, len("Contradiction evidence."),
                 True, True, "FRESH"),
    )
    dataset = GoldDataset("same-origin-v1", sources,
                          (GoldCase(case_id, "hypothesis-1", "PARTIAL", slots),))
    attempt = ScheduledAttempt(case_id, "PARTIAL", (
        _output("same-support-output", "same-support-source", "Support evidence.", "SUPPORTS"),
        _output("same-contra-output", "same-contra-source", "Contradiction evidence.", "CONTRADICTS"),
    ))

    result = evaluate_protocol(dataset, (attempt,))

    assert result.metrics["conflict_preservation"].denominator == 0
    assert result.metrics["conflict_preservation"].numerator == 0


@pytest.mark.parametrize("decoy", [
    {"freshness": "STALE"},
    {"relevance": False},
    {"admissibility": False},
    {"origin": None, "origin_confirmed": False},
], ids=["stale", "irrelevant", "inadmissible", "unknown-origin"])
def test_ineligible_direction_cannot_substitute_for_eligible_conflict_evidence(decoy):
    dataset, attempt = _conflict_fixture(include_eligible_support=False, decoy=decoy)
    result = evaluate_protocol(dataset, (attempt,))

    # The accepted decoy SUPPORTS item is not the eligible gold SUPPORTS slot.
    assert result.metrics["conflict_preservation"].denominator == 1
    assert result.metrics["conflict_preservation"].numerator == 0


def test_conflict_preservation_requires_partial_status():
    dataset, attempt = _conflict_fixture(status="SUPPORTED")
    result = evaluate_protocol(dataset, (attempt,))

    assert result.metrics["conflict_preservation"].numerator == 0


def test_multiple_eligible_pairs_pass_when_one_complete_pair_is_preserved():
    dataset, attempt = _multi_pair_fixture(("support-a", "contra-b", "support-b"))
    result = evaluate_protocol(dataset, (attempt,))

    assert result.metrics["conflict_preservation"].numerator == 1


def test_multiple_eligible_pairs_fail_when_no_complete_pair_is_preserved():
    dataset, attempt = _multi_pair_fixture(("support-a", "contra-a"))
    result = evaluate_protocol(dataset, (attempt,))

    assert result.metrics["conflict_preservation"].numerator == 0


def test_ambiguous_pair_assignment_that_changes_preservation_is_inconclusive():
    dataset, attempts = _ten_conflict_cases_with_ambiguity("changes")
    result = evaluate_protocol(dataset, attempts)

    assert result.metrics["conflict_preservation"].denominator == 10
    # The ambiguous candidate is not used to credit the case in the numerator.
    assert result.metrics["conflict_preservation"].numerator == 9
    assert result.metrics["conflict_preservation"].state == "INCONCLUSIVE"


def test_tie_across_multiple_eligible_pairs_is_inconclusive_without_hypothetical_credit():
    dataset, attempts = _ten_conflict_cases_with_multi_pair_tie()
    result = evaluate_protocol(dataset, attempts)

    assert result.metrics["conflict_preservation"].denominator == 10
    # Case zero's actual unmatched ambiguous emissions earn no credit; the other
    # nine cases do. Alternative one-to-one assignments change that case result.
    assert result.metrics["conflict_preservation"].numerator == 9
    assert result.metrics["conflict_preservation"].state == "INCONCLUSIVE"


def test_ambiguity_that_cannot_change_case_preservation_remains_scoreable():
    dataset, attempts = _ten_conflict_cases_with_ambiguity("unchanged")
    result = evaluate_protocol(dataset, attempts)

    assert result.metrics["conflict_preservation"].denominator == 10
    assert result.metrics["conflict_preservation"].numerator == 10
    assert result.metrics["conflict_preservation"].state == "PASS"


def test_competing_items_cannot_match_the_same_conflict_slot_twice():
    dataset, attempt = _conflict_fixture()
    competing = _output("competing-support", "eligible-support-source",
                        "Eligible support evidence.", "SUPPORTS")
    attempt = replace(attempt, items=(*attempt.items, competing))
    result = evaluate_protocol(dataset, (attempt,))

    assert result.metrics["conflict_preservation"].numerator == 1
    assert result.metrics["extra_unmatched_output_rate"].numerator == 1


def test_one_to_one_matching_counts_second_valid_emission_as_extra():
    dataset = single_slot_dataset()
    items = (_output("out-a"), _output("out-b"))
    result = evaluate_protocol(dataset, (_one_attempt(items),))
    assert result.metrics["support_recall"].numerator == 1
    assert result.metrics["missing_expected_slot_rate"].numerator == 0
    assert result.metrics["extra_unmatched_output_rate"].numerator == 1
    assert result.metrics["extra_unmatched_output_rate"].denominator == 2


def test_output_list_reordering_does_not_change_alignment_or_scores():
    text = "Support sentence. Contradiction sentence."
    source = FrozenSource("source-1", text, "source-v1", "origin-1", True)
    support_start = text.index("Support")
    contra_start = text.index("Contradiction")
    slots = (
        GoldSlot("g-support", "case-1", "hypothesis-1", "SUPPORTS", "source-1", "source-v1",
                 support_start, support_start + len("Support sentence."), True, True),
        GoldSlot("g-contra", "case-1", "hypothesis-1", "CONTRADICTS", "source-1", "source-v1",
                 contra_start, contra_start + len("Contradiction sentence."), True, True),
    )
    dataset = GoldDataset("v1", (source,), (GoldCase("case-1", "hypothesis-1", "PARTIAL", slots),))
    support = _output("z-id", quote="Support sentence.", stance="SUPPORTS")
    contra = _output("a-id", quote="Contradiction sentence.", stance="CONTRADICTS")
    first = evaluate_protocol(dataset, (ScheduledAttempt("case-1", "PARTIAL", (support, contra)),))
    reordered = evaluate_protocol(dataset, (ScheduledAttempt("case-1", "PARTIAL", (contra, support)),))
    assert first.metrics["support_recall"].numerator == reordered.metrics["support_recall"].numerator == 1
    assert first.metrics["contradiction_recall"].numerator == reordered.metrics["contradiction_recall"].numerator == 1
    assert first.metrics["missing_expected_slot_rate"].numerator == 0


def test_unadjudicated_repeated_quote_makes_affected_metrics_inconclusive():
    text = "The checklist was available. Later, The checklist was available."
    quote = "The checklist was available."
    first = text.index(quote)
    dataset = single_slot_dataset(text=text, quote=quote, start=first, end=first + len(quote))
    attempt = _one_attempt((_output(quote=quote),))
    result = evaluate_protocol(dataset, (attempt,))
    assert result.metrics["support_recall"].state == "INCONCLUSIVE"
    assert result.metrics["missing_expected_slot_rate"].state == "INCONCLUSIVE"


def test_ambiguous_contradiction_matching_makes_false_support_inconclusive():
    dataset, attempt = _repeated_quote_ambiguity("SUPPORTS")
    result = evaluate_protocol(dataset, (attempt,))

    # Resolving the repeated quote to CONTRADICTS yields false support; resolving
    # it to SUPPORTS does not. The unresolved occurrence must not be guessed.
    assert result.metrics["false_support"].denominator == 21
    assert result.metrics["false_support"].state == "INCONCLUSIVE"


def test_ambiguity_irrelevant_to_false_support_does_not_invalidate_it():
    dataset, attempt = _repeated_quote_ambiguity("SUPPORTS", first_stance="SUPPORTS")
    result = evaluate_protocol(dataset, (attempt,))

    assert result.metrics["false_support"].denominator == 20
    assert result.metrics["false_support"].numerator == 0
    assert result.metrics["false_support"].state == "PASS"


def test_pre_adjudicated_all_repeated_occurrences_resolve_to_same_slot():
    text = "same evidence; then same evidence"
    positions = [i for i in range(len(text)) if text.startswith("same evidence", i)]
    repeated = tuple(RepeatedOccurrenceAdjudication(
        "slot-1", "source-1", "same evidence", start, start + len("same evidence")
    ) for start in positions)
    start = text.index("same evidence")
    dataset = single_slot_dataset(text=text, quote="same evidence", start=start,
                                  end=start + len("same evidence"), repeated_occurrences=repeated)
    result = evaluate_protocol(dataset, (_one_attempt((_output(quote="same evidence"),)),))
    assert result.metrics["support_recall"].numerator == 1


def test_repeated_occurrence_adjudication_must_cover_every_occurrence():
    text = "same evidence; then same evidence"
    start = text.index("same evidence")
    only_first = (RepeatedOccurrenceAdjudication("slot-1", "source-1", "same evidence",
                                                 start, start + len("same evidence")),)
    dataset = single_slot_dataset(text=text, quote="same evidence", start=start,
                                  end=start + len("same evidence"), repeated_occurrences=only_first)
    with pytest.raises(ProtocolInputError, match="every repeated quote occurrence"):
        validate_gold_dataset(dataset)


def test_strict_subspan_requires_exact_pre_evaluation_adjudication():
    text = "Report says the checklist was available today."
    quote = "checklist was available"
    start = text.index(quote)
    dataset = single_slot_dataset(text=text, quote=text, start=0, end=len(text))
    item = _output(quote=quote)
    unapproved = evaluate_protocol(dataset, (_one_attempt((item,)),))
    assert unapproved.metrics["missing_expected_slot_rate"].numerator == 1
    assert unapproved.metrics["support_recall"].numerator == 0

    authorized = replace(dataset, subspan_adjudications=(
        SubspanAdjudication("slot-1", "source-1", start, start + len(quote)),
    ))
    approved_result = evaluate_protocol(authorized, (_one_attempt((item,)),))
    assert approved_result.metrics["support_recall"].numerator == 1


@pytest.mark.parametrize("bad_slot", [
    {"source_text_identity": "wrong-v2"},
    {"start": -1},
    {"end": 500},
    {"start": 5, "end": 4},
])
def test_source_identity_and_unicode_offsets_are_validated(bad_slot):
    dataset = single_slot_dataset()
    case = dataset.cases[0]
    slot = replace(case.slots[0], **bad_slot)
    invalid = replace(dataset, cases=(replace(case, slots=(slot,)),))
    with pytest.raises(ProtocolInputError):
        validate_gold_dataset(invalid)


@pytest.mark.parametrize("field_name", ["relevance", "admissibility"])
@pytest.mark.parametrize("bad_value", [None, 0, 1, "true", "false"])
def test_gold_slot_boolean_labels_require_exact_builtin_bool(field_name, bad_value):
    dataset = single_slot_dataset()
    case = dataset.cases[0]
    slot = replace(case.slots[0], **{field_name: bad_value})
    invalid = replace(dataset, cases=(replace(case, slots=(slot,)),))

    with pytest.raises(ProtocolInputError, match=f"GoldSlot\\.{field_name}"):
        validate_gold_dataset(invalid)


@pytest.mark.parametrize("field_name", [
    "GoldCase.eligible",
    "GoldCase.independently_authored",
    "FrozenSource.origin_confirmed",
    "GoldDataset.held_out",
    "ScheduledAttempt.inventory_known",
])
@pytest.mark.parametrize("bad_value", [None, 0, 1, "true", "false"])
def test_protocol_boolean_flags_require_exact_builtin_bool(field_name, bad_value):
    dataset = single_slot_dataset()
    if field_name.startswith("GoldCase."):
        case = dataset.cases[0]
        invalid = replace(dataset, cases=(replace(
            case, **{field_name.split(".")[1]: bad_value}
        ),))
        with pytest.raises(ProtocolInputError, match=field_name.replace(".", r"\.")):
            validate_gold_dataset(invalid)
    elif field_name == "FrozenSource.origin_confirmed":
        source = replace(dataset.sources[0], origin_confirmed=bad_value)
        invalid = replace(dataset, sources=(source,))
        with pytest.raises(ProtocolInputError, match=r"FrozenSource\.origin_confirmed"):
            validate_gold_dataset(invalid)
    elif field_name == "GoldDataset.held_out":
        with pytest.raises(ProtocolInputError, match=r"GoldDataset\.held_out"):
            validate_gold_dataset(replace(dataset, held_out=bad_value))
    else:
        attempt = ScheduledAttempt("case-1", "SUPPORTED", (), bad_value)
        with pytest.raises(ProtocolInputError, match=r"ScheduledAttempt\.inventory_known"):
            evaluate_protocol(dataset, (attempt,))


def test_exact_boolean_true_false_controls_are_accepted_before_scoring():
    dataset = single_slot_dataset(relevance=False, admissibility=True, origin_confirmed=False)
    case = replace(dataset.cases[0], independently_authored=False)
    dataset = replace(dataset, cases=(case,), held_out=False)
    validate_gold_dataset(dataset)
    result = evaluate_protocol(
        single_slot_dataset(),
        (ScheduledAttempt("case-1", None, None, False, "EVALUATION_ERROR"),),
    )
    assert result.metrics["emitted_evidence_integrity"].state == "INCONCLUSIVE"


def test_duplicate_gold_slot_ids_and_shared_spans_invalidate_annotation_set():
    dataset = single_slot_dataset()
    case = dataset.cases[0]
    second = replace(case.slots[0], gold_slot_id="slot-2")
    duplicated_span = replace(dataset, cases=(replace(case, slots=(case.slots[0], second)),))
    with pytest.raises(ProtocolInputError, match="shared source spans"):
        validate_gold_dataset(duplicated_span)
    duplicate_id = replace(dataset, cases=(replace(case, slots=(case.slots[0],
                                                                 replace(case.slots[0], case_id="case-1"))),))
    with pytest.raises(ProtocolInputError, match="duplicate gold_slot_id"):
        validate_gold_dataset(duplicate_id)


def test_error_rate_boundary_counts_each_attempt_once_and_status_error_once():
    dataset, attempts = minimum_heldout_cohort()
    changed = list(attempts)
    for i in (30, 31, 32):
        changed[i] = replace(changed[i], items=(replace(changed[i].items[0], output_id=None),))
    result = evaluate_protocol(dataset, tuple(changed))
    assert result.error_attempts == 3
    assert result.metrics["provider_error_rate"].numerator == 3
    assert result.metrics["provider_error_rate"].denominator == 60
    assert result.metrics["provider_error_rate"].rate == 0.05
    assert result.metrics["provider_error_rate"].state == "PASS"
    assert result.metrics["status_accuracy"].numerator == 57
    assert result.metrics["status_accuracy"].denominator == 60


def test_required_minimum_shortfall_is_inconclusive_and_adequate_failure_wins():
    dataset, attempts = minimum_heldout_cohort()
    remaining_neutral_slots = 19
    reduced_cases = []
    for case in dataset.cases:
        retained = []
        for slot in case.slots:
            if slot.expected_stance == "NEUTRAL":
                if remaining_neutral_slots:
                    retained.append(slot)
                    remaining_neutral_slots -= 1
            else:
                retained.append(slot)
        reduced_cases.append(replace(case, slots=tuple(retained)))
    reduced = replace(dataset, cases=tuple(reduced_cases))
    small_result = evaluate_protocol(reduced, attempts)
    assert small_result.sample_minima["neutral_slots"] == (19, 20, False)
    assert small_result.verdict == "INCONCLUSIVE"

    conflict_attempt = next(a for a in attempts if a.case_id == "heldout-00")
    lost_direction = replace(conflict_attempt, items=conflict_attempt.items[:1])
    combined_attempts = tuple(lost_direction if a.case_id == "heldout-00" else a for a in attempts)
    precedence = evaluate_protocol(reduced, combined_attempts)
    assert precedence.metrics["conflict_preservation"].state == "FAIL"
    assert precedence.verdict == "FAIL"


def test_status_and_diagnostic_zero_denominators_are_not_passes():
    dataset = GoldDataset("empty", (), (), True)
    result = evaluate_protocol(dataset, ())
    assert result.metrics["status_accuracy"].state == "N/A"
    assert result.metrics["valid_abstention_rate"].state == "N/A"
    assert result.verdict == "INCONCLUSIVE"


def test_contract_rejection_and_reviewer_agreement_diagnostics():
    contract = score_contract_rejections(
        ("invalid_source", "invalid_quote", "malformed_output", "unsupported_claim"),
        ("invalid_source", "wrong", "malformed_output", "unsupported_claim"),
    )
    assert (contract.numerator, contract.denominator, contract.state) == (3, 4, "DIAGNOSTIC")

    agreement = score_reviewer_agreement(
        {"stance": ("SUPPORTS", "CONTRADICTS", "NEUTRAL", "UNRESOLVED")},
        ("u1", "u2", "u3"),
        {"u1": {"stance": "SUPPORTS"}, "u2": {"stance": "UNRESOLVED"}},
        {"u1": {"stance": "SUPPORTS"}, "u2": {"stance": "NEUTRAL"}},
        {"u2": {"stance": "NEUTRAL"}},
    )
    assert agreement["stance"]["agreements"] == 1
    assert agreement["stance"]["denominator"] == 2
    assert agreement["stance"]["missing_units"] == 1
    assert agreement["stance"]["unresolved_units"] == 1
    assert agreement["stance"]["adjudicated_units"] == 1


class _OriginString(str):
    pass


@pytest.mark.parametrize("origin", [None, "", " \t\n", 17, True, b"origin", [], {}, _OriginString("origin")],
                         ids=["none", "empty", "whitespace", "integer", "boolean", "bytes",
                              "list", "dict", "string-subclass"])
def test_confirmed_source_origin_requires_exact_nonblank_builtin_string(origin):
    dataset = single_slot_dataset()
    source = replace(dataset.sources[0], source_origin_id=origin)
    invalid = replace(dataset, sources=(source,))
    with pytest.raises(ProtocolInputError, match="^invalid FrozenSource\\.source_origin_id$") as error:
        validate_gold_dataset(invalid)
    assert repr(origin) not in str(error.value)


@pytest.mark.parametrize("origin", [17, True, b"origin", [], {}, "", " \t"])
def test_unconfirmed_malformed_source_origin_is_rejected(origin):
    dataset = single_slot_dataset(origin_confirmed=False)
    invalid = replace(dataset, sources=(replace(dataset.sources[0], source_origin_id=origin),))
    with pytest.raises(ProtocolInputError, match="^invalid FrozenSource\\.source_origin_id$"):
        validate_gold_dataset(invalid)


def test_unconfirmed_none_and_valid_string_origins_are_accepted_but_not_eligible():
    for origin in (None, "present-but-unconfirmed"):
        dataset, attempt = _conflict_fixture()
        support = next(source for source in dataset.sources if source.source_record_id == "eligible-support-source")
        sources = tuple(replace(source, source_origin_id=origin, origin_confirmed=False)
                        if source is support else source for source in dataset.sources)
        dataset = replace(dataset, sources=sources)
        validate_gold_dataset(dataset)
        result = evaluate_protocol(dataset, (attempt,))
        assert result.metrics["conflict_preservation"].denominator == 0


@pytest.mark.parametrize("bad_dataset", [None, object()], ids=["none", "other-record"])
def test_dataset_requires_exact_gold_dataset_record(bad_dataset):
    with pytest.raises(ProtocolInputError, match="^dataset must be a GoldDataset$"):
        validate_gold_dataset(bad_dataset)


@pytest.mark.parametrize("field,value", [
    ("sources", None), ("sources", [object()]), ("cases", None), ("cases", [object()]),
    ("subspan_adjudications", None), ("subspan_adjudications", (object(),)),
    ("repeated_occurrences", None), ("repeated_occurrences", (object(),)),
])
def test_dataset_collection_boundaries_raise_protocol_input_error(field, value):
    dataset = single_slot_dataset()
    with pytest.raises(ProtocolInputError):
        validate_gold_dataset(replace(dataset, **{field: value}))


@pytest.mark.parametrize("field,value", [
    ("slots", None), ("slots", (object(),)),
    ("scenario_tags", []), ("scenario_tags", frozenset({1})),
])
def test_case_nested_boundaries_raise_protocol_input_error(field, value):
    dataset = single_slot_dataset()
    case = replace(dataset.cases[0], **{field: value})
    with pytest.raises(ProtocolInputError):
        validate_gold_dataset(replace(dataset, cases=(case,)))


@pytest.mark.parametrize("case_id", [[], {}, 1, True, ""])
def test_attempt_case_id_is_validated_before_lookup(case_id):
    dataset = single_slot_dataset()
    with pytest.raises(ProtocolInputError, match="^invalid ScheduledAttempt\\.case_id$"):
        evaluate_protocol(dataset, (ScheduledAttempt(case_id, "SUPPORTED", ()),))


@pytest.mark.parametrize("attempts", ["case-1", b"case-1", bytearray(b"case-1"), (object(),)])
def test_attempt_container_and_members_are_validated(attempts):
    dataset = single_slot_dataset()
    with pytest.raises(ProtocolInputError):
        evaluate_protocol(dataset, attempts)


@pytest.mark.parametrize("items", [[_output()], (object(),)])
def test_known_inventory_requires_tuple_of_exact_evidence_records(items):
    dataset = single_slot_dataset()
    attempt = ScheduledAttempt("case-1", "SUPPORTED", items)
    with pytest.raises(ProtocolInputError):
        evaluate_protocol(dataset, (attempt,))


def test_reviewer_diagnostic_rejects_unhashable_ids_and_labels_safely():
    registry = {"stance": ("SUPPORTS", "UNRESOLVED")}
    with pytest.raises(ProtocolInputError):
        score_reviewer_agreement(registry, (["unit"],), {}, {})
    with pytest.raises(ProtocolInputError):
        score_reviewer_agreement(registry, ("unit",), {"unit": {"stance": []}}, {})


@pytest.mark.parametrize("error_kind", [[], {}, True, b"PROVIDER_ERROR", _OriginString("PROVIDER_ERROR")])
def test_malformed_attempt_error_kind_is_rejected_with_fixed_message(error_kind):
    dataset = single_slot_dataset()
    attempt = ScheduledAttempt("case-1", "SUPPORTED", (), True, error_kind)
    with pytest.raises(ProtocolInputError, match="^invalid ScheduledAttempt\\.error_kind$") as error:
        evaluate_protocol(dataset, (attempt,))
    assert "CANARY" not in str(error.value)


@pytest.mark.parametrize("error_kind,expected_errors,expected_provider_errors,expected_evaluation_errors", [
    (None, 0, 0, 0),
    ("TRANSPORT_ERROR", 1, 1, 0),
    ("UNRECOGNIZED_KIND", 1, 0, 1),
])
def test_valid_attempt_error_kind_behavior_is_preserved(
        error_kind, expected_errors, expected_provider_errors, expected_evaluation_errors):
    result = evaluate_protocol(single_slot_dataset(), (
        ScheduledAttempt("case-1", "SUPPORTED", (), True, error_kind),
    ))
    assert result.error_attempts == expected_errors
    assert result.provider_transport_error_attempts == expected_provider_errors
    assert result.evaluation_error_attempts == expected_evaluation_errors


@pytest.mark.parametrize("case_id", [[], {"CASE-CANARY": True}])
def test_gold_case_id_is_validated_before_set_lookup(case_id):
    dataset = single_slot_dataset()
    case = replace(dataset.cases[0], case_id=case_id)
    invalid = replace(dataset, cases=(case,))
    with pytest.raises(ProtocolInputError, match="^invalid case_id$") as error:
        validate_gold_dataset(invalid)
    assert "CASE-CANARY" not in str(error.value)


@pytest.mark.parametrize("source_id", [[], {"SOURCE-CANARY": True}])
def test_frozen_source_id_is_validated_before_map_lookup(source_id):
    dataset = single_slot_dataset()
    source = replace(dataset.sources[0], source_record_id=source_id)
    invalid = replace(dataset, sources=(source,))
    with pytest.raises(ProtocolInputError, match="^invalid source_record_id$") as error:
        validate_gold_dataset(invalid)
    assert "SOURCE-CANARY" not in str(error.value)


@pytest.mark.parametrize("field", ["gold_slot_id", "case_id", "hypothesis_id", "source_record_id",
                                   "source_text_identity"])
def test_unhashable_slot_linkage_ids_are_rejected_before_lookup(field):
    dataset = single_slot_dataset()
    slot = replace(dataset.cases[0].slots[0], **{field: ["SLOT-CANARY"]})
    case = replace(dataset.cases[0], slots=(slot,))
    invalid = replace(dataset, cases=(case,))
    with pytest.raises(ProtocolInputError) as error:
        validate_gold_dataset(invalid)
    assert "SLOT-CANARY" not in str(error.value)


@pytest.mark.parametrize("record,field", [
    ("subspan", "gold_slot_id"), ("subspan", "source_record_id"),
    ("repeated", "gold_slot_id"), ("repeated", "source_record_id"),
])
def test_unhashable_adjudication_lookup_ids_are_rejected_before_lookup(record, field):
    dataset = single_slot_dataset()
    if record == "subspan":
        entry = SubspanAdjudication("slot-1", "source-1", 1, 2)
        collection = "subspan_adjudications"
    else:
        entry = RepeatedOccurrenceAdjudication("slot-1", "source-1", "x", 0, 1)
        collection = "repeated_occurrences"
    invalid_entry = replace(entry, **{field: ["ADJ-CANARY"]})
    invalid = replace(dataset, **{collection: (invalid_entry,)})
    with pytest.raises(ProtocolInputError) as error:
        validate_gold_dataset(invalid)
    assert "ADJ-CANARY" not in str(error.value)


def test_evaluate_rejects_malformed_origin_before_conflict_scoring(monkeypatch):
    dataset, attempt = _conflict_fixture()
    source = next(source for source in dataset.sources
                  if source.source_record_id == "eligible-support-source")
    invalid = replace(dataset, sources=tuple(
        replace(entry, source_origin_id={"ORIGIN-CANARY": True}) if entry is source else entry
        for entry in dataset.sources
    ))

    def scoring_must_not_run(*args, **kwargs):
        raise AssertionError("conflict scoring ran before dataset validation")

    monkeypatch.setattr(protocol_v1, "_eligible_conflict_pairs", scoring_must_not_run)
    with pytest.raises(ProtocolInputError, match="^invalid FrozenSource\\.source_origin_id$") as error:
        evaluate_protocol(invalid, (attempt,))
    assert "ORIGIN-CANARY" not in str(error.value)


@pytest.mark.parametrize("attempts,expected_message,canary", [
    ((ScheduledAttempt("UNKNOWN-CASE-CANARY", "SUPPORTED", ()),),
     "attempt case_id is not eligible", "UNKNOWN-CASE-CANARY"),
    ((ScheduledAttempt("case-1", "SUPPORTED", ()), ScheduledAttempt("case-1", "SUPPORTED", ())),
     "duplicate scheduled attempt case_id", "case-1"),
])
def test_attempt_case_rejections_use_fixed_messages(attempts, expected_message, canary):
    with pytest.raises(ProtocolInputError, match=f"^{expected_message}$") as error:
        evaluate_protocol(single_slot_dataset(), attempts)
    assert canary not in str(error.value)


@pytest.mark.parametrize("field_registry,reviewer_one,expected_message,canary", [
    ({"FIELD-CANARY": ()}, {}, "reviewer field has no permitted labels", "FIELD-CANARY"),
    ({"FIELD-CANARY": ("OK",)}, {"unit": {"FIELD-CANARY": "BAD-CANARY"}},
     "reviewer label outside frozen registry", "FIELD-CANARY"),
])
def test_reviewer_field_rejections_use_fixed_messages(
        field_registry, reviewer_one, expected_message, canary):
    with pytest.raises(ProtocolInputError, match=f"^{expected_message}$") as error:
        score_reviewer_agreement(
            field_registry, ("unit",), reviewer_one, {"unit": {"FIELD-CANARY": "OK"}}
        )
    assert canary not in str(error.value)
    assert "BAD-CANARY" not in str(error.value)
