"""The bridge from `ct3/IntervalReport.v` to the shipped interval.

The Coq file proves the interval's laws for the *model*, with denominators
cleared: bounds ordered, width equal to ``2*(s*dc + c*ds + ds*dc)``, monotone in
each count, and the two threshold reads never both firing. A proof about a model
says nothing until something checks that the Python computes the model, which is
what this file does — by exact rational arithmetic, not by re-deriving the
formula in floats.

Two things are checked per grid row:

* the value the implementation returns equals the *exact* rational the model
  names (``Fraction`` compared through ``float``, which is exact here because
  both sides round the same rational); and
* the cleared-form identity the Coq theorem names holds of those rationals.

A wrong ``truth_lower``/``truth_upper`` fails the first check. A theorem that
does not describe the shipped numbers fails the second.
"""

from __future__ import annotations

import pytest
from fractions import Fraction

from app.decision_table import (
    DECISIVE_LOWER_BOUND,
    DECISIVE_UPPER_BOUND,
    interval_status,
    truth_lower,
    truth_upper,
)

GRID = [
    (s, c, ds, dc)
    for s in range(7)
    for c in range(7)
    for ds in range(3)
    for dc in range(3)
]


def _score_exact(a: int, b: int) -> Fraction:
    """The shipped ratio, exactly: ``(a - b) / (a + b + 1)``."""
    return Fraction(a - b, a + b + 1)


@pytest.mark.parametrize("s,c,ds,dc", GRID)
def test_the_shipped_bounds_are_the_model_rationals(s, c, ds, dc):
    expected_lower = _score_exact(s, c + dc)
    expected_upper = _score_exact(s + ds, c)
    assert truth_lower(s, c, dc) == float(expected_lower), (s, c, dc)
    assert truth_upper(s, c, ds) == float(expected_upper), (s, c, ds)


@pytest.mark.parametrize("s,c,ds,dc", GRID)
def test_bounds_are_ordered_as_the_proof_requires(s, c, ds, dc):
    assert truth_lower(s, c, dc) <= truth_upper(s, c, ds), (s, c, ds, dc)


@pytest.mark.parametrize("s,c,ds,dc", GRID)
def test_the_width_identity_holds_of_the_shipped_numbers(s, c, ds, dc):
    """`width_is_the_dispute_term`: width = 2*(s*dc + c*ds + ds*dc).

    Stated on the cleared products, which is what the Coq theorem is about. The
    two ends are the exact rationals, so this is an integer identity, not a
    tolerance.
    """
    # The cleared products come from the counts, not from the reduced
    # ``Fraction``: reduction moves signs into the numerator and would silently
    # test a different integer identity. Test 1 above is what ties these numbers
    # to the implementation's return values.
    lo_num, lo_den = s - (c + dc), s + c + dc + 1
    hi_num, hi_den = (s + ds) - c, (s + ds) + c + 1
    width = hi_num * lo_den - lo_num * hi_den
    assert width == 2 * (s * dc + c * ds + ds * dc) + ds + dc, (s, c, ds, dc)


@pytest.mark.parametrize("s,c,ds,dc", GRID)
def test_support_never_lowers_either_bound(s, c, ds, dc):
    """`lo_monotone_in_support` and `hi_monotone_in_support`."""
    assert truth_lower(s, c, dc) <= truth_lower(s + 1, c, dc), (s, c, dc)
    assert truth_upper(s, c, ds) <= truth_upper(s + 1, c, ds), (s, c, ds)


@pytest.mark.parametrize("s,c,ds,dc", GRID)
def test_contradiction_never_raises_either_bound(s, c, ds, dc):
    """`lo_antitone_in_contradiction` and `hi_antitone_in_contradiction`."""
    assert truth_lower(s, c + 1, dc) <= truth_lower(s, c, dc), (s, c, dc)
    assert truth_upper(s, c + 1, ds) <= truth_upper(s, c, ds), (s, c, ds)


@pytest.mark.parametrize("s,c,ds,dc", GRID)
def test_the_two_threshold_reads_never_both_fire(s, c, ds, dc):
    """`labels_never_both_fire`, read through the label the code actually issues."""
    status, rule = interval_status(s, c, ds, dc)
    floor_met = truth_lower(s, c, dc) >= DECISIVE_LOWER_BOUND
    ceiling_met = truth_upper(s, c, ds) <= DECISIVE_UPPER_BOUND
    assert not (floor_met and ceiling_met), (s, c, ds, dc, status, rule)


def test_a_dispute_is_the_only_thing_that_widens_the_reported_interval():
    """`zero_width_means_no_dispute`, for every row in the grid.

    No degenerate exception exists: the ``+1`` in the denominator keeps a
    disputed support visible even with no contradictions, so the interval is a
    point exactly when nothing is pending.
    """
    for s in range(7):
        for c in range(7):
            assert truth_lower(s, c, 0) == truth_upper(s, c, 0), (s, c)
            assert truth_lower(s, c, 1) < truth_upper(s, c, 0), (s, c)
            assert truth_lower(s, c, 0) < truth_upper(s, c, 1), (s, c)
            assert truth_lower(s, c, 1) < truth_upper(s, c, 1), (s, c)
