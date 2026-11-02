"""Slice 9: the ``_count_groups`` partition, pinned.

``_count_groups`` is the single place where evidence records become the group
counts everything else consumes. It returns five sets in one pass:

    (support, contradiction, disputed_support, disputed_contradiction,
     disputed_all)

and each test below fixes one clause of that partition: what never counts, what
counts once, where a challenged record lands, and where a neutral record does
not. These are assertion-for-assertion pins, not re-derivations of the score
properties (those live in ``test_decision_table.py``).
"""

from datetime import datetime, timezone

from app.decision_table import (
    _count_groups,
    directional_groups,
    disputed_directions,
    disputed_groups,
)
from app.models import Evidence, EvidenceReviewState, Stance

NOW = datetime.now(timezone.utc)


def item(
    stance,
    group,
    *,
    stale=False,
    review_state=EvidenceReviewState.ACCEPTED,
    disputed=False,
    record_id=None,
):
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
# What never counts
# --------------------------------------------------------------------------

def test_unverified_records_never_count():
    """UNVERIFIED is a filter, not a weight: it appears in no returned set."""
    evidence = [
        item(Stance.SUPPORTS, "u", review_state=EvidenceReviewState.UNVERIFIED),
        item(Stance.CONTRADICTS, "u2", review_state=EvidenceReviewState.UNVERIFIED),
        item(Stance.NEUTRAL, "u3", review_state=EvidenceReviewState.UNVERIFIED),
    ]
    support, contradiction, disputed_support, disputed_contradiction, disputed_all = \
        _count_groups(evidence)
    assert support == set()
    assert contradiction == set()
    assert disputed_support == set()
    assert disputed_contradiction == set()
    assert disputed_all == set()


def test_unverified_disputed_record_never_count():
    """A challenge on an unverified record does not surface it as disputed."""
    evidence = [item(Stance.SUPPORTS, "u", disputed=True,
                     review_state=EvidenceReviewState.UNVERIFIED)]
    support, contradiction, disputed_support, disputed_contradiction, disputed_all = \
        _count_groups(evidence)
    assert support == set()
    assert contradiction == set()
    assert disputed_support == set()
    assert disputed_contradiction == set()
    assert disputed_all == set()


def test_stale_records_never_count():
    """A stale accepted record moves no count, in either direction."""
    evidence = [
        item(Stance.SUPPORTS, "s", stale=True),
        item(Stance.CONTRADICTS, "c", stale=True),
        item(Stance.NEUTRAL, "n", stale=True),
        item(Stance.SUPPORTS, "sd", stale=True, disputed=True),
    ]
    support, contradiction, disputed_support, disputed_contradiction, disputed_all = \
        _count_groups(evidence)
    assert support == set()
    assert contradiction == set()
    assert disputed_support == set()
    assert disputed_contradiction == set()
    assert disputed_all == set()


# --------------------------------------------------------------------------
# Where a disputed record lands
# --------------------------------------------------------------------------

def test_disputed_support_lands_only_in_disputed_support():
    _, _, disputed_support, disputed_contradiction, disputed_all = \
        _count_groups([item(Stance.SUPPORTS, "g", disputed=True)])
    assert disputed_support == {"g"}
    assert disputed_contradiction == set()
    assert disputed_all == {"g"}

    support, contradiction, _, _, _ = _count_groups([item(Stance.SUPPORTS, "g", disputed=True)])
    assert support == set()
    assert contradiction == set()


def test_disputed_contradiction_lands_only_in_disputed_contradiction():
    support, contradiction, disputed_support, disputed_contradiction, disputed_all = \
        _count_groups([item(Stance.CONTRADICTS, "g", disputed=True)])
    assert disputed_contradiction == {"g"}
    assert disputed_support == set()
    assert disputed_all == {"g"}
    assert support == set()
    assert contradiction == set()


def test_disputed_directions_projects_the_two_disputed_sets():
    evidence = [
        item(Stance.SUPPORTS, "ds", disputed=True),
        item(Stance.CONTRADICTS, "dc", disputed=True),
        item(Stance.SUPPORTS, "plain"),
    ]
    assert disputed_directions(evidence) == ({"ds"}, {"dc"})
    # The undisputed support is not disputed, so it is absent here.
    assert disputed_groups(evidence) == {"ds", "dc"}


# --------------------------------------------------------------------------
# Independence: one group is one unit
# --------------------------------------------------------------------------

def test_two_records_in_one_group_count_once():
    """Two records from the same source group are one unit of evidence."""
    evidence = [
        item(Stance.SUPPORTS, "g", record_id="r1"),
        item(Stance.SUPPORTS, "g", record_id="r2"),
    ]
    support, contradiction, _, _, _ = _count_groups(evidence)
    assert support == {"g"}
    assert contradiction == set()
    assert directional_groups(evidence) == ({"g"}, set())


def test_two_disputed_records_in_one_group_count_once():
    evidence = [
        item(Stance.SUPPORTS, "g", record_id="r1", disputed=True),
        item(Stance.SUPPORTS, "g", record_id="r2", disputed=True),
    ]
    _, _, disputed_support, _, disputed_all = _count_groups(evidence)
    assert disputed_support == {"g"}
    assert disputed_all == {"g"}
    assert disputed_groups(evidence) == {"g"}


def test_group_is_partitioned_by_record_between_undisputed_and_disputed():
    """One group holding a challenged and an unchallenged record is in both sets.

    The partition is per record, so the same group can appear in ``support`` and
    in ``disputed_support``; ``decide_evidence`` is what de-duplicates before the
    as-if arithmetic.
    """
    evidence = [
        item(Stance.SUPPORTS, "g", record_id="r1"),
        item(Stance.SUPPORTS, "g", record_id="r2", disputed=True),
    ]
    support, _, disputed_support, _, disputed_all = _count_groups(evidence)
    assert support == {"g"}
    assert disputed_support == {"g"}
    assert disputed_all == {"g"}


# --------------------------------------------------------------------------
# Neutral records
# --------------------------------------------------------------------------

def test_undisputed_neutral_lands_nowhere_directional():
    """NEUTRAL is not evidence in either direction, and is not disputed."""
    evidence = [item(Stance.NEUTRAL, "n")]
    support, contradiction, disputed_support, disputed_contradiction, disputed_all = \
        _count_groups(evidence)
    assert support == set()
    assert contradiction == set()
    assert disputed_support == set()
    assert disputed_contradiction == set()
    assert disputed_all == set()
    assert directional_groups(evidence) == (set(), set())
    assert disputed_groups(evidence) == set()


def test_disputed_neutral_is_in_disputed_groups_but_not_directional():
    """``disputed_all`` is stance-blind: a challenged neutral is still reported."""
    evidence = [item(Stance.NEUTRAL, "n", disputed=True)]
    support, contradiction, disputed_support, disputed_contradiction, disputed_all = \
        _count_groups(evidence)
    assert support == set()
    assert contradiction == set()
    assert disputed_support == set()
    assert disputed_contradiction == set()
    assert disputed_all == {"n"}
    assert disputed_groups(evidence) == {"n"}
    assert disputed_directions(evidence) == (set(), set())
