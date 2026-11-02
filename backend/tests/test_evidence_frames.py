"""Laws of ``app.evidence_frames``: the policy table, composition, and silence.

The module is one total function, ``Attribution -> Force``, plus a shallow scan
that turns a prefix into ``Attribution``s. These tests pin what its docstring
promises at the level a caller can observe: the verdict for a construction, the
class / polarity / quantifier it was derived from, how verdicts compose, and the
neighbours that must stay *unrecognised*.

That last distinction is the one the caller stands on: ``None`` means "no frame
found, fall back to your own lexical reading", while ``Force.WITHHOLDS`` means
"a matrix clause denied that the proposition was reported". A module that
answered ``WITHHOLDS`` for silence would be safe-looking and wrong in the other
direction, so ``None`` is asserted directly rather than by omission.

One rule covers both verb classes: a negated frame withholds, whether the verb
reports an establishment (``confirm``) or an utterance (``say``). The table used
to certify denied speech acts; that was reversed on 2026-11-02, and the rows
below marked ``REVERSED`` are the ones that moved.

House rule, as in ``test_scope_layer.py``: every recognised construction is
pinned next to a minimal neighbour that must not fire, so widening a lexicon or
a quantifier regex fails here rather than in the guard.
"""
from __future__ import annotations

import itertools

import pytest

from app.evidence_frames import (
    EVIDENTIAL,
    POLARITY_AFFIRMATIVE,
    POLARITY_NEGATED,
    QUANTIFIER_ALL,
    QUANTIFIER_NONE,
    QUANTIFIER_SOME,
    SPEECH_ACT,
    Attribution,
    Force,
    assertion_force,
    compose_forces,
    force_of_prefix,
    frames,
    verb_class_of,
)


# --- the policy table ---------------------------------------------------------
#
# Evidential x speech act, each affirmative and negated. Negation arrives three
# ways -- an auxiliary ("did not"), a ``no one`` / ``nobody`` subject, and
# ``none of`` -- and the table must not care which: every negated row withholds,
# because denying a report denies that the proposition was put on the record.

POLICY = [
    ("no-one-confirmed", "No one confirmed that the checklist was unavailable.",
     Force.WITHHOLDS),
    ("nobody-had-checked", "Nobody had checked whether the checklist was available.",
     Force.WITHHOLDS),
    # REVERSED 2026-11-02: a denied report is an absence of evidence, not support.
    ("none-of-staff-reported",
     "None of the staff reported that the checklist was unavailable.",
     Force.WITHHOLDS),
    ("did-not-confirm", "The auditor did not confirm that the checklist was unavailable.",
     Force.WITHHOLDS),
    ("some-did-not-confirm",
     "Some staff did not confirm that the checklist was unavailable.",
     Force.WITHHOLDS),
    ("confirmed", "The auditor confirmed that the checklist was unavailable.",
     Force.ASSERTS),
    ("reported", "Staff reported that the checklist was unavailable.",
     Force.ASSERTS),
    # The remaining rows tie the table to the corpus the docstring names.
    ("nobody-documented", "Nobody documented that the binder was missing.",
     Force.WITHHOLDS),
    ("several-confirmed", "Several staff confirmed that the binder was missing.",
     Force.ASSERTS),
    # REVERSED 2026-11-02: CU-NO-ONE-SAID; nobody speaking is not evidence.
    ("no-one-said", "No one said the binder was missing.", Force.WITHHOLDS),
    # REVERSED 2026-11-02: SC-NO-ONE-REPORTED.
    ("no-one-reported", "No one reported that the colleague was absent.",
     Force.WITHHOLDS),
    # REVERSED 2026-11-02: CU-MATRIX-NEVER-CLAIMED.
    ("never-claimed", "We never claimed the checklist was available.",
     Force.WITHHOLDS),
    # REVERSED 2026-11-02: CU-MATRIX-DID-NOT-SAY.
    ("did-not-say", "The auditor did not say the binder was at the desk.",
     Force.WITHHOLDS),
]


@pytest.mark.parametrize("case, prefix, expected", POLICY, ids=[row[0] for row in POLICY])
def test_the_policy_table(case, prefix, expected):
    assert force_of_prefix(prefix) is expected, case


GRID = [
    (quantifier, polarity, verb_class)
    for quantifier in (QUANTIFIER_ALL, QUANTIFIER_SOME, QUANTIFIER_NONE)
    for polarity in (POLARITY_AFFIRMATIVE, POLARITY_NEGATED)
    for verb_class in (EVIDENTIAL, SPEECH_ACT)
]


@pytest.mark.parametrize("quantifier, polarity, verb_class", GRID,
                         ids=[f"{class_}-{polarity}-{quantifier}"
                              for quantifier, polarity, class_ in GRID])
def test_the_force_function_is_total_over_class_and_polarity(
        quantifier, polarity, verb_class):
    """Exhaustive over the typed grid: every denied frame withholds, either class.

    ``assertion_force`` is total -- every recognised frame gets a force -- so
    the only way an unknown verb can fail to certify is never becoming an
    ``Attribution`` at all, which the neighbour below the composition section
    pins.
    """
    attribution = Attribution(
        agent="the auditor",
        quantifier=quantifier,
        polarity=polarity,
        verb_class=verb_class,
    )
    withholds = polarity == POLARITY_NEGATED
    assert assertion_force(attribution) is (
        Force.WITHHOLDS if withholds else Force.ASSERTS)


QUANTIFIED = [
    ("no-one", "No one confirmed that ", QUANTIFIER_NONE),
    ("nobody", "Nobody had checked whether ", QUANTIFIER_NONE),
    ("none-of", "None of the staff reported that ", QUANTIFIER_NONE),
    ("some", "Some staff did not confirm that ", QUANTIFIER_SOME),
    ("plain", "The auditor did not confirm that ", QUANTIFIER_ALL),
]


@pytest.mark.parametrize("case, prefix, expected", QUANTIFIED,
                         ids=[row[0] for row in QUANTIFIED])
def test_the_quantifier_is_read_off_the_subject(case, prefix, expected):
    """The quantifier is what the table's verdict is read from, so pin it."""
    found = frames(prefix)
    assert found, f"{case}: no frame recognised"
    assert found[0].quantifier == expected


# --- composition --------------------------------------------------------------


def test_one_withholding_frame_among_asserting_ones_withholds():
    forces = [Force.ASSERTS, Force.ASSERTS, Force.WITHHOLDS, Force.ASSERTS]
    assert compose_forces(forces) is Force.WITHHOLDS


def test_one_withholding_matrix_clause_withholds_an_otherwise_asserting_sentence():
    prefix = "Several staff confirmed that nobody had documented that "
    assert len(frames(prefix)) == 2, "the sentence should yield two frames"
    assert force_of_prefix(prefix) is Force.WITHHOLDS


def test_frames_that_all_assert_assert():
    prefix = "Several staff confirmed that the auditor reported that "
    assert len(frames(prefix)) == 2, "the sentence should yield two frames"
    assert force_of_prefix(prefix) is Force.ASSERTS


def test_the_empty_prefix_is_unrecognised_and_not_withholding():
    """Load-bearing: silence is ``None``, not the conservative bottom.

    ``compose_forces`` is a meet, so ``None`` cannot be produced by composing
    forces -- it can only mean the scan found nothing. A caller that read
    ``WITHHOLDS`` here would abstain on every cue it ever saw.
    """
    assert compose_forces(()) is None
    assert compose_forces([]) is None
    assert compose_forces(iter(())) is None
    assert force_of_prefix("") is None
    assert force_of_prefix("   ") is None
    assert force_of_prefix("") is not Force.WITHHOLDS


def test_silence_still_sits_beside_a_recognised_frame():
    """Neighbour: ``None`` is per-prefix absence, not a blanket answer."""
    assert force_of_prefix("The ") is None
    assert force_of_prefix("the checklist was unavailable, ") is None
    assert force_of_prefix("No one confirmed that ") is Force.WITHHOLDS


# --- neighbours that must not be read as a frame ------------------------------


def test_a_verb_in_the_cues_own_predicate_is_not_a_frame():
    """The cue's clause is the proposition; it is not a clause above it.

    ``unavailable`` carries no lexicon verb at all. ``checked`` and ``reported``
    in the two rows below do, so a scan that fired on any lexicon verb would
    turn the cue into its own attribution and return ``ASSERTS``.
    """
    for prefix in (
        "the checklist was unavailable",
        "the checklist was checked last week",
        "the report was reported to the board",
    ):
        assert force_of_prefix(prefix) is None, prefix


def test_a_noun_that_looks_like_a_verb_is_not_a_frame():
    """``report`` and ``note`` as nouns, with an adjectival predicate after."""
    for prefix in (
        "the report was missing",
        "The report was missing.",
        "the note was missing",
    ):
        assert force_of_prefix(prefix) is None, prefix


def test_a_denial_in_a_separate_sentence_does_not_govern_the_earlier_cue():
    """The prefix is bounded by position, not by "the sentence contains a no one".

    The same text also has to fire for the cue the denial actually governs, or
    the first assertion would pass merely because the denial is invisible
    everywhere.
    """
    sentence = ("The checklist was unavailable. "
                "No one confirmed that the binder was at the desk.")
    first_cue = sentence.casefold().index("checklist was unavailable")
    second_cue = sentence.casefold().index("binder was at the desk")

    assert force_of_prefix(sentence[:first_cue]) is None
    assert force_of_prefix(sentence[:second_cue]) is Force.WITHHOLDS


def test_a_denial_in_a_separate_sentence_does_not_reach_a_later_frame():
    """CLOSED (was a strict xfail): a polarity leak across a sentence boundary.

    The first version scanned negation over the whole prefix while the agent was
    clause-scoped, so ``No one said …`` in sentence one marked an affirmative
    evidential frame in sentence two as negated. Polarity is now read in the
    verb's own clause, on sentence boundaries: the second frame stays
affirmative and asserts on its own. The composed force withholds because
    sentence one is now a denied report in its own right, not because the denial
    leaked -- which is why the per-frame forces are asserted as well as the
    composition.
    """
    prefix = ("No one said the binder was missing. "
              "The auditor documented that the checklist was unavailable.")
    found = frames(prefix)
    assert [frame.polarity for frame in found] == [
        POLARITY_NEGATED, POLARITY_AFFIRMATIVE]
    assert [assertion_force(frame) for frame in found] == [
        Force.WITHHOLDS, Force.ASSERTS]
    assert force_of_prefix(prefix) is Force.WITHHOLDS


def test_a_fronted_adverbial_does_not_break_the_clause_scope():
    """Neighbour: the boundary is a sentence, not a comma.

    Scoping to the last comma instead would lose the quantifier in
    ``In the ward, no one confirmed that …`` and certify the complement.
    """
    assert frames("In the ward, no one confirmed that ")[0].polarity == (
        POLARITY_NEGATED)
    assert force_of_prefix("In the ward, no one confirmed that ") is Force.WITHHOLDS


def test_no_evidence_is_aboutness_not_attribution():
    """``no evidence that`` reports an absence, not an act by an agent.

    Neighbour: ``no`` in a subject position that *does* name an act still
    withholds, so this is not "the word no suppresses the frame".
    """
    assert force_of_prefix("no evidence that ") is None
    assert force_of_prefix("there was no evidence that ") is None
    assert force_of_prefix("No one documented that ") is Force.WITHHOLDS


# --- determinism and order-independence ---------------------------------------


def test_compose_is_constant_over_every_permutation():
    withholding = [Force.ASSERTS, Force.ASSERTS, Force.WITHHOLDS]
    assert {compose_forces(list(order))
            for order in itertools.permutations(withholding)} == {Force.WITHHOLDS}

    asserting = [Force.ASSERTS, Force.ASSERTS, Force.ASSERTS]
    assert {compose_forces(list(order))
            for order in itertools.permutations(asserting)} == {Force.ASSERTS}


def test_repeated_calls_on_the_same_prefix_are_equal():
    prefix = "No one confirmed that some staff had documented whether "
    first = frames(prefix)
    assert len(first) == 2, "the prefix should yield two frames"

    assert frames(prefix) == first
    assert force_of_prefix(prefix) == force_of_prefix(prefix)
    assert [frame.describe() for frame in frames(prefix)] == [
        frame.describe() for frame in first]


# --- the two lexicons are not interchangeable ---------------------------------


def test_the_two_classes_stay_labelled_and_share_the_negation_rule():
    """The classes are still distinguishable, but they no longer disagree on force.

    Before 2026-11-02 this test was a discriminator: a denied speech act asserted
    while a denied evidential frame withheld, so swapping ``_VERB_CLASS``'s two
    sources flipped three assertions. Now both classes withhold, and what the
    label buys is the audit trail (``describe()``) plus the guard's reason
    strings -- not a different verdict. A class that stopped being recognised
    would still fail here, and so would one that stopped appearing in the frame.
    """
    assert verb_class_of("confirmed") == EVIDENTIAL
    assert verb_class_of("reported") == SPEECH_ACT

    evidential = frames(
        "The auditor did not confirm that the checklist was unavailable.")[0]
    speech_act = frames(
        "The auditor did not report that the checklist was unavailable.")[0]
    assert (evidential.verb_class, speech_act.verb_class) == (
        EVIDENTIAL, SPEECH_ACT)
    assert evidential.describe() != speech_act.describe()

    for denial in (
        "The auditor did not confirm that the checklist was unavailable.",
        "The auditor did not say that the checklist was unavailable.",
        "The auditor did not report that the checklist was unavailable.",
    ):
        assert force_of_prefix(denial) is Force.WITHHOLDS, denial
    for affirmation in (
        "The auditor confirmed that the checklist was unavailable.",
        "The auditor said that the checklist was unavailable.",
        "The auditor reported that the checklist was unavailable.",
    ):
        assert force_of_prefix(affirmation) is Force.ASSERTS, affirmation
