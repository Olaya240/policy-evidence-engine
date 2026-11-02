"""API schemas and typed domain models."""
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Stance(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"


class EvidenceReviewState(str, Enum):
    ACCEPTED = "ACCEPTED"
    UNVERIFIED = "UNVERIFIED"


class Status(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT = "INSUFFICIENT"


class Hypothesis(BaseModel):
    id: str
    label: str


HYPOTHESES = [
    Hypothesis(id="CHECKLIST_UNAVAILABLE", label="The handover checklist was unavailable"),
    Hypothesis(id="TRAINING_GAP", label="A training gap affected handover completeness"),
    Hypothesis(id="STAFFING_CONSTRAINTS", label="Staffing constraints affected handover completeness"),
    Hypothesis(id="PMS_SYSTEM_ISSUE", label="A PMS system issue affected handover completeness"),
    Hypothesis(id="TIME_PRESSURE", label="Time pressure affected handover completeness"),
]


class InvestigationPreset(str, Enum):
    """Fixed user-facing question choices; clients cannot define hypotheses."""

    HANDOVER_OMISSIONS = "handover_omissions"
    CHECKLIST_ACCESS = "checklist_access"
    DESK_COVERAGE = "desk_coverage"
    PROPERTY_SYSTEM = "property_system"


INVESTIGATION_PRESET_QUESTIONS = {
    InvestigationPreset.HANDOVER_OMISSIONS: "Did time pressure contribute to recurring handover omissions?",
    InvestigationPreset.CHECKLIST_ACCESS: "Did checklist availability contribute to missing handover information?",
    InvestigationPreset.DESK_COVERAGE: "Did staffing constraints affect how guest requests were handed over?",
    InvestigationPreset.PROPERTY_SYSTEM: "Did property system interruptions affect handover note completion?",
}

INVESTIGATION_PRESET_HYPOTHESES = {
    InvestigationPreset.HANDOVER_OMISSIONS: "TIME_PRESSURE",
    InvestigationPreset.CHECKLIST_ACCESS: "CHECKLIST_UNAVAILABLE",
    InvestigationPreset.DESK_COVERAGE: "STAFFING_CONSTRAINTS",
    InvestigationPreset.PROPERTY_SYSTEM: "PMS_SYSTEM_ISSUE",
}


class Evidence(BaseModel):
    # Empty ids are the identity field of a citation: an evidence row that cites
    # nothing cannot be grounded, traced, or challenged.
    source_record_id: str = Field(min_length=1)
    timestamp: datetime
    quote: str
    stance: Stance
    review_state: EvidenceReviewState = EvidenceReviewState.ACCEPTED
    # Guarded assessments retain the proposal and phrase-level decision for audit.
    proposed_stance: Optional[Stance] = None
    semantic_relation: Optional[Stance] = None
    rationale: str
    stale: bool = False
    department: str
    source_group: Optional[str] = None
    disputed: bool = False


class Claim(BaseModel):
    id: str
    hypothesis_id: str
    status: Status
    # Magnitude of the evidence margin, kept for existing consumers. It cannot
    # distinguish one source for from one source against; the sign is carried by
    # `evidence_score` and `evidence_direction` below.
    confidence: float = Field(ge=0, le=1)
    # Additive, signed view of the same decision (range (-1, 1), 0 = no net
    # direction). Optional and defaulted, following `explanation_trace`, so rows
    # persisted before the signed table existed still validate unchanged. No
    # bound is enforced here on purpose: a constraint added later must not be
    # able to reject a stored snapshot.
    evidence_score: Optional[float] = None
    evidence_direction: Optional[Literal["FOR", "AGAINST", "NONE"]] = None
    uncertainty: str
    summary: str
    evidence: list[Evidence]
    conflicts: list[str]
    missing_evidence: list[str]
    dependencies: list[str]
    version: int
    # Additive audit metadata; absent legacy snapshots serialize as unavailable.
    explanation_trace: Optional[dict] = None


class InvestigationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=8, max_length=500)
    # Optional to preserve existing question-only API callers. The frontend's
    # supported presets always provide this server-validated selector.
    preset_id: Optional[InvestigationPreset] = None

    # `mode="before"` so `min_length` measures the stripped value: otherwise
    # "        x" passed the length bound and was then stored as "x".
    @field_validator("question", mode="before")
    @classmethod
    def non_blank(cls, value: object) -> object:
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("Question must not be blank")
            return value.strip()
        return value


class ChallengeCreate(BaseModel):
    # Same contract as InvestigationCreate: a caller sending an unknown field is
    # told so instead of having it silently dropped.
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=8, max_length=1000)
    source_record_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=3, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def non_blank_reason(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Challenge reason must not be blank")
        return value.strip()


# Ingestion MVP bound: one plain-text document per request. Sized for a shift
# note or a pasted paragraph, not a file. The bound is enforced by the schema, so
# an oversized body is a 422 before SQLite is touched rather than a stored or
# truncated row.
INGEST_TEXT_MAX_CHARS = 20_000
INGEST_TAG_MAX_CHARS = 40
INGEST_TAG_LIMIT = 20


class IngestCreate(BaseModel):
    """One text document to store as a record.

    Scope, deliberately: text only. No file upload, no PDF/DOCX extraction, no
    new dependency, no environment variable or flag. The document becomes a
    `Record`, so it flows through the same table, visibility filter and clock as
    the rest of the API.

    `restricted` must never appear here: a client that could set it would write a
    row it cannot then read. The field is absent and `extra="forbid"` turns an
    attempt to send it into a 422.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=INGEST_TEXT_MAX_CHARS)
    department: str = Field(min_length=1, max_length=80)
    # Absent means "stamp it with the write clock" (see app/ingest.py); the
    # injection point is the clock argument, never a call to datetime.now().
    timestamp: Optional[datetime] = None
    source_group: Optional[str] = Field(default=None, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=INGEST_TAG_LIMIT)

    # `mode="before"` so the length bounds measure the stripped value: otherwise
    # "   x" satisfied min_length and was then stored as "x".
    @field_validator("text", "department", mode="before")
    @classmethod
    def non_blank(cls, value: object) -> object:
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("Ingested text and department must not be blank")
            return value.strip()
        return value

    @field_validator("source_group", mode="before")
    @classmethod
    def blank_source_group_is_absent(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def bounded_tags(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        cleaned = []
        for tag in value:
            if not isinstance(tag, str):
                return value
            stripped = tag.strip()
            if not stripped:
                raise ValueError("Tags must not be blank")
            if len(stripped) > INGEST_TAG_MAX_CHARS:
                raise ValueError(f"Tags must be at most {INGEST_TAG_MAX_CHARS} characters")
            cleaned.append(stripped)
        return cleaned


class Record(BaseModel):
    id: str
    timestamp: datetime
    department: str
    text: str
    tags: list[str]
    restricted: bool = False
    source_group: Optional[str] = None


class Investigation(BaseModel):
    id: str
    question: str
    preset_id: Optional[InvestigationPreset] = None
    created_at: datetime
    version: int
    claims: list[Claim]


class HistoryEntry(BaseModel):
    version: int
    created_at: datetime
    event: str
    claim_id: Optional[str] = None
    reason: Optional[str] = None
    before: Optional[dict] = None
    after: Optional[dict] = None
    evidence_changes: list[str] = []
    recomputed_claim_ids: list[str] = []

