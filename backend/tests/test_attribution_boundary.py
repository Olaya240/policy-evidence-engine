"""Where the frame reader stops being right: a generated corpus against five laws.

`test_evidence_frames.py` pins the constructions the module was written for. This
file attacks the *boundaries* of that reader with a sentence generator of its own
— no dependency, one seed — and measures how far each law holds over it.

The grammar is imported, never copied. Verb forms are derived from
`app.evidence_frames.EVIDENTIAL_VERBS` / `SPEECH_ACT_VERBS` by suffix, and the
propositions are the directional phrases of `app.semantic_guard._CUES` placed into
clause form by a small grammatical dispatch (`_clause`), so widening either
lexicon changes the corpus instead of leaving it stale.

Five laws, stated over the corpus rather than over a table:

1. **No polarity leak.** A frame in sentence one cannot change any frame in
   sentence two. Checked by constructing pairs and comparing the target's frames
   alone against the target's frames when preceded by a lead.
2. **Determinism.** Same input, same force, over repeated calls and over case and
   whitespace variants.
3. **Composition is a meet.** ``force_of_prefix`` is ``WITHHOLDS`` exactly when
   some recognised frame withholds, ``ASSERTS`` exactly when frames were found and
   none withholds, and ``None`` exactly when none were found.
4. **None is not Withholds.** A sentence whose only verbs lie inside the cue
   produces no frame at all, so the caller falls back to its own lexical reading
   instead of abstaining.
5. **Negation placement.** ``did not confirm`` (negation before the verb, carried
   by an auxiliary), ``confirmed not`` (negation after it, over the complement),
   and a negation inside a nested complement (``said that no one confirmed``),
   each with the reading this file claims.

Policy neutrality
-----------------
Laws 1-4 need no reading of their own: they compare the reader against itself.
Law 5 needs to know what a *negated frame of class C* is worth, and it asks
`assertion_force` rather than restating a table here. So this file does not say
which of the two verb classes withholds — it says that whatever
`assertion_force` decides for a frame, the sentence's force is that frame's force,
and the placement rules must hand it the right `(polarity, verb_class)` pair. A
change to the speech-act policy moves the answers and leaves these laws intact;
that is deliberate, because the policy was being edited while this corpus was
written.

Pinned disagreements
--------------------
Four laws held on every generated sentence. Law 5, and the coordination family
under §"law 1, clause joins", do not: the two shapes below are measured
counterexamples, each with the reading this file claims and a strict ``xfail`` so
that a fix fails loudly rather than silently passing.

* ``post_verbal_not`` — ``"The auditor confirmed not that P"``. The scan reads
  negation only in the text *before* the verb, and the complement-opening test
  then refuses the tail, so the prefix yields no frame at all. The sentence denies
  that P was established, so the reader should withhold.
* ``coordinated_and`` — ``"No one said X, and the auditor documented that P"``.
  `_clause_of` breaks on ``.!?;\\n`` but not on a conjunction, so the first
  conjunct's quantifier negates the second conjunct's verb. The second conjunct is
  its own clause: the auditor did document it.

``PINNED`` records how many cases each shape has. The aggregate tests fail both
when a new shape appears and when a pinned one changes size, so this file cannot
quietly start passing over a defect it still describes, and cannot quietly start
failing over one that was fixed.
"""
from __future__ import annotations

import collections
import random
from dataclasses import dataclass

import pytest

from app.evidence_frames import (
    EVIDENTIAL,
    EVIDENTIAL_VERBS,
    POLARITY_AFFIRMATIVE,
    POLARITY_NEGATED,
    QUANTIFIER_ALL,
    SPEECH_ACT,
    SPEECH_ACT_VERBS,
    Attribution,
    Force,
    assertion_force,
    compose_forces,
    force_of_prefix,
    frames,
)
from app.semantic_guard import _CUES

SEED = 20261102
MIN_SENTENCES = 5000

#: ``(law, shape) -> how many cases that shape had`` — measured on the tree this
#: file was written against, with the policy named in the module docstring.
#: Zero is not listed: a law that holds has no shape.
# Re-recorded 2026-11-02 after the negative-frame rule was extended to speech acts
# and cognition verbs: the frame now withholds in shapes it used to pass through, so
# the disagreement counts move *with the policy* rather than with the code's quality.
# A count that moves without a policy change is the signal this table exists to send.
#
# Re-recorded again 2026-11-03 after the reader learned (a) to scope negation at the
# clause's last comma when the pre-comma run carries no negating subject, which
# removes fronted adverbials from the frame's way, and (b) to read ``no`` + up to
# two head modifiers as a negated subject. Both repairs take sentences out of the
# wrong shapes, so ``embedded_negation_leak`` (negations inside a first conjunct's
# complement no longer reaching the second conjunct) and ``post_verbal_not``
# (denial left unrecognised before an added lexicon verb) both drop.
PINNED = {
    ("law1-coordination", "coordinated_and"): 900,
    ("law1-control", "embedded_negation_leak"): 15,
    ("law5", "post_verbal_not"): 336,
}


# --- the grammar --------------------------------------------------------------
#
# Verb *forms* are derived, not listed: a base form is one whose ``-s``/``-es``
# third person is in the same lexicon, a past form is one ending in ``-ed``, and a
# third-person form is one ending in ``-s``. That keeps the corpus grammatical
# without duplicating a lexicon this file is supposed to be testing.

_ALL_VERBS = frozenset(EVIDENTIAL_VERBS) | frozenset(SPEECH_ACT_VERBS)
_LEXICONS = {EVIDENTIAL: EVIDENTIAL_VERBS, SPEECH_ACT: SPEECH_ACT_VERBS}


def _forms(lexicon) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """``(base, past, third_person)`` forms present in ``lexicon``."""
    base = sorted(w for w in lexicon if w + "s" in _ALL_VERBS or w + "es" in _ALL_VERBS)
    past = sorted(w for w in lexicon if w.endswith("ed"))
    third = sorted(w for w in lexicon if w.endswith("s") and not w.endswith("ed"))
    return tuple(base), tuple(past), tuple(third)


NAMED = (
    "the auditor",
    "the ward nurse",
    "the senior registrar",
    "the duty manager",
    "the review panel",
    "the night shift",
    "staff",
    "the records clerk",
    "the on-call doctor",
    "the team",
)
SOME = ("some staff", "several staff", "most staff", "a few staff", "many staff",
        "a number of staff")
NONE = ("no one", "nobody", "none of the staff", "neither of the auditors",
        "not one of the nurses")

#: ``(phrase, shape)`` — ``shape`` is the polarity device the phrase carries.
AGENTS = (
    tuple((agent, "affirmative") for agent in NAMED)
    + tuple((agent, "affirmative") for agent in SOME)
    + tuple((agent, "auxiliary") for agent in NAMED)
    + tuple((agent, "auxiliary") for agent in SOME)
    + tuple((agent, "quantifier") for agent in NONE)
)

#: Complement shapes. ``"none"`` is a determiner-initial complement with no
#: complementiser: the bare ``"{verb} {proposition}"`` form is ungrammatical for
#: these propositions ("confirmed checklist unavailable"), so the only
#: zero-complementiser construction the grammar can build is a noun-headed one.
COMPLEMENTS = ("that ", "whether ", "if ", "the claim that ", "the fact that ")

JOINS = (", and ", ", but ", " and ", " but ")
SEPARATORS = (". ", "; ", "\n")

_AS_IS = frozenset({"the", "a", "an"})
_HEAD_NOUN = frozenset({"binder", "checklist", "printed", "colleague", "system",
                       "shift"})
_VERB_INITIAL = frozenset({"walked", "needed", "attended", "ran", "could"})
_ADJECTIVAL = frozenset({"short", "short-staffed", "understaffed"})
_NOUNISH = frozenset({"not", "enough", "time"})


def _clause(phrase: str) -> str:
    """The cue phrase in clause form, or ``""`` if the grammar cannot place it.

    The dispatch keys on the phrase's first token only, so it reads the inventory
    rather than restating it. A phrase whose subject was elided ("walked through
    the handover") takes a subject, an adjective fragment takes a copula, and a
    noun fragment takes an existential.
    """
    first = phrase.split()[0].casefold()
    if first in _AS_IS:
        return phrase
    if first in _HEAD_NOUN:
        return "the " + phrase
    if first in _VERB_INITIAL:
        return "the team " + phrase
    if first in _ADJECTIVAL:
        return "the ward was " + phrase
    if first in _NOUNISH:
        return "there was " + phrase
    if first in _ALL_VERBS or first in {"does", "did"}:
        # A phrase that opens with one of the reader's own verbs: "says nothing
        # about checklist availability" is a meta-statement and needs a subject
        # that is not itself a report.
        return "the note " + phrase
    return ""


def _inventory() -> tuple[tuple[str, str, str, str], ...]:
    """``(hypothesis, stance, phrase, clause)`` for every cue phrase, unplaced dropped."""
    rows = []
    for hypothesis, by_stance in _CUES.items():
        for stance, phrases in by_stance.items():
            for phrase in phrases:
                clause = _clause(phrase)
                if clause:
                    rows.append((hypothesis, stance.value, phrase, clause))
    return tuple(rows)


_INVENTORY = _inventory()
#: Propositions the matrix-frame laws use. NEUTRAL phrases are meta-statements
#: ("says nothing about checklist availability"), not propositions, so they appear
#: only in law 4, where the point is that the verb sits inside the cue. The
#: comparison casefolds: ``Stance.value`` is upper case, so a literal "neutral"
#: here silently admitted both meta-statements into the frame corpus.
PROPOSITIONS = tuple(sorted({row[3] for row in _INVENTORY
                             if row[1].casefold() != "neutral"}))
CUE_ONLY = tuple(sorted({row[3] for row in _INVENTORY}))


def _pick(total: int, count: int, rng: random.Random) -> list[int]:
    """``count`` distinct indices below ``total``, reproducibly."""
    if total <= count:
        return list(range(total))
    return sorted(rng.sample(range(total), count))


def _product(lengths) -> int:
    total = 1
    for length in lengths:
        total *= length
    return total


def _decode(index: int, lengths) -> tuple[int, ...]:
    """Mixed-radix digits of ``index`` below ``_product(lengths)``."""
    digits = []
    for length in reversed(tuple(lengths)):
        index, remainder = divmod(index, length)
        digits.append(remainder)
    return tuple(reversed(digits))


# --- the corpus ---------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One generated sentence, the shape that produced it, and the claimed reading."""

    shape: str
    sentence: str
    reading: str
    intent: tuple[tuple[str, str], ...] = ()  # ((verb_class, polarity), ...)


@dataclass(frozen=True)
class Pair:
    """A lead sentence and a target sentence, used to look for a leak."""

    shape: str
    lead: str
    target: str
    separator: str


def _single(rng: random.Random, count: int) -> list[Case]:
    """One matrix frame over every agent kind, verb class and complement shape."""
    classes = (EVIDENTIAL, SPEECH_ACT)
    forms = {class_: _forms(_LEXICONS[class_]) for class_ in classes}
    verbs = max(len(base) for base, _, _ in forms.values())
    axes = (len(AGENTS), len(classes), len(COMPLEMENTS), len(PROPOSITIONS), verbs)
    out = []
    for index in _pick(_product(axes), count, rng):
        agent_i, class_i, comp_i, prop_i, verb_i = _decode(index, axes)
        class_ = classes[class_i]
        agent, device = AGENTS[agent_i]
        base, past, _third = forms[class_]
        verb_pool = base if device == "auxiliary" else past
        verb = verb_pool[verb_i % len(verb_pool)]
        complement = COMPLEMENTS[comp_i]
        proposition = PROPOSITIONS[prop_i]
        if device == "auxiliary":
            sentence = f"{agent} did not {verb} {complement}{proposition}."
            polarity = POLARITY_NEGATED
            reading = ("an auxiliary negates the matrix verb: the frame is typed "
                       "negated and its force is assertion_force's answer for it")
        elif device == "quantifier":
            sentence = f"{agent} {verb} {complement}{proposition}."
            polarity = POLARITY_NEGATED
            reading = ("a none-quantifier subject negates the frame without a "
                       "negation word: same typed frame as the auxiliary row")
        else:
            sentence = f"{agent} {verb} {complement}{proposition}."
            polarity = POLARITY_AFFIRMATIVE
            reading = "an affirmative frame over a reported complement"
        out.append(Case("single", sentence, reading, ((class_, polarity),)))
    return out


def _nested(rng: random.Random, count: int) -> list[Case]:
    """Two frames: an affirmative outer clause over a none-quantified inner one."""
    classes = (EVIDENTIAL, SPEECH_ACT)
    verbs = max(len(_forms(_LEXICONS[class_])[1]) for class_ in classes)
    axes = (len(NAMED), len(classes), len(classes), len(NONE), len(COMPLEMENTS),
            len(PROPOSITIONS), verbs)
    out = []
    for index in _pick(_product(axes), count, rng):
        outer_i, class_i, inner_class_i, inner_i, comp_i, prop_i, verb_i = _decode(
            index, axes)
        outer_class = classes[class_i]
        inner_class = classes[inner_class_i]
        outer_agent = NAMED[outer_i]
        inner_agent = NONE[inner_i]
        outer_past = _forms(_LEXICONS[outer_class])[1]
        inner_past = _forms(_LEXICONS[inner_class])[1]
        outer = outer_past[verb_i % len(outer_past)]
        inner = inner_past[(verb_i // 2) % len(inner_past)]
        sentence = (f"{outer_agent} {outer} that {inner_agent} {inner} "
                    f"{COMPLEMENTS[comp_i]}{PROPOSITIONS[prop_i]}.")
        out.append(Case(
            "nested", sentence,
            "the outer clause asserts the saying/establishing; the inner denies "
            "the report, so the proposition beneath it is not established and the "
            "meet withholds",
            ((outer_class, POLARITY_AFFIRMATIVE),
             (inner_class, POLARITY_NEGATED)),
        ))
    return out


def _coordination(rng: random.Random, count: int) -> list[Pair]:
    """Two conjuncts in one sentence: does conjunct one's negation reach two?"""
    classes = (EVIDENTIAL, SPEECH_ACT)
    verbs = max(len(_forms(_LEXICONS[class_])[1]) for class_ in classes)
    axes = (len(NONE), len(classes), len(JOINS), len(NAMED), len(PROPOSITIONS), verbs)
    out = []
    for index in _pick(_product(axes), count, rng):
        lead_i, class_i, join_i, agent_i, prop_i, verb_i = _decode(index, axes)
        lead_class = classes[class_i]
        lead_past = _forms(_LEXICONS[lead_class])[1]
        target_past = _forms(EVIDENTIAL_VERBS)[1]
        # Both conjuncts take a complement: "no one documented that P" rather than
        # the transitive verb standing alone.
        lead = (f"{NONE[lead_i]} {lead_past[verb_i % len(lead_past)]} that "
                f"{PROPOSITIONS[prop_i]}")
        target = (f"{NAMED[agent_i]} {target_past[(verb_i // 2) % len(target_past)]} "
                  f"that {PROPOSITIONS[(prop_i + 1) % len(PROPOSITIONS)]}.")
        out.append(Pair("coordinated_and", lead, target, JOINS[join_i]))
    return out


def _coordination_control(rng: random.Random, count: int) -> list[Pair]:
    """The same join with an affirmative first conjunct: nothing should leak.

    This is the discriminator for the family above. If coordination *as such*
    broke clause scope, this family would fail as well; if only a negation in the
    first conjunct leaks, it passes and the coordinator's failure is attributed to
    the polarity rather than to the join.
    """
    classes = (EVIDENTIAL, SPEECH_ACT)
    axes = (len(NAMED), len(classes), len(JOINS), len(NAMED), len(PROPOSITIONS))
    out = []
    for index in _pick(_product(axes), count, rng):
        lead_i, class_i, join_i, agent_i, prop_i = _decode(index, axes)
        lead_past = _forms(_LEXICONS[classes[class_i]])[1]
        target_past = _forms(EVIDENTIAL_VERBS)[1]
        lead = f"{NAMED[lead_i]} {lead_past[0]} that {PROPOSITIONS[prop_i]}"
        target = (f"{NAMED[agent_i]} {target_past[1 % len(target_past)]} "
                  f"that {PROPOSITIONS[(prop_i + 1) % len(PROPOSITIONS)]}.")
        out.append(Pair("coordination_control", lead, target, JOINS[join_i]))
    return out


def _leaks(rng: random.Random, count: int) -> list[Pair]:
    """Sentence one denies a frame; sentence two states one."""
    leads = []
    for class_ in (EVIDENTIAL, SPEECH_ACT):
        base, past, _ = _forms(_LEXICONS[class_])
        for agent in NAMED:
            leads.append(f"{agent} did not {base[0]} that {PROPOSITIONS[0]}.")
            leads.append(f"{agent} never {base[min(1, len(base) - 1)]} that "
                         f"{PROPOSITIONS[1]}.")
        for agent in NONE:
            leads.append(f"{agent} {past[0]} that {PROPOSITIONS[2]}.")
    # A lead with a negation and no frame: "did not review" carries no lexicon
    # verb, so there is nothing to leak and the target must be untouched.
    leads.extend([
        f"{agent} did not review the checklist." for agent in NAMED[:3]
    ])

    targets = []
    for class_ in (EVIDENTIAL, SPEECH_ACT):
        _, past, _ = _forms(_LEXICONS[class_])
        for agent in NAMED:
            targets.append(f"{agent} {past[0]} that {PROPOSITIONS[0]}.")
        for agent in SOME:
            targets.append(f"{agent} {past[1 % len(past)]} that {PROPOSITIONS[1]}.")

    axis = (leads, targets, SEPARATORS)
    total = len(leads) * len(targets) * len(SEPARATORS)
    out = []
    for index in _pick(total, count, rng):
        rest, separator = divmod(index, len(SEPARATORS))
        rest, target_index = divmod(rest, len(targets))
        rest, lead_index = divmod(rest, len(leads))
        del rest
        out.append(Pair("leak", leads[lead_index], targets[target_index],
                        SEPARATORS[separator]))
    return out


def _placement(rng: random.Random, count: int) -> list[Case]:
    """Negation before the verb, after it, and inside a nested complement."""
    classes = (EVIDENTIAL, SPEECH_ACT)
    axes = (len(NAMED), len(classes), 2, len(PROPOSITIONS), 4)
    out = []
    for index in _pick(_product(axes), count, rng):
        agent_i, class_i, comp_i, prop_i, pick_verb = _decode(index, axes)
        class_ = classes[class_i]
        agent = NAMED[agent_i]
        base, past, _third = _forms(_LEXICONS[class_])
        verb = base[pick_verb % len(base)]
        past_verb = past[(pick_verb + 1) % len(past)]
        comp = COMPLEMENTS[comp_i]
        proposition = PROPOSITIONS[prop_i]
        if pick_verb % 2:
            sentence = f"{agent} did not {verb} {comp}{proposition}."
            shape = "placement_auxiliary"
            reading = ("the auxiliary negates the matrix verb itself, so the frame "
                       "is negated and takes assertion_force's answer for a "
                       "negated frame of its class")
        else:
            sentence = f"{agent} {past_verb} not {comp}{proposition}."
            shape = "placement_post_verbal"
            reading = ("the negation scopes over the complement, not over the act: "
                       "the establishment is not of this proposition, so the "
                       "proposition is not asserted and the reader must withhold "
                       "for either verb class -- the speech-act tolerance below "
                       "does not apply, because the saying is asserted and the "
                       "content denied, the opposite of 'did not say'")
        out.append(Case(shape, sentence, reading, ((class_, POLARITY_NEGATED),)))
    return out


CUE_LEADS = ("At the ward round", "On the night shift", "According to the notes",
             "In the review", "During handover", "At 03:10")


def _cue_only(rng: random.Random, count: int) -> list[Case]:
    """Sentences with no matrix verb at all: every verb, if any, is in the cue."""
    shapes = ("{lead}, {clause}.", "{clause}.", "{lead}: {clause}.",
              "{clause}; {lead}, {clause}.")
    axes = (len(CUE_LEADS), len(CUE_ONLY), len(shapes))
    out = []
    for index in _pick(_product(axes), count, rng):
        lead_i, clause_i, shape_i = _decode(index, axes)
        sentence = shapes[shape_i].format(lead=CUE_LEADS[lead_i],
                                          clause=CUE_ONLY[clause_i])
        out.append(Case(
            "cue_only", sentence,
            "no matrix clause: nothing above the cue reports anything, so the "
            "reader must say None and let the caller use its lexical reading",
        ))
    return out


def _build():
    rng = random.Random(SEED)
    single = _single(rng, 2600)
    nested = _nested(rng, 1200)
    coordination = _coordination(rng, 900)
    control = _coordination_control(rng, 400)
    leaks = _leaks(rng, 900)
    placement = _placement(rng, 700)
    cue_only = _cue_only(rng, 400)
    sentences = [case.sentence for case in single + nested + placement + cue_only]
    for pair in coordination + control + leaks:
        # Both halves and the join: the composed string is what the reader sees.
        sentences.extend((pair.lead, pair.target,
                          pair.lead + pair.separator + pair.target))
    return {
        "single": single,
        "nested": nested,
        "coordination": coordination,
        "control": control,
        "leaks": leaks,
        "placement": placement,
        "cue_only": cue_only,
        "sentences": tuple(dict.fromkeys(sentences)),
    }


CORPUS = _build()


def _expected_force(intent: tuple[tuple[str, str], ...]) -> Force | None:
    """The force the *law* gives a sentence with this intended frame sequence.

    Policy-free by construction: each intended frame is handed to
    `assertion_force`, and composition is the meet. This file therefore never
    states which verb class withholds; it states that the reader must agree with
    the answer `assertion_force` already gives for the frame it was supposed to
    recognise.
    """
    return compose_forces(
        assertion_force(Attribution(agent="", quantifier=QUANTIFIER_ALL,
                                    polarity=polarity, verb_class=verb_class))
        for verb_class, polarity in intent
    )


# --- the laws -----------------------------------------------------------------


def _signature(sentence: str) -> tuple[tuple[str, str, str], ...]:
    """The typed part of every frame. The agent string is verbatim text."""
    return tuple((frame.verb_class, frame.polarity, frame.quantifier)
                 for frame in frames(sentence))


def _detail(case: Case, expected: object = None) -> str:
    found = frames(case.sentence)
    return (
        f"sentence: {case.sentence}\n"
        f"  frames:  {[frame.describe() for frame in found]}\n"
        f"  force:   {force_of_prefix(case.sentence)}"
        + (f" (expected {expected})" if expected is not None else "")
        + f"\n  reading: {case.reading}"
    )


def _law1() -> tuple[int, list[tuple[str, str]]]:
    """No polarity leak across a sentence boundary, both directions."""
    failures = []
    checked = 0
    for pair in CORPUS["leaks"]:
        checked += 1
        alone = frames(pair.target)
        alone_force = force_of_prefix(pair.target)
        joined = pair.lead + pair.separator + pair.target
        lead_frames = frames(pair.lead)
        got = frames(joined)
        got_lead, got_target = got[:len(lead_frames)], got[len(lead_frames):]
        if got_lead != lead_frames:
            failures.append(("lead_changed", _detail(
                Case("leak", joined, "sentence one's own frames cannot depend on "
                     "what follows them"))))
        if got_target != alone:
            case = Case("leak", joined,
                        "sentence two is its own clause: its frames must be the "
                        f"frames of {pair.target!r} alone, whose force is "
                        f"{alone_force}")
            failures.append(("target_changed", _detail(case)))
    return checked, failures


def _tail_signature(joined: str, target: str) -> tuple[tuple[str, str, str], ...]:
    """The typed triples of ``joined``'s last frames — the ones the target made.

    A coordinated conjunct's recorded *agent* is verbatim text and legitimately
    carries the conjunction ("and the ward nurse"), which no decision reads:
    `assertion_force` uses polarity and verb class only. So the comparison here is
    the typed triple, while law 1 across a sentence boundary compares the whole
    frame, agent included.
    """
    count = len(frames(target))
    return _signature(joined)[-count:] if count else ()


_NEGATION_WORDS = frozenset({"not", "never", "no", "nobody", "none", "neither"})


def _carries_negation(text: str) -> bool:
    return any(word.casefold() in _NEGATION_WORDS for word in text.replace("-", " ").split())


def _law1_coordination_control() -> tuple[int, list[tuple[str, str]]]:
    """Control: an affirmative first conjunct must not reach the second.

    Split by where the lead's negation, if any, sits. ``control_clean`` has none at
    all, so a failure there would mean the join itself breaks clause scope.
    ``embedded_negation_leak`` puts it inside the lead's own complement clause
    ("checked that there was not enough time"), where it governs nothing at all.
    """
    failures = []
    checked = 0
    for pair in CORPUS["control"]:
        checked += 1
        joined = pair.lead + pair.separator + pair.target
        if _tail_signature(joined, pair.target) != _signature(pair.target):
            shape = ("embedded_negation_leak" if _carries_negation(pair.lead)
                     else "control_clean")
            failures.append((shape, _detail(Case(
                shape, joined,
                "the second conjunct is its own clause either way; a negation "
                "inside the first conjunct's complement clause governs the "
                "complement and nothing after it"))))
    return checked, failures


def _law1_coordination() -> tuple[int, list[tuple[str, str]]]:
    """The same idea for two conjuncts joined by a comma: the second is a clause.

    Measured separately from law 1 because a comma is not a sentence boundary, so
    this is not the law as stated above. It is the same defect shape -- a negation
    reaching a verb it does not govern -- and it is the largest class of
    disagreement the corpus finds, so it is counted rather than assumed away.
    """
    failures = []
    checked = 0
    for pair in CORPUS["coordination"]:
        checked += 1
        joined = pair.lead + pair.separator + pair.target
        if _tail_signature(joined, pair.target) != _signature(pair.target):
            case = Case(
                "coordinated_and", joined,
                "conjunct two has its own subject and its own verb, so the "
                f"negation in conjunct one does not govern it"
                f"{pair.separator!r} is not a clause boundary; the second "
                f"conjunct is {pair.target!r}",
            )
            failures.append(("coordinated_and", _detail(case, expected="(frames of "
                                                         "the target alone)")))
    return checked, failures


def _law2() -> tuple[int, list[tuple[str, str]]]:
    """Same input, same force: repetition, case and whitespace."""
    failures = []
    checked = 0

    def variants(sentence: str):
        return (
            ("repeated", sentence),
            ("upper", sentence.upper()),
            ("lower", sentence.lower()),
            ("double_space", sentence.replace(" ", "  ")),
            ("leading", "   " + sentence),
            ("trailing", sentence + "   "),
            ("tab", sentence.replace(" ", "\t")),
        )

    for sentence in CORPUS["sentences"]:
        first_signature = _signature(sentence)
        first_force = force_of_prefix(sentence)
        if _signature(sentence) != first_signature or force_of_prefix(sentence) != first_force:
            failures.append(("repeat", f"sentence: {sentence}\n  force: "
                                       f"{first_force} then {force_of_prefix(sentence)}"))
        for name, variant in variants(sentence)[1:]:
            checked += 1
            if force_of_prefix(variant) != first_force:
                failures.append((name, (
                    f"sentence: {sentence}\n  force:   {first_force}\n"
                    f"  variant: {variant}\n  got:     {force_of_prefix(variant)}"
                )))
            elif _signature(variant) != first_signature:
                failures.append((name + "_signature", (
                    f"sentence: {sentence}\n  frames:  {first_signature}\n"
                    f"  variant: {variant}\n  got:     {_signature(variant)}"
                )))
    return checked, failures


def _law3() -> tuple[int, list[tuple[str, str]]]:
    """Composition is a meet, and silence is not the bottom."""
    failures = []
    checked = 0
    for sentence in CORPUS["sentences"]:
        checked += 1
        found = frames(sentence)
        withholds = [frame for frame in found
                     if assertion_force(frame) is Force.WITHHOLDS]
        if not found:
            expected = None
        elif withholds:
            expected = Force.WITHHOLDS
        else:
            expected = Force.ASSERTS
        composed = force_of_prefix(sentence)
        if composed is not expected:
            failures.append(("not_a_meet", _detail(
                Case("meet", sentence,
                     f"expected {expected}: {len(found)} frame(s), "
                     f"{len(withholds)} withholding"))))
        per_frame = compose_forces(assertion_force(frame) for frame in found)
        if per_frame is not composed:
            failures.append(("compose_disagrees", _detail(
                Case("meet", sentence,
                     "force_of_prefix must equal compose_forces over its own frames"))))
    return checked, failures


def _lexicon_occurrences(sentence: str) -> set[int]:
    """Offsets of words in either lexicon — the vocabulary, not a parse."""
    out = set()
    for index, word in enumerate(sentence.replace(",", " ").replace(".", " ")
                                 .replace(":", " ").replace(";", " ").split()):
        if word.casefold() in _ALL_VERBS:
            out.add(index)
    return out


def _law4() -> tuple[int, list[tuple[str, str]]]:
    """No matrix verb, no frame: ``None``, never ``WITHHOLDS``."""
    failures = []
    checked = 0
    for case in CORPUS["cue_only"]:
        checked += 1
        got = force_of_prefix(case.sentence)
        if got is not None:
            failures.append(("cue_only_frame", _detail(case, expected=None)))
        elif frames(case.sentence):
            failures.append(("cue_only_frames", _detail(case, expected=None)))
    return checked, failures


def _law5() -> tuple[int, list[tuple[str, str]]]:
    """Negation before the verb, after it, and inside a nested complement."""
    failures = []
    checked = 0
    for case in CORPUS["placement"] + CORPUS["nested"]:
        checked += 1
        expected = _expected_force(case.intent)
        got = force_of_prefix(case.sentence)
        if got is not expected:
            families = {"placement_post_verbal": "post_verbal_not",
                        "placement_auxiliary": "placement_auxiliary",
                        "nested": "nested"}
            failures.append((families[case.shape], _detail(case, expected=expected)))
    return checked, failures


# --- the pinned disagreements -------------------------------------------------


def _pinned(law: str, failures: list[tuple[str, str]]) -> collections.Counter:
    shapes = collections.Counter(shape for shape, _ in failures)
    unpinned = {}
    for shape, count in shapes.items():
        recorded = PINNED.get((law, shape))
        if recorded is None or recorded != count:
            unpinned[shape] = (recorded, count)
    if unpinned:
        lines = [f"{law}: recorded disagreement count changed "
                 f"(shape: recorded -> now)"]
        for shape, (recorded, count) in sorted(unpinned.items()):
            lines.append(f"  {shape}: {recorded} -> {count}")
        seen = set()
        for shape, detail in failures:
            if shape in unpinned and shape not in seen:
                seen.add(shape)
                lines.append(f"\n[{shape}] {detail}")
        raise AssertionError("\n".join(lines))
    return shapes


def test_the_generator_reaches_every_dimension():
    """Coverage first: a clean invariant pass over an empty grammar means nothing."""
    base_e, past_e, third_e = _forms(EVIDENTIAL_VERBS)
    base_s, past_s, third_s = _forms(SPEECH_ACT_VERBS)
    assert base_e and past_e and third_e, "evidential forms were not derived"
    assert base_s and past_s and third_s, "speech-act forms were not derived"

    placed = {row[2] for row in _INVENTORY}
    every = {phrase for by in _CUES.values() for phrases in by.values()
             for phrase in phrases}
    assert placed, "the clause grammar placed no cue phrase"
    assert len(placed) <= len(every)

    clauses = {case.sentence for case in CORPUS["single"]}
    assert any("did not" in sentence for sentence in clauses)
    assert any(agent in sentence for sentence in clauses for agent in NONE)
    assert any(agent + " " in sentence for sentence in clauses for agent in SOME)

    print(f"\ninventory: {len(placed)}/{len(every)} cue phrases placed into clauses")
    print(f"propositions: {len(PROPOSITIONS)}  cue-only clauses: {len(CUE_ONLY)}")
    print(f"verbs: evidential {len(base_e)}/{len(past_e)}/{len(third_e)} "
          f"(base/past/3sg), speech act {len(base_s)}/{len(past_s)}/{len(third_s)}")


def test_the_corpus_is_large_enough():
    assert len(CORPUS["sentences"]) >= MIN_SENTENCES, len(CORPUS["sentences"])


def test_law_1_no_polarity_leak_across_a_sentence_boundary():
    checked, failures = _law1()
    shapes = _pinned("law1", failures)
    assert sum(shapes.values()) == 0, f"{checked} pairs, {sum(shapes.values())} leaks"


def test_law_1_holds_across_a_coordinated_clause_too():
    """Recorded, not assumed: see ``coordinated_and`` in the module docstring."""
    checked, failures = _law1_coordination()
    shapes = _pinned("law1-coordination", failures)
    assert sum(shapes.values()) == PINNED.get(("law1-coordination", "coordinated_and"), 0)


def test_the_coordination_failure_is_the_negation_and_not_the_join():
    """The control: same joins, affirmative first conjunct.

    ``control_clean`` must be silent. ``embedded_negation_leak`` is pinned, not
    excused: a negation inside the first conjunct's complement still reaches the
    second conjunct, which is the same defect with a different source.
    """
    checked, failures = _law1_coordination_control()
    shapes = _pinned("law1-control", failures)
    clean = shapes.get("control_clean", 0)
    assert clean == 0, (
        f"{checked} control pairs: coordination alone leaked {clean} times, so the "
        "failure above cannot be attributed to the negation alone")


def test_law_2_determinism_over_repetition_case_and_whitespace():
    checked, failures = _law2()
    shapes = _pinned("law2", failures)
    assert sum(shapes.values()) == 0, f"{checked} variants, {sum(shapes.values())} differ"


def test_law_3_composition_is_a_meet():
    checked, failures = _law3()
    shapes = _pinned("law3", failures)
    assert sum(shapes.values()) == 0, f"{checked} sentences, {sum(shapes.values())} differ"


def test_law_4_none_is_not_withholds():
    checked, failures = _law4()
    shapes = _pinned("law4", failures)
    assert sum(shapes.values()) == 0, f"{checked} sentences, {sum(shapes.values())} framed"


def test_law_5_negation_placement():
    checked, failures = _law5()
    shapes = _pinned("law5", failures)
    assert sum(shapes.values()) == PINNED.get(("law5", "post_verbal_not"), 0)


# --- strict xfails: the cases verified as genuinely wrong ---------------------
#
# Representative rows only; the aggregate test above counts the whole class. Each
# asserts the law, so a fix turns it into an XPASS and fails loudly.

_POST_VERBAL = [case for case in CORPUS["placement"]
                if case.shape == "placement_post_verbal"][:3]
_COORDINATED = CORPUS["coordination"][:2]


@pytest.mark.xfail(strict=True, reason=(
    "post-verbal negation: the scan reads negation only before the verb, and the "
    "complement-opening gate then refuses the tail, so a sentence that denies the "
    "establishment of P returns None instead of withholding"))
@pytest.mark.parametrize("case", _POST_VERBAL, ids=[case.sentence for case in _POST_VERBAL])
def test_post_verbal_negation_withholds(case):
    assert force_of_prefix(case.sentence) is _expected_force(case.intent), _detail(case)


@pytest.mark.xfail(strict=True, reason=(
    "a coordinated conjunct is not a clause boundary in _clause_of, so conjunct "
    "one's quantifier negates conjunct two's verb; conjunct two is its own clause"))
@pytest.mark.parametrize("pair", _COORDINATED,
                         ids=[pair.lead + pair.separator + pair.target
                              for pair in _COORDINATED])
def test_a_coordinated_conjunct_keeps_its_own_polarity(pair):
    joined = pair.lead + pair.separator + pair.target
    assert _tail_signature(joined, pair.target) == _signature(pair.target), _detail(
        Case("coordinated_and", joined, ""))


# --- the numbers the report quotes --------------------------------------------


def _summary() -> str:
    rows = []
    for name, law in (
        ("law1 leak pairs", _law1),
        ("law1 coordination", _law1_coordination),
        ("law1 control", _law1_coordination_control),
        ("law2 variants", _law2),
        ("law3 meet", _law3),
        ("law4 cue-only", _law4),
        ("law5 placement", _law5),
    ):
        checked, failures = law()
        shapes = collections.Counter(shape for shape, _ in failures)
        rows.append(f"{name:22s} {checked:6d} checks  "
                    f"{sum(shapes.values()):5d} disagreements  "
                    f"{dict(sorted(shapes.items())) or '{}'}")
    rows.append(f"{'corpus':22s} {len(CORPUS['sentences']):6d} distinct sentences")
    rows.append(f"{'inventory placed':22s} {len({row[3] for row in _INVENTORY}):6d} of "
                f"{len({phrase for by in _CUES.values() for phrases in by.values() for phrase in phrases})} phrases")
    return "\n".join(rows)


if __name__ == "__main__":  # pragma: no cover - used to regenerate the report
    print(_summary())
