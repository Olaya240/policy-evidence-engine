"""Slice-6 contracts: validation-time staleness, the injected clock, and the
empty-evidence decision shape.

The behaviours pinned here are the ones a reader would otherwise have to infer
from a `>` versus `>=` or from the presence of a keyword argument.
"""

from datetime import datetime, timedelta, timezone

from app.engine import (
    STALE_DAYS,
    AssessmentEngine,
    _summarize_status_decision,
    _validate_assessment_with_time,
)
from app.models import Evidence, Record, Stance, Status

FIXED = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def record(rid="T1", text="Checklist binder was unavailable during handover.", days=1, department="Front Office"):
    return Record(
        id=rid,
        timestamp=FIXED - timedelta(days=days),
        department=department,
        text=text,
        tags=[],
    )


def proposal(rid="T1", quote="binder", stance="SUPPORTS", rationale="because"):
    return {"source_record_id": rid, "quote": quote, "stance": stance, "rationale": rationale}


def validate(raw, records, now):
    evidence, evaluated_at = _validate_assessment_with_time(raw, records, now=now)
    return evidence, evaluated_at


# --------------------------------------------------------------------------
# 1. The injected clock is the one used for staleness
# --------------------------------------------------------------------------

def test_an_injected_clock_decides_staleness_not_the_wall_clock():
    records = {"T1": record(days=STALE_DAYS + 10)}

    old = validate(proposal(), records, FIXED)[0]
    fresh = validate(proposal(), records, FIXED - timedelta(days=STALE_DAYS + 5))[0]

    # Same record, same proposal: only the clock differs, and the verdict flips.
    assert old.stale is True
    assert fresh.stale is False


def test_the_injected_clock_is_returned_as_the_evaluation_time():
    records = {"T1": record(days=1)}
    _evidence, evaluated_at = validate(proposal(), records, FIXED)
    assert evaluated_at == FIXED


# --------------------------------------------------------------------------
# 2. A record dated after the evaluation instant is never current proof
# --------------------------------------------------------------------------

def test_a_future_dated_record_is_not_current_evidence():
    """`age > STALE_DAYS` alone would leave this record fresh forever."""
    records = {"T1": record(days=-5)}  # five days after FIXED
    evidence, _ = validate(proposal(), records, FIXED)
    assert evidence.stale is True


def test_a_naive_record_timestamp_is_read_as_utc_not_rejected():
    """store.py passes stored text through, so an offset-less row is reachable."""
    naive = Record(
        id="T1",
        timestamp=FIXED.replace(tzinfo=None) - timedelta(days=1),
        department="Front Office",
        text="Checklist binder was unavailable during handover.",
        tags=[],
    )
    evidence, _ = validate(proposal(), {"T1": naive}, FIXED)
    assert evidence.stale is False
    assert evidence.timestamp.tzinfo is not None


# --------------------------------------------------------------------------
# 3. The threshold is exclusive, and truncated to whole days
# --------------------------------------------------------------------------

def test_exactly_at_the_threshold_is_not_stale_and_one_day_over_is():
    assert STALE_DAYS > 0

    at = validate(proposal(), {"T1": record(days=STALE_DAYS)}, FIXED)[0]
    over = validate(proposal(), {"T1": record(days=STALE_DAYS + 1)}, FIXED)[0]

    # `stale=age > STALE_DAYS`, so the boundary day itself is still current.
    assert at.stale is False
    assert over.stale is True


def test_partial_days_are_truncated_before_the_comparison():
    """`timedelta.days` floors, so 90 days and 23 hours reads as 90 — still current."""
    records = {"T1": record(days=STALE_DAYS)}
    almost = _validate_assessment_with_time(
        proposal(), records, now=FIXED + timedelta(hours=23)
    )[0]
    assert almost.stale is False

    full = _validate_assessment_with_time(
        proposal(), records, now=FIXED + timedelta(days=1)
    )[0]
    assert full.stale is True


# --------------------------------------------------------------------------
# 4. The empty-evidence decision is total, not degenerate
# --------------------------------------------------------------------------

def test_empty_evidence_produces_a_coherent_decision():
    decision = _summarize_status_decision([])

    assert decision.status is Status.INSUFFICIENT
    assert decision.confidence == 0
    assert decision.evidence_score == 0
    assert decision.contested is False
    assert decision.status_rule_id == "STATUS.V2_NO_DIRECTIONAL_EVIDENCE"
    assert decision.confidence_rule_id == "CONFIDENCE.V2_ZERO_MARGIN"
    assert decision.uncertainty  # a reader is told why, not left with a blank
    for bucket in (
        decision.supports,
        decision.contradicts,
        decision.neutrals,
        decision.stale_support,
        decision.stale_contradictions,
        decision.stale_accepted,
        decision.disputed,
        decision.unverified,
        decision.independent_groups,
        decision.dependent_support_ids,
        decision.conflicts,
    ):
        assert bucket == []


# --------------------------------------------------------------------------
# 5. Clock defaults and per-instance injection
# --------------------------------------------------------------------------

def test_the_default_clock_is_wall_clock():
    engine = AssessmentEngine()
    now = engine.clock()
    assert now.tzinfo is not None
    # A 2026-01-01 constant is in the past, so a wall clock must be after it.
    assert now > FIXED


def test_two_engines_with_fixed_clocks_report_their_own_clock():
    """The contrast case for the default: with an injected clock the value is
    exactly what was supplied, so two engines are independent."""
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second = datetime(2026, 2, 1, tzinfo=timezone.utc)

    assert AssessmentEngine(clock=lambda: first).clock() == first
    assert AssessmentEngine(clock=lambda: second).clock() == second
    assert first != second


# --------------------------------------------------------------------------
# 6. A group counted once, even when it holds a challenged and a clean record
# --------------------------------------------------------------------------

def item(source_group, *, stance=Stance.SUPPORTS, disputed=False):
    return Evidence(
        source_record_id=source_group.lower(),
        timestamp=FIXED,
        quote="binder",
        stance=stance,
        rationale="because",
        department="Front Office",
        source_group=source_group,
        disputed=disputed,
    )


def test_a_group_with_a_challenged_and_a_clean_record_is_one_source():
    from app.decision_table import decide_evidence

    decision = decide_evidence([item("G1"), item("G1", disputed=True)])

    # G1 is already counted as an undisputed support. Adding it again would
    # present one source as two, reach 2:0, and mark the challenge decision
    # relevant — a PARTIAL that no real configuration of this evidence explains.
    assert decision.support_groups == 1
    assert decision.disputed_groups == 1
    assert decision.score == 0.5
    assert decision.status_rule_id != "STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT"


def test_a_disputed_group_that_is_genuinely_additional_is_still_decision_relevant():
    """The positive control for the line above."""
    from app.decision_table import decide_evidence

    decision = decide_evidence([item("G1"), item("G2", disputed=True)])

    # Undisputed 1:0 is PARTIAL; as-if 2:0 is SUPPORTED, so the challenge could
    # flip the verdict and the claim must read PARTIAL.
    assert decision.status_rule_id == "STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT"
