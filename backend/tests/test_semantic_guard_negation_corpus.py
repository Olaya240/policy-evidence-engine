"""Negation corpus for the phrase cue guard (`app/semantic_guard.py`).

``_is_negated`` was widened to catch a negation carried by an auxiliary that
sits between the negation word and the cue ("did not have enough time ...").
That fix is only correct if it fires on true clause negation and stays silent
when ``not`` / ``no`` / ``never`` appears in the sentence without negating the
cue's own clause ("No one said the binder was missing.").

Every row below asserts both the exact relation and the exact reason code:

* ``NEGATED`` rows are true negations of the matched cue. The guard must abstain
  with ``NEGATED_CUE``; certifying either direction inverts the sentence.
* ``CERTIFIES`` rows contain a negation token that does *not* negate the cue
  (contrast, matrix-clause negation with the cue in the complement, a quoted
  "No", a negation inside a NEUTRAL cue's own wording, negation of a different
  cue in the same sentence). They must still certify the cue's stance with no
  reason code.

Rows whose expectation the guard does not meet are left failing on purpose: the
failing assertion is the defect report (see ``ct3/audit/W9-negation-corpus.md``).
"""
import pytest

from app.models import Stance
from app.semantic_guard import reviewed_relation_details

NEGATED = "NEGATED"
CERTIFIES = "CERTIFIES"

# (case id, sentence, hypothesis id, expected relation, expected reason code, kind)
CORPUS = [
    # Quantifier negation scoping over the cue's subject: abstain.
    ("TG-NOBODY-WALKED-2", "Nobody walked through the handover with her.", "TRAINING_GAP", None, "NEGATED_CUE", "NEGATED"),
    ("SC-NO-ONE-WAS-2", "No one was short staffed.", "STAFFING_CONSTRAINTS", None, "NEGATED_CUE", "NEGATED"),
    ("CU-NOBODY-SAW", "Nobody saw the binder was missing.", "CHECKLIST_UNAVAILABLE", None, "NEGATED_CUE", "NEGATED"),
    ("PMS-NO-ONE-NOTICED", "No one noticed the system timed out.", "PMS_SYSTEM_ISSUE", None, "NEGATED_CUE", "NEGATED"),
    ("TP-NOBODY-HAD", "Nobody had time pressure during the shift.", "TIME_PRESSURE", None, "NEGATED_CUE", "NEGATED"),
    # Quantifier over a reporting verb, not the cue: the cue must still certify.
    ("CU-NO-ONE-SAID", "No one said the binder was missing.", "CHECKLIST_UNAVAILABLE", "SUPPORTS", None, "CERTIFIES"),
    ("CU-NOBODY-CLAIMED", "Nobody claimed the checklist was available.", "CHECKLIST_UNAVAILABLE", "CONTRADICTS", None, "CERTIFIES"),
    ("SC-NO-ONE-REPORTED", "No one reported that the colleague was absent.", "STAFFING_CONSTRAINTS", "SUPPORTS", None, "CERTIFIES"),
    # --- true negations: the clause containing the cue is negated -------------
    ("TP-AUX-PLAIN", "We did not have enough time to review every open item.",
     "TIME_PRESSURE", None, "NEGATED_CUE", NEGATED),
    ("TP-AUX-CONTRACTED", "They don't have enough time to review every open item.",
     "TIME_PRESSURE", None, "NEGATED_CUE", NEGATED),
    ("TP-AUX-CURLY", "We didn’t have enough time to review every open item.",
     "TIME_PRESSURE", None, "NEGATED_CUE", NEGATED),
    ("TP-AUX-DOES", "The shift does not have enough time to review every open item.",
     "TIME_PRESSURE", None, "NEGATED_CUE", NEGATED),
    ("TP-AUX-NEVER-HAD", "We never had time pressure on that shift.",
     "TIME_PRESSURE", None, "NEGATED_CUE", NEGATED),
    ("TP-PLAIN-NO", "There was no time pressure during the shift.",
     "TIME_PRESSURE", None, "NEGATED_CUE", NEGATED),
    ("TP-PLAIN-NO-TRAILING", "There was no time pressure at all.",
     "TIME_PRESSURE", None, "NEGATED_CUE", NEGATED),
    ("TP-WITHOUT", "The shift ran the handover without time pressure.",
     "TIME_PRESSURE", None, "NEGATED_CUE", NEGATED),
    ("TP-NEVER-RAN-OUT", "We never ran out of time before the inspection.",
     "TIME_PRESSURE", None, "NEGATED_CUE", NEGATED),
    ("SC-NO-SUBJECT", "No colleague was absent that morning.",
     "STAFFING_CONSTRAINTS", None, "NEGATED_CUE", NEGATED),
    ("SC-NOT-UNDERSTAFFED", "The ward was not understaffed during the night shift.",
     "STAFFING_CONSTRAINTS", None, "NEGATED_CUE", NEGATED),
    ("SC-NEVER-SHORT", "It was never short staffed on the late shift.",
     "STAFFING_CONSTRAINTS", None, "NEGATED_CUE", NEGATED),
    ("SC-NOT-ENOUGH-PEOPLE", "There were not enough people on duty at midnight.",
     "STAFFING_CONSTRAINTS", None, "NEGATED_CUE", NEGATED),
    ("SC-AUX-NEVER-HAD", "The team never had enough people on duty.",
     "STAFFING_CONSTRAINTS", None, "NEGATED_CUE", NEGATED),
    ("SC-AUX-DOES-NOT-HAVE", "The shift does not have enough people on duty tonight.",
     "STAFFING_CONSTRAINTS", None, "NEGATED_CUE", NEGATED),
    ("TG-NO-SUBJECT", "No colleague was unsure about the handover.",
     "TRAINING_GAP", None, "NEGATED_CUE", NEGATED),
    # Negation carried by a quantifier over the cue subject: the sentence denies
    # that the cue happened, but the negation token is not adjacent to the cue.
    ("TG-NOBODY-WALKED", "Nobody walked through the handover with her.",
     "TRAINING_GAP", None, "NEGATED_CUE", NEGATED),
    ("SC-NO-ONE-WAS", "No one was short staffed.",
     "STAFFING_CONSTRAINTS", None, "NEGATED_CUE", NEGATED),

    # --- non-negations: a negation token appears, the cue still stands --------
    ("CU-CONTRAST-ITEM", "The binder was missing, not the checklist.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS, None, CERTIFIES),
    ("CU-MATRIX-NO-ONE", "No one said the binder was missing.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS, None, CERTIFIES),
    ("CU-WEATHER-WHEN", "It was not raining when the binder was missing.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS, None, CERTIFIES),
    ("CU-MATRIX-CONFIRM", "No one could confirm that the checklist was unavailable.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS, None, CERTIFIES),
    ("CU-MATRIX-SUPERVISOR", "No supervisor said the binder was missing.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS, None, CERTIFIES),
    ("CU-QUOTED-NO", "'No,' the auditor said, 'the binder was missing.'",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS, None, CERTIFIES),
    ("CU-AUX-TO-GUESS", "The staff did not have to guess whether the checklist "
     "was unavailable.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS, None, CERTIFIES),
    ("CU-LATER-NO-ONE", "The checklist was unavailable but no one complained.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS, None, CERTIFIES),
    # "did not have" in the same clause but a separate comma clause: the widened
    # auxiliary window must not reach across it to swallow the cue.
    ("CU-AUX-OTHER-CLAUSE", "The staff did not have training, the checklist "
     "was unavailable.",
     "CHECKLIST_UNAVAILABLE", Stance.SUPPORTS, None, CERTIFIES),
    ("CU-CONTRAST-OPPOSITE", "The checklist opened normally, not the binder.",
     "CHECKLIST_UNAVAILABLE", Stance.CONTRADICTS, None, CERTIFIES),
    ("CU-MATRIX-NEVER-CLAIMED", "We never claimed the checklist was available.",
     "CHECKLIST_UNAVAILABLE", Stance.CONTRADICTS, None, CERTIFIES),
    ("CU-MATRIX-DID-NOT-SAY", "The auditor did not say the binder was at the desk.",
     "CHECKLIST_UNAVAILABLE", Stance.CONTRADICTS, None, CERTIFIES),
    # A negation inside the NEUTRAL cue's own fixed wording is not a negation of
    # that cue; the neutral row must still be certified.
    ("CU-NEUTRAL-OWN-NOT", "The note does not address checklist availability.",
     "CHECKLIST_UNAVAILABLE", Stance.NEUTRAL, None, CERTIFIES),
    ("CU-NEUTRAL-SAYS-NOTHING", "The report says nothing about checklist availability.",
     "CHECKLIST_UNAVAILABLE", Stance.NEUTRAL, None, CERTIFIES),
    # One cue negated, a second cue in the same sentence left intact.
    ("SC-MIXED-NEGATED-FIRST", "The ward was not understaffed, the colleague was absent.",
     "STAFFING_CONSTRAINTS", Stance.SUPPORTS, None, CERTIFIES),
    ("SC-MATRIX-DOUBT", "There is no doubt that the colleague was absent.",
     "STAFFING_CONSTRAINTS", Stance.SUPPORTS, None, CERTIFIES),
    ("SC-MATRIX-NOT-CLEAR", "It is not clear why the colleague was absent.",
     "STAFFING_CONSTRAINTS", Stance.SUPPORTS, None, CERTIFIES),
    ("TP-MATRIX-NO-ONE-DISPUTED", "No one disputed that the shift had enough time.",
     "TIME_PRESSURE", Stance.CONTRADICTS, None, CERTIFIES),
    ("TP-CONTRAST-BUT-NOT", "There was enough time to review every open item, "
     "but not for the checklist.",
     "TIME_PRESSURE", Stance.CONTRADICTS, None, CERTIFIES),
    ("TP-MATRIX-NO-ONE-SAID", "No one said time pressure caused the miss.",
     "TIME_PRESSURE", Stance.SUPPORTS, None, CERTIFIES),
    ("PMS-LEADING-CUE", "The system timed out, not the printer.",
     "PMS_SYSTEM_ISSUE", Stance.SUPPORTS, None, CERTIFIES),
    ("PMS-TRAILING-NOT-ONLY", "The system was unavailable, not only slow.",
     "PMS_SYSTEM_ISSUE", Stance.SUPPORTS, None, CERTIFIES),
    ("PMS-MATRIX-NO-ONE-REPORTED", "No one reported that the system was unavailable.",
     "PMS_SYSTEM_ISSUE", Stance.SUPPORTS, None, CERTIFIES),
    ("PMS-MATRIX-NOTHING-SAYS", "Nothing in the notes says the system worked normally.",
     "PMS_SYSTEM_ISSUE", Stance.CONTRADICTS, None, CERTIFIES),
    ("PMS-AUX-TO-BE-TOLD", "The staff did not have to be told twice: the system "
     "timed out.",
     "PMS_SYSTEM_ISSUE", Stance.SUPPORTS, None, CERTIFIES),
    ("TG-MATRIX-NO-ONE-DOUBTED", "No one doubted that the colleague was unsure "
     "about the handover.",
     "TRAINING_GAP", Stance.SUPPORTS, None, CERTIFIES),
    ("TG-MATRIX-NOT-OBVIOUS", "It was not obvious that she needed guidance on the handover.",
     "TRAINING_GAP", Stance.SUPPORTS, None, CERTIFIES),
]

# Two rows document a gap this widening does not close: a quantifier negation
# ("Nobody walked", "No one was") sits before the cue subject rather than next to
# it, so the cue is still certified in the affirmative direction. They are strict
# xfails: when the guard learns quantifier negation they XPASS and fail, which is
# the signal to delete the marker rather than let the gap go quiet.
_KNOWN_UNFIXED: dict[str, str] = {}

_CASES = [
    pytest.param(sentence, hypothesis_id, expected_relation, expected_reason,
                 kind, id=case_id,
                 marks=(pytest.mark.xfail(strict=True, reason=_KNOWN_UNFIXED[case_id])
                        if case_id in _KNOWN_UNFIXED else ()))
    for case_id, sentence, hypothesis_id, expected_relation, expected_reason, kind
    in CORPUS
]


def test_corpus_covers_both_kinds_and_is_large_enough():
    assert len(CORPUS) >= 30, len(CORPUS)
    negations = [row for row in CORPUS if row[5] == NEGATED]
    certifications = [row for row in CORPUS if row[5] == CERTIFIES]
    assert len(negations) >= 12, len(negations)
    assert len(certifications) >= 15, len(certifications)
    # Both contracted forms of the auxiliary negation are exercised, since the
    # widened regex matches the curly apostrophe through a separate branch.
    assert any("don't" in row[1] for row in CORPUS)
    assert any("didn’t" in row[1] for row in CORPUS)


def test_every_corpus_row_actually_matches_a_cue():
    """A row that matched no cue would abstain for the wrong reason."""
    for case_id, sentence, hypothesis_id, _, _, _ in CORPUS:
        detail = reviewed_relation_details(sentence, hypothesis_id)
        assert detail["cue_ids"], (case_id, sentence)
        assert all(cue_id.startswith(hypothesis_id + ".") for cue_id in detail["cue_ids"]), (
            case_id, detail["cue_ids"]
        )


@pytest.mark.parametrize(
    "sentence,hypothesis_id,expected_relation,expected_reason,kind", _CASES
)
def test_negation_corpus_row(sentence, hypothesis_id, expected_relation,
                             expected_reason, kind):
    detail = reviewed_relation_details(sentence, hypothesis_id)
    assert detail["relation"] == expected_relation, (
        f"{kind} row expected relation {expected_relation!r} for {sentence!r}; "
        f"got {detail['relation']!r} with reason {detail['reason_code']!r} "
        f"and cues {detail['cue_ids']!r}"
    )
    assert detail["reason_code"] == expected_reason, (
        f"{kind} row expected reason {expected_reason!r} for {sentence!r}; "
        f"got {detail['reason_code']!r}"
    )
