"""Narrow phrase cue guard for the synthetic prototype, not general NLP.

Unmatched or mixed cues, including cues immediately preceded by explicit
negation, are unreviewed, not neutral. This cannot reliably handle paraphrase,
complex negation, context, or causal inference in arbitrary text.

Neutral cues are explicit statements that the quoted observation does not
address the hypothesis. Their presence can justify a neutral review outcome;
absence of directional cues alone never does. This is still phrase matching,
so it does not establish that the observation is actually neutral in context.
"""
import re

from .models import Stance
from .scope_layer import SentenceScope, build_scope
from .stance_algebra import (
    Clause,
    Modality,
    NegationScope,
    Polarity,
    QuantifierScope,
    combine_reasons,
    compose_all,
    to_guard_reading,
)


_NEGATION_SUFFIX = re.compile(
    r"(?:\b(?:not|never|no|without)\b|\b(?:am|is|are|was|were|do|does|did|"
    r"can|could|has|have|had)n['’]t\b)"
    r"(?:\s+(?:very|really|currently|yet|at\s+all))?[\s,]*$",
    re.IGNORECASE,
)

_CONTRASTING_CURRENT_NEGATION = re.compile(
    r"^\s*(?:(?:am|is|are|was|were|do|does|did)\s+)?"
    r"(?:not|never|no\s+longer)\b"
    r"(?:\s+[\w’'-]+){0,2}\s*(?:now|anymore|currently|today)\b",
    re.IGNORECASE,
)
_CURRENT_MARKER = re.compile(r"\b(?:now|anymore|currently|today)\b", re.IGNORECASE)


# "We did not have enough time": the negation is carried by an auxiliary that
# sits between it and the cue, so the clause does not end with the negation
# itself. Without this, the same proposition was certified in opposite
# directions depending on whether "not" landed before or after "have".
_NEGATED_AUXILIARY_SUFFIX = re.compile(
    r"(?:\b(?:not|never|no|without)\b|\b(?:am|is|are|was|were|do|does|did|"
    r"can|could|has|have|had)n['’]t\b)"
    r"\s+(?:have|has|had|be|been|being|do|does|did|get|got)\b[\s,]*$",
    re.IGNORECASE,
)


# "Nobody walked through the handover": the negation is a subject quantifier
# rather than an adjacent "not", so neither suffix above sees it. The reporting
# verbs matter: "No one said the binder was missing" negates the *saying*, not the
# binder, and must keep certifying the cue.
# "It is not true that the checklist was unavailable": the negation is a frame over
# the whole complement clause, so it is neither adjacent to the cue (the suffix above
# cannot see it) nor a subject quantifier. Without this the cue certified SUPPORTS —
# the sentence denies the hypothesis and was counted as support for it. The guard
# abstains rather than flipping the cue, because flipping a negative cue is an
# inference it does not make anywhere else.
_NEGATED_FRAME = re.compile(
    r"\bnot\s+(?:true|the\s+case)\s+that\b",
    re.IGNORECASE,
)

# "Staff did not have enough time, so the checklist was unavailable": the negation
# sits in the premise clause of a consequence, a whole clause away from the cue, so
# neither suffix sees it and the cue was certified in the affirmative direction. A
# bare comma is not enough — "The staff did not have training, the checklist was
# unavailable" keeps certifying — so the rule needs the consequence link itself.
_CONSEQUENCE_LINK = re.compile(
    r"^\s*(?:so(?:\s+that)?|therefore|thus|hence|as\s+a\s+result|"
    r"which\s+is\s+why|which\s+meant(?:\s+that)?|meaning(?:\s+that)?)\b",
    re.IGNORECASE,
)

# A negation word or contraction, deliberately *without* a plain ``no``: the
# quantifier rows ("No one could confirm ...") are handled above and must keep
# certifying, and ``no`` on its own is what the adjacent suffixes already read.
_NEGATION_IN_CLAUSE = re.compile(
    r"\b(?:not|never|without)\b|"
    r"\b(?:do|does|did|is|are|was|were|has|have|had|can|could|would|should)n['’]t\b",
    re.IGNORECASE,
)

# "The team did not confirm the checklist was available": the negation scopes over
# the evidential verb, and the sentence states the absence of confirmation rather
# than the falsity of the cue. Only evidential verbs are listed. Speech-act verbs
# (say / claim / report / state / note) negate the saying, not the complement, and
# the corpus pins them as still certifying ("The auditor did not say the binder was
# at the desk" -> CONTRADICTS).
_EVIDENTIAL_VERB = re.compile(
    r"\b(?:confirm|confirmed|establish|established|verify|verified|observe|"
    r"observed|record|recorded|document|documented|demonstrate|demonstrated)\b",
    re.IGNORECASE,
)

# "No evidence the checklist was available" is a statement about the evidence
# base, not about the checklist: the cue is reported as unestablished rather than
# asserted or denied. The frame must be in the cue's own clause segment, so a
# "no evidence" in another clause or after the cue cannot swallow it, and it is a
# closed list so "no doubt" / "nothing in the notes says" keep certifying.
_EVIDENCE_ABOUTNESS_FRAME = re.compile(
    r"\b(?:no\s+(?:evidence|indication|sign)|nothing\s+(?:suggests|indicates|"
    r"shows))\b",
    re.IGNORECASE,
)

# "Perhaps the checklist was unavailable": a sentence-initial epistemic adverbial
# proposes the cue instead of asserting it, and the guard only certifies asserted
# propositions. Before this rule the cue was certified SUPPORTS — a possibility
# counted as a finding. The frame is read in the cue's own comma segment, where
# English puts these markers: an adverb inside the fixed phrase ("was probably
# unavailable") already breaks the cue and abstains as NO_CUE_MATCH, a hedge in a
# preceding comma clause does not reach the cue ("Perhaps the ward was busy, and
# the checklist was unavailable" still certifies), and a hedge *after* the cue is
# outside this rule and remains uncertified only by nothing at all — that residual
# is recorded in ct3/audit/SEMANTIC-BENCHMARK.md rather than papered over.
# Deliberately absent: "may" / "might", which almost always sit inside the fixed
# cue ("may have been unavailable") and so never reach a contiguous cue match, and
# bare "could", which is a cue word in "could not review every open item".
_HEDGE_FRAME = re.compile(
    r"\b(?:perhaps|possibly|probably|maybe|presumably|apparently|conceivably)\b"
    r"|\bit\s+(?:seems|appears)\b"
    r"|\b(?:it\s+is|it\s+was)\s+(?:possible|likely|probable)\b",
    re.IGNORECASE,
)

# "Was the checklist unavailable at the ward round?": a yes/no question asks
# *whether* the cue holds and asserts nothing, so nothing can be certified. The
# excluded rows that make this rule necessary certified the question's cue as
# though it were a statement. The unit is the sentence, not the quote: a question
# mark in one sentence does not reach a cue in another, so "The checklist was
# unavailable. Was the binder at the desk?" keeps its assertion, and a tag
# question ("The checklist was unavailable, wasn't it?") is one interrogative
# sentence and is read as a question.
_SENTENCE_TERMINATOR = re.compile(r"[.!?]+|\n")

# "If the checklist was unavailable, the team should have escalated": a
# conditional clause proposes the cue and says what follows from it, so the cue
# is not asserted. The marker has to open the cue's own clause; the clause the
# cue sits in — and the clause before it — is read by ``scope_layer``, because a
# cue one side of the comma and a cue the other side are the same operator. The
# mid-sentence temporal "when" in the corpus row "It was not raining when the
# binder was missing" does not open the clause and is not a conditional.
_CONDITIONAL_CLAUSE_OPENING = re.compile(
    r"^\s*(?:even\s+)?(?:if|when|unless|provided\s+that)\b",
    re.IGNORECASE,
)

_SUBJECT_QUANTIFIER = re.compile(r"\b(?:nobody|no\s+one|none\s+of|neither)\b", re.IGNORECASE)
_REPORTING_VERB = re.compile(
    r"\b(?:said|says|saying|claimed|claims|reported|reports|mentioned|mentions|"
    r"noted|notes|stated|states|argued|argues|suggested|suggests|denied|denies|"
    r"told|tells|wrote|writes|confirmed|confirms)\b",
    re.IGNORECASE,
)


def _is_quantified_negation(final_clause: str) -> bool:
    """A subject quantifier scoping over the cue, not over a matrix clause.

    "Nobody walked through the handover" negates the walking. "No one said that
    the binder was missing" negates the saying: the cue sits in a complement
    clause, so either an explicit complementiser or a reporting verb between the
    quantifier and the cue means the quantifier does not scope over it.
    """
    quantifier = _SUBJECT_QUANTIFIER.search(final_clause)
    if quantifier is None:
        return False
    tail = final_clause[quantifier.end():]
    if _REPORTING_VERB.search(tail) is not None:
        return False
    return re.search(r"\bthat\b", tail, re.IGNORECASE) is None


def _cue_prefix_clause(text: str, start: int) -> str:
    """The clause between the last sentence/contrast boundary and the cue."""
    prefix = text[:start]
    boundaries = [prefix.rfind(char) for char in ".!?;\n"]
    clause = prefix[max(boundaries) + 1:]
    contrast = re.split(r"\b(?:but|however)\b", clause, flags=re.IGNORECASE)
    return contrast[-1]


def _is_negated_premise_clause(final_clause: str) -> bool:
    """A negated premise clause joined to the cue's clause by a consequence.

    "Staff did not have enough time, so the checklist was unavailable" reads the
    cue through a negated premise. The guard does not decide whether the
    consequence holds, so it abstains instead of certifying the cue's stance.
    """
    segments = final_clause.split(",")
    if len(segments) < 2:
        return False
    if _CONSEQUENCE_LINK.match(segments[-1]) is None:
        return False
    return any(_NEGATION_IN_CLAUSE.search(segment) for segment in segments[:-1])


def _is_negated_evidential_verb(final_clause: str) -> bool:
    """A negation over an evidential verb in the cue's own comma segment.

    "The team did not confirm the checklist was available" reports the absence of
    confirmation. Neither the cue nor its negation is stated, so nothing can be
    certified. The scan stays inside the cue's comma segment: a negation in a
    separate clause is not the cue's negation (``CU-AUX-OTHER-CLAUSE``).
    """
    segment = final_clause.split(",")[-1]
    negation = _NEGATION_IN_CLAUSE.search(segment)
    if negation is None:
        return False
    return _EVIDENTIAL_VERB.search(segment[negation.end():]) is not None


def _negation_scope(final_clause: str) -> NegationScope:
    """Where the negation sits relative to the cue, if there is one.

    The three scopes are read separately because they are different kinds of
    evidence — an adjacent ``not`` is in the cue's own phrase, a frame negation
    is a matrix clause over it, and a negated evidential verb reports the absence
    of a report — but every one of them withholds the clause rather than flipping
    it. Which scope fired is recorded, not used to pick a direction.
    """
    if (_NEGATION_SUFFIX.search(final_clause) is not None
            or _NEGATED_AUXILIARY_SUFFIX.search(final_clause) is not None):
        return NegationScope.ADJACENT
    if (_NEGATED_FRAME.search(final_clause) is not None
            or _is_negated_premise_clause(final_clause)):
        return NegationScope.FRAME
    if _is_negated_evidential_verb(final_clause):
        return NegationScope.VERB_SEPARATED
    return NegationScope.NONE


def _has_subject_wide_quantifier(final_clause: str) -> bool:
    """A subject quantifier that scopes over the cue rather than over a matrix."""
    return _is_quantified_negation(final_clause)


def _is_negated(final_clause: str) -> bool:
    """Detect an explicit negation scoping over a cue, within its clause."""
    return (_negation_scope(final_clause) is not NegationScope.NONE
            or _has_subject_wide_quantifier(final_clause))


def _is_evidence_aboutness_frame(final_clause: str) -> bool:
    """A statement about the evidence, in the cue's own comma segment."""
    segment = final_clause.split(",")[-1]
    return _EVIDENCE_ABOUTNESS_FRAME.search(segment) is not None


_POSTPOSED_HEDGE = re.compile(
    r"^\s*,\s*(?:perhaps|possibly|probably|maybe|presumably|apparently|conceivably)\b",
    re.IGNORECASE,
)


def _is_postposed_hedge(quote: str, end: int) -> bool:
    """A hedge after the cue, in the cue's own comma tail.

    `_cue_prefix_clause` returns the text *before* the cue, so a hedge that follows it
    ("… was unavailable, probably") was structurally invisible to `_is_hedged`: the
    clause it inspects cannot contain the words after the cue. Measured before this
    reader existed: "The checklist was unavailable, probably." certified SUPPORTS while
    "The checklist was probably unavailable." abstained — the same hedge, opposite
    treatment, decided by word order alone.
    """
    tail = quote[end:end + 48]
    stop = min((index for index in (tail.find("."), tail.find("!"), tail.find("?"), tail.find("\n")) if index != -1), default=len(tail))
    return _POSTPOSED_HEDGE.match(tail[:stop]) is not None


def _is_hedged(final_clause: str) -> bool:
    """An epistemic hedge over the cue, in the cue's own comma segment.

    "Perhaps the checklist was unavailable" proposes the proposition; it does not
    assert it, so neither direction can be certified. The scan stays in the cue's
    own segment: a hedge in a previous comma clause is not a hedge over the cue.
    """
    segment = final_clause.split(",")[-1]
    return _HEDGE_FRAME.search(segment) is not None


def _is_cue_in_question(text: str, start: int) -> bool:
    """The cue sits in a sentence whose own terminator is a question mark.

    A question asks whether the cue holds; it neither asserts nor denies it, so
    the guard abstains rather than certifying either direction. The scan stops at
    sentence boundaries, so a statement sharing a quote with a question keeps its
    assertion.

    Only ``.``, ``!``, ``?`` and a newline end a sentence. A colon or semicolon
    does not, so "The checklist was unavailable; was the ward busy?" is read as
    one interrogative sentence and abstains. That errs toward abstention, which
    this guard always prefers to a certified direction.
    """
    position = 0
    for terminator in _SENTENCE_TERMINATOR.finditer(text):
        if position <= start < terminator.start():
            return terminator.group().endswith("?")
        position = terminator.end()
    return False


def _is_conditional_cue(final_clause: str) -> bool:
    """The cue's own comma segment opens with a conditional marker.

    ``if`` / ``when`` / ``unless`` / ``provided that`` propose their content; the
    sentence asserts only whatever the main clause states about it. This reads
    the segment in front of the cue; the clause *after* the cue, and the
    antecedent clause, are read by :meth:`scope_layer.SentenceScope.
    conditional_scope_at`, so the marker gets one reading from either side of
    the comma.
    """
    return _CONDITIONAL_CLAUSE_OPENING.match(final_clause.split(",")[-1]) is not None


def _modality(quote: str, start: int, final_clause: str, end: int | None = None,
              scope: SentenceScope | None = None) -> Modality:
    """How the cue's clause states its content, in the order the guard reads it.

    Interrogative and conditional are sentence- and clause-level readings, so
    they are tested before the narrower frames; a clause that is both a question
    and a hedge is reported as a question because that is the reading that
    dominates.

    ``scope`` carries the readings that need the whole sentence rather than the
    text in front of the cue: a conditional marker in the antecedent clause or
    after the cue, and a sentence-initial hedge that spans across a semicolon.
    """
    if _is_cue_in_question(quote, start):
        return Modality.INTERROGATIVE
    if _is_conditional_cue(final_clause):
        return Modality.CONDITIONAL
    if scope is not None and scope.conditional_scope_at(start, end):
        return Modality.CONDITIONAL
    if _is_evidence_aboutness_frame(final_clause):
        return Modality.EVIDENTIAL_FRAME
    if _is_hedged(final_clause):
        return Modality.HEDGED
    if scope is not None and scope.hedge_scope_at(start):
        return Modality.HEDGED
    if end is not None and _is_postposed_hedge(quote, end):
        return Modality.HEDGED
    return Modality.ASSERTED


_POLARITY_BY_STANCE = {
    Stance.SUPPORTS: Polarity.SUPPORTS,
    Stance.CONTRADICTS: Polarity.CONTRADICTS,
    Stance.NEUTRAL: Polarity.NONE,
}


def _has_later_current_change(
    text: str, end: int, stance: Stance, cues: dict[Stance, tuple[str, ...]],
) -> bool:
    """Abstain when a later contrast explicitly changes current cue status."""
    remainder = text[end:]
    contrast = re.search(r"\b(?:but|however)\b", remainder, flags=re.IGNORECASE)
    if contrast is None:
        return False
    later_clause = remainder[contrast.end():]
    boundary = re.search(r"[.!?;\n]", later_clause)
    if boundary is not None:
        later_clause = later_clause[:boundary.start()]
    if _CONTRASTING_CURRENT_NEGATION.search(later_clause) is not None:
        return True

    if _CURRENT_MARKER.search(later_clause) is None:
        return False
    for other_stance, phrases in cues.items():
        if other_stance == stance:
            continue
        for phrase in phrases:
            words = phrase.split()
            # A contrast often omits the repeated subject and auxiliary:
            # "checklist unavailable, but available now". Only use the final
            # cue words to detect conflict; this path always abstains.
            for count in range(min(3, len(words)), 0, -1):
                tail = r"\s+".join(re.escape(word) for word in words[-count:])
                if re.search(r"\b" + tail + r"\b", later_clause, re.IGNORECASE):
                    return True
    return False


_CUES = {
    "CHECKLIST_UNAVAILABLE": {
        Stance.SUPPORTS: ("binder was missing", "checklist unavailable", "checklist was unavailable", "printed checklist was unavailable"),
        Stance.CONTRADICTS: ("checklist opened normally", "binder was at the desk", "checklist was available"),
        Stance.NEUTRAL: ("says nothing about checklist availability", "does not address checklist availability",),
    },
    "TRAINING_GAP": {
        Stance.SUPPORTS: ("colleague was unsure", "walked through the handover", "needed guidance on the handover"),
        Stance.CONTRADICTS: ("attended the handover briefing and completed the checklist",),
    },
    "STAFFING_CONSTRAINTS": {
        Stance.SUPPORTS: ("colleague was absent", "short staffed", "short-staffed", "understaffed"),
        Stance.CONTRADICTS: ("enough people on duty",),
    },
    "PMS_SYSTEM_ISSUE": {
        Stance.SUPPORTS: ("system timed out", "system failed while saving", "system was unavailable"),
        Stance.CONTRADICTS: ("system worked normally", "system was working normally"),
    },
    "TIME_PRESSURE": {
        Stance.SUPPORTS: ("not enough time", "ran out of time", "time pressure", "could not review every open item"),
        Stance.CONTRADICTS: ("enough time to review every open item", "shift had enough time"),
    },
}


def reviewed_relation(quote: str, hypothesis_id: str) -> Stance | None:
    """Return one explicitly cued relation; ambiguity and unmatched text abstain."""
    return reviewed_relation_details(quote, hypothesis_id)["relation"]


def _cue_id(hypothesis_id: str, stance: Stance, phrase: str) -> str:
    """Stable identifier derived from the fixed cue inventory, never quote text."""
    slug = phrase.casefold().replace("-", "_hyphen_").replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]+", "", slug).strip("_")
    return f"{hypothesis_id}.{stance.value}.{slug}"


def reviewed_relation_details(quote: str, hypothesis_id: str) -> dict:
    """Return the guard's existing decision plus bounded trace metadata.

    The relation selection is deliberately identical to ``reviewed_relation``;
    this companion only exposes which fixed cue strings matched or why they
    were excluded.
    """
    cues = _CUES.get(hypothesis_id)
    if cues is None:
        return {"relation": None, "cue_ids": [], "reason_code": "UNKNOWN_HYPOTHESIS"}
    # Each matched cue becomes one typed clause. The clause's scope fields decide
    # whether it commits to a direction or withholds, and the sentence's verdict is
    # the join of those contributions in ``stance_algebra``. Nothing here selects a
    # stance from a set: a set can only count, and counting cannot tell "two
    # assertions tied" from "one assertion plus something that says nothing".
    clauses: list[Clause] = []
    matched_cue_ids = []
    saw_cue = False
    # One sentence-scope pass per quote, shared by every cue in it: the clause
    # structure is a property of the sentence, not of the cue being read.
    scope = build_scope(quote)
    for stance, phrases in cues.items():
        for phrase in phrases:
            phrase_pattern = r"\s+".join(re.escape(part) for part in phrase.split())
            for found in re.finditer(phrase_pattern, quote, re.IGNORECASE):
                saw_cue = True
                cue_id = _cue_id(hypothesis_id, stance, phrase)
                if cue_id not in matched_cue_ids:
                    matched_cue_ids.append(cue_id)
                final_clause = _cue_prefix_clause(quote, found.start())
                clause = Clause(
                    polarity=_POLARITY_BY_STANCE[stance],
                    modality=_modality(quote, found.start(), final_clause,
                                       found.end(), scope),
                    negation=_negation_scope(final_clause),
                    quantifier=(QuantifierScope.SUBJECT_WIDE
                                if _has_subject_wide_quantifier(final_clause)
                                else QuantifierScope.NONE),
                    superseded=_has_later_current_change(quote, found.end(), stance, cues),
                )
                clauses.append(clause)
                if clause.certifies():
                    break
    # The same cue can occur once more whose subject was elided to a pronoun
    # ("…, and others say it was available"). No fixed phrase matches it, and
    # skipping it is the defect: the opposing clause disappeared and the support
    # clause certified alone. Each such clause is typed with its own scope, so it
    # opposes the named one and the join abstains. A clause whose pronoun has no
    # antecedent in the sentence is withheld rather than dropped.
    for stance, phrases in cues.items():
        for phrase in phrases:
            for derived in scope.derived_matches(phrase):
                saw_cue = True
                cue_id = _cue_id(hypothesis_id, stance, phrase)
                if cue_id not in matched_cue_ids:
                    matched_cue_ids.append(cue_id)
                if not derived.attributed:
                    clauses.append(Clause(
                        polarity=_POLARITY_BY_STANCE[stance],
                        quantifier=QuantifierScope.SUBJECT_WIDE,
                    ))
                    continue
                clauses.append(Clause(
                    polarity=_POLARITY_BY_STANCE[stance],
                    modality=_modality(quote, derived.start, derived.clause.text,
                                       derived.end, scope),
                    negation=_negation_scope(derived.clause.text),
                    superseded=_has_later_current_change(
                        quote, derived.end, stance, cues),
                ))
    reading = to_guard_reading(
        compose_all(clauses),
        abstain_reason=combine_reasons(
            (clause.withheld_by() for clause in clauses if not clause.certifies()),
            saw_cue=saw_cue,
        ),
        explicit_neutral_information=any(
            clause.certifies() and clause.polarity is Polarity.NONE
            for clause in clauses
        ),
    )
    return {
        "relation": Stance(reading.relation) if reading.relation is not None else None,
        "cue_ids": sorted(matched_cue_ids),
        "reason_code": reading.reason_code,
    }
