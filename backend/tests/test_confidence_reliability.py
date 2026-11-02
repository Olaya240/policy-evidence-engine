"""Confidence reliability for `app.decision_table` — ct3 audit workstream 4.

The question: does the number a caller reads as `confidence` deserve to be read?
`Decision.confidence` is defined as `abs(Decision.score)`, so every property is
stated over `score` and then re-read through `confidence`, over an exhaustive
enumeration of the two group counts rather than a sample.

**What `confidence` means now.** The verdict is reported as a truth interval —
`Decision.truth_lower`/`truth_upper`, see `app.decision_table` and
`tests/test_truth_interval.py` — and `confidence` is its projection onto the
strength axis: `abs(score)`, the magnitude of the *reported point* of the
interval, with the sign dropped. The value does not change; the claim does. It is
no longer "the strength of the verdict" but "the strength of one admissible
reading of it", so it cannot distinguish a decided verdict from an interval that
still contains one, and nothing derives a status from it: `decide`'s label is the
v2 rule, the interval's label is read off the two ends, and the same projected
number carries three different statuses on the 441-row grid
(`test_the_projection_is_not_used_for_the_status`). `Claim.confidence` keeps its
value and its `ge=0, le=1` bound; what it names is that projection.

Grids, named so `ct3/audit/CONFIDENCE-CALIBRATION.md` can cite them:

    U   s, c in 0..6                                               49 configurations
    D   U x (disputed_support, disputed_contradiction) in 0..2    441 configurations

Default policy only (`POLICY_SIGNED_MARGIN`): it is the rule proved in
`ct3/DecisionTable.v`. The other two policies exist so the threshold choice can
be named in one place; their consequences are explicitly unproved, so testing
them would pin behaviour nobody ratified.

Two of the six properties do not hold in the form they are usually written, and
this file states both the form that holds and the exception, so a future change
cannot move either silently:

  * `PARTIAL` reaches the decisive floor 0.5 at exactly one configuration,
    (1, 0), where the corroboration guard withholds a label the raw margin
    would allow. `PARTIAL` never exceeds that floor on the undisputed grid.
  * The disputed path re-prices the number to the challenged configuration
    whenever the challenge is decision-relevant. That is `decide`'s documented
    dispute rule and it is deliberate, but it means a `PARTIAL` row can carry a
    magnitude above 0.5 and the reported number is not monotone in the counts.

Neither exception is a defect in `score`; both are recorded with counts in the
audit rather than "fixed" here, because `score` is pinned as a function of the
counts alone (`test_table_differential.py::test_policy_choice_cannot_move_the_score`)
and the single-source row (1, 0) is the most common real configuration.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from itertools import permutations

import pytest

from app.decision_table import decide, decide_evidence, score
from app.models import Evidence, EvidenceReviewState, Stance, Status

NOW = datetime.now(timezone.utc)

# The manuscript's two grids.
UNDISPUTED = [(s, c) for s in range(7) for c in range(7)]
DISPUTED = [
    (s, c, ds, dc)
    for s in range(7)
    for c in range(7)
    for ds in range(3)
    for dc in range(3)
]

# The magnitude at which either decisive label begins: `s >= 3c + 1` solved for
# `(s - c) / (s + c + 1) >= 1/2`. Pinned as a number, not re-derived, so a change
# to the formula surfaces as a failure here.
DECISIVE_FLOOR = 0.5

SUPPORT_RAISE_STEPS = [(s, c) for s in range(6) for c in range(7)]
CONTRADICTION_LOWER_STEPS = [(s, c) for s in range(7) for c in range(6)]


def dec(row):
    """`decide` for either grid's row shape, so one loop can cover both."""
    if len(row) == 2:
        return decide(*row)
    s, c, ds, dc = row
    return decide(s, c, disputed_support=ds, disputed_contradiction=dc)


# ---------------------------------------------------------------------------
# 1. The bound, and confidence as the magnitude of the signed score
# ---------------------------------------------------------------------------

def test_score_is_bounded_and_confidence_is_exactly_its_magnitude():
    """`abs(score) <= 1` and `confidence == abs(score)`, on both grids.

    Equality, not `approx`: `confidence` is a property returning `abs(self.score)`,
    so a difference — even in the last bit — would mean the field had started
    carrying a separate number.
    """
    for row in (*UNDISPUTED, *DISPUTED):
        decision = dec(row)
        assert abs(decision.score) <= 1.0, row
        assert -1.0 < decision.score < 1.0, row  # the formula's bound is open
        assert decision.confidence == abs(decision.score), row
        assert decision.confidence >= 0.0, row


def test_confidence_is_zero_exactly_when_the_score_is():
    for row in (*UNDISPUTED, *DISPUTED):
        decision = dec(row)
        assert (decision.confidence == 0) == (decision.score == 0), row


# ---------------------------------------------------------------------------
# 2. Swapping the directions mirrors the score
# ---------------------------------------------------------------------------

def test_swapping_support_and_contradiction_negates_the_score():
    """`score(s, c) == -score(c, s)`, and the same through `decide` with no
    dispute: the sign is the direction and the magnitude is the strength, so a
    mirror image must not read differently."""
    for s, c in UNDISPUTED:
        assert score(s, c) == -score(c, s), (s, c)
        assert decide(s, c).score == -decide(c, s).score, (s, c)


def test_the_disputed_mirror_breaks_exactly_where_the_guard_does():
    """Under dispute the mirror needs `(ds, dc)` swapped too, and even then it
    fails — 16 of 441 rows — because relevance is direction-conditional.

    The witness pair: `(0, 1)` is already CONTRADICTED, so one challenged
    contradiction cannot change the label and the number stays `-0.5`; `(1, 0)`
    is held at PARTIAL by the corroboration guard, so the mirror challenge *is*
    decision-relevant and the number moves to the challenged configuration
    `score(2, 0)`. The asymmetry is the guard, not the formula.
    """
    already_decisive = decide(0, 1, disputed_contradiction=1)
    guard_blocked = decide(1, 0, disputed_support=1)

    assert already_decisive.score == -DECISIVE_FLOOR
    assert already_decisive.status is Status.CONTRADICTED
    assert guard_blocked.status is Status.PARTIAL
    assert guard_blocked.score == pytest.approx(score(2, 0))

    mirrored = [
        row
        for row in DISPUTED
        if dec(row).score != -dec((row[1], row[0], row[3], row[2])).score
    ]
    # The count recorded in ct3/audit/CONFIDENCE-CALIBRATION.md. A change that
    # makes the disputed path symmetric is a change to the dispute rule, so it
    # must update the audit as well as this number.
    assert len(mirrored) == 16


# ---------------------------------------------------------------------------
# 3. Directional monotonicity
# ---------------------------------------------------------------------------

def test_adding_a_support_group_never_lowers_the_score():
    for s, c in SUPPORT_RAISE_STEPS:
        assert decide(s + 1, c).score >= decide(s, c).score, (s, c)


def test_adding_a_contradiction_group_never_raises_the_score():
    for s, c in CONTRADICTION_LOWER_STEPS:
        assert decide(s, c + 1).score <= decide(s, c).score, (s, c)


def test_the_disputed_path_is_not_monotone_and_the_audit_records_it():
    """A known limitation, pinned so a future fix is visible rather than silent.

    `decide(1, 0, disputed_contradiction=1)` keeps the undisputed number
    (`score(1, 0) = 0.5`, the challenge cannot move a PARTIAL label). Add one
    support group and the same challenge becomes decision-relevant, so the
    number is re-priced to `score(2, 1) = 0.25`: *more* supporting evidence, a
    *lower* reported confidence. This is the shape v1 was replaced to remove,
    reintroduced only on the disputed path by the as-if pricing rule.
    """
    before = decide(1, 0, disputed_contradiction=1)
    after = decide(2, 0, disputed_contradiction=1)

    assert before.score == DECISIVE_FLOOR
    assert after.score == pytest.approx(score(2, 1))
    assert after.score < before.score

    support_steps = [
        (s, c, ds, dc)
        for ds in range(3)
        for dc in range(3)
        for s in range(6)
        for c in range(7)
        if dec((s + 1, c, ds, dc)).score < dec((s, c, ds, dc)).score
    ]
    contradiction_steps = [
        (s, c, ds, dc)
        for ds in range(3)
        for dc in range(3)
        for s in range(7)
        for c in range(6)
        if dec((s, c + 1, ds, dc)).score > dec((s, c, ds, dc)).score
    ]
    # Counts recorded in the audit: 378 support steps and 378 contradiction steps
    # per grid, of which these are the inversions.
    assert (len(support_steps), len(contradiction_steps)) == (26, 20)


# ---------------------------------------------------------------------------
# 4. Status and score agree about the band they are in
# ---------------------------------------------------------------------------

def test_each_status_implies_the_score_band_its_rule_requires():
    """No configuration reports a status its score contradicts.

    SUPPORTED and CONTRADICTED each require at least half the total weight on
    their own side; PARTIAL is the band inside the floor and INSUFFICIENT is the
    empty row. This is the property a consumer leans on when it reads the
    status and the number together.
    """
    for s, c in UNDISPUTED:
        decision = decide(s, c)
        assert (s, c) == (decision.support_groups, decision.contradiction_groups)
        if decision.status is Status.SUPPORTED:
            assert decision.score >= DECISIVE_FLOOR, (s, c, decision.score)
        elif decision.status is Status.CONTRADICTED:
            assert decision.score <= -DECISIVE_FLOOR, (s, c, decision.score)
        elif decision.status is Status.PARTIAL:
            assert abs(decision.score) <= DECISIVE_FLOOR, (s, c, decision.score)
        else:
            assert decision.status is Status.INSUFFICIENT
            assert decision.score == 0, (s, c)


def test_only_the_single_source_row_sits_on_the_decisive_floor_as_partial():
    """The one collision the literal property has: (1, 0) is PARTIAL at 0.5, the
    same magnitude as the weakest SUPPORTED row (4, 1).

    Two different statements share that magnitude: "the margin is at the
    decisive boundary but one source is never decisive" and "the margin is at
    the boundary and two corroborating groups are enough". The status is what
    separates them, which is why the number cannot travel without it.
    """
    partials_on_the_floor = [
        (s, c) for s, c in UNDISPUTED
        if decide(s, c).status is Status.PARTIAL
        and decide(s, c).confidence >= DECISIVE_FLOOR
    ]
    supported_magnitudes = sorted(
        decide(s, c).confidence for s, c in UNDISPUTED
        if decide(s, c).status is Status.SUPPORTED
    )

    assert partials_on_the_floor == [(1, 0)]
    assert supported_magnitudes[0] == DECISIVE_FLOOR
    assert decide(4, 1).status is Status.SUPPORTED
    assert decide(4, 1).confidence == decide(1, 0).confidence


def test_supported_never_carries_a_zero_score():
    """A decisive FOR verdict with no margin would be a contradiction in one
    row; the guard and the threshold make it unreachable on either grid."""
    for row in (*UNDISPUTED, *DISPUTED):
        decision = dec(row)
        if decision.status is Status.SUPPORTED:
            assert decision.score > 0, row
        if decision.status is Status.CONTRADICTED:
            assert decision.score < 0, row


def test_zero_score_is_insufficient_only_when_there_is_no_evidence():
    """`score == 0` alone is ambiguous by design — no evidence and a balanced
    contest both read zero — so `INSUFFICIENT` is keyed on the mass, and a PARTIAL
    at zero always has some."""
    for s, c in UNDISPUTED:
        decision = decide(s, c)
        if decision.status is Status.INSUFFICIENT:
            assert decision.score == 0 and decision.directional_evidence_mass == 0
        if decision.score == 0 and decision.status is Status.PARTIAL:
            assert decision.directional_evidence_mass > 0, (s, c)


# ---------------------------------------------------------------------------
# 5. The empty row
# ---------------------------------------------------------------------------

def test_no_directional_evidence_is_zero_and_non_committal():
    decision = decide(0, 0)

    assert decision.score == 0
    assert decision.confidence == 0
    assert decision.direction == "NONE"
    assert decision.directional_evidence_mass == 0
    assert decision.contested is False
    assert decision.status is Status.INSUFFICIENT
    assert decision.status not in (Status.SUPPORTED, Status.CONTRADICTED)
    assert decision.status_rule_id == "STATUS.V2_NO_DIRECTIONAL_EVIDENCE"
    assert decision.confidence_rule_id == "CONFIDENCE.V2_ZERO_MARGIN"


# ---------------------------------------------------------------------------
# 6. Determinism under permutation of the evidence list
# ---------------------------------------------------------------------------

def evidence(stance, group, *, review_state=EvidenceReviewState.ACCEPTED,
             stale=False, disputed=False):
    return Evidence(
        source_record_id=f"record-{group}-{stance.value}-{review_state.value}",
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


def test_permuting_the_evidence_list_cannot_move_the_decision():
    """Counting is over sets, so every one of the 5040 orders of one seven-record
    list must produce the same `Decision`, field for field.

    The list deliberately carries every filter the module applies: two distinct
    support groups, a contradiction, a challenged support in a group that also
    holds an undisputed record, a neutral, an unverified duplicate and a stale
    contradiction.
    """
    records = [
        evidence(Stance.SUPPORTS, "a"),
        evidence(Stance.SUPPORTS, "b"),
        evidence(Stance.CONTRADICTS, "c"),
        evidence(Stance.SUPPORTS, "c", disputed=True),
        evidence(Stance.NEUTRAL, "d"),
        evidence(Stance.SUPPORTS, "a", review_state=EvidenceReviewState.UNVERIFIED),
        evidence(Stance.CONTRADICTS, "e", stale=True),
    ]
    base = decide_evidence(records)

    # Not a degenerate row: if the verdict were INSUFFICIENT the invariance would
    # be trivially true and prove nothing about ordering.
    assert base.status is Status.PARTIAL
    assert (base.support_groups, base.contradiction_groups) == (2, 1)
    assert base.disputed_groups == 1

    orders = 0
    for order in permutations(records):
        orders += 1
        assert decide_evidence(list(order)) == base, [r.source_record_id for r in order]

    assert orders == 5040


def test_permuting_a_support_only_list_cannot_move_the_decision():
    """The decisive case as well, so the invariance is not only pinned on a
    non-committal verdict."""
    records = [
        evidence(Stance.SUPPORTS, "a"),
        evidence(Stance.SUPPORTS, "b"),
        evidence(Stance.SUPPORTS, "a"),
        evidence(Stance.CONTRADICTS, "c", stale=True),
        evidence(Stance.NEUTRAL, "d"),
    ]
    base = decide_evidence(records)
    assert base.status is Status.SUPPORTED
    assert base.score == pytest.approx(score(2, 0))

    for order in permutations(records):
        assert decide_evidence(list(order)) == base


# Measured discontinuity at a status switch, pinned rather than fixed away.
#
# `decide` reports the *settled* configuration's score, except when the challenged
# configuration changes the label — then it reports the challenged one, so a PARTIAL
# verdict cannot advertise the strength of evidence whose support is exactly what is
# being challenged. That switch is where monotonicity breaks: the two configurations
# are ordered independently, so at a switch point more support can mean a lower score.
#
#   decide(1, 0, disputed_contradiction=1) -> PARTIAL, 0.50   (status unchanged)
#   decide(2, 0, disputed_contradiction=1) -> PARTIAL, 0.25   (status switched)
#
# Both verdicts are defensible; the pair cannot both hold. Monotonicity is the one
# that gives, and this test keeps the cost visible instead of letting a future change
# restore monotonicity by silently re-advertising a challenged configuration.
def test_the_reported_score_is_discontinuous_exactly_at_a_status_switch():
    from app.decision_table import decide

    settled_below, settled_above = decide(1, 0), decide(2, 0)
    below = decide(1, 0, disputed_contradiction=1)
    above = decide(2, 0, disputed_contradiction=1)

    # The settled evidence strengthens with support; the reported score does not.
    assert settled_above.score > settled_below.score
    assert below.score > above.score
    assert below.status is Status.PARTIAL and above.status is Status.PARTIAL

    # Only the higher row crossed a label boundary, which is what moved the number.
    assert above.status_rule_id == "STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT"
    assert below.status_rule_id == "STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED"
    assert above.score < 0.5 <= below.score

    # And the same magnitude can carry two statuses, so score alone never implies one.
    assert decide(4, 1).status is Status.SUPPORTED and decide(4, 1).score == 0.5
    assert decide(1, 0).status is Status.PARTIAL and decide(1, 0).score == 0.5


# ---------------------------------------------------------------------------
# 7. The projection is a projection: no status is read off it
# ---------------------------------------------------------------------------

def test_the_projection_is_not_used_for_the_status():
    """`confidence` is a projection of the interval, never the input to a label.

    The value is unchanged (`abs(score)`) so existing consumers keep working, but
    the claim is narrowed to one admissible reading: the magnitude of the reported
    point. A label cannot be a function of it. On this grid the same projected
    number carries up to three statuses — 0.5 is PARTIAL in 17 rows, CONTRADICTED
    in 6 and SUPPORTED in 3, and 0.0 is INSUFFICIENT in one row and PARTIAL in 60
    — so a consumer that infers a label from `confidence` is wrong in 9 of the 24
    projected values that occur, and the labels come from the interval's two ends
    (`Decision.truth_lower`/`truth_upper`, `tests/test_truth_interval.py`).
    """
    by_confidence: dict[float, Counter[str]] = {}
    for row in DISPUTED:
        decision = dec(row)
        assert decision.confidence == abs(decision.score), row
        # The projection is the reported point, and the point is inside the report.
        assert decision.truth_lower <= decision.score <= decision.truth_upper, row
        by_confidence.setdefault(decision.confidence, Counter())[decision.status.value] += 1

    multi = {value: counts for value, counts in by_confidence.items() if len(counts) > 1}
    print(
        f"projection: {len(by_confidence)} distinct confidences, "
        f"{len(multi)} carry more than one status"
    )
    assert len(by_confidence) == 24
    assert len(multi) == 9
    assert dict(by_confidence[0.5]) == {"PARTIAL": 17, "CONTRADICTED": 6, "SUPPORTED": 3}
    assert dict(by_confidence[0.0]) == {"INSUFFICIENT": 1, "PARTIAL": 60}

    # The witness pair: one projected value, two verdicts, and the interval is what
    # separates them. (4, 1) is decisive under every settlement; (1, 0) is
    # undecided under the v2 guard and its interval still reaches the floor.
    assert decide(4, 1).confidence == decide(1, 0).confidence == DECISIVE_FLOOR
    assert decide(4, 1).status is Status.SUPPORTED
    assert decide(1, 0).status is Status.PARTIAL
    assert decide(1, 0).truth_lower == DECISIVE_FLOOR
    assert decide(1, 0).interval_status is Status.SUPPORTED

    # And the projection never stands in for an end: a claim whose interval still
    # straddles the floor can project above it.
    straddling = decide(2, 0, disputed_contradiction=1)
    assert straddling.confidence < DECISIVE_FLOOR
    assert straddling.interval_status is Status.PARTIAL
    assert straddling.truth_lower < DECISIVE_FLOOR < straddling.truth_upper
