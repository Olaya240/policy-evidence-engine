"""Slice 18 pins for the phrase cue guard (`app/semantic_guard.py`).

The guard is a fixed phrase inventory plus a narrow negation/contrast filter, not
general NLP. These tests pin the properties the review decision leans on:

1. cue matching is deterministic and hands back fresh trace objects;
2. an absent cue yields ``ASSESSMENT_REVIEW`` and never a verdict;
3. the guard never turns a ``CONTRADICTS`` proposal into ``SUPPORTS`` (or back);
4. disabling the guard is explicit and trace-marked;
5. no input mutates the ``Evidence``/records it is given.

Two tests are characterisations, not pins: they record where the guard's decision
contradicts the stance it reports (see ``S18.md``). The ``xfail(strict=True)``
test is the defect stated as a property, so a fix flips it to a failure that must
be removed with the defect.
"""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.engine import AssessmentEngine
from app.mock_provider import MockProvider
from app.models import EvidenceReviewState, Record, Stance
from app.semantic_guard import reviewed_relation, reviewed_relation_details

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)


def _record(record_id, quote, *, department="Front Office"):
    return Record(
        id=record_id,
        timestamp=datetime(2026, 10, 30, tzinfo=timezone.utc),
        department=department,
        text=quote,
        tags=[],
    )


def _claim(quote, stance, hypothesis_id, *, semantic_guard=True):
    record = _record("SLICE18-1", quote)
    provider = MockProvider(assessment_overrides={hypothesis_id: [
        {"source_record_id": record.id, "quote": quote, "stance": stance,
         "rationale": "synthetic slice 18 fixture"},
    ]})
    engine = AssessmentEngine(provider, semantic_guard=semantic_guard, clock=lambda: NOW)
    claim = engine.assess_hypothesis([record], hypothesis_id)
    return claim, claim["explanation_trace"]["semantic_guard"]["decisions"][0]


def test_cue_matching_is_deterministic_and_returns_fresh_trace_objects():
    cases = [
        ("The checklist was unavailable.", "CHECKLIST_UNAVAILABLE"),
        ("We did not have enough time to review every open item.", "TIME_PRESSURE"),
        ("The property system timed out while saving the handover notes.", "PMS_SYSTEM_ISSUE"),
        ("There is no relevant phrase here.", "STAFFING_CONTRADICTS_NEVER"),
        ("The checklist was unavailable, but available now.", "CHECKLIST_UNAVAILABLE"),
    ]
    for quote, hypothesis_id in cases:
        first = reviewed_relation_details(quote, hypothesis_id)
        # The relation is read from a set of matched stances; a set with one
        # member must still yield the same value on every call.
        for _ in range(25):
            assert reviewed_relation_details(quote, hypothesis_id) == first
            assert reviewed_relation(quote, hypothesis_id) == first["relation"]
        # Sorted cue ids keep the row stable across phrase-inventory order.
        assert first["cue_ids"] == sorted(first["cue_ids"])
        # Fresh containers: a caller editing the returned row cannot poison the
        # next decision for the same text.
        assert reviewed_relation_details(quote, hypothesis_id) is not first
        first["cue_ids"].append("injected")
        assert "injected" not in reviewed_relation_details(quote, hypothesis_id)["cue_ids"]


def test_absent_cue_yields_assessment_review_and_never_a_verdict():
    quote = "Nothing in this record addresses the question."
    for hypothesis_id in ("CHECKLIST_UNAVAILABLE", "TRAINING_GAP",
                          "STAFFING_CONSTRAINTS", "PMS_SYSTEM_ISSUE", "TIME_PRESSURE"):
        detail = reviewed_relation_details(quote, hypothesis_id)
        assert detail == {"relation": None, "cue_ids": [], "reason_code": "NO_CUE_MATCH"}
        claim, row = _claim(quote, "SUPPORTS", hypothesis_id)
        assert row["review_state"] == EvidenceReviewState.UNVERIFIED.value
        assert row["semantic_relation"] is None
        assert row["reason_code"] == "NO_CUE_MATCH"
        assert row["decision_source"] == "ASSESSMENT_REVIEW"
        assert claim["evidence"][0]["review_state"] == EvidenceReviewState.UNVERIFIED.value
        # No directional cue means no directional weight.
        assert claim["evidence_score"] == 0.0

    # An unknown hypothesis is refused the same way, never promoted.
    assert reviewed_relation_details(quote, "NOT_A_HYPOTHESIS") == {
        "relation": None, "cue_ids": [], "reason_code": "UNKNOWN_HYPOTHESIS"
    }


@pytest.mark.parametrize(
    "quote,hypothesis_id,proposed,reported",
    [
        ("The checklist was unavailable.", "CHECKLIST_UNAVAILABLE",
         Stance.CONTRADICTS, Stance.SUPPORTS),
        ("The checklist was available.", "CHECKLIST_UNAVAILABLE",
         Stance.SUPPORTS, Stance.CONTRADICTS),
        ("The system worked normally.", "PMS_SYSTEM_ISSUE",
         Stance.SUPPORTS, Stance.CONTRADICTS),
    ],
)
def test_guard_never_flips_the_proposed_stance(quote, hypothesis_id, proposed, reported):
    claim, row = _claim(quote, proposed.value, hypothesis_id)
    assert reviewed_relation(quote, hypothesis_id) == reported
    # The proposal keeps the direction it came with ...
    assert row["proposed_stance"] == proposed.value
    assert claim["evidence"][0]["stance"] == proposed.value
    # ... while the disagreement is recorded, not acted on.
    assert row["semantic_relation"] == reported.value
    assert row["review_state"] == EvidenceReviewState.UNVERIFIED.value
    assert row["reason_code"] == "CUE_MISMATCHES_PROPOSAL"
    # A mismatch is retained for review and carries no directional weight.
    assert claim["evidence_score"] == 0.0


def test_disabling_the_guard_is_explicit_and_trace_marked():
    quote = "Nothing in this record addresses the question."
    assert AssessmentEngine().semantic_guard is True

    claim, row = _claim(quote, "SUPPORTS", "STAFFING_CONSTRAINTS", semantic_guard=False)
    trace = claim["explanation_trace"]["semantic_guard"]
    assert trace["enabled"] is False
    assert trace["rule_set_version"] == "phrase-guard-v1"
    assert row["guard_enabled"] is False
    assert row["semantic_relation"] is None
    assert row["cue_ids"] == []
    assert row["reason_code"] == "GUARD_DISABLED_BY_ENGINE_CONFIGURATION"
    assert row["decision_source"] == "ASSESSMENT_REVIEW"
    # The unguarded baseline is the old default, and it is labelled as such
    # rather than silently presented as a verified cue match.
    assert row["review_state"] == EvidenceReviewState.ACCEPTED.value
    assert claim["evidence"][0]["review_state"] == EvidenceReviewState.ACCEPTED.value

    guarded_claim, guarded_row = _claim(quote, "SUPPORTS", "STAFFING_CONSTRAINTS")
    assert guarded_claim["explanation_trace"]["semantic_guard"]["enabled"] is True
    assert guarded_row["review_state"] != row["review_state"]


def test_inputs_are_not_mutated_by_guard_or_review():
    quote = "The checklist was unavailable."
    record = _record("SLICE18-1", quote)
    record_before = deepcopy(record.model_dump(mode="json"))
    overrides = {"CHECKLIST_UNAVAILABLE": [
        {"source_record_id": record.id, "quote": quote, "stance": "SUPPORTS",
         "rationale": "synthetic slice 18 fixture"},
    ]}
    overrides_before = deepcopy(overrides)
    engine = AssessmentEngine(MockProvider(assessment_overrides=overrides), clock=lambda: NOW)

    first = engine.assess_hypothesis([record], "CHECKLIST_UNAVAILABLE")
    second = engine.assess_hypothesis([record], "CHECKLIST_UNAVAILABLE")

    assert record.model_dump(mode="json") == record_before
    assert overrides == overrides_before
    # Identical inputs still produce identical claims; nothing carried over.
    assert first == second

    # `reviewed_relation_details` takes only text, so purity means no sharing and
    # no interning side effects on the caller's strings.
    text = "".join(["The checklist ", "was unavailable."])
    text_before = text
    detail = reviewed_relation_details(text, "CHECKLIST_UNAVAILABLE")
    assert text == text_before
    assert detail["relation"] == Stance.SUPPORTS
    assert reviewed_relation_details(text, "CHECKLIST_UNAVAILABLE") == detail


def test_explicit_negation_before_a_cue_never_certifies_a_relation():
    quote = "We did not have enough time to review every open item."
    detail = reviewed_relation_details(quote, "TIME_PRESSURE")
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "NEGATED_CUE", detail


def test_verb_carried_negation_cannot_certify_the_opposite_stance():
    """The S18 defect, stated as the property the fix must keep.

    Both sentences assert time pressure. The second carries its negation in "did
    not have", away from the cue; before the fix it was certified as a clean
    CONTRADICTS match. It must now refuse to certify that direction at all.
    """
    supported = "There was not enough time to review every open item."
    negated_by_verb = "We did not have enough time to review every open item."

    support_detail = reviewed_relation_details(supported, "TIME_PRESSURE")
    contradict_detail = reviewed_relation_details(negated_by_verb, "TIME_PRESSURE")

    assert support_detail["relation"] == Stance.SUPPORTS
    assert contradict_detail["relation"] is not Stance.CONTRADICTS
    assert contradict_detail["relation"] is None
    assert contradict_detail["reason_code"] == "NEGATED_CUE"

def test_certified_row_cites_an_opposite_stance_cue_without_marking_it_rejected():
    """Characterisation: the row's cited cues contradict the direction it certifies.

    ``cue_ids`` lists every cue whose text appeared, including the ones the
    negation/contrast filter rejected, and the row records no per-cue reason.
    Here the only alternative cue is a CONTRADICTS cue, so the ACCEPTED SUPPORTS
    row cites a cue id from the opposite stance and cannot be told apart from a
    clean single-direction match.
    """
    quote = "There was not enough time to review every open item."
    _, row = _claim(quote, "SUPPORTS", "TIME_PRESSURE")
    assert row["review_state"] == EvidenceReviewState.ACCEPTED.value
    assert row["semantic_relation"] == Stance.SUPPORTS.value
    assert row["reason_code"] == "CUE_MATCHES_PROPOSAL"
    assert row["cue_ids"] == [
        "TIME_PRESSURE.CONTRADICTS.enough_time_to_review_every_open_item",
        "TIME_PRESSURE.SUPPORTS.not_enough_time",
    ]
    certified = f".{row['semantic_relation']}."
    assert any(certified not in cue_id for cue_id in row["cue_ids"]), (
        "the row cites a cue from the stance it did not certify"
    )


# --- a parenthetical inside the cue phrase -----------------------------------
#
# Cue words were joined with ``\s+``, so punctuation ended the phrase: "The
# checklist, as it happens, was unavailable." reported ``NO_CUE_MATCH`` while the
# same sentence with a newline matched. ``NO_CUE_MATCH`` means "the quote says
# nothing about this hypothesis"; these sentences assert the cue directly, so the
# reason code was false and the quote was dropped from the review in silence. The
# matcher now allows a delimited aside between two cue words, with the neighbours
# pinned: every cue word is still required, in order, and a joined match is
# discarded when the aside is really a clause about a cue.

_CUE = "CHECKLIST_UNAVAILABLE.SUPPORTS.checklist_was_unavailable"


def test_a_parenthetical_inside_the_cue_phrase_does_not_break_the_match():
    cases = [
        "The checklist, as it happens, was unavailable.",
        "The checklist (as it happens) was unavailable.",
        "The checklist [as it happens] was unavailable.",
        "The checklist \u2014 as it happens \u2014 was unavailable.",
        "The checklist - as it happens - was unavailable.",
        "The checklist\nwas unavailable.",
    ]
    for quote in cases:
        detail = reviewed_relation_details(quote, "CHECKLIST_UNAVAILABLE")
        assert detail["cue_ids"] == [_CUE], quote
        assert detail["relation"] == Stance.SUPPORTS, (quote, detail)
        assert detail["reason_code"] is None, (quote, detail)


def test_the_aside_cannot_be_the_cue():
    """Only an aside *between* cue words is allowed, never in place of one."""
    for quote in [
        "The checklist, as it happens.",
        "The checklist, as it happens, was checked.",
        "The checklist, as it happens, was fine.",
    ]:
        detail = reviewed_relation_details(quote, "CHECKLIST_UNAVAILABLE")
        assert detail["cue_ids"] == [], (quote, detail)
        assert detail["relation"] is None, (quote, detail)
        assert detail["reason_code"] == "NO_CUE_MATCH", (quote, detail)


def test_a_negation_inside_the_aside_does_not_negate_the_cue():
    """The aside is a comment on the claim, not part of its negation scope."""
    detail = reviewed_relation_details(
        "The checklist, as one might not expect, was unavailable.",
        "CHECKLIST_UNAVAILABLE",
    )
    assert detail["cue_ids"] == [_CUE]
    assert detail["relation"] == Stance.SUPPORTS, detail
    assert detail["reason_code"] is None, detail


def test_a_negation_outside_the_aside_still_abstains():
    """Neighbours of the aside rule: tolerating punctuation must not license
    skipping a negation, which sits here between two cue words but outside any
    aside. The cue's own wording does not occur, so nothing is certified either
    way and the sentence abstains rather than being read as a double negative."""
    detail = reviewed_relation_details(
        "The checklist, as one might expect, was not unavailable.",
        "CHECKLIST_UNAVAILABLE",
    )
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "NO_CUE_MATCH", detail


def test_a_cue_is_not_matched_across_an_aside_that_carries_another_cue():
    """A comma clause about a cue is a clause boundary, not a parenthetical.

    Joining the phrase across it would type the sentence from half of it — the
    clause-level readers (``_cue_prefix_clause``, ``_is_hedged``) split on the
    comma, so they would see the aside as the cue's own context.
    """
    joined = reviewed_relation_details(
        "The checklist, as the binder was missing, was unavailable.",
        "CHECKLIST_UNAVAILABLE",
    )
    assert _CUE not in joined["cue_ids"], joined
    assert joined["cue_ids"] == ["CHECKLIST_UNAVAILABLE.SUPPORTS.binder_was_missing"], joined

    # The same shape with the aside's cue negated: the aside still claims
    # something about the cue, so the phrase is not joined across it and the
    # negated clause is not a cue — the sentence is not read at all.
    negated = reviewed_relation_details(
        "The checklist, the binder was not missing, was unavailable.",
        "CHECKLIST_UNAVAILABLE",
    )
    assert negated["cue_ids"] == [], negated
    assert negated["reason_code"] == "NO_CUE_MATCH", negated


def test_the_guard_reads_verb_classes_from_the_frame_module():
    """One list, in ``app/evidence_frames.py``, for both modules.

    The guard used to carry ``_EVIDENTIAL_VERB`` and ``_REPORTING_VERB``, its own
    second copies of subsets of the frame lexicons (``_EVIDENTIAL_VERB`` had
    already fallen behind ``EVIDENTIAL_VERBS``: no ``check``, no ``substantiate``).
    These assertions fail if either list is reintroduced, and if a verb the frame
    module calls evidential stops withholding the cue.
    """
    from app import evidence_frames, semantic_guard

    assert not hasattr(semantic_guard, "_EVIDENTIAL_VERB")
    assert not hasattr(semantic_guard, "_REPORTING_VERB")
    for verb in sorted(evidence_frames.EVIDENTIAL_VERBS):
        quote = f"The team did not {verb} the checklist was unavailable."
        detail = reviewed_relation_details(quote, "CHECKLIST_UNAVAILABLE")
        assert detail["cue_ids"] == [_CUE], (verb, detail)
        assert detail["relation"] is None, (verb, detail)
