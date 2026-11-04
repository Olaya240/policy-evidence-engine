"""Differential: ``evidence_frames`` against the guard's older lexical rules.

The guard decides attribution through ``app.evidence_frames`` now
(``_modality`` asks ``force_of_prefix`` for ``Modality.ATTRIBUTED_DENIAL``), but
the rest of its reading is still the regex layer in ``app.semantic_guard``. Two
readers of the same prefix therefore exist, and this file measures where they
disagree instead of assuming they agree.

What is generated
-----------------
Six thousand sentences, deterministic from ``SEED``, from a product over the
axes the finding has to hold across: agent (plain and ``no one``/``nobody``/
``none of``/``not one of``), polarity (bare, ``did not``, ``had not``,
``never``, ``could not``), verb (every finite form of both lexicon classes,
read from ``evidence_frames`` at runtime), complementiser (``that``,
``whether``, none), cue (every directional cue in ``_CUES`` that can take a
complement, read at runtime), and a wrapper for the guard's own scope rules:
bare, sentence-initial hedge, evidence aboutness, postposed hedge, conditional,
question. A second stratum (300 sentences) has no matrix verb at all, so the
``force is None`` branch of the invariant is exercised rather than vacuous.

What is compared
----------------
For a sentence and a hypothesis, the frame module is read twice:

* ``primary`` — ``force_of_prefix(_cue_prefix_clause(quote, start))`` at the
  leftmost cue occurrence, which is literally the prefix the guard hands it;
* ``composed`` — ``compose_forces`` over *every* cue occurrence's prefix, i.e.
  what the frame module itself says about the sentence once every occurrence of
  the cue is taken into account (``compose_forces`` is imported, not rebuilt).

The guard is read once: ``reviewed_relation_details(quote, hypothesis)``. A
"commit" is ``SUPPORTS`` or ``CONTRADICTS``; ``NEUTRAL`` and ``None`` are not.

The invariant, and what it is worth
-----------------------------------
    force is WITHHOLDS  =>  the guard commits nothing
    force is ASSERTS    =>  the guard may commit, but never on a reason in the
                            withholding family (``ATTRIBUTED_DENIAL``)
    force is None       =>  the frame said nothing, so the guard's own lexical
                            reading is what decides; it may commit

Two of the three hold. This file pins the third as an **open safety defect** with
a strict ``xfail`` (``test_a_withholding_frame_never_lets_the_guard_commit``),
so the defect is visible, counted, and turns green the moment it is fixed
instead of being forgotten. Read ``ct3/audit/FRAME-DIFFERENTIAL.md`` before
changing an assertion here.

The scan is one-directional on purpose. A frame that stays silent about a
withholding construction looks exactly like a frame that found nothing, so a
*false negative* in ``frames`` is invisible to this invariant; §5 of the audit
names the construction where that happens.
"""
from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass

import pytest

from app import semantic_guard
from app.evidence_frames import (
    EVIDENTIAL_VERBS,
    SPEECH_ACT_VERBS,
    Force,
    compose_forces,
    force_of_prefix,
    frames,
    verb_class_of,
)
from app.models import Stance
from app.scope_layer import _AUXILIARIES, split_cue

SEED = 20261102
FRAME_SAMPLE = 5700
# SILENT_SAMPLE is the *draw dimension* (rows the corpus builds for the silent
# stratum), not a floor. It stays 300 for corpus size so the audit's percentages
# keep their denominators. The floor is separate: 2026-11-03's scoping and lexicon
# repairs moved ~180 corpus sentences out of silence -- they now draw frames and
# withhold, which is the point -- leaving 116 silent rows on this draw. A floor of
# 60 below that still leaves both outcomes thickly represented, which is what the
# degenerate-corpus test exists to check.
SILENT_SAMPLE = 300
SILENT_FLOOR = 60

#: ``say``/``tell``/``write`` do not take ``-ed``. Everything else in the two
#: lexicons is regular, and :func:`_finite_pairs` refuses to invent a form that
#: the lexicon does not contain, so the module stays the authority on its own
#: inventory.
_IRREGULAR = {"say": "said", "tell": "told", "write": "wrote"}

#: A ``none`` quantifier is already a negation, so a second one (``no one did not
#: confirm``) is not a construction the corpus has to carry.
_QUANTIFIED_AGENTS = ("No one ", "Nobody ", "None of the staff ", "Not one of the staff ")
_PLAIN_AGENTS = ("Staff ", "The auditor ", "Some staff ", "Several staff ",
                 "The team ", "We ", "The supervisor ")
_POLARITIES = ("", "did not ", "had not ", "never ", "could not ")
_COMPLEMENTISERS = ("that ", "whether ", "")
_LEADS = ("", "At the ward round, ", "In the ward, ", "During the handover, ")
#: A denial in the *previous* comma clause, kept as its own axis because it is the
#: one shape where the frame's polarity read and its clause boundary can disagree.
_LEAK_LEADS = ("", "No one had confirmed the ward was quiet, and ")
_TAILS = ("", ", and the shift ended on time", " as the night log records")
_WRAPPERS = ("bare", "hedge", "aboutness", "postposed", "conditional", "question")
#: Strata with no matrix verb. Each sentence is grammatical and asserts or
#: proposes the cue on its own; ``force_of_prefix`` returns ``None`` for all of
#: them, which is what the third clause of the invariant is about.
_SILENT_WRAPPERS = ("plain", "plain_aboutness", "plain_hedge")


def _finite_pairs() -> list[tuple[str, str]]:
    """``(base, finite)`` for every verb in both lexicons, read at runtime."""
    lexicon = EVIDENTIAL_VERBS | SPEECH_ACT_VERBS
    pairs = []
    for base in sorted(lexicon):
        if base.endswith(("s", "ing", "ed")):
            continue
        for candidate in (_IRREGULAR.get(base), base + "ed", base + "d",
                          base[:-1] + "ied"):
            if candidate and candidate in lexicon:
                pairs.append((base, candidate))
                break
    return pairs


def _directional_cues() -> list[tuple[str, Stance, str]]:
    """Every directional cue in the inventory, read from ``_CUES`` itself."""
    out = []
    for hypothesis in sorted(semantic_guard._CUES):
        for stance, phrases in sorted(semantic_guard._CUES[hypothesis].items(),
                                      key=lambda item: item[0].value):
            if stance not in (Stance.SUPPORTS, Stance.CONTRADICTS):
                continue
            for phrase in phrases:
                out.append((hypothesis, stance, phrase))
    return out


def _takes_complement(phrase: str) -> bool:
    """Can this cue sit in a complement position ("… confirmed that <cue>")?

    A cue needs a subject part and a finite predicate; ``split_cue`` is the
    scope layer's own answer to that, and the auxiliary requirement keeps
    adjectival cues (``short staffed``, ``understaffed``) out of a slot they do
    not fit. The cues this drops are counted and reported in §2 of the audit.
    """
    if split_cue(phrase) is None:
        return False
    return any(word.lower().strip(".,;:") in _AUXILIARIES for word in phrase.split())


_VERBS = _finite_pairs()
_ALL_CUES = _directional_cues()
_CUES = tuple(row for row in _ALL_CUES if _takes_complement(row[2]))
_AGENT_AUX = tuple((agent, aux) for agent in _PLAIN_AGENTS for aux in _POLARITIES) + tuple(
    (agent, "") for agent in _QUANTIFIED_AGENTS)


# --- generation -------------------------------------------------------------


def _sentence(wrapper: str, leak: str, lead: str, agent: str, aux: str, verb: str,
              complementiser: str, cue: str, tail: str) -> str:
    """One sentence for one cell of the product."""
    body = f"{lead}{agent}{aux}{verb} {complementiser}{cue}{tail}"
    if wrapper == "bare":
        return f"{leak}{body}."
    if wrapper == "postposed":
        return (f"{leak}{lead}{agent}{aux}{verb} {complementiser}{cue}, "
                f"probably{tail}.")
    if wrapper == "conditional":
        return (f"{leak}{lead}{agent}{aux}{verb} {complementiser}{cue} "
                f"if the ward was busy{tail}.")
    if wrapper == "question":
        return f"{leak}{lead}{agent}{aux}{verb} {complementiser}{cue}{tail}?"
    # A wrapped form opens the sentence with the operator, so the body's first
    # letter is lowered rather than left as a capital mid-sentence.
    head = f"{leak}{body}"
    head = head[0].lower() + head[1:]
    if wrapper == "hedge":
        return "Perhaps " + head + "."
    if wrapper == "aboutness":
        return "No evidence shows that " + head + "."
    raise AssertionError(f"unknown wrapper {wrapper!r}")


def _frame_shape() -> tuple[int, ...]:
    return (len(_WRAPPERS), len(_LEAK_LEADS), len(_LEADS), len(_AGENT_AUX),
            len(_VERBS), len(_COMPLEMENTISERS), len(_CUES), len(_TAILS))


def _decode(index: int, shape: tuple[int, ...]) -> tuple[int, ...]:
    """Mixed-radix decode of one index into one slot per axis."""
    slots = []
    for size in reversed(shape):
        index, slot = divmod(index, size)
        slots.append(slot)
    return tuple(reversed(slots))


def _frame_sentence(slots: tuple[int, ...]) -> tuple[str, str]:
    wrapper, leak, lead, pair, verb_pair, complementiser, cue, tail = slots
    agent, aux = _AGENT_AUX[pair]
    base, finite = _VERBS[verb_pair]
    verb = finite if aux in ("", "never ", "had not ") else base
    hypothesis, _stance, phrase = _CUES[cue]
    text = _sentence(_WRAPPERS[wrapper], _LEAK_LEADS[leak], _LEADS[lead],
                     agent, aux, verb, _COMPLEMENTISERS[complementiser],
                     phrase, _TAILS[tail])
    return text, hypothesis


def _silent_shape() -> tuple[int, ...]:
    return (len(_SILENT_WRAPPERS), len(_LEADS), len(_CUES), len(_TAILS))


def _silent_sentence(slots: tuple[int, ...]) -> tuple[str, str]:
    wrapper, lead, cue, tail = slots
    hypothesis, _stance, phrase = _CUES[cue]
    body = f"{_LEADS[lead]}{phrase}{_TAILS[tail]}"
    body = body[0].lower() + body[1:]
    wrapper = _SILENT_WRAPPERS[wrapper]
    if wrapper == "plain":
        return f"{body}.", hypothesis
    if wrapper == "plain_aboutness":
        return f"No evidence shows that {body}.", hypothesis
    if wrapper == "plain_hedge":
        return f"Perhaps {body}.", hypothesis
    raise AssertionError(f"unknown silent wrapper {wrapper!r}")


@dataclass(frozen=True)
class Reading:
    """One generated sentence and both readers' answers to it."""

    text: str
    hypothesis: str
    cue: str
    prefix: str
    primary: Force | None
    composed: Force | None
    occurrences: int
    nested: bool
    relation: Stance | None
    reason: str | None

    @property
    def committed(self) -> bool:
        return self.relation in (Stance.SUPPORTS, Stance.CONTRADICTS)

    @property
    def withdrawal_family(self) -> bool:
        """A reason the frame module owns rather than the guard's regex layer."""
        return self.reason == "ATTRIBUTED_DENIAL"

    @property
    def frame_leak(self) -> bool:
        """The withholding verdict was read off a clause the cue is not in.

        The cue's own clause starts after the last comma (the boundary
        ``evidence_frames._subject_before`` itself uses). If that clause carries
        a frame and that frame asserts, a ``WITHHOLDS`` verdict for the whole
        prefix came from somewhere other than the cue's clause.
        """
        if self.composed is not Force.WITHHOLDS:
            return False
        comma = self.prefix.rfind(",")
        if comma == -1:
            return False
        tail = self.prefix[comma + 1:]
        return bool(frames(tail)) and force_of_prefix(tail) is Force.ASSERTS


def _occurrences(text: str, cues) -> list[tuple[int, int, str]]:
    """Every cue occurrence for this hypothesis, using the guard's own pattern."""
    spans = []
    for _hypothesis, _stance, phrase in cues:
        pattern = semantic_guard._phrase_pattern(phrase)
        for found in re.finditer(pattern, text, re.IGNORECASE):
            spans.append((found.start(), found.end(), phrase))
    return spans


def _nested(spans: list[tuple[int, int, str]]) -> bool:
    """Is one occurrence contained in another occurrence's span?"""
    for index, first in enumerate(spans):
        for second in spans[index + 1:]:
            if first[0] < second[1] and second[0] < first[1]:
                return True
    return False


def _read(text: str, hypothesis: str, cue: str) -> Reading:
    cues = semantic_guard._CUES[hypothesis]
    spans = _occurrences(text, tuple(
        (hypothesis, stance, phrase) for stance, phrases in cues.items()
        for phrase in phrases))
    starts = sorted({span[0] for span in spans})
    prefixes = [semantic_guard._cue_prefix_clause(text, start) for start in starts]
    forces = [force_of_prefix(prefix) for prefix in prefixes]
    details = semantic_guard.reviewed_relation_details(text, hypothesis)
    return Reading(
        text=text,
        hypothesis=hypothesis,
        cue=cue,
        prefix=prefixes[0],
        primary=forces[0],
        # ``None`` is per-prefix silence, so it is filtered before the meet: the
        # frame module's own docstring says a caller must fall back to its lexical
        # reading for it, and ``compose_forces`` treats a ``None`` element as a
        # frame it saw (see the audit's finding 4).
        composed=compose_forces([force for force in forces if force is not None]),
        occurrences=len(starts),
        nested=_nested(spans),
        relation=details["relation"],
        reason=details["reason_code"],
    )


@dataclass(frozen=True)
class Sample:
    """The generated corpus, built once per session."""

    readings: tuple[Reading, ...]
    duplicates: int


_SAMPLE: Sample | None = None


def _build_sample() -> Sample:
    rng = random.Random(SEED)
    frame_shape = _frame_shape()
    frame_total = 1
    for size in frame_shape:
        frame_total *= size
    silent_shape = _silent_shape()
    silent_total = 1
    for size in silent_shape:
        silent_total *= size

    sentences: list[tuple[str, str]] = []
    for index in rng.sample(range(frame_total), min(FRAME_SAMPLE, frame_total)):
        sentences.append(_frame_sentence(_decode(index, frame_shape)))
    for index in rng.sample(range(silent_total), min(SILENT_SAMPLE, silent_total)):
        sentences.append(_silent_sentence(_decode(index, silent_shape)))

    readings = tuple(_read(text, hypothesis, "") for text, hypothesis in sentences)
    duplicates = len(sentences) - len({text for text, _ in sentences})
    return Sample(readings=readings, duplicates=duplicates)


def sample() -> Sample:
    global _SAMPLE
    if _SAMPLE is None:
        _SAMPLE = _build_sample()
    return _SAMPLE


def readings() -> tuple[Reading, ...]:
    return sample().readings


# --- the taxonomy -----------------------------------------------------------

#: Every case lands in exactly one of these. ``AGREE_*`` and ``SILENT_*`` are
#: agreements (or, for ``SILENT_*``, cases where there is no frame to agree
#: with); ``GUARD_RULE`` is a disagreement the guard's own documented rule
#: justifies; ``SAFETY`` is the class the invariant forbids.
CLASSES = (
    "AGREE_ASSERT",     # frame asserts, guard commits
    "AGREE_WITHHOLD",   # frame withholds, guard commits nothing
    "GUARD_RULE",       # frame asserts, guard abstains on one of its own rules
    "SILENT_COMMIT",    # no frame recognised, guard commits on its own reading
    "SILENT_ABSTAIN",   # no frame recognised, guard abstains on its own reading
    "SAFETY",           # frame withholds, guard commits a direction
)

#: The guard's own scope rules. Each is a rule ``evidence_frames`` does not
#: model, and each can only abstain — none of them can commit a direction.
_GUARD_OWN_RULES = (
    "CUE_IN_QUESTION",
    "CONDITIONAL_CUE",
    "EVIDENCE_ABOUTNESS_FRAME",
    "HEDGED_CUE",
    "NEGATED_CUE",
    "CONTRAST_CHANGED_CURRENT_STATE",
)


def classify(reading: Reading) -> str:
    if reading.committed:
        if reading.composed is Force.WITHHOLDS:
            return "SAFETY"
        if reading.composed is Force.ASSERTS:
            return "AGREE_ASSERT"
        return "SILENT_COMMIT"
    if reading.composed is Force.WITHHOLDS:
        return "AGREE_WITHHOLD"
    if reading.composed is Force.ASSERTS:
        return "GUARD_RULE"
    return "SILENT_ABSTAIN"


def class_counts() -> Counter:
    """Class -> count. The audit quotes this; the tests assert its shape."""
    return Counter(classify(reading) for reading in readings())


def by_class(name: str) -> tuple[Reading, ...]:
    return tuple(reading for reading in readings() if classify(reading) == name)


# --- 1. the corpus ----------------------------------------------------------


def test_the_corpus_is_generated_once_and_is_not_degenerate():
    """A corpus that mostly said nothing would make every count below empty.

    Asserts the denominators the audit's percentages use: the sample size, that
    no sentence is a duplicate of another, that both frame verdicts and the
    silent verdict are all present in quantity, and that every sentence in the
    frame stratum did draw a cue (``NO_CUE_MATCH`` there would mean the harness
    built text its own matcher cannot see).
    """
    corpus = sample()
    assert len(corpus.readings) == FRAME_SAMPLE + SILENT_SAMPLE
    assert corpus.duplicates == 0, f"{corpus.duplicates} duplicate sentences"

    # The draw is uniform over the product, so the distribution is skewed by the
    # axes themselves: one polarity in five is affirmative, and a denial in the
    # neighbouring clause (half the cells) withholds every sentence it precedes.
    # The bounds below only keep each branch of the invariant in the thousands or
    # hundreds; they are not claims about prevalence, and the audit says so.
    forces = Counter(reading.composed for reading in corpus.readings)
    assert forces[Force.WITHHOLDS] > 0.25 * len(corpus.readings), forces
    assert forces[Force.ASSERTS] > 0.05 * len(corpus.readings), forces
    assert forces[None] >= SILENT_FLOOR, forces

    reasons = Counter(reading.reason for reading in corpus.readings
                      if not reading.committed)
    assert "NO_CUE_MATCH" not in reasons, reasons
    assert len(reasons) >= 4, reasons
    assert sample() is corpus, "the sample must be built once per session"


def test_reading_the_same_sentence_twice_gives_the_same_answer():
    """Determinism is a precondition for the counts, so it gets its own check."""
    for reading in readings()[:250]:
        again = _read(reading.text, reading.hypothesis, reading.cue)
        assert (again.primary, again.composed, again.relation, again.reason) == (
            reading.primary, reading.composed, reading.relation, reading.reason)


def test_the_primary_and_composed_reads_agree_except_where_occurrences_nest():
    """The two ways of asking the frame module must not drift apart.

    ``primary`` is the literal call the guard makes (one prefix); ``composed``
    is the frame module's own verdict once every occurrence of the cue is
    counted. They can only differ when one occurrence sits inside another, and
    that is exactly the defect class below — so this pins the mechanism instead
    of assuming it.
    """
    divergent = [reading for reading in readings() if reading.primary != reading.composed]
    assert all(reading.nested for reading in divergent), (
        "primary/composed differ without nested cue occurrences: "
        f"{[(r.text, r.primary, r.composed) for r in divergent][:3]}"
    )


# --- 2. the invariant -------------------------------------------------------


def test_every_case_lands_in_exactly_one_class():
    counts = class_counts()
    assert set(counts) <= set(CLASSES), set(counts) - set(CLASSES)
    assert sum(counts.values()) == len(readings())
    assert len(counts) == len(CLASSES), (
        f"unexercised classes: {set(CLASSES) - set(counts)}; counts={dict(counts)}")


# Known defect: a truncating prefix drops the frame (section 3 of the report).
@pytest.mark.xfail(strict=True, reason=(
    "open safety defect: a shorter cue phrase that matches inside a longer one "
    "gets its own prefix, that prefix truncates inside the complement's noun "
    "phrase ('... did not mention printed '), evidence_frames drops the frame "
    "because 'printed ' is not complement-shaped, and the guard certifies the "
    "shorter occurrence while the longer one was withheld. Section 3 of "
    "ct3/audit/FRAME-DIFFERENTIAL.md; delete this marker when it passes."))
def test_a_withholding_frame_never_lets_the_guard_commit():
    """The invariant this file exists for, stated against the frame module.

    Everything else here is bookkeeping; this is the claim. It fails on the
    nested-occurrence class and passes on the other 99.7% of the corpus.
    """
    violations = [reading for reading in readings() if reading.committed
                  and reading.composed is Force.WITHHOLDS]
    assert not violations, (
        f"{len(violations)} of {len(readings())} sentences commit a direction "
        f"the frame withholds: {[(r.text, r.relation) for r in violations][:5]}"
    )


def test_commits_under_a_withholding_frame_are_the_nested_cue_occurrences():
    """The defect's boundary, asserted so it cannot quietly become something else.

    If a commit ever appears under a withholding frame *without* two overlapping
    cue occurrences, the mechanism is not the one the audit describes and the
    finding above is understated rather than closed.
    """
    violations = [reading for reading in readings() if reading.committed
                  and reading.composed is Force.WITHHOLDS]
    assert all(reading.nested and reading.occurrences > 1 for reading in violations), (
        f"violations outside the nested-occurrence mechanism: "
        f"{[(r.text, r.occurrences, r.nested) for r in violations][:3]}"
    )


def test_a_frame_that_does_not_withhold_never_produces_a_withholding_reason():
    """``ASSERTS``/``None`` must not be answered with ``ATTRIBUTED_DENIAL``.

    That reason means "a matrix clause denied this was established", and the
    frame module is the only thing that reads it. If the guard reports it while
    the frame module does not withhold, one of the two read a different string —
    which is a bug in the guard's call site, not a policy choice.
    """
    mismatches = [reading for reading in readings() if reading.withdrawal_family
                  and reading.composed is not Force.WITHHOLDS]
    assert not mismatches, (
        f"{len(mismatches)} denials the frame module does not report: "
        f"{[(r.text, r.composed) for r in mismatches][:3]}"
    )


def test_a_silent_frame_leaves_the_guard_its_own_reading():
    """``None`` is not a verdict: the guard decides, and may commit.

    The silent stratum exists so this is not vacuous. Both outcomes must appear —
    a guard that abstained on every silent prefix would be as wrong as one that
    committed, and neither would show up if the stratum were empty.
    """
    silent = [reading for reading in readings() if reading.composed is None]
    assert len(silent) >= SILENT_FLOOR
    assert all(reading.composed is None and reading.primary is None for reading in silent)
    assert any(reading.committed for reading in silent), "no silent prefix committed"
    assert any(not reading.committed for reading in silent), "no silent prefix abstained"
    assert not any(reading.withdrawal_family for reading in silent)


# --- 3. the justified disagreement -----------------------------------------


def test_the_justified_class_is_the_guards_own_scope_rules():
    """The one disagreement class that is a division of labour, not a defect.

    The frame module reads *attribution*: who denied which act of reporting, in
    the words before the cue. It cannot see a postposed hedge, a question
    terminator, a conditional's consequent or an evidence-aboutness clause, and
    it does not try to. The guard abstains on all four, which is the safe
    direction, and every reason it reports for doing so is one of its own codes.
    """
    justified = by_class("GUARD_RULE")
    assert justified, "the justified class is empty; the wrapper axis is not reaching"
    codes = Counter(reading.reason for reading in justified)
    assert set(codes) <= set(_GUARD_OWN_RULES), set(codes) - set(_GUARD_OWN_RULES)
    assert len(codes) >= 3, f"only {dict(codes)} exercised"
    assert not any(reading.withdrawal_family for reading in justified)


def test_the_justified_disagreements_are_not_silent_frame_failures():
    """Neighbour: each justified case names the operator that caused it.

    A wrapper that the guard ignores would land here as ``NEGATED_CUE`` or not at
    all; requiring the reason to match the operator generated is what keeps the
    class from becoming a catch-all.
    """
    expected = {
        "question": "CUE_IN_QUESTION",
        "conditional": "CONDITIONAL_CUE",
        "hedge": "HEDGED_CUE",
        "aboutness": "EVIDENCE_ABOUTNESS_FRAME",
    }
    seen = Counter()
    for reading in by_class("GUARD_RULE"):
        if reading.reason == "HEDGED_CUE":
            seen["hedge_or_postposed"] += 1
        else:
            seen[reading.reason] += 1
    assert set(seen) <= set(expected.values()) | {"hedge_or_postposed"}
    assert seen["CUE_IN_QUESTION"] > 0 and seen["CONDITIONAL_CUE"] > 0


# --- 4. the frame bug -------------------------------------------------------


@pytest.mark.xfail(strict=True, reason=(
    "open frame defect: evidence_frames._clause_of stops at a sentence "
    "terminator and not at a comma-coordinated clause, so a denial in the "
    "previous clause ('No one had confirmed the ward was quiet, and the auditor "
    "recorded that ...') withholds the cue's own clause, which asserts. Section "
    "4 of ct3/audit/FRAME-DIFFERENTIAL.md; delete this marker when it passes."))
def test_a_withholding_frame_never_reads_its_negation_from_another_clause():
    """The frame's verdict must belong to the clause the cue is in.

    ``_clause_of`` documents its sentence-only boundary as deliberate, and it is
    right for a fronted adverbial ("In the ward, no one confirmed that …"). It is
    wrong for a coordinate clause, which is the construction the guard's own
    ``scope_layer`` already separates with ``_SYNDETIC_OPENING``.
    """
    leaks = [reading for reading in readings() if reading.frame_leak]
    assert not leaks, (
        f"{len(leaks)} withholding verdicts read a denial from a different "
        f"comma clause: {[r.text for r in leaks][:3]}"
    )
