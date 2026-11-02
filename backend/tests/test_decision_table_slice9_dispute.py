"""Slice-9 contracts for `decide`'s dispute handling.

`decide` excludes a challenged record from the counts (its stance is exactly what
is in dispute) but also evaluates the table *as if* the challenge were settled in
the direction it was aimed at. Four things about that are load-bearing and are
pinned here:

  * if the two labels differ the dispute is decision-relevant: the verdict drops
    to PARTIAL and the reported number describes the challenged configuration,
    not the undisputed one;
  * if they agree the dispute is irrelevant and the verdict, its rule id and its
    score are all unchanged;
  * how many groups are challenged is a separate fact, reported from
    `disputed_total` when the caller supplies it, never recomputed from the
    as-if arithmetic;
  * `contested` is true exactly when both directions hold or a dispute is
    reported, and no configuration produces a score outside [-1, 1].

`reference_label` below is transcribed from the v2 table stated in the module
docstring (`min_support_groups`, `imbalance_per_group`, `contest_blocks_decisive`)
rather than read out of `_label`, so a disagreement means `decide`'s as-if
evaluation has drifted from the rule the prose claims.
"""

import pytest

from app.decision_table import (
    POLICY_CONTEST_BLOCKS,
    POLICY_SIGNED_MARGIN,
    POLICY_TWO_TO_ONE,
    decide,
    score,
)
from app.models import Status

POLICIES = (POLICY_SIGNED_MARGIN, POLICY_CONTEST_BLOCKS, POLICY_TWO_TO_ONE)

DECISION_RELEVANT = "STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT"
NO_DIRECTIONAL_EVIDENCE = "STATUS.V2_NO_DIRECTIONAL_EVIDENCE"
SUPPORT_OUTWEIGHS = "STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION"


def reference_label(s, c, policy):
    """The documented table, with no dispute handling.

    Kept literal on purpose: the thresholds are the ones the module docstring
    names, so this is the specification a reader of the prose would implement.
    """
    if policy.contest_blocks_decisive and s > 0 and c > 0:
        return Status.PARTIAL
    if s >= policy.min_support_groups and s >= policy.imbalance_per_group * c + 1:
        return Status.SUPPORTED
    if c >= policy.imbalance_per_group * s + 1:
        return Status.CONTRADICTED
    if s == 0 and c == 0:
        return Status.INSUFFICIENT
    return Status.PARTIAL


def is_decision_relevant(s, c, ds, dc, policy):
    """Whether settling the challenges would move the label."""
    return reference_label(s + ds, c + dc, policy) is not reference_label(s, c, policy)


# --------------------------------------------------------------------------
# The two arms, on the shape the docstring argues about
# --------------------------------------------------------------------------

def test_a_relevant_dispute_downgrades_to_partial_and_prices_the_challenge():
    """Two supporting groups are SUPPORTED; one challenged contradiction would
    make the claim PARTIAL if it were settled, so the verdict is withheld.

    The number must move with the withheld verdict: leaving it at +0.667 would
    let a consumer reading `score` alone infer SUPPORTED from a PARTIAL claim.
    """
    undisputed = decide(2, 0)
    assert undisputed.status is Status.SUPPORTED
    assert undisputed.score == pytest.approx(score(2, 0))

    challenged = decide(2, 0, disputed_contradiction=1)

    assert challenged.status is Status.PARTIAL
    assert challenged.status_rule_id == DECISION_RELEVANT
    assert challenged.score == pytest.approx(score(2, 1))
    assert challenged.score != pytest.approx(score(2, 0))
    # The undisputed counts are still reported as they were counted.
    assert (challenged.support_groups, challenged.contradiction_groups) == (2, 0)
    assert challenged.disputed_groups == 1
    assert challenged.contested


def test_an_irrelevant_dispute_leaves_the_verdict_untouched():
    """Five support groups outvote one contradiction even after it is settled,
    so one unrelated challenge must not demote a well-corroborated claim.

    A blanket "any dispute means PARTIAL" rule would pass the previous test and
    fail this one; the pair is what separates the two readings.
    """
    undisputed = decide(5, 0)
    challenged = decide(5, 0, disputed_contradiction=1)

    assert challenged.status is Status.SUPPORTED
    assert challenged.status_rule_id == SUPPORT_OUTWEIGHS
    assert challenged.score == pytest.approx(score(5, 0))
    # Same verdict and same number as if there were no challenge at all; only
    # the report of the challenge differs.
    assert (challenged.status, challenged.score) == (undisputed.status, undisputed.score)
    assert challenged.disputed_groups == 1
    assert challenged.contested


def test_relevance_is_relative_to_the_policy_in_force():
    """Identical numbers, opposite outcomes, decided by `contest_blocks_decisive`.

    Under the looser two-to-one rule a single support group is already decisive,
    so adding a challenged support changes nothing; under the proved rule that
    same challenge is exactly what makes the claim contested.
    """
    looser = decide(1, 0, disputed_support=1, policy=POLICY_TWO_TO_ONE)
    proved = decide(1, 0, disputed_support=1, policy=POLICY_SIGNED_MARGIN)

    assert looser.status is Status.SUPPORTED
    assert looser.status_rule_id == SUPPORT_OUTWEIGHS
    assert looser.score == pytest.approx(score(1, 0))

    assert proved.status is Status.PARTIAL
    assert proved.status_rule_id == DECISION_RELEVANT
    assert proved.score == pytest.approx(score(2, 0))

    # A rule that forbids a decisive label while both directions are present
    # makes every cross-direction challenge relevant.
    blocking = decide(5, 0, disputed_contradiction=1, policy=POLICY_CONTEST_BLOCKS)
    assert blocking.status is Status.PARTIAL
    assert blocking.status_rule_id == DECISION_RELEVANT


# --------------------------------------------------------------------------
# The report is not the as-if arithmetic
# --------------------------------------------------------------------------

def test_disputed_total_is_reported_verbatim_not_recomputed_from_the_as_if_counts():
    """The caller may have dropped a group it already counted; the report is
    that fact, so `disputed_groups` must not be `disputed_support +
    disputed_contradiction` when `disputed_total` says otherwise.

    Seven is a number the as-if arithmetic cannot produce here (it adds one
    group), which is what makes the assertion discriminating.
    """
    decision = decide(2, 0, disputed_contradiction=1, disputed_total=7)

    assert decision.disputed_groups == 7
    # The score is a function of the evidence, not of the size of the report.
    assert decision.score == pytest.approx(score(2, 1))
    assert decision.directional_evidence_mass == 2


def test_a_report_with_no_as_if_groups_downgrades_nothing_but_is_still_reported():
    """`decide_evidence` passes a total even when the subtraction left nothing
    to add (a group holding a challenged and an unchallenged record). The
    challenge is still a reported fact and must still mark the claim contested,
    but it must not invent a label change that the arithmetic does not support.
    """
    decision = decide(0, 0, disputed_total=3)

    assert decision.status is Status.INSUFFICIENT
    assert decision.status_rule_id == NO_DIRECTIONAL_EVIDENCE
    assert decision.score == 0
    assert decision.disputed_groups == 3
    assert decision.contested
    assert decision.directional_evidence_mass == 0


def test_disputed_groups_defaults_to_the_directional_sum():
    for ds in range(4):
        for dc in range(4):
            decision = decide(2, 0, disputed_support=ds, disputed_contradiction=dc)
            assert decision.disputed_groups == ds + dc


# --------------------------------------------------------------------------
# Grid: every count/policy/report combination
# --------------------------------------------------------------------------

def _grid():
    for policy in POLICIES:
        for s in range(0, 9):
            for c in range(0, 9):
                for ds in range(0, 4):
                    for dc in range(0, 4):
                        for total in (None, ds + dc, ds + dc + 4):
                            yield policy, s, c, ds, dc, total


def test_every_combination_agrees_with_the_documented_rule():
    for policy, s, c, ds, dc, total in _grid():
        kwargs = {"disputed_support": ds, "disputed_contradiction": dc,
                  "policy": policy}
        if total is not None:
            kwargs["disputed_total"] = total
        decision = decide(s, c, **kwargs)
        reported = ds + dc if total is None else total
        relevant = bool(ds + dc) and is_decision_relevant(s, c, ds, dc, policy)

        if relevant:
            assert decision.status is Status.PARTIAL, (s, c, ds, dc, policy.policy_id)
            assert decision.status_rule_id == DECISION_RELEVANT
            assert decision.score == pytest.approx(score(s + ds, c + dc))
        else:
            assert decision.status is reference_label(s, c, policy), \
                (s, c, ds, dc, policy.policy_id)
            assert decision.status_rule_id != DECISION_RELEVANT
            assert decision.score == pytest.approx(score(s, c))

        assert decision.policy_id == policy.policy_id
        assert (decision.support_groups, decision.contradiction_groups) == (s, c)
        assert decision.disputed_groups == reported
        assert decision.contested == ((s > 0 and c > 0) or reported > 0)
        assert decision.directional_evidence_mass == s + c


def test_no_configuration_scores_outside_the_unit_interval():
    """The stated bound is [-1, 1]; the formula's denominator is `s + c + 1`, so
    the observed bound is strictly open at both ends. Asserting the stated bound
    keeps a future change to `score` from leaving the closed interval unnoticed.
    """
    for policy, s, c, ds, dc, total in _grid():
        kwargs = {"disputed_support": ds, "disputed_contradiction": dc,
                  "policy": policy}
        if total is not None:
            kwargs["disputed_total"] = total
        decision = decide(s, c, **kwargs)
        assert -1 <= decision.score <= 1, (s, c, ds, dc, policy.policy_id)
        assert 0 <= decision.confidence <= 1
        assert decision.confidence == pytest.approx(abs(decision.score))
        assert -1 <= score(s + ds, c + dc) <= 1


# --------------------------------------------------------------------------
# The boundary the interval claim rests on
# --------------------------------------------------------------------------

def test_negative_counts_raise_instead_of_returning_an_out_of_interval_score():
    """`score` is only in [-1, 1] for non-negative group counts; the guard is
    what makes the interval claim true, so it is pinned rather than assumed.
    """
    with pytest.raises(ValueError):
        score(-1, 0)
    with pytest.raises(ValueError):
        score(0, -1)

    with pytest.raises(ValueError):
        decide(-1, 0)
    with pytest.raises(ValueError):
        decide(0, -1)
    # A negative as-if count only surfaces when the challenge is the reason the
    # label moved, which is the case here; `decide` must not absorb it.
    with pytest.raises(ValueError):
        decide(0, 0, disputed_support=-1)
    with pytest.raises(ValueError):
        decide(0, 0, disputed_contradiction=-1)
