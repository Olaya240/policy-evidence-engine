"""Signed evidence decision table (v2).

The shipped table assigns one non-negative number to a claim and reuses the same
number for opposite verdicts: ``0.68`` is both SUPPORTED (corroborated) and
CONTRADICTED (refuted). It also reorders evidence shapes rather than combining
them, so adding a supporting record to a contradicted claim lowers its number,
and one stale accepted record demotes a well-corroborated claim.

This module replaces the ordered branches with one signed score

    score(s, c) = (s - c) / (s + c + 1)      in (-1, 1)

over counts of *independent source groups* holding a fresh, accepted, undisputed
directional record. The sign is the direction; the magnitude is the strength.

Properties, machine-checked in ``ct3/DecisionTable.v`` (Coq, stdlib only) and
re-checked against this implementation in ``tests/test_decision_table.py``:

  * exclusivity      the labels cannot both apply          (v2_states_exclusive)
  * single source    s = 1 can never be SUPPORTED          (v2_single_source_is_partial)
  * monotone up      one more support group strictly raises the score
                                                           (v2_support_raises)
  * monotone down    one more contradiction group strictly lowers it
                                                           (v2_contradiction_lowers)
  * stale invariant  a stale record cannot move either count (v2_stale_ignored)
  * order invariant  counts do not depend on input order    (v2_order_irrelevant)

**The proof covers ``POLICY_SIGNED_MARGIN`` only.** The other two policies below
exist so the threshold choice can be named and switched in one place; their
consequences are not machine-checked, so switching the default is a change that
must be re-proved, not a configuration tweak.

Scope of the proof, stated so it is not overclaimed: the monotonicity theorems
are about the two integer counts, which are *group* counts here. The list lemmas
(`v2_stale_ignored`, `v2_order_irrelevant`) are proved over record lists and are
therefore one step weaker than the code, which deduplicates records into groups
before counting. `tests/test_decision_table.py::test_records_sharing_a_group_are_one_unit`
covers the step the Coq file does not. The dispute rule in ``decide`` is also
outside the Coq model.

Deliberately *not* in the score: staleness, review state, dispute status, neutral
stance, department diversity. Those are reported as separate fields so that a
number which moved always has an arithmetic explanation.

**The truth interval (v3): one scalar cannot hold both laws.**

A single number has to answer two questions at once — where is the verdict, and
how sure is it — and every rule that squeezed both into one number broke one of
the two laws a reader relies on: monotonicity (more support never weakens the
verdict) or label consistency (the label agrees with the number). `decide`'s
dispute rule is the shipped example: to stop a PARTIAL verdict from advertising
the strength of evidence whose support is exactly what is challenged, it
re-prices the score to the challenged configuration, and the reported number
then falls as support is added (`test_confidence_reliability.py`,
``test_the_reported_score_is_discontinuous_exactly_at_a_status_switch``).

So the verdict is reported as an *interval* instead:

    truth_lower = score(s, c + dc)      every pending challenge lands against
    truth_upper = score(s + ds, c)      every pending challenge lands for

where ``ds``/``dc`` are the groups a human has challenged (0 when none have).
The interval is the set of readings the evidence admits across every settlement
of the pending challenges, so it answers "where is the verdict" and "how sure"
separately: a wide interval is uncertain *because it is wide*, not because one
number came out small. Status is then a statement about the whole interval
(``truth_interval``):

    INSUFFICIENT   no admissible evidence and nothing pending
    SUPPORTED      truth_lower >= 0.5      decisive under every settlement
    CONTRADICTED   truth_upper <= -0.5     decisive under every settlement
    PARTIAL        otherwise; direction only when the interval misses zero

All four interval laws — order, both monotonicities in the counts, both in the
disputed counts, and label consistency — hold on the full grid in
``tests/test_truth_interval.py``. The interval is built from ``score`` and not
from the bare ratio ``(s - c) / (s + c)``: the bare ratio saturates at +/-1 as
soon as one side is empty, so ``score(5, 0) == score(6, 0)`` and *nothing* can be
strictly monotone at the top of the range. The laws themselves do not depend on
the smoothing — ``test_the_interval_laws_also_hold_for_the_unsmoothed_ratio``
re-checks order and monotonicity against the bare ratio — but the strictness of
the shipped scalar does.

``decide`` keeps its v2 label rule, and the interval does not silently replace
it: ``Decision.status`` is still the rule proved in ``ct3/DecisionTable.v``, while
``Decision.interval_status`` is the interval reading. The two differ exactly where
the single-source guard withdraws a label the raw margin would grant — (1, 0) is
v2 PARTIAL and interval SUPPORTED — so a caller that wants one source to stay
undecisive must read ``status``, and a caller that wants the margin must read the
interval. Unifying them is a change to the proved table, not to this module.
"""

from __future__ import annotations

import unicodedata

_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)


from dataclasses import dataclass

from .models import Evidence, EvidenceReviewState, Stance, Status


@dataclass(frozen=True)
class ThresholdPolicy:
    """A named, ratifiable choice of decisive thresholds.

    ``min_support_groups``  SUPPORTED needs at least this many support groups.
    ``imbalance_per_group`` the multiplier in ``s >= k*c + 1`` and ``c >= k*s + 1``,
                            i.e. how many extra groups of one kind are needed per
                            group of the other before a label is decisive.
    ``contest_blocks_decisive``
                            when true, the presence of directional evidence on both
                            sides forbids a decisive label outright.
    """

    policy_id: str
    min_support_groups: int
    imbalance_per_group: int
    contest_blocks_decisive: bool = False


# The shipped rule and the one proved in ct3/DecisionTable.v.
POLICY_SIGNED_MARGIN = ThresholdPolicy(
    policy_id="SIGNED_MARGIN_3_TO_1",
    min_support_groups=2,
    imbalance_per_group=3,
)

# Stricter: one fresh contradiction of any size keeps the claim at PARTIAL. This
# is the shipped tables's effective behaviour before v2, and the reading in which
# a contested claim is never called SUPPORTED.
POLICY_CONTEST_BLOCKS = ThresholdPolicy(
    policy_id="CONTEST_BLOCKS_DECISIVE",
    min_support_groups=2,
    imbalance_per_group=3,
    contest_blocks_decisive=True,
)

# Looser: one source can be decisive and a two-to-one split settles a claim.
POLICY_TWO_TO_ONE = ThresholdPolicy(
    policy_id="TWO_TO_ONE",
    min_support_groups=1,
    imbalance_per_group=2,
)

# Kept as module-level names for callers and tests that reference them directly.
MIN_SUPPORT_GROUPS = POLICY_SIGNED_MARGIN.min_support_groups
IMBALANCE_PER_GROUP = POLICY_SIGNED_MARGIN.imbalance_per_group


# Rule ids for the interval reading, kept distinct from the STATUS.V2_* ids so a
# consumer can tell which rule produced the label it is holding.
INTERVAL_SUPPORTED = "STATUS.V3_INTERVAL_SUPPORTED"
INTERVAL_CONTRADICTED = "STATUS.V3_INTERVAL_CONTRADICTED"
INTERVAL_PARTIAL = "STATUS.V3_INTERVAL_PARTIAL"
INTERVAL_INSUFFICIENT = "STATUS.V3_INTERVAL_NO_ADMISSIBLE_EVIDENCE"

# The decisive floor on the signed axis: the bounds a verdict has to clear under
# every settlement of the pending challenges.
DECISIVE_LOWER_BOUND = 0.5
DECISIVE_UPPER_BOUND = -0.5


def truth_lower(
    support_groups: int,
    contradiction_groups: int,
    disputed_contradiction: int = 0,
) -> float:
    """Weakest reading the evidence admits: every challenged group lands against.

    Only the disputed *contradictions* widen this end; challenged support cannot
    lower the lower bound, because the lower bound already ignores it.
    """
    if disputed_contradiction < 0:
        raise ValueError("disputed counts must be non-negative")
    return score(support_groups, contradiction_groups + disputed_contradiction)


def truth_upper(
    support_groups: int,
    contradiction_groups: int,
    disputed_support: int = 0,
) -> float:
    """Strongest reading the evidence admits: every challenged group lands for."""
    if disputed_support < 0:
        raise ValueError("disputed counts must be non-negative")
    return score(support_groups + disputed_support, contradiction_groups)


def interval_status(
    support_groups: int,
    contradiction_groups: int,
    disputed_support: int = 0,
    disputed_contradiction: int = 0,
) -> tuple[Status, str]:
    """The v3 label: a statement about the interval, never about one number.

    ``INSUFFICIENT`` is the row with nothing admissible and nothing pending. A row
    whose only directional evidence is challenged is ``PARTIAL``, not empty: an
    unresolved challenge is uncertainty about a record that exists, and the
    interval it produces (``[score(0, 0), score(ds, 0)]``) contains zero, so it
    cannot be misread as support.
    """
    lower = truth_lower(support_groups, contradiction_groups, disputed_contradiction)
    upper = truth_upper(support_groups, contradiction_groups, disputed_support)
    if support_groups == contradiction_groups == 0 and not (disputed_support or disputed_contradiction):
        return Status.INSUFFICIENT, INTERVAL_INSUFFICIENT
    if lower >= DECISIVE_LOWER_BOUND:
        return Status.SUPPORTED, INTERVAL_SUPPORTED
    if upper <= DECISIVE_UPPER_BOUND:
        return Status.CONTRADICTED, INTERVAL_CONTRADICTED
    return Status.PARTIAL, INTERVAL_PARTIAL


@dataclass(frozen=True)
class TruthInterval:
    """A verdict as two numbers instead of one.

    ``truth_lower``/``truth_upper`` are the weakest and strongest readings the
    evidence admits once every pending challenge is settled (see the module
    docstring). The interval is the report; ``status`` is what the interval says;
    ``magnitude`` is a projection for callers that still need one number, and
    nothing in here derives the status from it.
    """

    truth_lower: float
    truth_upper: float
    support_groups: int
    contradiction_groups: int
    disputed_support: int
    disputed_contradiction: int
    status: Status
    status_rule_id: str

    def __post_init__(self) -> None:
        # Order is an invariant of the report, not a convention: a consumer that
        # reads only one end of it must not be able to read the two ends in the
        # wrong order, so a swapped construction fails at the construction site
        # rather than quietly reporting an inverted interval.
        if self.truth_lower > self.truth_upper:
            raise ValueError(
                "truth_lower must not exceed truth_upper: "
                f"{self.truth_lower} > {self.truth_upper}"
            )

    @property
    def intervals_contain_zero(self) -> bool:
        return self.truth_lower <= 0.0 <= self.truth_upper

    @property
    def direction(self) -> str:
        """`FOR`, `AGAINST` or `NONE`, and `NONE` whenever zero is in reach.

        The direction is only stated when the *whole* interval is on one side, so
        a challenged record that could flip the verdict withholds the direction
        instead of guessing which way the review will land.
        """
        if self.truth_lower > 0.0:
            return "FOR"
        if self.truth_upper < 0.0:
            return "AGAINST"
        return "NONE"

    @property
    def magnitude(self) -> float:
        """Projection of the interval onto the strength axis.

        The greatest strength any admissible settlement reaches, so a straddling
        interval reports 1.0: some settlement is total. It is not
        ``Decision.confidence`` (that is the magnitude of the reported point) and
        it is not a probability; ``test_truth_interval.py`` pins rows where it
        and ``status`` disagree, which is why it cannot stand in for the status.
        """
        return max(abs(self.truth_lower), abs(self.truth_upper))


def truth_interval(
    support_groups: int,
    contradiction_groups: int,
    *,
    disputed_support: int = 0,
    disputed_contradiction: int = 0,
) -> TruthInterval:
    """The verdict as a truth interval.

    No as-if re-pricing happens here, and none is needed: the interval already
    spans every settlement of the challenged groups, so the discontinuity that
    monotonicity died at in ``decide`` cannot arise. Adding an admissible support
    group raises ``truth_lower`` and ``truth_upper`` together; adding a
    challenged contradiction lowers only ``truth_lower``, which is what uncertainty
    about a challenge should do.
    """
    status, status_rule = interval_status(
        support_groups,
        contradiction_groups,
        disputed_support,
        disputed_contradiction,
    )
    return TruthInterval(
        truth_lower=truth_lower(support_groups, contradiction_groups, disputed_contradiction),
        truth_upper=truth_upper(support_groups, contradiction_groups, disputed_support),
        support_groups=support_groups,
        contradiction_groups=contradiction_groups,
        disputed_support=disputed_support,
        disputed_contradiction=disputed_contradiction,
        status=status,
        status_rule_id=status_rule,
    )


@dataclass(frozen=True)
class Decision:
    """Result of the table.

    ``score`` is signed and, with ``confidence``, is a *projection* of the verdict;
    ``truth_lower``/``truth_upper`` are the verdict. ``status`` is the v2 label
    rule (the one proved in ``ct3/DecisionTable.v``); ``interval_status`` is the
    label the interval itself supports. See ``confidence``.
    """

    status: Status
    score: float
    truth_lower: float
    truth_upper: float
    interval_status: Status
    support_groups: int
    contradiction_groups: int
    disputed_groups: int
    contested: bool
    status_rule_id: str
    confidence_rule_id: str
    policy_id: str

    @property
    def confidence(self) -> float:
        """Projection of the truth interval onto the strength axis: ``|score|``.

        What it means now: the magnitude of the *reported point* of the truth
        interval. ``score`` is the reading of the counts ``decide`` reports — the
        settled counts, or the challenged configuration when the challenge is
        decision-relevant — and that reading lies inside ``[truth_lower,
        truth_upper]`` (pinned by
        ``tests/test_truth_interval.py::test_the_reported_score_lies_inside_the_interval``).
        So ``confidence`` is one point of the interval with the sign dropped, not
        a summary of the interval and not a probability.

        The value is unchanged from v2 (``abs(score)``, the shipped
        ``Claim.confidence`` field), and it is deliberately *not* what any status
        is derived from: the label comes from the bounds, so this number cannot
        express that a challenge is pending or that the evidence is undecided.
        A magnitude alone also collides across directions by construction — one
        support group and one contradiction group are both 0.5 — which is why
        ``direction`` and the interval travel with it.
        """
        return abs(self.score)

    @property
    def direction(self) -> str:
        """`FOR`, `AGAINST` or `NONE`. The half of the pair that `confidence` omits."""
        if self.score > 0:
            return "FOR"
        if self.score < 0:
            return "AGAINST"
        return "NONE"

    @property
    def directional_evidence_mass(self) -> int:
        """``support + contradiction`` groups. With ``score`` this makes the
        payload injective: ``(score=0, mass=0)`` is no directional evidence at
        all, while ``(score=0, mass>0)`` is a balanced contest."""
        return self.support_groups + self.contradiction_groups


def _count_groups(
    evidence: list[Evidence],
) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    """One pass over the evidence, returning all five group sets.

    Returns ``(support, contradiction, disputed_support, disputed_contradiction,
    disputed_all)``. ``disputed_all`` keeps the stance-blind behaviour the public
    ``disputed_groups`` helper had, including neutral records.
    """
    support: set[str] = set()
    contradiction: set[str] = set()
    disputed_support: set[str] = set()
    disputed_contradiction: set[str] = set()
    disputed_all: set[str] = set()
    for item in evidence:
        if item.review_state is not EvidenceReviewState.ACCEPTED:
            continue
        if item.stale:
            continue
        group = group_key(item)
        supports = item.stance is Stance.SUPPORTS
        contradicts = item.stance is Stance.CONTRADICTS
        if item.disputed:
            disputed_all.add(group)
            if supports:
                disputed_support.add(group)
            elif contradicts:
                disputed_contradiction.add(group)
        elif supports:
            support.add(group)
        elif contradicts:
            contradiction.add(group)
    return support, contradiction, disputed_support, disputed_contradiction, disputed_all


def directional_groups(evidence: list[Evidence]) -> tuple[set[str], set[str]]:
    """Independent source groups per direction.

    Counting is per group, not per record: two records from the same group are
    one unit of independent evidence. Review state, staleness and dispute status
    are filters, never weights — an unverified, stale or disputed record does not
    make the score move.
    """
    support, contradiction, _, _, _ = _count_groups(evidence)
    return support, contradiction


def disputed_directions(evidence: list[Evidence]) -> tuple[set[str], set[str]]:
    """Disputed groups split by the stance the challenge is aimed at."""
    _, _, disputed_support, disputed_contradiction, _ = _count_groups(evidence)
    return disputed_support, disputed_contradiction


def disputed_groups(evidence: list[Evidence]) -> set[str]:
    """Groups holding an accepted, fresh record that a human has challenged.

    These are deliberately outside the score — an unresolved challenge is not
    evidence in either direction — but they must still be visible, otherwise a
    disputed claim would read INSUFFICIENT and the challenge would disappear.
    """
    _, _, _, _, disputed_all = _count_groups(evidence)
    return disputed_all


def score(support_groups: int, contradiction_groups: int) -> float:
    """Signed strength, exactly ``(s - c) / (s + c + 1)``."""
    if support_groups < 0 or contradiction_groups < 0:
        raise ValueError("group counts must be non-negative")
    return (support_groups - contradiction_groups) / (
        support_groups + contradiction_groups + 1
    )


def _label(s: int, c: int, policy: ThresholdPolicy) -> tuple[Status, str]:
    """The table itself, with no dispute handling."""
    if policy.contest_blocks_decisive and s > 0 and c > 0:
        return Status.PARTIAL, "STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED"
    if s >= policy.min_support_groups and s >= policy.imbalance_per_group * c + 1:
        return Status.SUPPORTED, "STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION"
    if c >= policy.imbalance_per_group * s + 1:
        return Status.CONTRADICTED, "STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT"
    if s == 0 and c == 0:
        return Status.INSUFFICIENT, "STATUS.V2_NO_DIRECTIONAL_EVIDENCE"
    return Status.PARTIAL, "STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED"


def decide(
    support_groups: int,
    contradiction_groups: int,
    *,
    disputed_support: int = 0,
    disputed_contradiction: int = 0,
    disputed_total: int | None = None,
    policy: ThresholdPolicy = POLICY_SIGNED_MARGIN,
) -> Decision:
    """Label the evidence, downgrading only when a pending challenge could flip it.

    A challenged record is excluded from the counts because its stance is exactly
    what is in dispute. Excluding it silently would let a pending review vanish
    from the verdict, so the table is also evaluated *as if* the disputed records
    were counted. If the two labels differ, the dispute is decision-relevant and
    the claim reads PARTIAL; if they agree, the dispute cannot change the answer
    and the verdict stands. That keeps a five-source claim from being demoted to
    PARTIAL by one unrelated challenge, which a blanket "any dispute means
    PARTIAL" rule would do.

    The default ``policy`` is the rule proved in ``ct3/DecisionTable.v``. Passing
    another policy is a supported way to answer "what would the stricter rule
    say", not a way to change production behaviour without re-proving it.

    The disputed counts are added to the undisputed ones, so they must name
    groups the undisputed counts do not already contain. A group that holds both
    a challenged and an unchallenged record is one unit of independent evidence;
    counting it twice would report a score its evidence cannot reach.
    """
    s, c = support_groups, contradiction_groups
    status, status_rule = _label(s, c, policy)
    confidence_rule = "CONFIDENCE.V2_ZERO_MARGIN" if s == c == 0 else "CONFIDENCE.V2_SIGNED_MARGIN"
    disputed = disputed_support + disputed_contradiction
    # How many groups are challenged is a fact about the evidence, not about the
    # as-if arithmetic above, so it is reported separately whenever the caller
    # had to drop a group it already counted.
    reported_disputed = disputed if disputed_total is None else disputed_total
    effective_s, effective_c = s, c
    if disputed:
        challenged_status, _ = _label(s + disputed_support, c + disputed_contradiction, policy)
        if challenged_status is not status:
            status = Status.PARTIAL
            status_rule = "STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT"
            # The verdict is withheld, so the number must not describe the
            # undisputed evidence as if the challenge were settled. Report the
            # challenged configuration; otherwise a PARTIAL claim could carry
            # +0.667 and a consumer reading score alone would infer SUPPORTED.
            #
            # Known cost, pinned by
            # `tests/test_confidence_reliability.py::test_the_reported_score_is_discontinuous_exactly_at_a_status_switch`:
            # the two configurations are ordered independently, so the reported
            # score is *not* monotone in the undisputed support at a switch point.
            # decide(1,0,disputed_contradiction=1) is 0.50 and
            # decide(2,0,disputed_contradiction=1) is 0.25. Status integrity was
            # chosen over monotonicity; restoring monotonicity would mean
            # advertising the strength of evidence that is exactly what is doubted.
            effective_s, effective_c = s + disputed_support, c + disputed_contradiction
    # The interval is reported from the counts the caller can verify, widened by the
    # challenged groups, so the reported point above always lies inside it. The
    # interval label is computed here rather than by the as-if rule because the
    # interval does not need a settlement to be chosen: every settlement is in it.
    lower = truth_lower(s, c, disputed_contradiction)
    upper = truth_upper(s, c, disputed_support)
    interval_label, _ = interval_status(s, c, disputed_support, disputed_contradiction)
    return    Decision(
        status=status,
        score=score(effective_s, effective_c),
        truth_lower=lower,
        truth_upper=upper,
        interval_status=interval_label,
        support_groups=s,
        contradiction_groups=c,
        disputed_groups=reported_disputed,
        contested=(s > 0 and c > 0) or reported_disputed > 0,
        status_rule_id=status_rule,
        confidence_rule_id=confidence_rule,
        policy_id=policy.policy_id,
    )


def decide_evidence(
    evidence: list[Evidence],
    *,
    policy: ThresholdPolicy = POLICY_SIGNED_MARGIN,
) -> Decision:
    support, contradiction, disputed_support, disputed_contradiction, _ = _count_groups(evidence)
    return decide(
        len(support),
        len(contradiction),
        # ``_count_groups`` partitions a group by record, so the same group can
        # appear on both sides when it holds a challenged and an unchallenged
        # record. The as-if evaluation adds these to the undisputed counts, so
        # only the groups it does not already hold may be passed.
        disputed_support=len(disputed_support - support),
        disputed_contradiction=len(disputed_contradiction - contradiction),
        disputed_total=len(disputed_support | disputed_contradiction),
        policy=policy,
    )


def group_key(item):
    """Canonical identity of the source group a record belongs to.

    Independence is a claim about *sources*, so a source's identity must not be
    spoofable by an invisible character. Raw equality treated `ops-team` and
    `ops-team\u200b` as two sources, and NFC/NFD spellings of one name the same
    way — either one lets a single source corroborate itself.
    """
    raw = item.source_group or item.source_record_id
    return unicodedata.normalize("NFC", raw).translate(_INVISIBLE).strip()
