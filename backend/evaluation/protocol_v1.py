"""Isolated, in-memory implementation of the approved synthetic protocol v1.

This module deliberately has no application, provider, filesystem, database, or
network dependencies.  It accepts frozen annotation and attempt objects and
returns typed metric records; callers decide how to persist or present them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence


STANCES = frozenset({"SUPPORTS", "CONTRADICTS", "NEUTRAL"})
DIRECTIONAL_STANCES = frozenset({"SUPPORTS", "CONTRADICTS"})
STATUSES = frozenset({"SUPPORTED", "PARTIAL", "CONTRADICTED", "INSUFFICIENT"})
REVIEW_STATES = frozenset({"ACCEPTED", "UNVERIFIED"})
FRESHNESS = frozenset({"FRESH", "STALE", "UNKNOWN"})
SCENARIO_MINIMA = {
    "ambiguity_unresolved": 10,
    "stale": 10,
    "unknown_freshness": 10,
    "shared_lineage": 10,
    "independent_sources": 10,
    "insufficient_evidence": 10,
}


class ProtocolInputError(ValueError):
    """Input cannot represent the frozen protocol records reliably."""


@dataclass(frozen=True)
class FrozenSource:
    source_record_id: str
    text: str
    text_identity: str
    source_origin_id: str | None = None
    origin_confirmed: bool = False


@dataclass(frozen=True)
class GoldSlot:
    gold_slot_id: str
    case_id: str
    hypothesis_id: str
    expected_stance: str
    source_record_id: str
    source_text_identity: str
    start: int
    end: int
    relevance: bool
    admissibility: bool
    freshness: str = "UNKNOWN"


@dataclass(frozen=True)
class GoldCase:
    case_id: str
    hypothesis_id: str
    expected_status: str
    slots: tuple[GoldSlot, ...] = ()
    eligible: bool = True
    independently_authored: bool = False
    scenario_tags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SubspanAdjudication:
    """Frozen authorization for one exact emitted source span."""

    gold_slot_id: str
    source_record_id: str
    start: int
    end: int


@dataclass(frozen=True)
class RepeatedOccurrenceAdjudication:
    """Pre-adjudication that an occurrence represents one gold slot."""

    gold_slot_id: str
    source_record_id: str
    quote: str
    start: int
    end: int


@dataclass(frozen=True)
class GoldDataset:
    version: str
    sources: tuple[FrozenSource, ...]
    cases: tuple[GoldCase, ...]
    held_out: bool = False
    subspan_adjudications: tuple[SubspanAdjudication, ...] = ()
    repeated_occurrences: tuple[RepeatedOccurrenceAdjudication, ...] = ()


@dataclass(frozen=True)
class EmittedEvidence:
    """Raw parseable emitted item; output_id=None represents a missing ID."""

    output_id: Any = None
    source_record_id: Any = None
    quote: Any = None
    stance: Any = None
    review_state: Any = "ACCEPTED"
    proposed_stance: Any = None


@dataclass(frozen=True)
class ScheduledAttempt:
    """One scheduled attempt. Keep parseable raw items, including bad IDs."""

    case_id: str
    status: str | None = None
    items: tuple[EmittedEvidence, ...] | None = ()
    inventory_known: bool = True
    error_kind: str | None = None


@dataclass(frozen=True)
class MetricResult:
    name: str
    unit: str
    numerator: int | None
    denominator: int | None
    rate: float | None
    state: str
    required: bool = False
    threshold: float | int | None = None
    minimum: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    metrics: Mapping[str, MetricResult]
    sample_minima: Mapping[str, tuple[int, int, bool]]
    missing_id_items: int
    duplicate_id_items: int
    error_attempts: int
    scheduled_attempts: int
    verdict: str
    provider_transport_error_attempts: int = 0
    evaluation_error_attempts: int = 0
    malformed_id_items: int = 0


@dataclass(frozen=True)
class _PreparedItem:
    raw: EmittedEvidence
    original_index: int
    structurally_valid: bool
    integrity_valid: bool
    effective_stance: str | None
    unverified: bool
    possible_slots: frozenset[str]
    ambiguous_slots: frozenset[str]


def _require_nonempty_text(value: Any, label: str) -> None:
    if type(value) is not str or not value:
        raise ProtocolInputError(f"{label} must be a non-empty string")


def _require_exact_text(value: Any, message: str, *, nonempty: bool = True) -> None:
    if type(value) is not str or (nonempty and not value):
        raise ProtocolInputError(message)


def _require_record_tuple(value: Any, record_type: type, message: str) -> None:
    if type(value) is not tuple or any(type(entry) is not record_type for entry in value):
        raise ProtocolInputError(message)


def _require_exact_bool(value: Any, field_name: str) -> None:
    """Require a real built-in bool, excluding integer and nullable lookalikes."""
    if type(value) is not bool:
        raise ProtocolInputError(f"invalid boolean field: {field_name}")


def _all_occurrences(text: str, quote: str) -> tuple[tuple[int, int], ...]:
    if not quote:
        return ()
    found: list[tuple[int, int]] = []
    start = 0
    while True:
        at = text.find(quote, start)
        if at < 0:
            return tuple(found)
        found.append((at, at + len(quote)))
        start = at + 1  # Include overlapping repeated occurrences.


def validate_gold_dataset(dataset: GoldDataset) -> None:
    """Validate IDs, frozen identities, code-point spans, and adjudications."""

    if type(dataset) is not GoldDataset:
        raise ProtocolInputError("dataset must be a GoldDataset")
    _require_exact_bool(dataset.held_out, "GoldDataset.held_out")
    _require_nonempty_text(dataset.version, "dataset version")
    _require_record_tuple(dataset.sources, FrozenSource, "invalid GoldDataset.sources")
    _require_record_tuple(dataset.cases, GoldCase, "invalid GoldDataset.cases")
    _require_record_tuple(dataset.subspan_adjudications, SubspanAdjudication,
                          "invalid GoldDataset.subspan_adjudications")
    _require_record_tuple(dataset.repeated_occurrences, RepeatedOccurrenceAdjudication,
                          "invalid GoldDataset.repeated_occurrences")
    for case in dataset.cases:
        _require_record_tuple(case.slots, GoldSlot, "invalid GoldCase.slots")
        if type(case.scenario_tags) is not frozenset or any(type(tag) is not str for tag in case.scenario_tags):
            raise ProtocolInputError("invalid GoldCase.scenario_tags")
    # Validate every identifier before any dictionary or set lookup/insertion.
    for source in dataset.sources:
        _require_exact_text(source.source_record_id, "invalid source_record_id")
        _require_exact_text(source.text_identity, "invalid source text identity")
        if source.source_origin_id is None:
            if source.origin_confirmed is True:
                raise ProtocolInputError("invalid FrozenSource.source_origin_id")
        elif (type(source.source_origin_id) is not str
              or not source.source_origin_id.strip()):
            raise ProtocolInputError("invalid FrozenSource.source_origin_id")
    for case in dataset.cases:
        _require_exact_text(case.case_id, "invalid case_id")
        _require_exact_text(case.hypothesis_id, "invalid hypothesis_id")
        for slot in case.slots:
            _require_exact_text(slot.gold_slot_id, "invalid gold_slot_id")
            _require_exact_text(slot.case_id, "invalid slot case_id")
            _require_exact_text(slot.hypothesis_id, "invalid slot hypothesis_id")
            _require_exact_text(slot.source_record_id, "invalid slot source_record_id")
            _require_exact_text(slot.source_text_identity, "invalid slot source text identity")
    for entry in dataset.subspan_adjudications:
        _require_exact_text(entry.gold_slot_id, "invalid subspan gold_slot_id")
        _require_exact_text(entry.source_record_id, "invalid subspan source_record_id")
    for entry in dataset.repeated_occurrences:
        _require_exact_text(entry.gold_slot_id, "invalid repeated-occurrence gold_slot_id")
        _require_exact_text(entry.source_record_id, "invalid repeated-occurrence source_record_id")
    sources: dict[str, FrozenSource] = {}
    for source in dataset.sources:
        _require_exact_bool(source.origin_confirmed, "FrozenSource.origin_confirmed")
        if type(source.text) is not str:
            raise ProtocolInputError("frozen source text must be a string")
        if source.source_record_id in sources:
            raise ProtocolInputError("duplicate source record ID")
        sources[source.source_record_id] = source

    case_ids: set[str] = set()
    slots: dict[str, GoldSlot] = {}
    spans: dict[tuple[str, int, int], str] = {}
    for case in dataset.cases:
        _require_exact_bool(case.eligible, "GoldCase.eligible")
        _require_exact_bool(case.independently_authored, "GoldCase.independently_authored")
        if case.case_id in case_ids:
            raise ProtocolInputError("duplicate case_id")
        case_ids.add(case.case_id)
        if not isinstance(case.expected_status, str) or case.expected_status not in STATUSES:
            raise ProtocolInputError("invalid gold status")
        for tag in case.scenario_tags:
            if tag not in SCENARIO_MINIMA:
                raise ProtocolInputError("unknown scenario tag")
        for slot in case.slots:
            if slot.gold_slot_id in slots:
                raise ProtocolInputError("duplicate gold_slot_id")
            if slot.case_id != case.case_id or slot.hypothesis_id != case.hypothesis_id:
                raise ProtocolInputError("slot linkage mismatch")
            if not isinstance(slot.expected_stance, str) or slot.expected_stance not in STANCES:
                raise ProtocolInputError("invalid gold stance")
            source = sources.get(slot.source_record_id)
            if source is None:
                raise ProtocolInputError("unknown source record")
            if slot.source_text_identity != source.text_identity:
                raise ProtocolInputError("source identity mismatch")
            if (not isinstance(slot.start, int) or isinstance(slot.start, bool)
                    or not isinstance(slot.end, int) or isinstance(slot.end, bool)
                    or not 0 <= slot.start < slot.end <= len(source.text)):
                raise ProtocolInputError("invalid Unicode code-point span")
            if not isinstance(slot.freshness, str) or slot.freshness not in FRESHNESS:
                raise ProtocolInputError("invalid freshness label")
            _require_exact_bool(slot.relevance, "GoldSlot.relevance")
            _require_exact_bool(slot.admissibility, "GoldSlot.admissibility")
            span_key = (slot.source_record_id, slot.start, slot.end)
            previous = spans.get(span_key)
            if previous is not None and previous != slot.gold_slot_id:
                raise ProtocolInputError("shared source spans between gold slots are prohibited")
            spans[span_key] = slot.gold_slot_id
            slots[slot.gold_slot_id] = slot

    subspan_keys: set[tuple[str, str, int, int]] = set()
    for adjudication in dataset.subspan_adjudications:
        slot = slots.get(adjudication.gold_slot_id)
        source = sources.get(adjudication.source_record_id)
        if slot is None or source is None or slot.source_record_id != adjudication.source_record_id:
            raise ProtocolInputError("subspan adjudication must identify its gold slot and source")
        if (not isinstance(adjudication.start, int) or isinstance(adjudication.start, bool)
                or not isinstance(adjudication.end, int) or isinstance(adjudication.end, bool)
                or not 0 <= adjudication.start < adjudication.end <= len(source.text)):
            raise ProtocolInputError("invalid adjudicated emitted span")
        if not (slot.start <= adjudication.start and adjudication.end <= slot.end):
            raise ProtocolInputError("adjudicated subspan must lie within its gold span")
        if (adjudication.start, adjudication.end) == (slot.start, slot.end):
            raise ProtocolInputError("subspan exception must be a strict subspan")
        key = (adjudication.gold_slot_id, adjudication.source_record_id,
               adjudication.start, adjudication.end)
        if key in subspan_keys:
            raise ProtocolInputError("duplicate subspan adjudication")
        subspan_keys.add(key)

    repeated: dict[tuple[str, str], list[RepeatedOccurrenceAdjudication]] = {}
    for occurrence in dataset.repeated_occurrences:
        slot = slots.get(occurrence.gold_slot_id)
        source = sources.get(occurrence.source_record_id)
        if slot is None or source is None or slot.source_record_id != occurrence.source_record_id:
            raise ProtocolInputError("repeated occurrence must identify its gold slot and source")
        if not isinstance(occurrence.quote, str) or not occurrence.quote:
            raise ProtocolInputError("repeated occurrence quote must be non-empty")
        if (not isinstance(occurrence.start, int) or isinstance(occurrence.start, bool)
                or not isinstance(occurrence.end, int) or isinstance(occurrence.end, bool)
                or not 0 <= occurrence.start < occurrence.end <= len(source.text)):
            raise ProtocolInputError("invalid repeated occurrence span")
        if source.text[occurrence.start:occurrence.end] != occurrence.quote:
            raise ProtocolInputError("repeated occurrence quote does not equal frozen source span")
        repeated.setdefault((occurrence.source_record_id, occurrence.quote), []).append(occurrence)

    for (source_id, quote), entries in repeated.items():
        source = sources[source_id]
        expected = set(_all_occurrences(source.text, quote))
        actual = {(entry.start, entry.end) for entry in entries}
        target_slots = {entry.gold_slot_id for entry in entries}
        if len(actual) != len(entries) or actual != expected or len(target_slots) != 1:
            raise ProtocolInputError(
                "every repeated quote occurrence must be pre-adjudicated to the same gold slot"
            )


def _eligible_conflict_pairs(
    case: GoldCase, sources: Mapping[str, FrozenSource],
) -> tuple[tuple[GoldSlot, GoldSlot], ...]:
    supports = [slot for slot in case.slots if slot.expected_stance == "SUPPORTS"]
    contradicts = [slot for slot in case.slots if slot.expected_stance == "CONTRADICTS"]
    eligible_supports = [slot for slot in supports if slot.relevance is True
                         and slot.admissibility is True and slot.freshness == "FRESH"]
    eligible_contradicts = [slot for slot in contradicts if slot.relevance is True
                            and slot.admissibility is True and slot.freshness == "FRESH"]
    pairs: list[tuple[GoldSlot, GoldSlot]] = []
    for left in eligible_supports:
        left_source = sources[left.source_record_id]
        if (left_source.origin_confirmed is not True
                or type(left_source.source_origin_id) is not str
                or not left_source.source_origin_id.strip()):
            continue
        for right in eligible_contradicts:
            right_source = sources[right.source_record_id]
            if (right_source.origin_confirmed is True
                    and type(right_source.source_origin_id) is str
                    and right_source.source_origin_id.strip()
                    and left_source.source_origin_id != right_source.source_origin_id):
                pairs.append((left, right))
    return tuple(pairs)


def _prepare_item(item: EmittedEvidence, index: int, dataset: GoldDataset,
                  slots_by_source: Mapping[str, Sequence[GoldSlot]]) -> _PreparedItem:
    sources = {source.source_record_id: source for source in dataset.sources}
    structural = (
        isinstance(item.review_state, str) and item.review_state in REVIEW_STATES
        and isinstance(item.stance, str) and item.stance in STANCES
        and (item.review_state != "UNVERIFIED"
             or (isinstance(item.proposed_stance, str) and item.proposed_stance in STANCES))
    )
    effective = item.stance if item.review_state == "ACCEPTED" else item.proposed_stance
    source = sources.get(item.source_record_id) if isinstance(item.source_record_id, str) else None
    integrity = bool(source and isinstance(item.quote, str) and item.quote and item.quote in source.text)
    if not structural or not integrity:
        return _PreparedItem(item, index, structural, integrity, effective, item.review_state == "UNVERIFIED",
                             frozenset(), frozenset())

    positions = _all_occurrences(source.text, item.quote)
    repeated_lookup: dict[tuple[str, str, int, int], str] = {
        (entry.source_record_id, entry.quote, entry.start, entry.end): entry.gold_slot_id
        for entry in dataset.repeated_occurrences
    }
    subspan_lookup = {
        (entry.gold_slot_id, entry.source_record_id, entry.start, entry.end)
        for entry in dataset.subspan_adjudications
    }
    possible: set[str] = set()
    ambiguous: set[str] = set()
    for slot in slots_by_source.get(source.source_record_id, ()):
        exact_positions = [(start, end) for start, end in positions
                           if start == slot.start and end == slot.end]
        authorized_subspans = [(start, end) for start, end in positions
                               if (slot.gold_slot_id, source.source_record_id, start, end) in subspan_lookup]
        if exact_positions:
            if len(positions) == 1:
                possible.add(slot.gold_slot_id)
            else:
                all_same_slot = all(
                    repeated_lookup.get((source.source_record_id, item.quote, start, end)) == slot.gold_slot_id
                    for start, end in positions
                )
                if all_same_slot:
                    possible.add(slot.gold_slot_id)
                else:
                    ambiguous.add(slot.gold_slot_id)
        elif authorized_subspans:
            # The frozen subspan locator identifies the exact permitted span.
            # If the same quote has other occurrences, the explicit occurrence
            # rule must also resolve them to this slot.
            if len(positions) == 1 or all(
                repeated_lookup.get((source.source_record_id, item.quote, start, end)) == slot.gold_slot_id
                for start, end in positions
            ):
                possible.add(slot.gold_slot_id)
            else:
                ambiguous.add(slot.gold_slot_id)
        elif any(slot.start <= start and end <= slot.end for start, end in positions):
            # Strict subspans without frozen authorization are non-matches.
            continue
        elif any((start, end) == (slot.start, slot.end) for start, end in positions):
            ambiguous.add(slot.gold_slot_id)
    return _PreparedItem(item, index, structural, integrity, effective, item.review_state == "UNVERIFIED",
                         frozenset(possible), frozenset(ambiguous))


def _max_matchings(items: Sequence[_PreparedItem]) -> tuple[dict[int, str], ...]:
    """Enumerate maximum one-to-one assignments for one scheduled attempt."""
    usable = [item for item in items if item.structurally_valid and item.integrity_valid
              and _is_valid_output_id(item.raw.output_id)]
    usable.sort(key=lambda entry: entry.raw.output_id)
    best_size = -1
    assignments: list[dict[int, str]] = []

    def visit(position: int, used_slots: set[str], mapping: dict[int, str]) -> None:
        nonlocal best_size, assignments
        if position == len(usable):
            size = len(mapping)
            if size > best_size:
                best_size, assignments = size, [dict(mapping)]
            elif size == best_size:
                assignments.append(dict(mapping))
            return
        entry = usable[position]
        # Leaving a valid emission unmatched is allowed; it will be extra.
        visit(position + 1, used_slots, mapping)
        for slot_id in sorted(entry.possible_slots - used_slots):
            mapping[entry.original_index] = slot_id
            used_slots.add(slot_id)
            visit(position + 1, used_slots, mapping)
            used_slots.remove(slot_id)
            del mapping[entry.original_index]

    visit(0, set(), {})
    return tuple(assignments or ({},))


def _is_valid_output_id(output_id: Any) -> bool:
    """IDs are producer-supplied opaque non-empty strings up to 128 chars."""
    return type(output_id) is str and 0 < len(output_id) <= 128


def _output_id_violations(output_ids: Sequence[Any]) -> tuple[int, int, int]:
    """Return missing, duplicate-member, and malformed item counts safely."""
    missing = 0
    malformed = 0
    valid_ids: dict[str, int] = {}
    for output_id in output_ids:
        if output_id is None:
            missing += 1
        elif not _is_valid_output_id(output_id):
            malformed += 1
        else:
            valid_ids[output_id] = valid_ids.get(output_id, 0) + 1
    duplicate_members = sum(count for count in valid_ids.values() if count > 1)
    return missing, duplicate_members, malformed


def _attempt_error(attempt: ScheduledAttempt, items: Sequence[_PreparedItem]) -> bool:
    if attempt.error_kind is not None or not attempt.inventory_known:
        return True
    missing, duplicate_members, malformed = _output_id_violations(
        tuple(item.raw.output_id for item in items)
    )
    return missing > 0 or duplicate_members > 0 or malformed > 0


def _metric(name: str, unit: str, numerator: int | None, denominator: int | None,
            *, required: bool = False, threshold: float | int | None = None,
            minimum: int | None = None, inconclusive: bool = False, detail: str = "") -> MetricResult:
    if denominator == 0:
        return MetricResult(name, unit, numerator, denominator, None, "N/A", required,
                            threshold, minimum, detail or "zero denominator")
    rate = None if numerator is None or denominator is None else numerator / denominator
    if inconclusive or (required and minimum is not None and denominator < minimum):
        state = "INCONCLUSIVE"
    elif required:
        if threshold is None:
            raise ProtocolInputError(f"required metric {name} has no approved threshold")
        passed = numerator == threshold if name == "false_support" else (
            rate <= threshold if name == "provider_error_rate" else rate >= threshold
        )
        state = "PASS" if passed else "FAIL"
    else:
        state = "DIAGNOSTIC"
    return MetricResult(name, unit, numerator, denominator, rate, state, required,
                        threshold, minimum, detail)


def _assignments_for(attempt_items: Sequence[_PreparedItem], assignment: Mapping[int, str]) -> dict[str, list[_PreparedItem]]:
    matched: dict[str, list[_PreparedItem]] = {}
    for index, slot_id in assignment.items():
        item = next(item for item in attempt_items if item.original_index == index)
        matched.setdefault(slot_id, []).append(item)
    return matched


def _assignment_signature(case: GoldCase, attempt: ScheduledAttempt,
                          items: Sequence[_PreparedItem], assignment: Mapping[int, str],
                          eligible_conflict_pairs: Sequence[tuple[GoldSlot, GoldSlot]]) -> Mapping[str, int]:
    matches = _assignments_for(items, assignment)
    is_error = (_attempt_error(attempt, items)
                or not isinstance(attempt.status, str) or attempt.status not in STATUSES
                or any(not item.structurally_valid for item in items))
    false_support = recall_support = recall_contradict = false_neutral = unverified_slots = 0
    missing = 0
    for slot in case.slots:
        matched_items = matches.get(slot.gold_slot_id, []) if not is_error else []
        if not matched_items:
            missing += 1
        accepted = [entry for entry in matched_items if entry.raw.review_state == "ACCEPTED"]
        accepted_stances = {entry.raw.stance for entry in accepted}
        if (slot.expected_stance in {"NEUTRAL", "CONTRADICTS"}
                and "SUPPORTS" in accepted_stances):
            false_support += 1
        if slot.expected_stance == "SUPPORTS":
            if "SUPPORTS" in accepted_stances:
                recall_support += 1
        elif slot.expected_stance == "CONTRADICTS":
            if "CONTRADICTS" in accepted_stances:
                recall_contradict += 1
        if slot.expected_stance in DIRECTIONAL_STANCES and not is_error:
            has_direction = bool(accepted_stances & DIRECTIONAL_STANCES)
            has_neutral = "NEUTRAL" in accepted_stances
            has_unverified_direction = any(
                entry.unverified and entry.raw.proposed_stance in DIRECTIONAL_STANCES
                for entry in matched_items
            )
            if has_neutral or not has_direction or (has_unverified_direction and not has_direction):
                false_neutral += 1
        if (not is_error and not accepted and any(
                entry.unverified and entry.raw.proposed_stance in DIRECTIONAL_STANCES
                for entry in matched_items)):
            unverified_slots += 1

    valid_indices = {item.original_index for item in items if item.integrity_valid and item.structurally_valid}
    unmatched = len(valid_indices - set(assignment))
    conflict_preserved = 1
    if eligible_conflict_pairs:
        conflict_preserved = int(
            not is_error
            and attempt.status == "PARTIAL"
            and any(
                any(entry.raw.review_state == "ACCEPTED" and entry.raw.stance == "SUPPORTS"
                    for entry in matches.get(support.gold_slot_id, []))
                and any(entry.raw.review_state == "ACCEPTED" and entry.raw.stance == "CONTRADICTS"
                        for entry in matches.get(contradict.gold_slot_id, []))
                for support, contradict in eligible_conflict_pairs
            )
        )
    return {
        "false_support": false_support,
        "support_recall": recall_support,
        "contradiction_recall": recall_contradict,
        "false_neutral": false_neutral,
        "unverified_slot": unverified_slots,
        "missing_slot": missing,
        "extra_unmatched": unmatched,
        "conflict_preservation": conflict_preserved,
    }


def _validate_attempt_structure(attempt: ScheduledAttempt) -> tuple[EmittedEvidence, ...]:
    if not attempt.inventory_known:
        return ()
    if attempt.items is None:
        raise ProtocolInputError("known emitted-item inventory must be provided")
    if not isinstance(attempt.items, tuple):
        raise ProtocolInputError("emitted items must be a tuple in the immutable attempt record")
    if any(type(item) is not EmittedEvidence for item in attempt.items):
        raise ProtocolInputError("emitted inventory contains a non-evidence item")
    return attempt.items


def _result_metrics(results: Mapping[str, MetricResult], sample_minima: Mapping[str, tuple[int, int, bool]],
                    error_attempts: int, attempts: int) -> tuple[dict[str, MetricResult], str]:
    metrics = dict(results)
    unmet = any(not met for _, _, met in sample_minima.values())
    for key, metric in tuple(metrics.items()):
        if metric.required and metric.state == "FAIL" and metric.minimum is not None:
            if metric.denominator is not None and metric.denominator < metric.minimum:
                metrics[key] = MetricResult(metric.name, metric.unit, metric.numerator, metric.denominator,
                                            metric.rate, "INCONCLUSIVE", metric.required,
                                            metric.threshold, metric.minimum,
                                            "minimum denominator not met")
    if any(metric.required and metric.state == "FAIL" for metric in metrics.values()):
        return metrics, "FAIL"
    if unmet or any(metric.required and metric.state in {"INCONCLUSIVE", "N/A"}
                    for metric in metrics.values()):
        return metrics, "INCONCLUSIVE"
    return metrics, "PASS"


def evaluate_protocol(dataset: GoldDataset, attempts: Sequence[ScheduledAttempt]) -> EvaluationResult:
    """Validate and score one frozen in-memory cohort against protocol v1."""

    validate_gold_dataset(dataset)
    if (not isinstance(attempts, Sequence)
            or isinstance(attempts, (str, bytes, bytearray))):
        raise ProtocolInputError("attempts must be a sequence")
    if any(type(attempt) is not ScheduledAttempt for attempt in attempts):
        raise ProtocolInputError("attempts must contain ScheduledAttempt values")
    for attempt in attempts:
        _require_exact_text(attempt.case_id, "invalid ScheduledAttempt.case_id")
        _require_exact_bool(attempt.inventory_known, "ScheduledAttempt.inventory_known")
        if attempt.error_kind is not None and type(attempt.error_kind) is not str:
            raise ProtocolInputError("invalid ScheduledAttempt.error_kind")
    raw_items_by_attempt = tuple(_validate_attempt_structure(attempt) for attempt in attempts)
    eligible_cases = [case for case in dataset.cases if case.eligible]
    case_by_id = {case.case_id: case for case in eligible_cases}
    attempt_by_case: dict[str, ScheduledAttempt] = {}
    raw_items_by_case: dict[str, tuple[EmittedEvidence, ...]] = {}
    for attempt, raw_items in zip(attempts, raw_items_by_attempt):
        if attempt.case_id not in case_by_id:
            raise ProtocolInputError("attempt case_id is not eligible")
        if attempt.case_id in attempt_by_case:
            raise ProtocolInputError("duplicate scheduled attempt case_id")
        attempt_by_case[attempt.case_id] = attempt
        raw_items_by_case[attempt.case_id] = raw_items
    missing_cases = set(case_by_id) - set(attempt_by_case)
    if missing_cases:
        # No approved rule defines how an unscheduled/missing attempt is scored.
        raise ProtocolInputError("provide one explicit scheduled attempt record per eligible case")

    sources = {source.source_record_id: source for source in dataset.sources}
    slots = [slot for case in eligible_cases for slot in case.slots]
    slots_by_source: dict[str, list[GoldSlot]] = {}
    for slot in slots:
        slots_by_source.setdefault(slot.source_record_id, []).append(slot)

    prepared_by_case: dict[str, tuple[_PreparedItem, ...]] = {}
    errors_by_case: dict[str, bool] = {}
    provider_error_cases: set[str] = set()
    evaluation_error_cases: set[str] = set()
    missing_id_items = duplicate_id_items = malformed_id_items = 0
    integrity_total = integrity_valid = 0
    unknown_inventory = False
    for case_id, attempt in attempt_by_case.items():
        raw_items = raw_items_by_case[case_id]
        if not attempt.inventory_known:
            unknown_inventory = True
        if attempt.inventory_known:
            missing_for_attempt, duplicate_for_attempt, malformed_for_attempt = \
                _output_id_violations(tuple(item.output_id for item in raw_items))
            missing_id_items += missing_for_attempt
            duplicate_id_items += duplicate_for_attempt
            malformed_id_items += malformed_for_attempt
        else:
            missing_for_attempt = duplicate_for_attempt = malformed_for_attempt = 0
        prepared = tuple(_prepare_item(item, index, dataset, slots_by_source)
                         for index, item in enumerate(raw_items))
        # A parseable malformed structure is an evaluation error; invalid source
        # IDs and quotes alone remain integrity failures, not attempt errors.
        malformed = (any(not item.structurally_valid for item in prepared)
                     or (attempt.error_kind is None
                         and (not isinstance(attempt.status, str) or attempt.status not in STATUSES)))
        provider_error = attempt.error_kind in {"PROVIDER_ERROR", "TRANSPORT_ERROR"}
        evaluation_error = (
            malformed
            or missing_for_attempt > 0
            or duplicate_for_attempt > 0
            or malformed_for_attempt > 0
            or (not attempt.inventory_known and not provider_error)
            or (attempt.error_kind is not None and not provider_error)
        )
        attempt_error = provider_error or evaluation_error
        if provider_error:
            provider_error_cases.add(case_id)
        if evaluation_error:
            evaluation_error_cases.add(case_id)
        errors_by_case[case_id] = attempt_error
        prepared_by_case[case_id] = prepared
        if attempt.inventory_known:
            integrity_total += len(prepared)
            integrity_valid += sum(item.integrity_valid for item in prepared)

    error_attempts = sum(errors_by_case.values())
    all_slots = slots
    class_counts = {stance: sum(slot.expected_stance == stance for slot in all_slots) for stance in STANCES}
    non_support_count = sum(slot.expected_stance in {"NEUTRAL", "CONTRADICTS"} for slot in all_slots)
    conflict_pairs_by_case = {
        case.case_id: _eligible_conflict_pairs(case, sources)
        for case in eligible_cases
    }
    conflict_cases = [case for case in eligible_cases if conflict_pairs_by_case[case.case_id]]
    scenario_counts = {
        name: sum(name in case.scenario_tags for case in eligible_cases)
        for name in SCENARIO_MINIMA
    }
    scenario_counts["conflicts"] = len(conflict_cases)
    scenario_counts["insufficient_evidence"] = sum(
        case.expected_status == "INSUFFICIENT" for case in eligible_cases
    )
    sample_minima: dict[str, tuple[int, int, bool]] = {
        "independently_authored_heldout_cases": (
            sum(case.independently_authored for case in eligible_cases) if dataset.held_out else 0,
            60, dataset.held_out and sum(case.independently_authored for case in eligible_cases) >= 60,
        ),
        "support_slots": (class_counts["SUPPORTS"], 20, class_counts["SUPPORTS"] >= 20),
        "contradiction_slots": (class_counts["CONTRADICTS"], 20, class_counts["CONTRADICTS"] >= 20),
        "neutral_slots": (class_counts["NEUTRAL"], 20, class_counts["NEUTRAL"] >= 20),
        "non_support_slots": (non_support_count, 20, non_support_count >= 20),
        "conflict_cases": (scenario_counts["conflicts"], 10, scenario_counts["conflicts"] >= 10),
    }
    sample_minima.update({name: (scenario_counts[name], minimum, scenario_counts[name] >= minimum)
                          for name, minimum in SCENARIO_MINIMA.items()})

    # Per-case maximum matchings are enumerated to detect whether an unresolved
    # tie changes any numerator. Stable IDs order display/tie resolution only
    # after the metric signatures prove that a choice cannot affect correctness.
    signatures: dict[str, list[Mapping[str, int]]] = {}
    matched_by_case: dict[str, dict[str, list[_PreparedItem]]] = {}
    uncertain: set[str] = set()

    def record_signature_variation(case_signatures: Sequence[Mapping[str, int]]) -> None:
        metric_keys = set(case_signatures[0]) if case_signatures else set()
        metric_names = {
            "missing_slot": "missing_expected_slot_rate",
            "extra_unmatched": "extra_unmatched_output_rate",
            "unverified_slot": "unverified_slot_rate",
        }
        for key in metric_keys:
            if len({signature[key] for signature in case_signatures}) > 1:
                uncertain.add(metric_names.get(key, key))

    for case in eligible_cases:
        attempt = attempt_by_case[case.case_id]
        prepared = prepared_by_case[case.case_id]
        if errors_by_case[case.case_id]:
            assignments = ({},)
        else:
            assignments = _max_matchings(prepared)
        eligible_conflict_pairs = conflict_pairs_by_case[case.case_id]
        case_signatures = [
            _assignment_signature(case, attempt, prepared, assignment, eligible_conflict_pairs)
            for assignment in assignments
        ]
        signatures[case.case_id] = case_signatures
        matched_by_case[case.case_id] = _assignments_for(prepared, assignments[0])
        record_signature_variation(case_signatures)

        # Ambiguous locators are not eligible matches. For uncertainty analysis
        # only, consider each unresolved candidate edge and mark a metric
        # inconclusive only when those hypothetical assignments change its
        # numerator. These assignments are never used to produce metric scores.
        if any(item.ambiguous_slots for item in prepared) and not errors_by_case[case.case_id]:
            ambiguity_candidates = tuple(
                replace(item, possible_slots=item.possible_slots | item.ambiguous_slots)
                for item in prepared
            )
            possible_assignments = _max_matchings(ambiguity_candidates)
            possible_signatures = [
                _assignment_signature(case, attempt, ambiguity_candidates, assignment,
                                      eligible_conflict_pairs)
                for assignment in possible_assignments
            ]
            # Compare unresolved outcomes too: an ambiguous item may have no
            # uniquely valid match, so the actual (unmatched) assignments are
            # also possible metric outcomes until the locator is adjudicated.
            record_signature_variation([*case_signatures, *possible_signatures])

    def total_signature(key: str) -> int:
        return sum(signatures[case.case_id][0][key] for case in eligible_cases)

    support_den = class_counts["SUPPORTS"]
    contra_den = class_counts["CONTRADICTS"]
    directional_den = support_den + contra_den
    non_support_den = non_support_count
    metrics: dict[str, MetricResult] = {}
    metrics["false_support"] = _metric(
        "false_support", "gold_slot", total_signature("false_support"), non_support_den,
        required=True, threshold=0, minimum=20, inconclusive="false_support" in uncertain,
    )
    metrics["support_recall"] = _metric(
        "support_recall", "gold_slot", total_signature("support_recall"), support_den,
        required=True, threshold=0.80, minimum=20,
        inconclusive=support_den < 20 or "support_recall" in uncertain,
    )
    metrics["contradiction_recall"] = _metric(
        "contradiction_recall", "gold_slot", total_signature("contradiction_recall"), contra_den,
        required=True, threshold=0.80, minimum=20,
        inconclusive=contra_den < 20 or "contradiction_recall" in uncertain,
    )
    metrics["directional_coverage_support"] = _metric(
        "directional_coverage_support", "gold_slot", total_signature("support_recall"), support_den,
        required=True, threshold=0.70, minimum=20,
        inconclusive=support_den < 20 or "directional_coverage_support" in uncertain,
    )
    metrics["directional_coverage_contradiction"] = _metric(
        "directional_coverage_contradiction", "gold_slot", total_signature("contradiction_recall"), contra_den,
        required=True, threshold=0.70, minimum=20,
        inconclusive=contra_den < 20 or "directional_coverage_contradiction" in uncertain,
    )
    status_correct = sum(
        not errors_by_case[case.case_id]
        and attempt_by_case[case.case_id].status == case.expected_status
        for case in eligible_cases
    )
    status_den = len(eligible_cases)
    metrics["status_accuracy"] = _metric(
        "status_accuracy", "scheduled_attempt", status_correct, status_den,
        required=True, threshold=0.80, minimum=60,
        inconclusive=status_den < 60,
    )
    conflict_numerator = sum(
        signatures[case.case_id][0]["conflict_preservation"]
        for case in conflict_cases
    )
    metrics["conflict_preservation"] = _metric(
        "conflict_preservation", "case", conflict_numerator, len(conflict_cases),
        required=True, threshold=1.0, minimum=10,
        inconclusive=len(conflict_cases) < 10 or "conflict_preservation" in uncertain,
    )
    if unknown_inventory:
        metrics["emitted_evidence_integrity"] = MetricResult(
            "emitted_evidence_integrity", "emitted_item", integrity_valid, None, None,
            "INCONCLUSIVE", True, 1.0, None, "complete emitted-item inventory is unknown",
        )
    else:
        metrics["emitted_evidence_integrity"] = _metric(
            "emitted_evidence_integrity", "emitted_item", integrity_valid, integrity_total,
            required=True, threshold=1.0, inconclusive=False,
            detail="zero emitted items is N/A, not a pass" if integrity_total == 0 else "",
        )
    metrics["provider_error_rate"] = _metric(
        "provider_error_rate", "scheduled_attempt", error_attempts, status_den,
        required=True, threshold=0.05, minimum=60,
        inconclusive=status_den < 60,
    )

    # Diagnostic/report-only metrics. Error attempts remain in applicable case
    # denominators, but are never successful outcomes or false-neutral events.
    missing_slots = total_signature("missing_slot")
    metrics["missing_expected_slot_rate"] = _metric(
        "missing_expected_slot_rate", "gold_slot", missing_slots, len(all_slots),
        inconclusive="missing_expected_slot_rate" in uncertain,
    )
    valid_item_count = sum(item.integrity_valid and item.structurally_valid
                           for items in prepared_by_case.values() for item in items)
    extra_unmatched = total_signature("extra_unmatched")
    metrics["extra_unmatched_output_rate"] = _metric(
        "extra_unmatched_output_rate", "emitted_item", extra_unmatched, valid_item_count,
        inconclusive="extra_unmatched_output_rate" in uncertain or unknown_inventory,
    )
    insufficient_cases = [case for case in eligible_cases if case.expected_status == "INSUFFICIENT"]
    accepted_by_case: dict[str, set[str]] = {}
    unverified_by_case: dict[str, bool] = {}
    for case in eligible_cases:
        accepted_by_case[case.case_id] = {
            item.raw.stance for item in prepared_by_case[case.case_id]
            if item.structurally_valid and item.raw.review_state == "ACCEPTED"
        } if not errors_by_case[case.case_id] else set()
        unverified_by_case[case.case_id] = any(
            item.unverified and item.structurally_valid
            for item in prepared_by_case[case.case_id]
        ) and not errors_by_case[case.case_id]
    abstentions = sum(not accepted_by_case[case.case_id] and not errors_by_case[case.case_id]
                      for case in insufficient_cases)
    metrics["valid_abstention_rate"] = _metric(
        "valid_abstention_rate", "case", abstentions, len(insufficient_cases),
    )
    metrics["unverified_case_rate"] = _metric(
        "unverified_case_rate", "case", sum(unverified_by_case.values()), status_den,
    )
    metrics["unverified_slot_rate"] = _metric(
        "unverified_slot_rate", "gold_slot", total_signature("unverified_slot"), len(all_slots),
        inconclusive="unverified_slot_rate" in uncertain,
    )
    empty_outputs = sum(
        not errors_by_case[case.case_id]
        and not prepared_by_case[case.case_id]
        for case in eligible_cases
    )
    metrics["empty_output_rate"] = _metric(
        "empty_output_rate", "scheduled_attempt", empty_outputs, status_den,
    )
    neutral_only = sum(
        not errors_by_case[case.case_id]
        and "NEUTRAL" in accepted_by_case[case.case_id]
        and not (accepted_by_case[case.case_id] & DIRECTIONAL_STANCES)
        and accepted_by_case[case.case_id] <= {"NEUTRAL"}
        for case in eligible_cases
    )
    metrics["neutral_only_output_rate"] = _metric(
        "neutral_only_output_rate", "scheduled_attempt", neutral_only, status_den,
    )
    metrics["primary_false_neutral_rate"] = _metric(
        "primary_false_neutral_rate", "gold_slot", total_signature("false_neutral"),
        directional_den, inconclusive="false_neutral" in uncertain,
        detail="diagnostic/report-only; accepted opposite-direction stance is excluded",
    )

    metrics, verdict = _result_metrics(metrics, sample_minima, error_attempts, status_den)
    return EvaluationResult(
        metrics, sample_minima, missing_id_items, duplicate_id_items,
        error_attempts, status_den, verdict,
        malformed_id_items=malformed_id_items,
        provider_transport_error_attempts=len(provider_error_cases),
        evaluation_error_attempts=len(evaluation_error_cases),
    )


def score_contract_rejections(expected_codes: Sequence[str], observed_codes: Sequence[str]) -> MetricResult:
    """Score the four local rejection outcomes separately from semantic cases."""
    if (not isinstance(expected_codes, Sequence) or isinstance(expected_codes, (str, bytes, bytearray))
            or not isinstance(observed_codes, Sequence)
            or isinstance(observed_codes, (str, bytes, bytearray))):
        raise ProtocolInputError("contract rejection diagnostic requires the four local cases")
    if len(expected_codes) != 4 or len(observed_codes) != 4:
        raise ProtocolInputError("contract rejection diagnostic requires the four local cases")
    if any(type(code) is not str for code in (*expected_codes, *observed_codes)):
        raise ProtocolInputError("invalid contract rejection code")
    correct = sum(expected == observed for expected, observed in zip(expected_codes, observed_codes))
    return _metric("contract_rejection", "local_contract_case", correct, 4, detail="diagnostic only")


def score_reviewer_agreement(
    field_registry: Mapping[str, Sequence[str]],
    annotation_record_ids: Sequence[str],
    reviewer_one: Mapping[str, Mapping[str, str | None]],
    reviewer_two: Mapping[str, Mapping[str, str | None]],
    adjudicated: Mapping[str, Mapping[str, str | None]] | None = None,
) -> Mapping[str, Mapping[str, int | float | None | str]]:
    """Return per-field raw agreement and separate missing/unresolved counts."""
    if type(field_registry) is not dict or any(type(k) is not str for k in field_registry):
        raise ProtocolInputError("invalid reviewer field registry")
    if not isinstance(annotation_record_ids, Sequence) or isinstance(annotation_record_ids, (str, bytes, bytearray)):
        raise ProtocolInputError("invalid annotation record IDs")
    if any(type(record_id) is not str or not record_id for record_id in annotation_record_ids):
        raise ProtocolInputError("invalid annotation record IDs")
    adjudicated_records = {} if adjudicated is None else adjudicated
    for registry in (reviewer_one, reviewer_two, adjudicated_records):
        if type(registry) is not dict or any(type(key) is not str for key in registry):
            raise ProtocolInputError("invalid reviewer labels")
        for labels in registry.values():
            if type(labels) is not dict or any(type(key) is not str for key in labels):
                raise ProtocolInputError("invalid reviewer labels")
            if any(value is not None and type(value) is not str for value in labels.values()):
                raise ProtocolInputError("invalid reviewer labels")
    for permitted in field_registry.values():
        if not isinstance(permitted, Sequence) or isinstance(permitted, (str, bytes, bytearray)):
            raise ProtocolInputError("invalid reviewer field registry")
        if any(type(label) is not str for label in permitted):
            raise ProtocolInputError("invalid reviewer field registry")
    if not field_registry:
        raise ProtocolInputError("freeze a non-empty reviewer field registry")
    adjudicated = adjudicated or {}
    if len(set(annotation_record_ids)) != len(annotation_record_ids):
        raise ProtocolInputError("annotation record IDs must be unique")
    expected_records = set(annotation_record_ids)
    if not (set(reviewer_one) | set(reviewer_two) | set(adjudicated)) <= expected_records:
        raise ProtocolInputError("reviewer labels reference a record outside the frozen annotation set")
    results: dict[str, Mapping[str, int | float | None | str]] = {}
    for field_name, permitted in field_registry.items():
        allowed = set(permitted)
        if not allowed:
            raise ProtocolInputError("reviewer field has no permitted labels")
        units = expected_records
        both = agreements = missing = unresolved = adjudicated_count = 0
        for unit in units:
            left = reviewer_one.get(unit, {}).get(field_name)
            right = reviewer_two.get(unit, {}).get(field_name)
            final = adjudicated.get(unit, {}).get(field_name)
            if final is not None:
                adjudicated_count += 1
            if left is None or right is None:
                missing += 1
                continue
            if left not in allowed or right not in allowed:
                raise ProtocolInputError("reviewer label outside frozen registry")
            both += 1
            agreements += left == right
            unresolved += int(left == "UNRESOLVED" or right == "UNRESOLVED")
        results[field_name] = {
            "agreements": agreements,
            "denominator": both,
            "raw_agreement": agreements / both if both else None,
            "state": "DIAGNOSTIC" if both else "N/A",
            "missing_units": missing,
            "unresolved_units": unresolved,
            "adjudicated_units": adjudicated_count,
        }
    return results
