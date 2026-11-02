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


def _is_negated(final_clause: str) -> bool:
    """Detect an explicit negation scoping over a cue, within its clause."""
    return (_NEGATION_SUFFIX.search(final_clause) is not None
            or _NEGATED_AUXILIARY_SUFFIX.search(final_clause) is not None
            or _NEGATED_FRAME.search(final_clause) is not None
            or _is_quantified_negation(final_clause)
            or _is_negated_premise_clause(final_clause)
            or _is_negated_evidential_verb(final_clause))


def _is_evidence_aboutness_frame(final_clause: str) -> bool:
    """A statement about the evidence, in the cue's own comma segment."""
    segment = final_clause.split(",")[-1]
    return _EVIDENCE_ABOUTNESS_FRAME.search(segment) is not None


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
    matches = set()
    matched_cue_ids = []
    rejected_reasons = set()
    saw_cue = False
    for stance, phrases in cues.items():
        for phrase in phrases:
            phrase_pattern = r"\s+".join(re.escape(part) for part in phrase.split())
            for found in re.finditer(phrase_pattern, quote, re.IGNORECASE):
                saw_cue = True
                cue_id = _cue_id(hypothesis_id, stance, phrase)
                if cue_id not in matched_cue_ids:
                    matched_cue_ids.append(cue_id)
                final_clause = _cue_prefix_clause(quote, found.start())
                if _is_negated(final_clause):
                    rejected_reasons.add("NEGATED_CUE")
                    continue
                if _is_evidence_aboutness_frame(final_clause):
                    rejected_reasons.add("EVIDENCE_ABOUTNESS_FRAME")
                    continue
                if _has_later_current_change(quote, found.end(), stance, cues):
                    rejected_reasons.add("CONTRAST_CHANGED_CURRENT_STATE")
                    continue
                matches.add(stance)
                break
    relation = next(iter(matches)) if len(matches) == 1 else None
    if relation is not None:
        reason_code = None
        cue_ids = sorted(matched_cue_ids)
    else:
        cue_ids = sorted(matched_cue_ids)
        if len(matches) > 1:
            reason_code = "AMBIGUOUS_CUE_RELATIONS"
        elif not saw_cue:
            reason_code = "NO_CUE_MATCH"
        elif rejected_reasons == {"NEGATED_CUE"}:
            reason_code = "NEGATED_CUE"
        elif rejected_reasons == {"EVIDENCE_ABOUTNESS_FRAME"}:
            reason_code = "EVIDENCE_ABOUTNESS_FRAME"
        elif rejected_reasons == {"CONTRAST_CHANGED_CURRENT_STATE"}:
            reason_code = "CONTRAST_CHANGED_CURRENT_STATE"
        else:
            reason_code = "ALL_MATCHED_CUES_REJECTED"
    return {"relation": relation, "cue_ids": cue_ids, "reason_code": reason_code}
