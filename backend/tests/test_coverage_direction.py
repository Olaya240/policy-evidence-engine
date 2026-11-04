"""Direction-aware coverage flags.

`covered_by_fresh_accepted` is direction-blind by design: the relevant set for a
PRIMARY category is ``SUPPORTS ∪ CONTRADICTS`` and ``covered = bool(fresh)``, so a
claim whose only fresh accepted record *contradicts* it is reported COVERED at
``engine.py:245``. The two flags added beside it answer the question the boolean
cannot, without redefining the boolean.
"""

from datetime import datetime, timezone

import pytest

from app.evidence_coverage import evidence_coverage
from app.models import Evidence, EvidenceReviewState, Stance

NOW = datetime.now(timezone.utc)
HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
PRIMARY = "checklist_access_context"
CORROBORATION = "independent_checklist_support"


def item(relation, *, review_state=EvidenceReviewState.ACCEPTED, stale=False,
         disputed=False, group=None, record_id=None):
    return Evidence(
        source_record_id=record_id or f"record-{relation.value}-{group or 'x'}",
        timestamp=NOW,
        quote="the handover checklist was unavailable",
        stance=relation,
        review_state=review_state,
        rationale="because",
        stale=stale,
        department="Front Office",
        source_group=group,
        disputed=disputed,
        semantic_relation=relation,
    )


def category(evidence, category_id=PRIMARY):
    coverage = evidence_coverage(HYPOTHESIS, evidence)
    return next(c for c in coverage["categories"] if c["category_id"] == category_id)


# --------------------------------------------------------------------------
# The defect, stated so a regression is visible
# --------------------------------------------------------------------------

def test_contradiction_only_still_reports_covered_by_fresh_accepted():
    """Documents the shipped meaning rather than changing it: direction-blind."""
    result = category([item(Stance.CONTRADICTS)])
    assert result["covered_by_fresh_accepted"] is True


def test_contradiction_only_is_flagged_against():
    result = category([item(Stance.CONTRADICTS)])
    assert result["covered_by_fresh_contradiction"] is True
    assert result["covered_by_fresh_support"] is False
    assert result["direction"] == "AGAINST"


# --------------------------------------------------------------------------
# The new fields
# --------------------------------------------------------------------------

def test_support_only_is_flagged_for():
    result = category([item(Stance.SUPPORTS)])
    assert result["covered_by_fresh_support"] is True
    assert result["covered_by_fresh_contradiction"] is False
    assert result["direction"] == "FOR"


def test_both_directions_are_contested():
    result = category([item(Stance.SUPPORTS, group="a"),
                       item(Stance.CONTRADICTS, group="b")])
    assert result["covered_by_fresh_support"] is True
    assert result["covered_by_fresh_contradiction"] is True
    assert result["direction"] == "CONTESTED"


def test_no_fresh_evidence_is_none():
    result = category([])
    assert result["covered_by_fresh_accepted"] is False
    assert result["covered_by_fresh_support"] is False
    assert result["covered_by_fresh_contradiction"] is False
    assert result["direction"] == "NONE"


# --------------------------------------------------------------------------
# The flags must be unreachable from untrusted evidence
# --------------------------------------------------------------------------

@pytest.mark.parametrize("review_state", [EvidenceReviewState.UNVERIFIED])
def test_unreviewed_evidence_sets_no_flag(review_state):
    """`EvidenceReviewState` has exactly ACCEPTED and UNVERIFIED, so trust is a
    single bit: anything that is not ACCEPTED cannot reach a flag."""
    result = category([item(Stance.SUPPORTS, review_state=review_state),
                       item(Stance.CONTRADICTS, review_state=review_state)])
    assert result["covered_by_fresh_support"] is False
    assert result["covered_by_fresh_contradiction"] is False
    assert result["direction"] == "NONE"


def test_stale_or_disputed_evidence_sets_no_flag():
    result = category([item(Stance.SUPPORTS, stale=True),
                       item(Stance.CONTRADICTS, disputed=True)])
    assert result["covered_by_fresh_support"] is False
    assert result["covered_by_fresh_contradiction"] is False
    assert result["direction"] == "NONE"


def test_neutral_evidence_sets_no_flag():
    result = category([item(Stance.NEUTRAL)])
    assert result["direction"] == "NONE"
    assert result["covered_by_fresh_support"] is False


# --------------------------------------------------------------------------
# The corroboration category can only ever point FOR
# --------------------------------------------------------------------------

def test_corroboration_needs_two_groups_and_only_points_for():
    single = category([item(Stance.SUPPORTS, group="a")], CORROBORATION)
    assert single["covered_by_fresh_accepted"] is False
    assert single["direction"] == "FOR"
    assert single["non_independent"] is True

    paired = category([item(Stance.SUPPORTS, group="a"),
                       item(Stance.SUPPORTS, group="b")], CORROBORATION)
    assert paired["covered_by_fresh_accepted"] is True
    assert paired["direction"] == "FOR"


def test_corroboration_ignores_contradictions():
    result = category([item(Stance.CONTRADICTS, group="a")], CORROBORATION)
    assert result["direction"] == "NONE"
    assert result["covered_by_fresh_contradiction"] is False


# --------------------------------------------------------------------------
# Existing keys are unchanged
# --------------------------------------------------------------------------

def test_existing_keys_keep_their_shape():
    result = category([item(Stance.SUPPORTS)])
    for key in ("category_id", "description", "role", "association", "indicators",
                "limitation", "covered_by_fresh_accepted", "non_independent",
                "fresh_accepted_support_ids", "fresh_accepted_contradiction_ids",
                "independent_source_groups", "matching_evidence",
                "neutral_evidence_ids", "unclassified_evidence_ids"):
        assert key in result
    assert result["fresh_accepted_support_ids"] == sorted(
        result["fresh_accepted_support_ids"])
