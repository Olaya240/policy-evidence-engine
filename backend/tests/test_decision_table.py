"""Executable counterpart of ct3/DecisionTable.v.

Every property the Coq file proves is re-checked here against the Python
implementation, over a finite grid, so a change to `decision_table.py` that
breaks a proved property fails CI rather than a proof that nobody re-runs.
"""

from datetime import datetime, timezone

import pytest

from app.decision_table import decide, decide_evidence, directional_groups, score
from app.models import Evidence, EvidenceReviewState, Stance, Status

NOW = datetime.now(timezone.utc)
GRID = range(0, 13)


def item(stance, group, *, stale=False, review_state=EvidenceReviewState.ACCEPTED,
         disputed=False, record_id=None):
    return Evidence(
        source_record_id=record_id or f"record-{group}",
        timestamp=NOW,
        quote="quoted source text",
        stance=stance,
        review_state=review_state,
        rationale="because",
        stale=stale,
        department="Front Office",
        source_group=group,
        disputed=disputed,
    )


# --------------------------------------------------------------------------
# The reported defects, re-run against v2
# --------------------------------------------------------------------------

def test_v2_inversion_is_fixed():
    """v1: 0.58 (contradicted) falls to 0.52 when a support is added."""
    assert score(1, 1) > score(0, 1)


def test_v2_collision_is_fixed():
    """v1: SUPPORTED and CONTRADICTED both read 0.68."""
    corroborated = decide(2, 0)
    refuted = decide(0, 2)
    assert corroborated.status is Status.SUPPORTED
    assert refuted.status is Status.CONTRADICTED
    assert corroborated.score > 0 > refuted.score
    assert corroborated.score != refuted.score


def test_v2_stale_support_does_not_demote():
    """v1: two independent supports plus one stale support drops to PARTIAL."""
    fresh = [item(Stance.SUPPORTS, "a"), item(Stance.SUPPORTS, "b")]
    assert decide_evidence(fresh).status is Status.SUPPORTED
    assert decide_evidence(fresh + [item(Stance.SUPPORTS, "c", stale=True)]) == \
        decide_evidence(fresh)


# --------------------------------------------------------------------------
# Proved properties, re-checked
# --------------------------------------------------------------------------

def test_labels_are_exclusive():
    for s in GRID:
        for c in GRID:
            supported = s >= 2 and s >= 3 * c + 1
            contradicted = c >= 3 * s + 1
            assert not (supported and contradicted)


def test_a_single_source_is_never_supported():
    for c in GRID:
        assert decide(1, c).status is not Status.SUPPORTED


def test_support_is_strictly_monotone():
    for s in GRID:
        for c in GRID:
            assert score(s + 1, c) > score(s, c)


def test_contradiction_is_strictly_monotone():
    for s in GRID:
        for c in GRID:
            assert score(s, c + 1) < score(s, c)


def test_sign_is_direction():
    for s in GRID:
        for c in GRID:
            value = score(s, c)
            assert (value > 0) == (s > c)
            assert (value == 0) == (s == c)
            assert (value < 0) == (s < c)


def test_score_stays_inside_the_open_unit_interval():
    for s in GRID:
        for c in GRID:
            assert -1 < score(s, c) < 1


def test_status_matches_the_thresholds():
    for s in GRID:
        for c in GRID:
            decision = decide(s, c)
            if s >= 2 and s >= 3 * c + 1:
                assert decision.status is Status.SUPPORTED
            elif c >= 3 * s + 1:
                assert decision.status is Status.CONTRADICTED
            elif s == 0 and c == 0:
                assert decision.status is Status.INSUFFICIENT
            else:
                assert decision.status is Status.PARTIAL


def test_contested_flag_prices_conflict():
    for s in GRID:
        for c in GRID:
            assert decide(s, c).contested == (s > 0 and c > 0)


def test_confidence_is_the_magnitude_of_the_signed_score():
    for s in GRID:
        for c in GRID:
            decision = decide(s, c)
            assert decision.confidence == pytest.approx(abs(decision.score))
            assert 0 <= decision.confidence < 1


# --------------------------------------------------------------------------
# Counting: what reaches the arithmetic
# --------------------------------------------------------------------------

def test_stale_unverified_and_disputed_records_cannot_move_the_counts():
    base = [item(Stance.SUPPORTS, "a"), item(Stance.CONTRADICTS, "b")]
    support, contradiction = directional_groups(base)
    extra = [
        item(Stance.SUPPORTS, "a2", stale=True),
        item(Stance.CONTRADICTS, "b2", stale=True),
        item(Stance.SUPPORTS, "a3", review_state=EvidenceReviewState.UNVERIFIED),
        item(Stance.CONTRADICTS, "b3", review_state=EvidenceReviewState.UNVERIFIED),
        item(Stance.SUPPORTS, "a4", disputed=True),
        item(Stance.NEUTRAL, "n1"),
    ]
    assert directional_groups(base + extra) == (support, contradiction)


def test_review_state_filter_is_the_only_source_of_trust():
    evidence = [item(Stance.SUPPORTS, "a", review_state=EvidenceReviewState.UNVERIFIED)]
    assert decide_evidence(evidence).status is Status.INSUFFICIENT


def test_records_sharing_a_group_are_one_unit():
    evidence = [item(Stance.SUPPORTS, "a", record_id="r1"),
                item(Stance.SUPPORTS, "a", record_id="r2")]
    assert decide_evidence(evidence).support_groups == 1


def test_record_order_cannot_change_the_result():
    evidence = [item(Stance.SUPPORTS, "a"), item(Stance.CONTRADICTS, "b"),
                item(Stance.SUPPORTS, "c")]
    reference = decide_evidence(evidence)
    assert decide_evidence(list(reversed(evidence))) == reference
    assert decide_evidence(evidence[1:] + evidence[:1]) == reference


def test_empty_evidence_is_insufficient_with_zero_mass():
    decision = decide(0, 0)
    assert decision.status is Status.INSUFFICIENT
    assert decision.score == 0
    assert decision.directional_evidence_mass == 0
    assert not decision.contested


def test_balanced_contest_is_distinguishable_from_no_evidence():
    """Same score, different mass: the pair is injective where the number is not."""
    nothing = decide(0, 0)
    balanced = decide(2, 2)
    assert nothing.score == balanced.score == 0
    assert nothing.directional_evidence_mass != balanced.directional_evidence_mass
    assert balanced.contested and not nothing.contested
    assert balanced.status is Status.PARTIAL


# --------------------------------------------------------------------------
# The magnitude field is not the fix on its own, and must not pretend to be
# --------------------------------------------------------------------------

def test_confidence_alone_still_collides_so_direction_must_travel_with_it():
    """`confidence` is |score|, kept for the shipped Claim field. A single source
    for and a single source against are both 0.5 — the pair separates them, the
    magnitude does not. This test exists so that no caller can claim otherwise."""
    for_group = decide(1, 0)
    against = decide(0, 1)
    assert for_group.confidence == against.confidence == 0.5
    assert for_group.direction != against.direction
    assert for_group.status is not against.status
    assert for_group.score != against.score


def test_direction_tracks_the_sign():
    assert decide(2, 0).direction == "FOR"
    assert decide(0, 2).direction == "AGAINST"
    assert decide(1, 1).direction == "NONE"
    assert decide(0, 0).direction == "NONE"


# --------------------------------------------------------------------------
# A challenge must not disappear into "insufficient"
# --------------------------------------------------------------------------

def test_disputed_evidence_reads_contested_not_insufficient():
    """v1 had a dedicated PARTIAL arm for accepted-but-disputed evidence.
    Excluding disputed records from the counts must not also erase the dispute."""
    evidence = [item(Stance.SUPPORTS, "a", disputed=True)]
    decision = decide_evidence(evidence)
    assert decision.status is Status.PARTIAL
    assert decision.disputed_groups == 1
    assert decision.contested
    assert decision.status_rule_id == "STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT"


def test_undisputed_single_source_is_still_partial():
    decision = decide_evidence([item(Stance.SUPPORTS, "a")])
    assert decision.status is Status.PARTIAL
    assert decision.disputed_groups == 0
    assert not decision.contested


def test_stale_dispute_is_not_counted():
    decision = decide_evidence([item(Stance.SUPPORTS, "a", disputed=True, stale=True)])
    assert decision.status is Status.INSUFFICIENT
    assert decision.disputed_groups == 0
