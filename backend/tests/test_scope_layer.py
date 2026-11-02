"""Unit tests for the sentence-scope layer.

`app/scope_layer.py` was written to close two measured defects in the guard's
reading — an operator in a conditional's consequent being ignored, and an
opposing clause with a pronoun subject vanishing — and until this file it had no
tests of its own. Every rule below is checked against the *structure* it claims
to produce, not only against a verdict: a reader that abstains for the wrong
reason looks identical to a correct one from the outside.

Each rule has a neighbour that must not fire. That is the whole point of the
file: a scope reader earns trust by the readings it leaves alone.
"""

from __future__ import annotations

import pytest

from app.scope_layer import build_scope, split_cue


# --- segmentation -----------------------------------------------------------


def test_a_single_clause_keeps_its_subject_and_predicate():
    scope = build_scope("The checklist was unavailable.")
    assert len(scope.clauses) == 1
    clause = scope.clauses[0]
    assert clause.subject == "The checklist"
    assert clause.number == "singular"
    assert scope.text[clause.end:].strip() in {"", "."}


def test_a_coordination_is_two_clauses_and_the_second_has_its_own_subject():
    scope = build_scope("The binder was missing, and the audit was postponed.")
    assert len(scope.clauses) == 2
    assert scope.clauses[1].subject == "the audit"


def test_a_reported_clause_is_its_own_clause():
    scope = build_scope("The auditor said the binder was missing.")
    reported = [clause for clause in scope.clauses if clause.reported]
    assert len(reported) == 1
    assert reported[0].subject == "the binder"


# --- pronoun resolution -----------------------------------------------------


def test_a_singular_pronoun_resolves_to_the_nearest_singular_subject():
    scope = build_scope("The checklist was unavailable, and the auditor said it "
                        "was available.")
    pronoun = scope.clauses[-1]
    assert pronoun.subject == "it"
    # Nearest-subject resolution picks the auditor, which is what a shallow
    # coreference step should do. The guard does not rely on this answer alone:
    # `_names_cue_subject` asks whether *any* referent could be the cue's
    # subject, which is the only question the verdict depends on.
    assert pronoun.antecedent == "the auditor"


def test_an_invariant_plural_is_not_a_singular_antecedent():
    """"staff" ends in no s and is plural; reading it as singular took "it\".

    This was a live defect: the first version of the reader resolved "it" to
    *staff*, so the derived opposing cue was never built and the sentence
    certified SUPPORTS while saying the opposite.
    """
    scope = build_scope("The checklist was unavailable, and staff say it was "
                        "available.")
    pronoun = scope.clauses[-1]
    assert pronoun.subject == "it"
    assert pronoun.antecedent == "The checklist"


def test_a_plural_pronoun_does_not_resolve_to_a_singular_subject():
    scope = build_scope("The checklist was unavailable, and they say so.")
    pronoun = [clause for clause in scope.clauses if clause.subject == "they"]
    assert pronoun, scope.clauses
    assert pronoun[-1].antecedent is None


# --- conditional scope ------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "If the ward was busy, the checklist was unavailable.",
        "If the checklist was unavailable, the team should have escalated.",
        "Provided that the ward was busy, the checklist was unavailable.",
        "Even if the ward was busy, the checklist was unavailable.",
    ],
)
def test_a_conditional_marker_scopes_the_consequent_and_the_antecedent(sentence):
    """The marker is sentence-scope: both sides of the comma are inside it."""
    scope = build_scope(sentence)
    offset = sentence.casefold().index("was unavailable")
    assert scope.conditional_scope_at(offset) is True


@pytest.mark.parametrize(
    "sentence",
    [
        "The checklist was unavailable when the ward round began.",
        "The team escalated the incident because the checklist was unavailable.",
        "Perhaps the ward was busy, and the checklist was unavailable.",
        "The ward was busy. The checklist was unavailable.",
    ],
)
def test_a_temporal_causal_or_new_sentence_marker_is_not_a_conditional(sentence):
    """Neighbours: three ways to put a marker nearby without governing the cue."""
    scope = build_scope(sentence)
    offset = sentence.casefold().index("was unavailable")
    assert scope.conditional_scope_at(offset) is False


def test_a_conditional_marker_in_the_other_sentence_does_not_reach():
    sentence = "If the ward was busy, staff covered it. The checklist was unavailable."
    scope = build_scope(sentence)
    offset = sentence.casefold().index("was unavailable")
    assert scope.conditional_scope_at(offset) is False


# --- sentence-initial hedge span -------------------------------------------


def test_a_sentence_initial_hedge_reaches_across_a_semicolon():
    sentence = "Perhaps the ward was busy; the checklist was unavailable."
    scope = build_scope(sentence)
    assert scope.hedge_scope_at(sentence.casefold().index("was unavailable")) is True


def test_a_coordinator_gives_the_conjunct_its_own_scope():
    """Neighbour, pinned before this layer existed: "and" separates the span."""
    sentence = "Perhaps the ward was busy, and the checklist was unavailable."
    scope = build_scope(sentence)
    assert scope.hedge_scope_at(sentence.casefold().index("was unavailable")) is False


def test_a_hedge_in_a_later_clause_does_not_reach_backwards():
    sentence = "The checklist was unavailable, and perhaps the ward was busy."
    scope = build_scope(sentence)
    assert scope.hedge_scope_at(sentence.casefold().index("was unavailable")) is False


# --- cue splitting ---------------------------------------------------------


def test_a_cue_splits_into_its_subject_and_its_predicate():
    left, right = split_cue("checklist was unavailable")
    assert left == "checklist"
    assert right == "was unavailable"


def test_a_cue_without_a_subject_is_not_derivable():
    assert split_cue("not enough time") is None


# --- derived occurrences ----------------------------------------------------


def test_a_derived_occurrence_carries_the_scope_of_its_own_clause():
    sentence = "The checklist was unavailable, and others say it was available."
    scope = build_scope(sentence)
    matches = scope.derived_matches("checklist was available")
    assert matches, "the pronoun clause should be an occurrence of the cue"
    assert all(match.attributed for match in matches)


def test_no_derived_occurrence_when_the_sentence_never_names_the_subject():
    sentence = "The binder was missing, and others say it was available."
    scope = build_scope(sentence)
    assert scope.derived_matches("checklist was available") == ()
