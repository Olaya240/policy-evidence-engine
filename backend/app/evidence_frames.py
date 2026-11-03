"""Typed attribution frames: what a sentence says about *who established what*.

`semantic_guard` decides the direction of a cue from a closed phrase list. That
list reads propositions; it says nothing about the sentence's scaffolding — the
matrix clause that reports, denies, quantifies or attributes the proposition. The
guard used to handle that scaffolding with a handful of ad-hoc regular
expressions over the text before the cue, which is why one construction had two
verdicts depending on which word was chosen:

    "The auditor did not confirm the checklist was unavailable."   -> abstains
    "No one confirmed that the checklist was unavailable."         -> SUPPORTS

The first had a negation the regex could see; the second had a *quantifier* doing
the negating, so nothing matched and the complement was certified. This module
replaces that pattern-matching with a small typed frame and one total function:

    Attribution(agent, quantifier, polarity, verb_class)  ->  Force

`Force` has two values, ``ASSERTS`` and ``WITHHOLDS``, ordered by information:
``WITHHOLDS`` is the bottom. Composition is the meet over the frames of a
prefix — if any matrix clause withholds the proposition, the proposition is not
asserted, no matter what the others say. That law is proved in
``ct3/Attribution.v`` and exercised over generated sentences in
``tests/test_evidence_frames.py``.

The policy, as a table
----------------------
A frame's force depends only on its polarity and on the class of the verb doing
the reporting:

    polarity      verb class      force
    -----------   -------------   --------
    affirmative   evidential      ASSERTS
    affirmative   speech act      ASSERTS
    negated       evidential      WITHHOLDS
    negated       speech act      WITHHOLDS

In one line: ``effective_negation && (evidential || speech_act) -> WITHHOLDS``.
Only an affirmative frame certifies. The class is still carried on the frame
because it says *what kind of act* the sentence attributed — ``confirm`` reports
an establishment, ``say`` reports an utterance — but it no longer decides the
verdict, and the two classes must not diverge again.

Why every denied report withholds
---------------------------------
The last row of that table once read ``ASSERTS``. The argument for it was that
denying an utterance denies only that words were spoken and leaves their content
untouched, so ``"None of the staff reported that the checklist was unavailable"``
denied the report and said nothing either way about the checklist — and the cue
was then read as if it had been asserted.

That argument gets the semantics roughly right and the product wrong. A denied
report is not a faint statement about the checklist; it is evidence that the
statement is *absent from the record*. A reviewer asking "does this file show the
checklist was unavailable?" is asking about the evidence base, and "nobody said
so" answers that question with a no. Reading it as a yes — certifying the
complement's direction out of silence about the complement — is precisely the
failure mode a policy-evidence tool exists to prevent, and it is the one error a
reader cannot catch by checking the citation: the sentence is real, the quote
supports it, and the inference from it is the invention.

The evidential row already refuses this. ``"No one confirmed that the checklist
was unavailable"`` and ``"No one reported that the checklist was unavailable"``
are the same sentence with one vocabulary item swapped: a quantifier over a
denied report, in both cases an absence of evidence about the checklist. Letting
the two classes disagree made the verdict turn on which verb the author happened
to choose, which is the exact defect this module was written to remove; the
speech-act half survived that rewrite only as a recorded product decision
(``ct3/audit/REVIEW-scope-interval.md``), and it was reversed on 2026-11-02.

The cost is a lost certification, not a weakened guard, and it is measured: on
the falsification corpus every commit that arrived through a denied speech act
was wrong by construction, so withholding them removes wrong commits and
commits in equal number rather than trading accuracy for recall. What remains
certifying is the affirmative frame — ``"Staff reported that the checklist was
unavailable"`` — and a negated frame that does not scope over its own reporting
verb (a negation in a separate clause, a contrast, a quoted denial) never becomes
a negated frame here at all, so it keeps its force.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "Attribution",
    "Force",
    "POLARITY_AFFIRMATIVE",
    "POLARITY_NEGATED",
    "QUANTIFIER_ALL",
    "QUANTIFIER_NONE",
    "QUANTIFIER_SOME",
    "SPEECH_ACT",
    "EVIDENTIAL",
    "assertion_force",
    "compose_forces",
    "force_of_prefix",
    "frames",
    "verb_class_of",
]


class Force(str, Enum):
    """What a matrix clause does to the proposition beneath it."""

    WITHHOLDS = "withholds"
    ASSERTS = "asserts"


POLARITY_AFFIRMATIVE = "affirmative"
POLARITY_NEGATED = "negated"

QUANTIFIER_ALL = "all"
QUANTIFIER_SOME = "some"
QUANTIFIER_NONE = "none"

EVIDENTIAL = "evidential"
SPEECH_ACT = "speech_act"

#: Verbs that report an *establishing act*. Denying one denies the establishment.
EVIDENTIAL_VERBS = frozenset({
    "confirm", "confirms", "confirmed", "confirming",
    "check", "checks", "checked", "checking",
    "verify", "verifies", "verified", "verifying",
    "establish", "establishes", "established", "establishing",
    "document", "documents", "documented", "documenting",
    "observe", "observes", "observed", "observing",
    "record", "records", "recorded", "recording",
    "demonstrate", "demonstrates", "demonstrated", "demonstrating",
    "substantiate", "substantiates", "substantiated",
    "find", "finds", "found", "finding",
    "show", "shows", "showed", "shown", "showing",
    "locate", "locates", "located", "locating",
    # Cognition verbs: "I do not think the checklist was unavailable" reports the
    # speaker's knowledge state exactly as "did not confirm" reports an
    # establishing act. Negated, neither asserts the complement. They were the
    # last construction in the falsification corpus that still certified.
    "think", "thinks", "thought",
    "believe", "believes", "believed",
    "expect", "expects", "expected",
    "recall", "recalls", "recalled",
    "remember", "remembers", "remembered",
    "know", "knows", "knew", "known",
})

#: Verbs that report an *utterance*. Denying one denies that the content was
#: put on the record at all, which is an absence of evidence and not support.
SPEECH_ACT_VERBS = frozenset({
    "say", "says", "said", "saying",
    "claim", "claims", "claimed", "claiming",
    "report", "reports", "reported", "reporting",
    "mention", "mentions", "mentioned", "mentioning",
    "note", "notes", "noted", "noting",
    "state", "states", "stated", "stating",
    "argue", "argues", "argued", "arguing",
    "suggest", "suggests", "suggested", "suggesting",
    "tell", "tells", "told", "telling",
    "write", "writes", "wrote", "written", "writing",
    "deny", "denies", "denied", "denying",
    "allege", "alleges", "alleged",
})

_VERB_CLASS: dict[str, str] = {
    **{verb: EVIDENTIAL for verb in EVIDENTIAL_VERBS},
    **{verb: SPEECH_ACT for verb in SPEECH_ACT_VERBS},
}

_NEGATION = re.compile(
    r"\b(?:not|never|without|nor)\b|\b(?:do|does|did|is|are|was|were|has|have|had|"
    r"can|could|would|should|will|may|might)n['’]t\b",
    re.IGNORECASE,
)

_NONE_QUANTIFIER = re.compile(
    r"\b(?:no\s+one|nobody|none\s+of|neither\s+of|not\s+one\s+of)\b",
    re.IGNORECASE,
)

#: A bare ``no`` determiner as the subject of the reporting verb that follows:
#: ``"No supervisor said …"`` negates the subject in the same way ``"No one
#: said …"`` does, and the quantifier list above only spells the pronoun form.
#: The head may carry up to two modifiers (``"No staff member said …"``), but a
#: function word inside the chain cancels the match — in ``"There was no doubt
#: that the auditor documented …"`` the ``no`` is not the subject of the verb, and
#: that sentence asserts. Anchored to the end of the verb's clause on purpose.
_NO_SUBJECT_CHAIN = re.compile(
    r"\bno\s+((?:[A-Za-z][A-Za-z'’\-]*\s+){0,2}[A-Za-z][A-Za-z'’\-]*)\s*$",
    re.IGNORECASE,
)

#: Words that cannot sit between ``no`` and its head in a subject phrase. Anything
#: else (a two-word noun phrase is fine) keeps the match; one of these ends it.
_NO_SUBJECT_STOP = frozenset({
    "that", "whether", "if", "the", "a", "an", "it", "there", "this",
    "these", "those", "was", "were", "is", "are", "has", "have", "had",
    "did", "do", "does", "not", "never", "and", "but", "or", "of", "to",
    "in", "on", "at", "for", "with", "without", "as",
})


def _no_subject_match(window: str):
    """The ``no <head[, modifier]?>`` match immediately before the verb, or ``None``."""
    match = _NO_SUBJECT_CHAIN.search(window)
    if match is None:
        return None
    if any(word.casefold() in _NO_SUBJECT_STOP
           for word in match.group(1).split()):
        return None
    return match


def _no_determiner_subject(window: str) -> bool:
    return _no_subject_match(window) is not None

_SOME_QUANTIFIER = re.compile(
    r"\b(?:some|several|a\s+few|many|most|a\s+number\s+of)\b",
    re.IGNORECASE,
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_COMPLEMENTISER = re.compile(r"\b(?:that|whether|if)\b", re.IGNORECASE)
_COMPLEMENT_OPENING = re.compile(
    r"^\s*(?:that|whether|if|the|a|an|it|they|she|he|we|i|you|staff|none|no|some|"
    r"this|these|those|its|their|his|her)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Attribution:
    """One matrix frame: who, how many, in which direction, reporting what kind of act."""

    agent: str
    quantifier: str
    polarity: str
    verb_class: str

    def withholds(self) -> bool:
        """A denied report withholds its complement, whatever kind of report it was.

        The class is checked rather than assumed so that a future third class does
        not inherit certification by default: the rule is ``negated`` *and* a
        recognised reporting class, not ``negated`` alone.
        """
        return (self.polarity == POLARITY_NEGATED
                and self.verb_class in (EVIDENTIAL, SPEECH_ACT))

    def describe(self) -> str:
        return (f"{self.verb_class}:{self.polarity}:{self.quantifier}"
                f"({self.agent or '-'})")


def verb_class_of(verb: str) -> str | None:
    return _VERB_CLASS.get(verb.casefold())


def assertion_force(attribution: Attribution) -> Force:
    """The total function the whole module exists for.

    Negated frame (evidential or speech act) -> ``WITHHOLDS``. Affirmative frame
    -> ``ASSERTS``. There is no third outcome on purpose: a frame whose class is
    unknown never becomes an ``Attribution`` at all, so an unrecognised verb
    cannot silently certify.
    """
    if attribution.withholds():
        return Force.WITHHOLDS
    return Force.ASSERTS


def compose_forces(forces) -> Force | None:
    """Meet over frames: one withholding clause withholds the proposition.

    ``None`` means no frame was recognised — the caller must then fall back to its
    own lexical reading rather than assume assertion.
    """
    seen = False
    for force in forces:
        seen = True
        if force is Force.WITHHOLDS:
            return Force.WITHHOLDS
    return Force.ASSERTS if seen else None


def _clause_of(text: str, end: int) -> str:
    """The text between the last sentence boundary and ``end``.

    The boundary is a sentence terminator, not a comma: ``"In the ward, no one
    confirmed that …"`` is one clause with a fronted adverbial, and scoping the
    negation to the last comma would lose it. It *is* a terminator because the
    first version of this module searched the whole prefix, so
    ``"No one said the binder was missing. The auditor documented that …"``
    borrowed the first sentence's quantifier and withheld a proposition the second
    sentence asserts — a verdict-changing polarity leak, caught by
    ``tests/test_evidence_frames.py``.
    """
    window = text[:end]
    boundary = max(window.rfind(char) for char in ".!?;\n")
    return window[boundary + 1:]


def _subject_before(text: str, end: int) -> str:
    """The words between the last clause boundary and ``end``, minus quantifiers."""
    window = text[:end]
    boundary = max(window.rfind(char) for char in ".;\n")
    window = window[boundary + 1:]
    comma = window.rfind(",")
    if comma != -1:
        window = window[comma + 1:]
    window = _NONE_QUANTIFIER.sub(" ", window)
    subject = _no_subject_match(window)
    if subject is not None:
        window = window[:subject.start()] + " " + window[subject.end():]
    window = _SOME_QUANTIFIER.sub(" ", window)
    return " ".join(window.split())


def frames(prefix: str) -> tuple[Attribution, ...]:
    """Every matrix frame in ``prefix``, in reading order.

    A frame is recognised when a verb from one of the two closed classes appears
    before the cue and the text around it supplies a polarity. Nested frames are
    all returned — ``"No one confirmed that the auditor said …"`` yields two — and
    ``compose_forces`` decides what their conjunction means.

    Recognition is deliberately shallow: no parse tree, no dependency labels. The
    question this answers is only "does any matrix clause deny that the
    proposition was reported", and a shallow scan answers it without pretending to
    more structure than the code has.
    """
    found: list[Attribution] = []
    for match in _WORD.finditer(prefix):
        verb = match.group(0)
        verb_class = verb_class_of(verb)
        if verb_class is None:
            continue
        after = prefix[match.end():]
        # Scope, not prefix. The negation and the quantifier are read in the
        # verb's own clause, so a denial in a previous sentence cannot reach it.
        before = _clause_of(prefix, match.start())
        quantified = (_NONE_QUANTIFIER.search(before) is not None
                      or _no_determiner_subject(before))
        # A fronted adverbial ("Without the key, the auditor confirmed …") does
        # not deny the reporting act, so text before the clause's last comma is
        # outside the negation's scope unless it carries the negating subject
        # itself ("No one, per the memo, …"). The quantifier scan above still
        # runs over the whole clause, because a quantified subject stays the
        # subject wherever commas put it.
        comma = before.rfind(",")
        if quantified or comma == -1:
            negation_window = before
        else:
            negation_window = before[comma + 1:]
        negated = quantified or _NEGATION.search(negation_window) is not None
        quantifier = QUANTIFIER_NONE if quantified else (
            QUANTIFIER_SOME if _SOME_QUANTIFIER.search(before) else QUANTIFIER_ALL
        )
        # A verb with no complementiser after it is probably the main predicate of
        # the cue's own clause ("the checklist was unavailable" has no such verb,
        # but "the team confirmed the checklist" does) — only frames that take a
        # complement can govern the proposition that follows.
        # A frame governs a complement, so something complement-shaped must
        # follow. An empty tail is the normal case at the guard's call site: the
        # caller slices the prefix *at* the cue, so the cue itself is the
        # complement and there is nothing left to inspect. Reading that as "no
        # complement" would silently disable the rule for every sentence whose cue
        # opens with a determiner.
        if after.strip() and not _COMPLEMENT_OPENING.match(after):
            continue
        found.append(Attribution(
            agent=_subject_before(prefix, match.start()),
            quantifier=quantifier,
            polarity=POLARITY_NEGATED if negated else POLARITY_AFFIRMATIVE,
            verb_class=verb_class,
        ))
    return tuple(found)


def force_of_prefix(prefix: str) -> Force | None:
    """The composed force of every frame in ``prefix``, or ``None`` if none."""
    return compose_forces(assertion_force(frame) for frame in frames(prefix))
