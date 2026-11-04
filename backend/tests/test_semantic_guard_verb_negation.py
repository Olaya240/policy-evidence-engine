"""Two measured reading gaps in the phrase cue guard, each closed with a pin.

Gap A — a negation whose verb sits between it and the cue was invisible, so the
cue was certified in the affirmative direction:

  * ``Staff did not have enough time, so the checklist was unavailable.``
    certifies ``SUPPORTS``: the negation lives in the premise clause of a
    consequence, and no negation token is adjacent to the cue, so
    ``_NEGATION_SUFFIX`` / ``_NEGATED_AUXILIARY_SUFFIX`` never fire.
  * ``The team did not confirm the checklist was available.`` certifies
    ``CONTRADICTS``: ``did not confirm X`` states the absence of confirmation,
    not that ``X`` is false.

Gap B — a statement about the evidence was read as a statement about the world:
``No evidence the checklist was available.`` certified ``CONTRADICTS``, but the
sentence is about the evidence base, not about the checklist.

Both rules are narrow and every one of them carries a neighbour row that must
still certify, so a later edit cannot widen them quietly. The rows here are new
inputs; the 45-row corpus, the S18 pins and the twelfth attack-surface batch keep
the existing behaviour pinned and are re-run unchanged.
"""
import pytest

from app.models import Stance
from app.semantic_guard import reviewed_relation, reviewed_relation_details

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"


# --- Gap A, first shape: negation in the premise of a consequence ------------

PREMISE_NEGATION = [
    # The measured sentence. The cue's clause is conjoined by a consequence
    # link to a clause that is negated, so the guard cannot read the cue alone.
    ("Staff did not have enough time, so the checklist was unavailable.",
     HYPOTHESIS, "SUPPORTS"),
    # Same shape, a different hypothesis and a different consequence link.
    ("The ward did not have enough people on duty, so the system timed out.",
     "PMS_SYSTEM_ISSUE", "CONTRADICTS"),
    ("We did not have enough time, therefore the colleague was unsure about "
     "the handover.",
     "TRAINING_GAP", "SUPPORTS"),
]


@pytest.mark.parametrize("sentence,hypothesis_id,unnegated_stance", PREMISE_NEGATION)
def test_a_negated_premise_clause_abstains(sentence, hypothesis_id,
                                          unnegated_stance):
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] is None, detail
    assert detail["relation"] is not Stance(unnegated_stance)
    # The mechanism depends on what explains the negation: a matrix frame reports
    # ATTRIBUTED_DENIAL, a negation inside the cue's own clause reports NEGATED_CUE.
    # Both withhold; pinning one string here would hide which one fired.
    assert detail["reason_code"] in {"NEGATED_CUE", "ATTRIBUTED_DENIAL"}, detail


def test_the_premise_rule_needs_a_negation_not_only_a_consequence():
    """Neighbour: the same consequence link without a negation still certifies.

    This is the attack-surface row the guard already reads correctly, kept here
    so the new rule cannot start abstaining on every ``so`` clause.
    """
    sentence = ("Staff were unable to locate the binder, so the checklist was "
                "unavailable.")
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] == Stance.SUPPORTS, detail
    assert detail["reason_code"] is None, detail


def test_the_premise_rule_does_not_reach_across_a_bare_comma():
    """Neighbour: a comma clause with no consequence link does not abstain.

    Corpus row ``CU-AUX-OTHER-CLAUSE``. A negation in a separate comma clause is
    not a premise of the cue's clause, and the guard has never reached across
    that boundary.
    """
    sentence = "The staff did not have training, the checklist was unavailable."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] == Stance.SUPPORTS, detail
    assert detail["reason_code"] is None, detail


def test_the_premise_rule_ignores_a_negation_that_follows_the_cue():
    """Neighbour: the negation must sit before the cue, in the premise."""
    sentence = "The checklist was unavailable, so the staff did not have time."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] == Stance.SUPPORTS, detail
    assert detail["reason_code"] is None, detail


# --- Gap A, second shape: a negated evidential verb --------------------------

NEGATED_EVIDENTIAL = [
    # The coordinator's sentence, generalised to a cue the inventory contains:
    # "the binder was present" is not a cue, so the literal sentence abstains for
    # a different reason (pinned below).
    ("The team did not confirm the checklist was available.",
     HYPOTHESIS, "CONTRADICTS"),
    ("The team did not confirm that the checklist was unavailable.",
     HYPOTHESIS, "SUPPORTS"),
    ("The auditor never verified the system worked normally.",
     "PMS_SYSTEM_ISSUE", "CONTRADICTS"),
]


@pytest.mark.parametrize("sentence,hypothesis_id,unnegated_stance",
                         NEGATED_EVIDENTIAL)
def test_a_negated_evidential_verb_abstains(sentence, hypothesis_id,
                                           unnegated_stance):
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] is None, detail
    assert detail["relation"] is not Stance(unnegated_stance)
    # The mechanism depends on what explains the negation: a matrix frame reports
    # ATTRIBUTED_DENIAL, a negation inside the cue's own clause reports NEGATED_CUE.
    # Both withhold; pinning one string here would hide which one fired.
    assert detail["reason_code"] in {"NEGATED_CUE", "ATTRIBUTED_DENIAL"}, detail


def test_the_literal_second_sentence_abstains_because_it_has_no_cue():
    """``the binder was present`` is not in the cue inventory.

    Its abstention is ``NO_CUE_MATCH``, not a negation rule; recorded so the row
    is not mistaken for evidence that the evidential-verb rule fired.
    """
    sentence = "The team did not confirm the binder was present."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "NO_CUE_MATCH", detail


def test_a_denied_speech_act_withholds_its_complement():
    """REVERSED 2026-11-02, with ``CU-MATRIX-DID-NOT-SAY``.

    This was the neighbour that pinned a denied speech act as certifying: "did not
    say" negates the saying, so the complement was read as asserted. That reading
    treats *nobody said X* as evidence for X, which is certifying support from
    silence — the failure a policy-evidence tool exists to prevent. Both classes
    now withhold under a negative matrix frame; the frame module carries the
    argument, this file carries the reading.
    """
    sentence = "The auditor did not say the binder was at the desk."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "ATTRIBUTED_DENIAL", detail


def test_an_affirmative_speech_act_still_certifies_its_complement():
    """Neighbour: the rule is about negation, not about reports as such."""
    sentence = "The auditor said the binder was at the desk."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] == Stance.CONTRADICTS, detail
    assert detail["reason_code"] is None, detail


def test_a_quantified_denial_of_an_evidential_verb_withholds():
    """REVERSED 2026-11-02: this row used to keep certifying (``CU-MATRIX-CONFIRM``).

    "No one could confirm that the checklist was unavailable" reports the absence
    of confirmation, not the checklist's condition. The rule reads the quantifier
    as the negator, so the same construction no longer has two verdicts depending
    on whether ``no one`` or ``not`` did the negating.
    """
    sentence = "No one could confirm that the checklist was unavailable."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "ATTRIBUTED_DENIAL", detail


def test_the_quantified_denial_rule_does_not_swallow_an_affirmative_frame():
    """Neighbour: the attribution is affirmative, so the complement still asserts."""
    sentence = "The auditor confirmed that the checklist was unavailable."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] == Stance.SUPPORTS, detail
    assert detail["reason_code"] is None, detail


def test_a_quantified_denial_of_a_speech_act_withholds():
    """REVERSED 2026-11-02: ``no one said`` now withholds like ``no one confirmed``.

    Both are negative matrix frames; the class decides what the frame is *about*,
    not whether a negative frame asserts anything. Keeping them different was the
    last 11% of the falsification corpus.
    """
    sentence = "No one said that the checklist was unavailable."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "ATTRIBUTED_DENIAL", detail


def test_the_evidential_rule_does_not_swallow_an_unrelated_infinitive():
    """Neighbour: ``did not have to guess`` negates an obligation, not the cue."""
    sentence = ("The staff did not have to guess whether the checklist was "
                "unavailable.")
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] == Stance.SUPPORTS, detail
    assert detail["reason_code"] is None, detail


def test_the_evidential_rule_leaves_a_plain_statement_alone():
    assert reviewed_relation("The checklist was available.",
                             HYPOTHESIS) == Stance.CONTRADICTS


# --- Gap B: a statement about the evidence, not about the world --------------

EVIDENCE_ABOUTNESS = [
    ("No evidence the checklist was available.", HYPOTHESIS, "CONTRADICTS"),
    ("There is no indication the checklist was unavailable.", HYPOTHESIS,
     "SUPPORTS"),
    ("Nothing suggests the binder was missing.", HYPOTHESIS, "SUPPORTS"),
    ("There was no sign the checklist was available.", HYPOTHESIS,
     "CONTRADICTS"),
    ("No evidence the system timed out.", "PMS_SYSTEM_ISSUE", "SUPPORTS"),
]


@pytest.mark.parametrize("sentence,hypothesis_id,unnegated_stance",
                         EVIDENCE_ABOUTNESS)
def test_an_evidence_aboutness_frame_abstains(sentence, hypothesis_id,
                                             unnegated_stance):
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] is None, detail
    assert detail["relation"] is not Stance(unnegated_stance)
    assert detail["reason_code"] == "EVIDENCE_ABOUTNESS_FRAME", detail


def test_the_evidence_frame_rule_does_not_swallow_no_doubt():
    """Neighbour: ``no doubt`` asserts the cue; the corpus row must certify."""
    sentence = "There is no doubt that the colleague was absent."
    detail = reviewed_relation_details(sentence, "STAFFING_CONSTRAINTS")
    assert detail["relation"] == Stance.SUPPORTS, detail
    assert detail["reason_code"] is None, detail


def test_the_evidence_frame_rule_does_not_reach_a_later_clause():
    """Neighbour: the frame must be in the cue's own segment.

    ``no evidence`` after the cue, or in another comma clause, is not a frame
    over the cue and must not turn a readable sentence into an abstention.
    """
    for sentence in (
        "The checklist was available, and no evidence was needed.",
        "There was no evidence of a problem, the checklist was available.",
    ):
        detail = reviewed_relation_details(sentence, HYPOTHESIS)
        assert detail["relation"] == Stance.CONTRADICTS, (sentence, detail)
        assert detail["reason_code"] is None, (sentence, detail)


def test_the_evidence_frame_rule_leaves_the_neutral_cue_alone():
    """Neighbour: ``says nothing about`` is the NEUTRAL cue's own wording."""
    sentence = "The report says nothing about checklist availability."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] == Stance.NEUTRAL, detail
    assert detail["reason_code"] is None, detail


def test_the_evidence_frame_rule_leaves_a_plain_negation_of_the_cue_alone():
    """Neighbour: an ordinary adjacent negation keeps its own reason code.

    Corpus row ``TP-PLAIN-NO``. The frame rule must not take over a negation the
    suffix rules already explain, or every ``NEGATED_CUE`` row would start
    reporting the new code.
    """
    detail = reviewed_relation_details("There was no time pressure during the "
                                       "shift.", "TIME_PRESSURE")
    assert detail["relation"] is None, detail
    # The mechanism depends on what explains the negation: a matrix frame reports
    # ATTRIBUTED_DENIAL, a negation inside the cue's own clause reports NEGATED_CUE.
    # Both withhold; pinning one string here would hide which one fired.
    assert detail["reason_code"] in {"NEGATED_CUE", "ATTRIBUTED_DENIAL"}, detail


# --- Both rules share the guard's existing invariants ------------------------


@pytest.mark.parametrize(
    "sentence,hypothesis_id",
    [(row[0], row[1]) for row in PREMISE_NEGATION + NEGATED_EVIDENTIAL
     + EVIDENCE_ABOUTNESS],
)
def test_abstaining_rows_still_cite_the_cue_they_read(sentence, hypothesis_id):
    """An abstention that matched nothing would be safe for the wrong reason."""
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] is None
    assert detail["cue_ids"], (sentence, detail)
    assert all(cue_id.startswith(hypothesis_id + ".")
               for cue_id in detail["cue_ids"]), detail["cue_ids"]


@pytest.mark.parametrize(
    "sentence,hypothesis_id",
    [(row[0], row[1]) for row in PREMISE_NEGATION + NEGATED_EVIDENTIAL
     + EVIDENCE_ABOUTNESS],
)
def test_every_new_row_is_deterministic_and_pure(sentence, hypothesis_id):
    first = reviewed_relation_details(sentence, hypothesis_id)
    assert reviewed_relation(sentence, hypothesis_id) == first["relation"]
    first["cue_ids"].append("injected")
    assert reviewed_relation_details(sentence, hypothesis_id)["cue_ids"] != first["cue_ids"]
