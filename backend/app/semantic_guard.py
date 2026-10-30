"""Narrow phrase cue guard for the synthetic prototype, not general NLP.

Unmatched or mixed cues are unreviewed, not neutral. This cannot reliably
handle paraphrase, negation, context, or causal inference in arbitrary text.

Neutral cues are explicit statements that the quoted observation does not
address the hypothesis. Their presence can justify a neutral review outcome;
absence of directional cues alone never does. This is still phrase matching,
so it does not establish that the observation is actually neutral in context.
"""
from .models import Stance


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
    cues = _CUES.get(hypothesis_id)
    if cues is None:
        return None
    normalized = quote.casefold()
    matches = [stance for stance, phrases in cues.items() if any(p in normalized for p in phrases)]
    return matches[0] if len(matches) == 1 else None
