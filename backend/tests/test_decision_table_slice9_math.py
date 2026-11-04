"""Slice 9 arithmetic pins for `app.decision_table`.

These are the properties a reader of the formula relies on without re-deriving
it: the score mirrors under exchange, the empty row is exactly zero, one more
support group never costs anything, and each label starts at the first integer
that satisfies its threshold. They are stated over the default policy only,
because that is the one proved in `ct3/DecisionTable.v`.
"""

import pytest

from app.decision_table import (
    IMBALANCE_PER_GROUP,
    MIN_SUPPORT_GROUPS,
    POLICY_SIGNED_MARGIN,
    decide,
    score,
)
from app.models import Status

GRID = range(0, 21)


# ---------------------------------------------------------------------------
# 1. Exchange mirrors the score
# ---------------------------------------------------------------------------

def test_score_is_antisymmetric_under_exchange():
    """`score(s, c) == -score(c, s)`: swapping the directions flips the sign and
    keeps the magnitude, so the pair carries direction without extra state."""
    for s in GRID:
        for c in GRID:
            assert score(s, c) == -score(c, s), (s, c)
            assert abs(score(s, c)) == abs(score(c, s)), (s, c)


def test_antisymmetry_is_exact_not_approximate():
    """The two sides share one denominator, so the identity holds bit-for-bit;
    an `approx` here would hide a rounding change in the formula."""
    for s in GRID:
        for c in GRID:
            assert (score(s, c) + score(c, s)) == 0.0, (s, c)


def test_the_guard_is_the_only_asymmetry_between_the_labels():
    """The score and both thresholds are symmetric under exchange; only
    SUPPORTED carries `min_support_groups`. That single asymmetry is why (1, 0)
    reads PARTIAL while its mirror (0, 1) reads CONTRADICTED."""
    for s in GRID:
        for c in GRID:
            assert decide(s, c).score == -decide(c, s).score, (s, c)
    assert decide(1, 0).status is Status.PARTIAL
    assert decide(0, 1).status is Status.CONTRADICTED
    assert decide(MIN_SUPPORT_GROUPS, 0).status is Status.SUPPORTED
    assert decide(0, MIN_SUPPORT_GROUPS).status is Status.CONTRADICTED


# ---------------------------------------------------------------------------
# 2. The diagonal is the zero of the score
# ---------------------------------------------------------------------------

def test_balanced_counts_score_exactly_zero():
    """`score(s, s) == 0`: a tie contributes no signed strength, whatever its
    mass. Signed zero would also satisfy `== 0` but must not appear, because
    `copysign`-based callers read the sign of a zero as a direction."""
    for s in GRID:
        assert score(s, s) == 0, s
        assert str(score(s, s)) == "0.0", s


# ---------------------------------------------------------------------------
# 3. The empty row
# ---------------------------------------------------------------------------

def test_empty_row_is_zero_mass_and_zero_confidence():
    decision = decide(0, 0)
    assert score(0, 0) == 0
    assert decision.status is Status.INSUFFICIENT
    assert decision.score == 0
    assert decision.confidence == 0
    assert decision.direction == "NONE"
    assert decision.directional_evidence_mass == 0
    assert decision.contested is False


# ---------------------------------------------------------------------------
# 4. One more support group never lowers the score
# ---------------------------------------------------------------------------

def test_adding_a_support_group_never_lowers_the_score():
    for s in GRID:
        for c in GRID:
            assert score(s + 1, c) >= score(s, c), (s, c)


def test_the_raise_is_in_fact_strict():
    """The contract only promises "never lowers"; the shipped formula raises,
    and pinning the stronger fact keeps a `max(0, ...)`-style clamp from being
    introduced silently."""
    for s in GRID:
        for c in GRID:
            assert score(s + 1, c) > score(s, c), (s, c)


def test_the_raise_is_largest_from_the_empty_row():
    """With no contradiction, the first group moves the score the most; the gain
    then shrinks monotonically. A reordering branch would break this."""
    gains = [score(s + 1, 0) - score(s, 0) for s in GRID]
    assert gains[0] == 0.5
    assert all(later < earlier for earlier, later in zip(gains, gains[1:]))


# ---------------------------------------------------------------------------
# 5. Label thresholds at their exact boundaries (default policy)
# ---------------------------------------------------------------------------

def test_supported_boundary_is_the_first_integer_that_satisfies_it():
    """For each contradiction count, `3c + 1` is SUPPORTED, `3c` is not, and
    `3c + 2` still is — the label is a threshold, not a band."""
    assert IMBALANCE_PER_GROUP == POLICY_SIGNED_MARGIN.imbalance_per_group
    for c in range(0, 8):
        at = IMBALANCE_PER_GROUP * c + 1
        if at < MIN_SUPPORT_GROUPS:
            # Below the corroboration guard the threshold cannot fire; the guard
            # is the binding constraint, which is what (1, 0) demonstrates.
            for s in range(0, MIN_SUPPORT_GROUPS):
                assert decide(s, c).status is not Status.SUPPORTED, (s, c)
        else:
            assert decide(at - 1, c).status is not Status.SUPPORTED, (at - 1, c)
            assert decide(at, c).status is Status.SUPPORTED, (at, c)
            assert decide(at + 1, c).status is Status.SUPPORTED, (at + 1, c)


def test_contradicted_boundary_is_the_first_integer_that_satisfies_it():
    for s in range(0, 8):
        at = IMBALANCE_PER_GROUP * s + 1
        assert decide(s, at - 1).status is not Status.CONTRADICTED, (s, at - 1)
        assert decide(s, at).status is Status.CONTRADICTED, (s, at)
        assert decide(s, at + 1).status is Status.CONTRADICTED, (s, at + 1)


def test_min_support_groups_is_the_boundary_of_the_guard():
    """`MIN_SUPPORT_GROUPS` is where the corroboration guard stops binding: one
    group short reads PARTIAL even though the imbalance threshold is satisfied."""
    assert MIN_SUPPORT_GROUPS == 2
    assert decide(1, 0).status is Status.PARTIAL
    assert decide(MIN_SUPPORT_GROUPS, 0).status is Status.SUPPORTED
    assert 1 >= IMBALANCE_PER_GROUP * 0 + 1  # the bare threshold fires at (1, 0)
    assert score(1, 0) == 0.5                # and the raw number already reads
                                             # "half the way", which is why the
                                             # guard, not the score, decides


def test_boundary_rows_report_the_matching_rule_id():
    assert decide(IMBALANCE_PER_GROUP + 1, 1).status is Status.SUPPORTED
    assert decide(IMBALANCE_PER_GROUP + 1, 1).status_rule_id == (
        "STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION"
    )
    assert decide(1, IMBALANCE_PER_GROUP + 1).status_rule_id == (
        "STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT"
    )
    assert decide(IMBALANCE_PER_GROUP, 1).status_rule_id == (
        "STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED"
    )


def test_score_at_the_threshold_is_the_half_the_policy_names():
    """Every SUPPORTED boundary row scores at least 1/2 and no CONTRA-threshold
    row scores less than 1/2 on the other side."""
    for c in range(0, 8):
        at = IMBALANCE_PER_GROUP * c + 1
        if at < MIN_SUPPORT_GROUPS:
            continue
        assert score(at, c) >= 0.5, (at, c)
        assert score(at - 1, c) < 0.5, (at - 1, c)
        assert score(c, at) <= -0.5, (c, at)
        assert score(c, at - 1) > -0.5, (c, at - 1)
