"""Twelfth probe batch: the guard's reading of adversarial but grammatical English.

Each row states the sentence, the stance a careful reader would take, and what the guard
actually returns. Where the guard is *safer* than the row (it abstains) the row records an
abstention, not a pass: abstention is the documented behaviour under doubt. The dangerous
direction is the other one — certifying a stance the sentence does not support.
"""

from __future__ import annotations

import pytest

from app.models import Stance
from app.semantic_guard import reviewed_relation_details

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"

ABSTAINS = [
    # Quantifier negation over the cue: the guard refuses to certify, which is safe.
    "Nobody on the team checked whether the checklist was available.",
    "None of the staff confirmed the binder was present.",
    "Neither the checklist nor the binder was available.",
    "The checklist might as well not have existed.",
    "There was no checklist and no binder.",
    "The checklist wasn't available at all.",
    "The checklist was not available; the binder was, however, present.",
]


@pytest.mark.parametrize("sentence", ABSTAINS)
def test_doubtful_negation_abstains(sentence):
    assert reviewed_relation_details(sentence, HYPOTHESIS)["relation"] is None


def test_a_cue_in_a_consequence_clause_still_supports():
    sentence = "Staff were unable to locate the binder, so the checklist was unavailable."
    assert reviewed_relation_details(sentence, HYPOTHESIS)["relation"] == Stance.SUPPORTS


def test_a_concessive_negation_does_not_flip_the_cue():
    sentence = "The checklist was available, though not for long."
    assert reviewed_relation_details(sentence, HYPOTHESIS)["relation"] == Stance.CONTRADICTS


# FIXED. "It is not true that X was unavailable" means X *was* available. The guard used
# to certify SUPPORTS here — the sentence denies the hypothesis and was counted as support
# for it — because the negation sat in a frame ("not true that") that neither the adjacent
# suffix nor the subject-quantifier rule could see. It now recognises the frame and
# abstains: the guard does not flip a negative cue into the opposite stance anywhere, so
# abstention is the behaviour consistent with the rest of the module.
def test_a_negated_propositional_frame_abstains():
    sentence = "It is not true that the checklist was unavailable."
    assert reviewed_relation_details(sentence, HYPOTHESIS)["relation"] is None


def test_the_frame_rule_does_not_swallow_a_plain_statement():
    assert reviewed_relation_details("The checklist was unavailable.", HYPOTHESIS)["relation"] == Stance.SUPPORTS


# FIXED. "No evidence the checklist was available" is a statement about the evidence,
# not about the checklist. The guard used to read the cue and certify CONTRADICTS; a
# careful reader would abstain. It now recognises the evidence-aboutness frame and
# abstains with its own reason code.
def test_a_statement_about_evidence_abstains():
    sentence = "No evidence the checklist was available."
    detail = reviewed_relation_details(sentence, HYPOTHESIS)
    assert detail["relation"] is None
    assert detail["reason_code"] == "EVIDENCE_ABOUTNESS_FRAME"
