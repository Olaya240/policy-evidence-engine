"""Small deterministic, in-memory fixtures for protocol v1 tests."""

from __future__ import annotations

from .protocol_v1 import (
    EmittedEvidence,
    FrozenSource,
    GoldCase,
    GoldDataset,
    GoldSlot,
    ScheduledAttempt,
)


def single_slot_dataset(
    *,
    text: str = "The checklist was available.",
    quote: str | None = None,
    stance: str = "SUPPORTS",
    status: str = "SUPPORTED",
    case_id: str = "case-1",
    source_id: str = "source-1",
    text_identity: str = "source-1-v1",
    start: int | None = None,
    end: int | None = None,
    freshness: str = "FRESH",
    relevance: bool = True,
    admissibility: bool = True,
    origin_id: str = "origin-1",
    origin_confirmed: bool = True,
    held_out: bool = False,
    subspan_adjudications=(),
    repeated_occurrences=(),
) -> GoldDataset:
    """Build one frozen gold slot, using code-point offsets into ``text``."""
    if quote is None:
        quote = text
    if start is None:
        start = text.find(quote)
    if end is None:
        end = start + len(quote)
    source = FrozenSource(source_id, text, text_identity, origin_id, origin_confirmed)
    slot = GoldSlot(
        "slot-1", case_id, "hypothesis-1", stance, source_id,
        text_identity, start, end, relevance, admissibility, freshness,
    )
    case = GoldCase(case_id, "hypothesis-1", status, (slot,))
    return GoldDataset("fixture-v1", (source,), (case,), held_out,
                       tuple(subspan_adjudications), tuple(repeated_occurrences))


def single_attempt(
    *,
    items: tuple[EmittedEvidence, ...] | None = None,
    status: str | None = "SUPPORTED",
    case_id: str = "case-1",
    inventory_known: bool = True,
    error_kind: str | None = None,
) -> ScheduledAttempt:
    if items is None and inventory_known:
        items = (EmittedEvidence("output-1", "source-1", "The checklist was available.", "SUPPORTS"),)
    return ScheduledAttempt(case_id, status, items, inventory_known, error_kind)


def minimum_heldout_cohort() -> tuple[GoldDataset, tuple[ScheduledAttempt, ...]]:
    """Create an entirely synthetic cohort meeting every approved minimum."""
    sources: list[FrozenSource] = []
    cases: list[GoldCase] = []
    attempts: list[ScheduledAttempt] = []

    def add_slot(case_id: str, index: int, stance: str, source_suffix: str,
                 origin: str, *, freshness: str = "FRESH") -> GoldSlot:
        source_id = f"source-{case_id}-{source_suffix}"
        text = f"Synthetic evidence {case_id} {source_suffix}."
        identity = f"identity-{case_id}-{source_suffix}-v1"
        sources.append(FrozenSource(source_id, text, identity, origin, True))
        return GoldSlot(
            f"slot-{case_id}-{source_suffix}", case_id, "hypothesis-1", stance,
            source_id, identity, 0, len(text), True, True, freshness,
        )

    for index in range(60):
        case_id = f"heldout-{index:02d}"
        tags: set[str] = set()
        slots: list[GoldSlot] = []
        if index < 10:
            status = "PARTIAL"
            support = add_slot(case_id, index, "SUPPORTS", "support", f"origin-{index}-a")
            contra = add_slot(case_id, index, "CONTRADICTS", "contra", f"origin-{index}-b")
            slots.extend((support, contra))
        elif index < 20:
            status = "SUPPORTED"
            freshness = "STALE" if index < 20 else "FRESH"
            tags.add("stale")
            slots.append(add_slot(case_id, index, "SUPPORTS", "only", f"origin-{index}", freshness=freshness))
        elif index < 30:
            status = "CONTRADICTED"
            tags.add("unknown_freshness")
            slots.append(add_slot(case_id, index, "CONTRADICTS", "only", f"origin-{index}", freshness="UNKNOWN"))
        else:
            status = "INSUFFICIENT"
            neutral_origin = "shared-origin-30s" if 30 <= index < 40 else f"origin-{index}"
            slots.append(add_slot(case_id, index, "NEUTRAL", "only", neutral_origin))
            tags.add("insufficient_evidence")
            if index < 40:
                tags.update({"ambiguity_unresolved", "shared_lineage"})
                slots.append(add_slot(case_id, index, "NEUTRAL", "related", neutral_origin))
            if 40 <= index < 50:
                tags.add("independent_sources")
                slots.append(add_slot(case_id, index, "NEUTRAL", "independent", f"origin-independent-{index}"))
        case = GoldCase(case_id, "hypothesis-1", status, tuple(slots), True, True, frozenset(tags))
        cases.append(case)
        emitted = tuple(
            EmittedEvidence(
                f"output-{case_id}-{slot.gold_slot_id}",
                slot.source_record_id,
                next(source.text for source in sources if source.source_record_id == slot.source_record_id),
                slot.expected_stance,
            )
            for slot in slots
        )
        attempts.append(ScheduledAttempt(case_id, status, emitted))

    return GoldDataset("synthetic-test-cohort-v1", tuple(sources), tuple(cases), True), tuple(attempts)

