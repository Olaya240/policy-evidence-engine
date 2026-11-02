"""Deterministic offline provider; no HTTP, model, or external API calls."""
import json
import math
from threading import Lock
from datetime import datetime, timezone

from .models import HYPOTHESES, Record, Stance
from .provider_safety import AssessmentContextRecord, LocalAssessmentProvider, ProviderSafetyError

# Deliberately small synthetic fixture set. Provider output remains untrusted and
# is checked again by engine.py before it can become a persisted assessment.
SEED_RECORDS = [
    Record(id="OPS-101", timestamp=datetime(2026, 10, 20, 6, 5, tzinfo=timezone.utc), department="Front Office", text="Night checklist binder was missing from the desk; we wrote room 412's late arrival on a loose note.", tags=["checklist", "late-arrival"]),
    Record(id="OPS-102", timestamp=datetime(2026, 10, 20, 14, 12, tzinfo=timezone.utc), department="Front Office", text="The digital checklist opened normally on both desk terminals during the afternoon handover.", tags=["checklist", "pms"]),
    Record(id="OPS-103", timestamp=datetime(2026, 10, 21, 6, 10, tzinfo=timezone.utc), department="Housekeeping", text="New colleague was unsure which section records rooms awaiting inspection; supervisor walked through the handover sheet.", tags=["training", "handover"]),
    Record(id="OPS-104", timestamp=datetime(2026, 10, 21, 14, 3, tzinfo=timezone.utc), department="Housekeeping", text="All scheduled team members attended the handover briefing and completed the checklist together.", tags=["training", "staffing"]),
    Record(id="OPS-105", timestamp=datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc), department="Front Office", text="Two agents covered the desk while one colleague was absent; several guest requests were passed verbally.", tags=["staffing", "time-pressure"]),
    Record(id="OPS-106", timestamp=datetime(2026, 10, 22, 14, 25, tzinfo=timezone.utc), department="Front Office", text="The property system timed out while saving the handover notes. IT restored service at 14:20.", tags=["pms", "system-issue"]),
    Record(id="OPS-107", timestamp=datetime(2026, 10, 23, 6, 2, tzinfo=timezone.utc), department="Front Office", text="The desk was quiet and the shift had enough time to review every open item before sign-off.", tags=["time-pressure"]),
    Record(id="OPS-108", timestamp=datetime(2026, 10, 23, 14, 7, tzinfo=timezone.utc), department="Housekeeping", text="The handover sheet listed two rooms as ready, but the next shift found both still awaiting inspection.", tags=["handover", "conflict"]),
    Record(id="OPS-109", timestamp=datetime(2025, 1, 3, 9, 0, tzinfo=timezone.utc), department="Front Office", text="A printed checklist was unavailable during the morning shift last winter.", tags=["checklist", "stale"]),
    Record(id="OPS-110", timestamp=datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc), department="Front Office", text="We had enough people on duty and the checklist binder was at the desk, but the printer was out of paper.", tags=["staffing", "checklist", "pms"]),
    Record(id="OPS-111", timestamp=datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc), department="Maintenance", text="A guest called about a lamp; maintenance repaired it before the evening handover.", tags=["maintenance"]),
    Record(id="OPS-112", timestamp=datetime(2026, 10, 22, 6, 4, tzinfo=timezone.utc), department="Front Office", text="Supervisor recap of OPS-105: two agents covered the desk while a colleague was absent; guest requests passed verbally.", tags=["staffing", "copied-source"], source_group="OPS-105"),
    Record(id="CANARY-RESTRICTED-001", timestamp=datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc), department="Restricted", text="RESTRICTED_CANARY_DO_NOT_DISCLOSE_8f2b1d", tags=["restricted"], restricted=True),
]

HYPOTHESIS_KEYWORDS = {
    "CHECKLIST_UNAVAILABLE": ("checklist", "binder", "sheet", "printer"),
    "TRAINING_GAP": ("unsure", "walked through", "training", "trained"),
    "STAFFING_CONSTRAINTS": ("absent", "short", "understaffed", "enough people", "team members"),
    "PMS_SYSTEM_ISSUE": ("system", "terminal", "timed out", "printer", "digital checklist"),
    "TIME_PRESSURE": ("time", "shift", "requests", "quiet", "deadline", "verbally"),
}


def assess_pair(record: Record | AssessmentContextRecord, hypothesis_id: str) -> dict | None:
    """Return a deliberately explicit fixture assessment, or no assertion."""
    text = record.text.lower()
    explicit = {
        ("OPS-101", "CHECKLIST_UNAVAILABLE"): (Stance.SUPPORTS, "Binder was reported missing during this handover."),
        ("OPS-102", "CHECKLIST_UNAVAILABLE"): (Stance.CONTRADICTS, "Checklist access was reported working."),
        ("OPS-103", "TRAINING_GAP"): (Stance.SUPPORTS, "A colleague needed guidance on the handover process."),
        ("OPS-104", "TRAINING_GAP"): (Stance.CONTRADICTS, "The record says the briefing was attended and the checklist completed."),
        ("OPS-105", "STAFFING_CONSTRAINTS"): (Stance.SUPPORTS, "An absence reduced desk coverage and requests were passed verbally."),
        ("OPS-106", "PMS_SYSTEM_ISSUE"): (Stance.SUPPORTS, "A save timeout interrupted handover notes."),
        ("OPS-107", "TIME_PRESSURE"): (Stance.CONTRADICTS, "The shift reported time to review every open item."),
        ("OPS-108", "CHECKLIST_UNAVAILABLE"): (Stance.NEUTRAL, "The mismatch concerns room status; it does not indicate whether the checklist was available."),
        ("OPS-109", "CHECKLIST_UNAVAILABLE"): (Stance.SUPPORTS, "The record reports a missing printed checklist, but it is stale."),
        ("OPS-110", "STAFFING_CONSTRAINTS"): (Stance.CONTRADICTS, "The shift explicitly reports enough staff."),
        ("OPS-110", "CHECKLIST_UNAVAILABLE"): (Stance.CONTRADICTS, "The binder was available, although a printer issue was separately reported."),
        ("OPS-111", "PMS_SYSTEM_ISSUE"): (Stance.NEUTRAL, "The lamp repair does not address property-system availability."),
        ("OPS-112", "STAFFING_CONSTRAINTS"): (Stance.SUPPORTS, "This recap repeats OPS-105 and is not an independent source."),
    }
    pair = explicit.get((record.id, hypothesis_id))
    if pair is None:
        keys = HYPOTHESIS_KEYWORDS[hypothesis_id]
        if not any(k in text for k in keys):
            return None
        # Unmapped keyword overlap is not treated as semantic support.
        pair = (Stance.NEUTRAL, "The source mentions a related term but does not establish this hypothesis.")
    stance, rationale = pair
    return {"source_record_id": record.id, "quote": record.text, "stance": stance.value, "rationale": rationale}


_PROPOSAL_KEYS = frozenset({"source_record_id", "quote", "stance", "rationale"})


def validate_fixture_output(output, records):
    """Refuse a configured fixture that cites evidence this call did not supply.

    A fixture is provider output, so it is held to the provenance rule the
    provider itself must obey: every ``source_record_id`` must be one of the
    records handed to *this* call, and every ``quote`` must appear in that
    record's own text. A fixture naming any other record is fabricated evidence
    even before the engine sees it, so it is refused here rather than echoed.

    Shape and provenance only; stance/rationale domain validity stays with the
    engine's boundary, which sees the same proposal list afterwards.
    """
    texts = {}
    for record in records:
        record_id, text = getattr(record, "id", None), getattr(record, "text", None)
        if type(record_id) is str and type(text) is str:
            texts[record_id] = text
    if type(output) is not list:
        raise ProviderSafetyError("malformed_output")
    for item in output:
        if type(item) is not dict or set(item) != _PROPOSAL_KEYS:
            raise ProviderSafetyError("malformed_output")
        source_id = item["source_record_id"]
        if type(source_id) is not str or source_id not in texts:
            raise ProviderSafetyError("invalid_source")
        quote = item["quote"]
        if type(quote) is not str or len(quote.strip()) < 3 or quote not in texts[source_id]:
            raise ProviderSafetyError("invalid_quote")
    return output


class MockProvider(LocalAssessmentProvider):
    """Offline provider interface. Its assessments are always independently validated."""

    __slots__ = ("_overrides", "_sequences", "_sequence_counts", "_lock", "_calls", "_history", "_failure_message", "_sealed")

    def __init__(self, *, assessment_overrides=None, assessment_sequences=None, failure_message=None):
        known = {hypothesis.id for hypothesis in HYPOTHESES}
        overrides = self._encode_mapping({} if assessment_overrides is None else assessment_overrides, known, sequences=False)
        sequences = self._encode_mapping({} if assessment_sequences is None else assessment_sequences, known, sequences=True)
        if failure_message is not None and type(failure_message) is not str:
            raise ValueError("Invalid mock failure fixture")
        object.__setattr__(self, "_overrides", overrides)
        object.__setattr__(self, "_sequences", sequences)
        object.__setattr__(self, "_sequence_counts", {})
        object.__setattr__(self, "_lock", Lock())
        object.__setattr__(self, "_calls", 0)
        object.__setattr__(self, "_history", [])
        object.__setattr__(self, "_failure_message", failure_message)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("mock provider configuration is immutable")
        object.__setattr__(self, name, value)

    @staticmethod
    def _plain_json(value):
        if type(value) in (str, int, bool) or value is None:
            return True
        if type(value) is float:
            return math.isfinite(value)
        if type(value) is list:
            return all(MockProvider._plain_json(item) for item in value)
        if type(value) is dict:
            return all(type(key) is str and MockProvider._plain_json(item) for key, item in value.items())
        return False

    @staticmethod
    def _encode_output(value):
        if not MockProvider._plain_json(value):
            raise ValueError("Invalid mock assessment fixture")
        try:
            encoded = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError):
            raise ValueError("Invalid mock assessment fixture") from None
        if len(encoded) > 4 * 1024:
            raise ValueError("Invalid mock assessment fixture")
        return encoded

    @classmethod
    def _encode_mapping(cls, mapping, known, *, sequences):
        if type(mapping) is not dict or any(type(key) is not str or key not in known for key in mapping):
            raise ValueError("Invalid mock assessment fixture")
        encoded = []
        for key, value in mapping.items():
            if sequences:
                if type(value) is not list or not value:
                    raise ValueError("Invalid mock assessment fixture")
                item = tuple(cls._encode_output(output) for output in value)
            else:
                item = cls._encode_output(value)
            encoded.append((key, item))
        return tuple(encoded)

    @property
    def assessment_call_count(self):
        with self._lock:
            return self._calls

    @property
    def assessment_history(self):
        with self._lock:
            return tuple(self._history)

    def _fixture_output(self, hypothesis_id):
        with self._lock:
            object.__setattr__(self, "_calls", self._calls + 1)
            self._history.append(hypothesis_id)
            if self._failure_message is not None:
                raise RuntimeError(self._failure_message)
            sequences = dict(self._sequences)
            if hypothesis_id in sequences:
                index = self._sequence_counts.get(hypothesis_id, 0)
                self._sequence_counts[hypothesis_id] = index + 1
                outputs = sequences[hypothesis_id]
                return True, json.loads(outputs[min(index, len(outputs) - 1)])
            overrides = dict(self._overrides)
            if hypothesis_id in overrides:
                return True, json.loads(overrides[hypothesis_id])
        return False, None

    def assess(self, records: list[Record | AssessmentContextRecord], hypothesis_id: str) -> list[dict]:
        if hypothesis_id not in {hyp.id for hyp in HYPOTHESES}:
            raise ValueError("Unknown hypothesis")
        has_fixture, fixture_output = self._fixture_output(hypothesis_id)
        if has_fixture:
            # Fixtures (overrides and sequences) are held to the same provenance
            # rule as generated output: cite only records this call was given.
            return validate_fixture_output(fixture_output, records)
        result = []
        for record in records:
            if record.restricted:
                continue
            assessment = assess_pair(record, hypothesis_id)
            if assessment is not None:
                result.append(assessment)
        return result

