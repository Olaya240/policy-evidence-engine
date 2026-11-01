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


def _is_negated(text: str, start: int) -> bool:
    """Detect a direct explicit negation before a cue, within its clause."""
    prefix = text[:start]
    boundaries = [prefix.rfind(char) for char in ".!?;\n"]
    clause = prefix[max(boundaries) + 1:]
    contrast = re.split(r"\b(?:but|however)\b", clause, flags=re.IGNORECASE)
    return _NEGATION_SUFFIX.search(contrast[-1]) is not None


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
                if _is_negated(quote, found.start()):
                    rejected_reasons.add("NEGATED_CUE")
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
        elif rejected_reasons == {"CONTRAST_CHANGED_CURRENT_STATE"}:
            reason_code = "CONTRAST_CHANGED_CURRENT_STATE"
        else:
            reason_code = "ALL_MATCHED_CUES_REJECTED"
    return {"relation": relation, "cue_ids": cue_ids, "reason_code": reason_code}
