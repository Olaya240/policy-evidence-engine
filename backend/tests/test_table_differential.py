"""Differential check of `app.decision_table` against an independent derivation.

The point of this file is *not* to restate the module. The reference below is
written from the prose rule only, in a different shape: the module branches on
integer thresholds (`s >= 3c + 1`), the reference cross-multiplies the score
comparison (`2(s - c) >= s + c + 1`). Those two forms should agree everywhere,
and if they ever stop agreeing the Coq proof in `ct3/DecisionTable.v` no longer
describes the code.

One deliberate asymmetry is pinned rather than smoothed over: the cross-multiplied
threshold alone would call a single supporting group SUPPORTED at (1, 0), because
2(1-0) >= 1+0+1 holds with equality. The shipped rule adds a corroboration guard,
so the reference carries that guard explicitly and `test_the_guard_is_load_bearing`
records what it buys.
"""

import math

import pytest

from app.decision_table import (
    IMBALANCE_PER_GROUP,
    MIN_SUPPORT_GROUPS,
    decide,
    score,
)
from app.models import Status

GRID = range(0, 15)


# ---------------------------------------------------------------------------
# Independent reference: cross-multiplied, guard made explicit
# ---------------------------------------------------------------------------

def reference_label(s: int, c: int) -> Status:
    """`score >= 1/2` cross-multiplied, plus the corroboration guard.

    Denominator (s + c + 1) is positive for non-negative counts, so multiplying
    through preserves the order: (s - c)/(s + c + 1) >= 1/2  <=>  2(s - c) >= s + c + 1.
    """
    if s >= MIN_SUPPORT_GROUPS and 2 * (s - c) >= s + c + 1:
        return Status.SUPPORTED
    if 2 * (c - s) >= s + c + 1:
        return Status.CONTRADICTED
    if s == 0 and c == 0:
        return Status.INSUFFICIENT
    return Status.PARTIAL


def reference_score(s: int, c: int) -> float:
    return (s - c) / (s + c + 1)


def reference_direction(s: int, c: int) -> str:
    if s > c:
        return "FOR"
    if c > s:
        return "AGAINST"
    return "NONE"


def reference_after_dispute(s: int, c: int, ds: int, dc: int) -> Status:
    base = reference_label(s, c)
    if ds + dc == 0:
        return base
    if reference_label(s + ds, c + dc) is not base:
        return Status.PARTIAL
    return base


# ---------------------------------------------------------------------------
# 1. The two implementations agree on the whole grid
# ---------------------------------------------------------------------------

def test_status_agrees_with_the_independent_derivation():
    disagreements = [
        (s, c, reference_label(s, c), decide(s, c).status)
        for s in GRID for c in GRID
        if reference_label(s, c) is not decide(s, c).status
    ]
    assert disagreements == []


def test_score_agrees_with_the_independent_derivation():
    for s in GRID:
        for c in GRID:
            assert score(s, c) == pytest.approx(reference_score(s, c), rel=1e-12, abs=1e-12)


def test_direction_agrees_with_the_independent_derivation():
    for s in GRID:
        for c in GRID:
            assert decide(s, c).direction == reference_direction(s, c)


def test_confidence_is_the_magnitude_of_the_signed_score():
    for s in GRID:
        for c in GRID:
            decision = decide(s, c)
            assert decision.confidence == pytest.approx(abs(reference_score(s, c)), abs=1e-12)
            assert decision.confidence >= 0


# ---------------------------------------------------------------------------
# 2. The cross-multiplied identity the Coq proof turns on
# ---------------------------------------------------------------------------

def test_supported_is_exactly_the_cross_multiplied_threshold_plus_the_guard():
    for s in GRID:
        for c in GRID:
            threshold_holds = 2 * (s - c) >= s + c + 1
            expected = threshold_holds and s >= MIN_SUPPORT_GROUPS
            assert (decide(s, c).status is Status.SUPPORTED) == expected, (s, c)


def test_contradicted_is_exactly_the_cross_multiplied_threshold():
    for s in GRID:
        for c in GRID:
            expected = 2 * (c - s) >= s + c + 1
            assert (decide(s, c).status is Status.CONTRADICTED) == expected, (s, c)


def test_the_integer_thresholds_are_the_cross_multiplication_solved():
    """`s >= 3c + 1` and `2(s-c) >= s+c+1` are the same predicate; this pins the
    algebra the module's comments claim."""
    for s in GRID:
        for c in GRID:
            assert (s >= 3 * c + 1) == (2 * (s - c) >= s + c + 1)
            assert (c >= 3 * s + 1) == (2 * (c - s) >= s + c + 1)


def test_the_guard_is_load_bearing():
    """Without the corroboration guard the pure threshold would call a single
    supporting group SUPPORTED, because the inequality holds with equality at
    (1, 0). This is the one place the two forms are not interchangeable."""
    assert 2 * (1 - 0) >= 1 + 0 + 1          # the bare threshold fires
    assert decide(1, 0).status is Status.PARTIAL  # the guard stops it
    assert decide(1, 0).score == 0.5


# ---------------------------------------------------------------------------
# 3. Dispute handling, enumerated
# ---------------------------------------------------------------------------

def test_dispute_downgrade_matches_decision_relevance():
    for s in range(0, 5):
        for c in range(0, 5):
            for ds in range(0, 3):
                for dc in range(0, 3):
                    decision = decide(
                        s, c, disputed_support=ds, disputed_contradiction=dc
                    )
                    assert decision.status is reference_after_dispute(s, c, ds, dc), (
                        s, c, ds, dc
                    )


def test_a_dispute_that_cannot_change_the_label_does_not_demote():
    """Five corroborating groups with one challenge still reads SUPPORTED."""
    decision = decide(5, 0, disputed_support=1)
    assert decision.status is Status.SUPPORTED
    assert decision.disputed_groups == 1
    assert decision.contested is True


def test_a_dispute_that_can_change_the_label_demotes():
    """One support and nothing else: counting the challenged record flips
    INSUFFICIENT to PARTIAL, so the label must not stay INSUFFICIENT."""
    decision = decide(0, 0, disputed_support=1)
    assert decision.status is Status.PARTIAL
    assert decision.status_rule_id == "STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT"


def test_dispute_count_is_the_sum_of_both_directions():
    decision = decide(2, 0, disputed_support=2, disputed_contradiction=1)
    assert decision.disputed_groups == 3


# ---------------------------------------------------------------------------
# 4. The named constants are the rule, not decoration
# ---------------------------------------------------------------------------

def test_constants_match_the_documented_rule():
    assert MIN_SUPPORT_GROUPS == 2
    assert IMBALANCE_PER_GROUP == 3


def test_the_imbalance_constant_actually_moves_a_row():
    """(4, 1) is SUPPORTED at 3-per-group and would not be at 4-per-group; if the
    constant were unused this assertion could not distinguish them."""
    assert decide(4, 1).status is Status.SUPPORTED
    assert not (4 >= 4 * 1 + 1)          # the same row under a 4-per-group rule
    assert decide(5, 1).status is Status.SUPPORTED  # and under the shipped rule


def test_the_score_never_leaves_the_open_unit_interval():
    for s in GRID:
        for c in GRID:
            value = score(s, c)
            assert -1 < value < 1
            assert not math.isnan(value)


def test_negative_counts_are_rejected():
    with pytest.raises(ValueError):
        score(-1, 0)


# ---------------------------------------------------------------------------
# 5. The policy surface: the default is the proved rule, and the alternatives
#    differ exactly where their names say they do
# ---------------------------------------------------------------------------

def test_the_default_is_the_proved_policy():
    """`ct3/DecisionTable.v` models POLICY_SIGNED_MARGIN only, so the default
    must be that object and must report its id."""
    from app.decision_table import POLICY_SIGNED_MARGIN

    assert POLICY_SIGNED_MARGIN.policy_id == "SIGNED_MARGIN_3_TO_1"
    assert POLICY_SIGNED_MARGIN.min_support_groups == MIN_SUPPORT_GROUPS
    assert POLICY_SIGNED_MARGIN.imbalance_per_group == IMBALANCE_PER_GROUP
    assert POLICY_SIGNED_MARGIN.contest_blocks_decisive is False
    for s in GRID:
        for c in GRID:
            assert decide(s, c) == decide(s, c, policy=POLICY_SIGNED_MARGIN)
            assert decide(s, c).policy_id == "SIGNED_MARGIN_3_TO_1"


def test_contest_blocks_policy_demotes_every_contested_shape():
    from app.decision_table import POLICY_CONTEST_BLOCKS

    for s in range(1, 6):
        for c in range(1, 6):
            assert decide(s, c, policy=POLICY_CONTEST_BLOCKS).status is Status.PARTIAL
    # and leaves one-sided shapes exactly as the default does
    assert decide(2, 0, policy=POLICY_CONTEST_BLOCKS).status is Status.SUPPORTED
    assert decide(0, 2, policy=POLICY_CONTEST_BLOCKS).status is Status.CONTRADICTED


def test_two_to_one_policy_makes_a_single_source_decisive():
    from app.decision_table import POLICY_TWO_TO_ONE

    assert decide(1, 0, policy=POLICY_TWO_TO_ONE).status is Status.SUPPORTED
    assert decide(0, 1, policy=POLICY_TWO_TO_ONE).status is Status.CONTRADICTED
    # two against one is a tie under this rule, not a win
    assert decide(2, 1, policy=POLICY_TWO_TO_ONE).status is Status.PARTIAL
    assert decide(3, 1, policy=POLICY_TWO_TO_ONE).status is Status.SUPPORTED
    # the default still refuses a single source
    assert decide(1, 0).status is Status.PARTIAL


def test_policy_choice_cannot_move_the_score():
    """The score is a property of the counts, not of the policy: only the label
    may move. If this ever fails, the two concepts have been conflated."""
    from app.decision_table import POLICY_CONTEST_BLOCKS, POLICY_TWO_TO_ONE

    for s in GRID:
        for c in GRID:
            base = score(s, c)
            for policy in (POLICY_CONTEST_BLOCKS, POLICY_TWO_TO_ONE):
                assert decide(s, c, policy=policy).score == base
