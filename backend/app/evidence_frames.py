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

Why only evidential denials withhold
------------------------------------
The policy split is deliberate and is *not* a claim about English:

* **evidential** verbs (``confirm``, ``check``, ``verify``, ``establish``,
  ``document``, ``observe``, ``record``, ``demonstrate``) report that something
  was established. Denying them denies the establishment, so the complement is
  not asserted: ``"No one confirmed that the checklist was unavailable"`` is
  evidence *about the evidence base*, not about the checklist.
* **speech-act** verbs (``say``, ``claim``, ``report``, ``mention``, ``note``,
  ``state``, ``argue``, ``suggest``, ``tell``, ``write``) report that words were
  uttered. Denying them denies the utterance and leaves the content untouched,
  which is the reading the negation corpus pins
  (``CU-MATRIX-DID-NOT-SAY``, ``CU-MATRIX-NEVER-CLAIMED``,
  ``SC-NO-ONE-REPORTED``).

The second rule is a policy choice, not a theorem, and the falsification corpus
counts it: roughly a sixth of the generated hostile sentences still commit a
direction through a denied speech act. It is named in
``ct3/audit/REVIEW-scope-interval.md`` as the remaining product decision rather
than fixed here, because reversing it changes what the tool is allowed to claim.
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
})

#: Verbs that report an *utterance*. Denying one leaves the content untouched.
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
        return self.polarity == POLARITY_NEGATED and self.verb_class == EVIDENTIAL

    def describe(self) -> str:
        return (f"{self.verb_class}:{self.polarity}:{self.quantifier}"
                f"({self.agent or '-'})")


def verb_class_of(verb: str) -> str | None:
    return _VERB_CLASS.get(verb.casefold())


def assertion_force(attribution: Attribution) -> Force:
    """The total function the whole module exists for.

    Negated evidential frame -> ``WITHHOLDS``. Every other recognised frame ->
    ``ASSERTS``. There is no third outcome on purpose: a frame whose class is
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
    proposition was established", and a shallow scan answers it without pretending
    to more structure than the code has.
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
        negated = _NEGATION.search(before) is not None
        if _NONE_QUANTIFIER.search(before) is not None:
            negated = True
        quantifier = QUANTIFIER_NONE if _NONE_QUANTIFIER.search(before) else (
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
