"""Interrogative and conditional mood: two cues the guard must not certify.

The guard certifies a stance when a fixed cue phrase appears in text it reads as
an assertion. Two moods were still being read as assertions, and both certified a
direction the sentence does not state:

* **Interrogative.** ``Was the checklist unavailable at the ward round?``
  certified ``SUPPORTS``: a yes/no question asks *whether* the cue holds and
  asserts nothing. ``Did the shift have enough time to review every open item?``
  certified ``CONTRADICTS`` for the same reason.
* **Conditional.** ``If the checklist was unavailable, the team should have
  escalated.`` certified ``SUPPORTS``: the antecedent *proposes* the cue, and the
  rest of the sentence is about what follows from it.

Both rules are written to abstain and never to flip a stance: a question or a
conditional does not state the opposite of the cue either, and the module's
charter forbids reading one direction out of the other.

Each rule carries neighbours that must keep certifying, so a later edit cannot
widen it quietly into ordinary statements. The interrogative boundary is the
sentence: a `?` in one sentence does not reach a cue in another, which is what
keeps ``The checklist was unavailable all morning. Was the binder at the desk?``
readable. The conditional boundary is the cue's own clause: a conditional
*elsewhere* in the sentence leaves a main-clause assertion intact, which is what
keeps both ``If the ward was busy, the checklist was unavailable.`` and the
corpus row ``It was not raining when the binder was missing.`` readable.

The 53-row negation corpus, the slice 18 pins, the verb-negation file and the
twelfth attack-surface batch are the existing contract and are re-run unchanged.
"""
import pytest

from app.models import Stance
from app.semantic_guard import reviewed_relation, reviewed_relation_details


# --- Rule I: a cue inside a question asserts nothing -------------------------
#
# ``would_be_stance`` is the direction the same sentence certified before the
# rule existed. It is here so the test can state the failure in both directions:
# the guard must not return it, and it must not return its opposite either.

CUES_IN_QUESTIONS = [
    # The measured rows from the benchmark's ``cue-in-question`` class.
    ("Was the checklist unavailable at the ward round?",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    ("Did anyone see that the binder was missing?",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    ("Did the shift have enough time to review every open item?",
     "TIME_PRESSURE", Stance.CONTRADICTS),
    ("Was anyone told that the checklist was unavailable?",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    ("Has the ward been short staffed this week?",
     "STAFFING_CONSTRAINTS", Stance.SUPPORTS),
    # New inputs: a wh-question, a modal question, and a question whose cue
    # sits in the complement of the interrogative verb.
    ("Why was the checklist unavailable during the ward round?",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    ("Should the clerk have logged that the system timed out?",
     "PMS_SYSTEM_ISSUE", Stance.SUPPORTS),
    ("Was there anyone who said the ward was short staffed?",
     "STAFFING_CONSTRAINTS", Stance.SUPPORTS),
]


@pytest.mark.parametrize("sentence,hypothesis_id,would_be_stance", CUES_IN_QUESTIONS)
def test_a_cue_in_a_question_abstains(sentence, hypothesis_id, would_be_stance):
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "CUE_IN_QUESTION", detail
    # Abstention only: neither the direction the question would have certified
    # nor the inverted one is returned.
    opposite = (Stance.CONTRADICTS if would_be_stance is Stance.SUPPORTS
                else Stance.SUPPORTS)
    assert detail["relation"] is not would_be_stance, detail
    assert detail["relation"] is not opposite, detail


# The boundary this rule chose: the *sentence*, not the whole quote. A `?` in one
# sentence does not reach a cue in a neighbouring sentence, so a statement next to
# a question — or an attributed assertion next to one — keeps certifying.

QUESTION_NEIGHBOURS = [
    # A real statement: the rule must not touch a flat assertion.
    ("The checklist was unavailable during the ward round.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    # Statement followed by a question; the cue is in the statement.
    ("The checklist was unavailable all morning. Was the binder at the desk?",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    # The complement of the hybrid: a question followed by a statement.
    ("Was the ward quiet? The checklist was unavailable.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    # A quotation that is itself an assertion, followed by a question about it.
    ("'The binder was missing,' the clerk said. Was that recorded?",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    # A question mark inside a quoted question does not reach the assertion that
    # follows it in the reporter's own sentence.
    ("The auditor asked 'was it missing?' and wrote that the binder was missing.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
]


@pytest.mark.parametrize("sentence,hypothesis_id,expected", QUESTION_NEIGHBOURS)
def test_the_question_rule_stops_at_the_sentence_boundary(sentence,
                                                          hypothesis_id,
                                                          expected):
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] == expected, (sentence, detail)
    assert detail["reason_code"] is None, (sentence, detail)


def test_a_tag_question_is_read_as_a_question():
    """Characterisation of the boundary: a tag question is still interrogative.

    ``The checklist was unavailable, wasn't it?`` is one interrogative sentence,
    so the cue inside it is not asserted. The rule keys on the sentence's own
    terminator rather than on word order, which is what keeps the boundary
    mechanical; a reader who treats the tag as an assertion would label this row
    differently, and this test records the choice rather than hiding it.
    """
    detail = reviewed_relation_details("The checklist was unavailable, wasn't it?",
                                       "CHECKLIST_UNAVAILABLE")
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "CUE_IN_QUESTION", detail


def test_a_quotation_inside_a_question_is_not_an_assertion():
    """A question governing a quoted cue asserts nothing about the world.

    The auditor may or may not have written it; the sentence asks which.
    """
    detail = reviewed_relation_details(
        "Did the auditor write: 'the binder was missing'?", "CHECKLIST_UNAVAILABLE")
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "CUE_IN_QUESTION", detail


# --- Rule II: a cue inside a conditional clause asserts nothing --------------
#
# Reversal, recorded here because an earlier version of this file pinned the
# opposite for the *consequent* of a fronted conditional: "If the ward was busy,
# the checklist was unavailable." certified SUPPORTS, on the reading that the
# main clause is asserted and the if-clause is context. That reading is decided
# by the comma, not by scope: the same sentence with the cue in the antecedent
# abstained, so the verdict depended on which side of the punctuation the cue
# fell on. A consequent holds only when its antecedent does, so a policy-evidence
# guard that commits on it is asserting a hypothetical. Both positions now
# abstain with ``CONDITIONAL_CUE``, and the anti-over-abstention guarantee this
# file used to make with those two rows is made instead by the temporal and
# causal neighbours below, which are not conditionals at all.


CONDITIONAL_CUES = [
    # The benchmark's ``conditional`` class.
    ("If the checklist was unavailable, the team should have escalated.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    ("If the system was unavailable, the clerk would have logged it.",
     "PMS_SYSTEM_ISSUE", Stance.SUPPORTS),
    ("Unless the checklist was unavailable, the audit proceeds as planned.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    # New inputs: each marker in the requirement, and each in a different
    # hypothesis so the rule is not keyed to one cue inventory.
    ("When the checklist was unavailable, the team improvised a verbal handover.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    ("Provided that the checklist was unavailable, the audit was postponed.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    ("If the ward was short staffed, agency staff would cover the shift.",
     "STAFFING_CONSTRAINTS", Stance.SUPPORTS),
    ("When the shift ran out of time, the review was abandoned.",
     "TIME_PRESSURE", Stance.SUPPORTS),
    ("Even if the binder was missing, the appointment went ahead.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    # The consequent of a fronted conditional. Previously asserted; reversed,
    # see the note above Rule II.
    ("If the ward was busy, the checklist was unavailable.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    ("If the audit was postponed, the checklist was available.",
     "CHECKLIST_UNAVAILABLE", Stance.CONTRADICTS),
]


@pytest.mark.parametrize("sentence,hypothesis_id,would_be_stance", CONDITIONAL_CUES)
def test_a_cue_in_a_conditional_clause_abstains(sentence, hypothesis_id,
                                                would_be_stance):
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "CONDITIONAL_CUE", detail
    opposite = (Stance.CONTRADICTS if would_be_stance is Stance.SUPPORTS
                else Stance.SUPPORTS)
    assert detail["relation"] is not would_be_stance, detail
    assert detail["relation"] is not opposite, detail


CONDITIONAL_NEIGHBOURS = [
    # Corpus row ``CU-WEATHER-WHEN``: a mid-sentence temporal ``when`` clause is
    # not a conditional opening the sentence, and the cue inside it certifies.
    ("It was not raining when the binder was missing.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    # A cue asserted *before* a trailing when-clause.
    ("The checklist was unavailable when the ward round began.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
    # A causal clause is not a conditional clause; it states its content.
    ("The team escalated the incident because the checklist was unavailable.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS),
]


@pytest.mark.parametrize("sentence,hypothesis_id,expected", CONDITIONAL_NEIGHBOURS)
def test_the_conditional_rule_leaves_a_main_clause_assertion_alone(
        sentence, hypothesis_id, expected):
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] == expected, (sentence, detail)
    assert detail["reason_code"] is None, (sentence, detail)


def test_a_conditional_governs_every_consequent_clause():
    """The marker scopes the whole consequent, not only its first clause.

    Both cues sit after the comma; both are withheld, and both are cited so the
    abstention is visible in the trace rather than silent.
    """
    sentence = ("If the checklist was unavailable, the binder was missing, and "
                "the audit was postponed.")
    detail = reviewed_relation_details(sentence, "CHECKLIST_UNAVAILABLE")
    assert detail["relation"] is None, detail
    assert detail["reason_code"] == "CONDITIONAL_CUE", detail
    assert len(detail["cue_ids"]) >= 2, detail


# --- Both rules share the guard's existing invariants ------------------------

ABSTAINING_ROWS = ([(row[0], row[1]) for row in CUES_IN_QUESTIONS]
                   + [("The checklist was unavailable, wasn't it?",
                       "CHECKLIST_UNAVAILABLE"),
                      ("Did the auditor write: 'the binder was missing'?",
                       "CHECKLIST_UNAVAILABLE")]
                   + [(row[0], row[1]) for row in CONDITIONAL_CUES])


@pytest.mark.parametrize("sentence,hypothesis_id", ABSTAINING_ROWS)
def test_an_abstaining_row_still_cites_the_cue_it_read(sentence, hypothesis_id):
    """An abstention that matched nothing would be safe for the wrong reason."""
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] is None, detail
    assert detail["cue_ids"], (sentence, detail)
    assert all(cue_id.startswith(hypothesis_id + ".")
               for cue_id in detail["cue_ids"]), detail["cue_ids"]


@pytest.mark.parametrize("sentence,hypothesis_id", ABSTAINING_ROWS)
def test_every_new_row_is_deterministic_and_pure(sentence, hypothesis_id):
    first = reviewed_relation_details(sentence, hypothesis_id)
    assert reviewed_relation(sentence, hypothesis_id) == first["relation"]
    assert reviewed_relation_details(sentence, hypothesis_id) == first
    first["cue_ids"].append("injected")
    assert "injected" not in reviewed_relation_details(sentence, hypothesis_id)["cue_ids"]


@pytest.mark.parametrize(
    "sentence,hypothesis_id",
    [(row[0], row[1]) for row in QUESTION_NEIGHBOURS + CONDITIONAL_NEIGHBOURS],
)
def test_a_certifying_neighbour_reports_no_reason_code(sentence, hypothesis_id):
    assert reviewed_relation_details(sentence, hypothesis_id)["reason_code"] is None


def test_a_plain_statement_is_untouched_by_both_rules():
    assert reviewed_relation("The checklist was unavailable.",
                             "CHECKLIST_UNAVAILABLE") == Stance.SUPPORTS
    assert reviewed_relation("The checklist was available.",
                             "CHECKLIST_UNAVAILABLE") == Stance.CONTRADICTS


def test_a_hedge_after_the_cue_withholds_too():
    """Word order decided this before: "… was unavailable, probably" certified.

    The cause was structural, not lexical: `_cue_prefix_clause` returns the text
    *before* the cue, so the hedge reader could never see words that follow it.
    """
    from app.semantic_guard import reviewed_relation_details

    assert reviewed_relation_details(
        "The checklist was unavailable, probably.", "CHECKLIST_UNAVAILABLE"
    )["relation"] is None


def test_a_hedge_about_the_reason_does_not_withhold_the_cue():
    """The neighbour: "and probably for good reason" hedges the reason, not the cue."""
    from app.models import Stance
    from app.semantic_guard import reviewed_relation_details

    assert reviewed_relation_details(
        "The checklist was unavailable, and probably for good reason.", "CHECKLIST_UNAVAILABLE"
    )["relation"] == Stance.SUPPORTS
