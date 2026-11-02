"""The truth interval: a verdict as two numbers, and the laws that need both.

`Decision.score` is one scalar, and one scalar cannot hold monotonicity and label
consistency at the same time — `decide`'s dispute rule buys the label by
re-pricing the number to the challenged configuration, and the reported number
then falls as support is added (`test_confidence_reliability.py`,
``test_the_reported_score_is_discontinuous_exactly_at_a_status_switch``). The
interval buys both:

    truth_lower = score(s, c + dc)     every pending challenge lands against
    truth_upper = score(s + ds, c)     every pending challenge lands for

Grids, all exhaustive over the counts the coordinator fixed:

    G   s, c in 0..6, ds, dc in 0..2                          441 configurations
    S   s in 0..5, c in 0..6, ds, dc in 0..2                  378 support steps
    C   s in 0..6, c in 0..5, ds, dc in 0..2                  378 contradiction steps
    DS  s, c in 0..6, ds in 0..1, dc in 0..2                  294 challenge-for steps
    DC  s, c in 0..6, ds in 0..2, dc in 0..1                  294 challenge-against steps

Four properties, each stated so that a change to the definition has to move a
number here:

  1. order        `truth_lower <= truth_upper`, and the two ends are exactly the
                  two `score` readings above (equality, not `approx`);
  2. monotonicity increasing either count moves *both* bounds the right way, and
                  increasing a challenged count moves only the end it can move —
                  strictly, on every one of the 1344 steps;
  3. consistency  the label is a statement about the whole interval: SUPPORTED
                  needs the lower end at the floor, CONTRADICTED the upper end,
                  and a PARTIAL row is one the interval has not decided;
  4. projection   `magnitude` is a projection, so it cannot produce the status.

**One part of property 3 does not hold as usually written.** "Every PARTIAL row
has an interval that straddles 0.5, straddles -0.5, or contains 0" is false for a
point interval inside the undecided band: `(2, 1)` is PARTIAL with the interval
`[0.25, 0.25]`, which does none of the three. The form that holds is the
five-shape classification pinned below — the three named shapes plus an interval
lying strictly between 0 and a threshold on one side, which is what an unsettled
but not contested row looks like. The counts for all five are asserted, so the
list cannot grow a sixth shape unnoticed.

The interval is built from `score`, which keeps the `+ 1` denominator of the Coq
model; the bare ratio `(s - c) / (s + c)` saturates at 1 as soon as one side is
empty and admits no strictly monotone scalar. The *laws* do not depend on that
choice, which is why
``test_the_interval_laws_also_hold_for_the_unsmoothed_ratio`` re-checks order and
monotonicity against the bare ratio: that is the form the Coq side is proving.

`decide` is not replaced here. Its `status` is still the v2 rule proved in
`ct3/DecisionTable.v`; the interval verdict is `interval_status`. The two are
different functions and this file counts the 21 rows where they disagree rather
than papering over them, because unifying them is a change to the proved table.
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.decision_table import (
    DECISIVE_LOWER_BOUND,
    DECISIVE_UPPER_BOUND,
    TruthInterval,
    decide,
    score,
    truth_interval,
    truth_lower,
    truth_upper,
)
from app.models import Status

# ---------------------------------------------------------------------------
# The grids
# ---------------------------------------------------------------------------

UNDISPUTED = [(s, c) for s in range(7) for c in range(7)]

GRID = [
    (s, c, ds, dc)
    for s in range(7)
    for c in range(7)
    for ds in range(3)
    for dc in range(3)
]

SUPPORT_STEPS = [
    (s, c, ds, dc)
    for ds in range(3)
    for dc in range(3)
    for s in range(6)
    for c in range(7)
]

CONTRADICTION_STEPS = [
    (s, c, ds, dc)
    for ds in range(3)
    for dc in range(3)
    for s in range(7)
    for c in range(6)
]

CHALLENGE_FOR_STEPS = [
    (s, c, ds, dc)
    for s in range(7)
    for c in range(7)
    for ds in range(2)
    for dc in range(3)
]

CHALLENGE_AGAINST_STEPS = [
    (s, c, ds, dc)
    for s in range(7)
    for c in range(7)
    for ds in range(3)
    for dc in range(2)
]


def interval(s: int, c: int, ds: int = 0, dc: int = 0) -> TruthInterval:
    return truth_interval(s, c, disputed_support=ds, disputed_contradiction=dc)


def ratio_lower(s: int, c: int, dc: int = 0) -> float:
    """`truth_lower` under the unsmoothed ratio, for the bridge test only."""
    total = s + c + dc
    return 0.0 if total == 0 else (s - (c + dc)) / total


def ratio_upper(s: int, c: int, ds: int = 0) -> float:
    total = s + ds + c
    return 0.0 if total == 0 else ((s + ds) - c) / total


# ---------------------------------------------------------------------------
# 1. Order: the lower end is never above the upper end
# ---------------------------------------------------------------------------

def test_the_lower_bound_never_exceeds_the_upper_bound_on_all_441_configurations():
    """`truth_lower <= truth_upper`, and each end is the `score` reading the
    definition names.

    The arithmetic is pinned separately from the inequality on purpose. The
    inequality alone would survive a swap of the two *names* if both were
    computed from the same widened configuration; the exact equalities are what
    make a swap fail even when the two ends happen to be ordered.
    """
    checked = 0
    for s, c, ds, dc in GRID:
        result = interval(s, c, ds, dc)
        assert result.truth_lower <= result.truth_upper, (s, c, ds, dc)
        # Exact, not approx: the ends are `score` applied to the widened counts,
        # so a formula change must surface here rather than inside a tolerance.
        assert result.truth_lower == score(s, c + dc), (s, c, ds, dc)
        assert result.truth_upper == score(s + ds, c), (s, c, ds, dc)
        checked += 1

    print(f"order: {checked}/{len(GRID)} configurations ordered")
    assert checked == 441


def test_a_swapped_interval_cannot_be_constructed():
    """The invariant is enforced where the report is built, not only in a test.

    With the ends swapped — the failure mode property 1 exists to catch — the
    constructor refuses, so no consumer can hold a `TruthInterval` whose
    `truth_lower` is its own upper bound. `(2, 0, 0, 1)` is the witness: its ends
    are 0.25 and 0.667, so swapping them is exactly the inversion above.
    """
    healthy = interval(2, 0, 0, 1)
    assert (healthy.truth_lower, healthy.truth_upper) == (0.25, score(2, 0))

    with pytest.raises(ValueError, match="truth_lower must not exceed truth_upper"):
        TruthInterval(
            truth_lower=healthy.truth_upper,
            truth_upper=healthy.truth_lower,
            support_groups=healthy.support_groups,
            contradiction_groups=healthy.contradiction_groups,
            disputed_support=healthy.disputed_support,
            disputed_contradiction=healthy.disputed_contradiction,
            status=healthy.status,
            status_rule_id=healthy.status_rule_id,
        )


# ---------------------------------------------------------------------------
# 2. Monotonicity, all of it
# ---------------------------------------------------------------------------

def test_one_more_support_group_never_lowers_either_bound():
    """Increasing `s` raises both ends — strictly, on all 378 steps.

    Strictness is the property v2 lost on the disputed path (26 inversions there,
    `test_confidence_reliability.py`); an interval that only weakly rises would
    still be able to sit flat while evidence arrives, so both counts are pinned.
    """
    lower_strict = upper_strict = 0
    for s, c, ds, dc in SUPPORT_STEPS:
        before, after = interval(s, c, ds, dc), interval(s + 1, c, ds, dc)
        assert after.truth_lower >= before.truth_lower, (s, c, ds, dc)
        assert after.truth_upper >= before.truth_upper, (s, c, ds, dc)
        lower_strict += after.truth_lower > before.truth_lower
        upper_strict += after.truth_upper > before.truth_upper

    print(
        f"support: {len(SUPPORT_STEPS)} steps, "
        f"{lower_strict} raised the lower bound, {upper_strict} the upper bound"
    )
    assert (len(SUPPORT_STEPS), lower_strict, upper_strict) == (378, 378, 378)


def test_one_more_contradiction_group_never_raises_either_bound():
    lower_strict = upper_strict = 0
    for s, c, ds, dc in CONTRADICTION_STEPS:
        before, after = interval(s, c, ds, dc), interval(s, c + 1, ds, dc)
        assert after.truth_lower <= before.truth_lower, (s, c, ds, dc)
        assert after.truth_upper <= before.truth_upper, (s, c, ds, dc)
        lower_strict += after.truth_lower < before.truth_lower
        upper_strict += after.truth_upper < before.truth_upper

    print(
        f"contradiction: {len(CONTRADICTION_STEPS)} steps, "
        f"{lower_strict} lowered the lower bound, {upper_strict} the upper bound"
    )
    assert (len(CONTRADICTION_STEPS), lower_strict, upper_strict) == (378, 378, 378)


def test_a_challenged_support_group_never_lowers_the_upper_bound():
    """`ds` widens the interval upward only: on all 294 steps the upper end rises
    strictly and the lower end does not move at all.

    That asymmetry is the whole point of the second dimension. Under v2 the same
    challenge was either ignored or re-priced the scalar; here it can only widen
    the interval, so more challenged support can never make the verdict stronger
    at the weak end.
    """
    raised = unmoved = 0
    for s, c, ds, dc in CHALLENGE_FOR_STEPS:
        before, after = interval(s, c, ds, dc), interval(s, c, ds + 1, dc)
        assert after.truth_upper >= before.truth_upper, (s, c, ds, dc)
        assert after.truth_lower == before.truth_lower, (s, c, ds, dc)
        raised += after.truth_upper > before.truth_upper
        unmoved += after.truth_lower == before.truth_lower

    print(
        f"challenged support: {len(CHALLENGE_FOR_STEPS)} steps, "
        f"{raised} raised the upper bound, lower bound unmoved in {unmoved}"
    )
    assert (len(CHALLENGE_FOR_STEPS), raised, unmoved) == (294, 294, 294)


def test_a_challenged_contradiction_group_never_raises_the_lower_bound():
    lowered = unmoved = 0
    for s, c, ds, dc in CHALLENGE_AGAINST_STEPS:
        before, after = interval(s, c, ds, dc), interval(s, c, ds, dc + 1)
        assert after.truth_lower <= before.truth_lower, (s, c, ds, dc)
        assert after.truth_upper == before.truth_upper, (s, c, ds, dc)
        lowered += after.truth_lower < before.truth_lower
        unmoved += after.truth_upper == before.truth_upper

    print(
        f"challenged contradiction: {len(CHALLENGE_AGAINST_STEPS)} steps, "
        f"{lowered} lowered the lower bound, upper bound unmoved in {unmoved}"
    )
    assert (len(CHALLENGE_AGAINST_STEPS), lowered, unmoved) == (294, 294, 294)


# ---------------------------------------------------------------------------
# 3. Label consistency: the label is a statement about the interval
# ---------------------------------------------------------------------------

def test_no_label_contradicts_the_interval_it_was_read_from():
    """The decisive labels require the *whole* interval to clear the floor.

    SUPPORTED is not "the strongest reading is decisive" — it is "every
    admissible settlement is", which is why it needs `truth_lower`; the mirror
    holds for CONTRADICTED. A PARTIAL row is one the interval has not decided, so
    it must fail both floors.
    """
    counts: Counter[str] = Counter()
    for s, c, ds, dc in GRID:
        result = interval(s, c, ds, dc)
        counts[result.status.value] += 1
        if result.status is Status.SUPPORTED:
            assert result.truth_lower >= DECISIVE_LOWER_BOUND, (s, c, ds, dc)
            assert result.truth_upper >= DECISIVE_LOWER_BOUND, (s, c, ds, dc)
        elif result.status is Status.CONTRADICTED:
            assert result.truth_upper <= DECISIVE_UPPER_BOUND, (s, c, ds, dc)
            assert result.truth_lower <= DECISIVE_UPPER_BOUND, (s, c, ds, dc)
        elif result.status is Status.PARTIAL:
            assert result.truth_lower < DECISIVE_LOWER_BOUND, (s, c, ds, dc)
            assert result.truth_upper > DECISIVE_UPPER_BOUND, (s, c, ds, dc)
        else:
            assert result.status is Status.INSUFFICIENT
            assert (s, c, ds, dc) == (0, 0, 0, 0)
            assert (result.truth_lower, result.truth_upper) == (0.0, 0.0)

    print(f"labels: {dict(sorted(counts.items()))} over {len(GRID)} configurations")
    assert counts == {
        "SUPPORTED": 36,
        "CONTRADICTED": 36,
        "PARTIAL": 368,
        "INSUFFICIENT": 1,
    }
    assert sum(counts.values()) == 441


def test_every_partial_row_fits_one_of_five_shapes_and_the_named_three_are_not_all():
    """The PARTIAL shapes, counted, with the gap in the usual statement named.

    The three shapes usually claimed — straddles 0.5, straddles -0.5, contains 0 —
    do not cover a PARTIAL row whose interval sits strictly inside the undecided
    band on one side: `(2, 1)` is `[0.25, 0.25]`, `(1, 2)` is `[-0.25, -0.25]`.
    Those are 126 of the 368 PARTIAL rows, so the claim is stated as five shapes
    with exact counts rather than as the three that happen to be memorable.
    """
    shapes: Counter[str] = Counter()
    witnesses: dict[str, tuple] = {}
    for s, c, ds, dc in GRID:
        result = interval(s, c, ds, dc)
        if result.status is not Status.PARTIAL:
            continue
        lower, upper = result.truth_lower, result.truth_upper
        if lower <= 0.0 <= upper:
            shape = "contains_zero"
        elif lower < DECISIVE_LOWER_BOUND < upper:
            shape = "straddles_0.5"
        elif lower < DECISIVE_UPPER_BOUND < upper:
            shape = "straddles_-0.5"
        elif 0.0 < lower:
            shape = "contained_positive"
        elif upper < 0.0:
            shape = "contained_negative"
        else:  # pragma: no cover - would mean the classification missed a case
            shape = "unclassified"
        shapes[shape] += 1
        witnesses.setdefault(shape, (s, c, ds, dc, lower, upper))

    print(f"partial shapes: {dict(sorted(shapes.items()))}")
    assert shapes == {
        "contains_zero": 164,
        "straddles_0.5": 39,
        "straddles_-0.5": 39,
        "contained_positive": 63,
        "contained_negative": 63,
    }
    assert sum(shapes.values()) == 368
    assert "unclassified" not in shapes

    # The witnesses for the two shapes the usual three-shape claim omits, and for
    # the ones it does name, so the counts above are reproducible from one row each.
    assert witnesses["contained_positive"] == (2, 1, 0, 0, 0.25, 0.25)
    assert witnesses["contained_negative"][:4] == (1, 2, 0, 0)
    assert witnesses["contained_negative"][4:] == (-0.25, -0.25)
    assert witnesses["straddles_0.5"] == (2, 0, 0, 1, 0.25, score(2, 0))
    assert witnesses["contains_zero"][4:] == (-0.5, 0.0)


def test_direction_is_withheld_exactly_when_zero_is_in_reach():
    """`direction` states a side only when the whole interval is on it.

    A challenged record that could flip the verdict withholds the direction
    instead of guessing how the review will land; the map below is asserted in
    full so a direction that appears on a straddling interval is a failure.
    """
    pair_counts: Counter[tuple[str, str]] = Counter()
    for s, c, ds, dc in GRID:
        result = interval(s, c, ds, dc)
        assert (result.direction == "NONE") == result.intervals_contain_zero, (s, c, ds, dc)
        if result.direction == "FOR":
            assert result.truth_lower > 0.0, (s, c, ds, dc)
        if result.direction == "AGAINST":
            assert result.truth_upper < 0.0, (s, c, ds, dc)
        if result.status is Status.SUPPORTED:
            assert result.direction == "FOR", (s, c, ds, dc)
        if result.status is Status.CONTRADICTED:
            assert result.direction == "AGAINST", (s, c, ds, dc)
        if result.status is Status.INSUFFICIENT:
            assert result.direction == "NONE", (s, c, ds, dc)
        pair_counts[(result.direction, result.status.value)] += 1

    print(f"direction x status: {dict(sorted(pair_counts.items()))}")
    assert pair_counts == {
        ("NONE", "PARTIAL"): 164,
        ("NONE", "INSUFFICIENT"): 1,
        ("FOR", "PARTIAL"): 102,
        ("FOR", "SUPPORTED"): 36,
        ("AGAINST", "PARTIAL"): 102,
        ("AGAINST", "CONTRADICTED"): 36,
    }


# ---------------------------------------------------------------------------
# 4. The projection is not the report
# ---------------------------------------------------------------------------

def test_the_magnitude_projection_cannot_produce_a_status():
    """`TruthInterval.magnitude` is a projection, and one projection per interval
    is not enough to recover the label.

    Twelve of the thirty-two magnitudes that occur carry more than one status;
    0.5 alone is PARTIAL in 35 rows, CONTRADICTED in 2 and SUPPORTED in 2. So a
    consumer that reads the projected number and infers a label is wrong on 441 -
    (12 + 20) rows, and the labels above are the ones the bounds produce.
    """
    by_magnitude: dict[float, Counter[str]] = {}
    for s, c, ds, dc in GRID:
        result = interval(s, c, ds, dc)
        by_magnitude.setdefault(result.magnitude, Counter())[result.status.value] += 1

    multi = {value: counts for value, counts in by_magnitude.items() if len(counts) > 1}
    print(
        f"projection: {len(by_magnitude)} distinct magnitudes, "
        f"{len(multi)} carry more than one status"
    )
    assert len(by_magnitude) == 32
    assert len(multi) == 12
    assert dict(by_magnitude[0.5]) == {"PARTIAL": 35, "CONTRADICTED": 2, "SUPPORTED": 2}

    # A row the projection would call decisive and the interval does not: the
    # strongest admissible settlement reaches 0.667, but a challenged
    # contradiction could still bring it down to 0.25.
    straddling = interval(2, 0, 0, 1)
    assert straddling.magnitude == score(2, 0) > DECISIVE_LOWER_BOUND
    assert straddling.truth_lower < DECISIVE_LOWER_BOUND
    assert straddling.status is Status.PARTIAL


# ---------------------------------------------------------------------------
# 5. The scalar is inside the report, so nothing is lost by keeping it
# ---------------------------------------------------------------------------

def test_the_reported_score_lies_inside_the_interval():
    """`decide(...).score` is one admissible reading, so it is inside the interval.

    This is the bridge that lets `Decision` keep `score` (and `confidence`) while
    the verdict becomes two-dimensional: the scalar is the reading of the counts
    `decide` reports — settled, or re-priced to the challenged configuration —
    and the interval is every reading the evidence admits. If the scalar ever
    escaped the interval the two halves of the report would describe different
    verdicts.
    """
    for s, c, ds, dc in GRID:
        decision = decide(s, c, disputed_support=ds, disputed_contradiction=dc)
        report = interval(s, c, ds, dc)
        assert report.truth_lower <= decision.score <= report.truth_upper, (s, c, ds, dc)
        assert (decision.truth_lower, decision.truth_upper) == (
            report.truth_lower,
            report.truth_upper,
        ), (s, c, ds, dc)
        assert decision.interval_status is report.status, (s, c, ds, dc)
        assert decision.status_rule_id.startswith("STATUS.V2_"), (s, c, ds, dc)
        assert report.status_rule_id.startswith("STATUS.V3_"), (s, c, ds, dc)


def test_the_interval_status_and_the_v2_label_disagree_in_21_rows():
    """Two labels, two functions, counted rather than reconciled.

    `decide.status` is the v2 rule proved in `ct3/DecisionTable.v`; the interval
    label is what the bounds say. They agree on 420 of 441 configurations and
    differ where the single-source guard withdraws a label the margin grants
    (`(1, 0)` is v2 PARTIAL, interval SUPPORTED) and where a pending challenge can
    cross a floor with some settlement (`(2, 0)` with two challenged supports and
    one challenged contradiction is v2 SUPPORTED, interval PARTIAL, because the
    lower end is 0.25).

    Unifying them is a change to the proved table, so it is reported, not made
    here: the coordinator owns that decision, and a test that hid the split would
    let one reading silently stand for the other.
    """
    disagreements: Counter[tuple[str, str]] = Counter()
    witnesses: dict[tuple[str, str], tuple] = {}
    for s, c, ds, dc in GRID:
        v2 = decide(s, c, disputed_support=ds, disputed_contradiction=dc).status
        v3 = interval(s, c, ds, dc).status
        if v2 is v3:
            continue
        key = (v2.value, v3.value)
        disagreements[key] += 1
        witnesses.setdefault(key, (s, c, ds, dc))

    print(f"v2 vs interval: {dict(sorted(disagreements.items()))}")
    assert disagreements == {
        ("SUPPORTED", "PARTIAL"): 9,
        ("CONTRADICTED", "PARTIAL"): 9,
        ("PARTIAL", "SUPPORTED"): 3,
    }
    assert sum(disagreements.values()) == 21
    assert witnesses[("PARTIAL", "SUPPORTED")] == (1, 0, 0, 0)
    assert witnesses[("SUPPORTED", "PARTIAL")] == (2, 0, 2, 1)
    assert witnesses[("CONTRADICTED", "PARTIAL")] == (0, 2, 1, 2)


# ---------------------------------------------------------------------------
# 6. The bridge to the Coq side: the same laws under the unsmoothed ratio
# ---------------------------------------------------------------------------

def test_the_interval_laws_also_hold_for_the_unsmoothed_ratio():
    """Order and all four monotonicities re-checked against `(s - c) / (s + c)`.

    The shipped module uses `score`, whose `+ 1` denominator keeps the scalar
    strictly monotone; the bare ratio saturates at 1 when one side is empty. The
    interval laws do not depend on that choice, and this test says so with
    numbers: the same grid, the same four step sets, the ratio instead of `score`.
    It is the check that lets the proof and the implementation describe the same
    function family rather than two unrelated ones.
    """
    ordered = 0
    for s, c, ds, dc in GRID:
        lower, upper = ratio_lower(s, c, dc), ratio_upper(s, c, ds)
        assert lower <= upper, (s, c, ds, dc)
        ordered += 1
    assert ordered == 441

    for s, c, ds, dc in SUPPORT_STEPS:
        assert ratio_lower(s + 1, c, dc) >= ratio_lower(s, c, dc), (s, c, ds, dc)
        assert ratio_upper(s + 1, c, ds) >= ratio_upper(s, c, ds), (s, c, ds, dc)
    for s, c, ds, dc in CONTRADICTION_STEPS:
        assert ratio_lower(s, c + 1, dc) <= ratio_lower(s, c, dc), (s, c, ds, dc)
        assert ratio_upper(s, c + 1, ds) <= ratio_upper(s, c, ds), (s, c, ds, dc)
    for s, c, ds, dc in CHALLENGE_FOR_STEPS:
        assert ratio_upper(s, c, ds + 1) >= ratio_upper(s, c, ds), (s, c, ds, dc)
        assert ratio_lower(s, c, dc) == ratio_lower(s, c, dc), (s, c, ds, dc)
    for s, c, ds, dc in CHALLENGE_AGAINST_STEPS:
        assert ratio_lower(s, c, dc + 1) <= ratio_lower(s, c, dc), (s, c, ds, dc)

    print(
        f"unsmoothed ratio: {ordered} ordered, "
        f"{len(SUPPORT_STEPS) + len(CONTRADICTION_STEPS) + len(CHALLENGE_FOR_STEPS) + len(CHALLENGE_AGAINST_STEPS)} monotone steps"
    )


# ---------------------------------------------------------------------------
# 7. Input contract
# ---------------------------------------------------------------------------

def test_negative_challenged_counts_are_refused():
    """A challenged count is a number of groups, so a negative one is a caller
    bug rather than an empty challenge."""
    with pytest.raises(ValueError, match="non-negative"):
        truth_lower(1, 0, -1)
    with pytest.raises(ValueError, match="non-negative"):
        truth_upper(1, 0, -1)
