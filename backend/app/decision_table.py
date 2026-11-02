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


@dataclass(frozen=True)
class Decision:
    """Result of the table. ``score`` is signed; ``confidence`` is its magnitude."""

    status: Status
    score: float
    support_groups: int
    contradiction_groups: int
    disputed_groups: int
    contested: bool
    status_rule_id: str
    confidence_rule_id: str
    policy_id: str

    @property
    def confidence(self) -> float:
        """Magnitude only, kept for the shipped `Claim.confidence` field.

        A magnitude alone collides across directions by construction: one
        support group and one contradiction group are both 0.5. It is only
        meaningful together with ``direction`` or ``status``, which is why both
        travel with it in the trace.
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
            effective_s, effective_c = s + disputed_support, c + disputed_contradiction
    return Decision(
        status=status,
        score=score(effective_s, effective_c),
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
