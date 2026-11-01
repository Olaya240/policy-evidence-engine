"""API schemas and typed domain models."""
from datetime import datetime
from enum import Enum
from typing import Optional

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
    source_record_id: str
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
    # Backward compatibility field: preserved temporarily for current clients.
    confidence: float = Field(ge=0, le=1)
    evidence_strength: Optional[float] = Field(default=None, ge=0, le=1)
    decision_confidence: Optional[float] = Field(default=None, ge=0, le=1)
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

    @field_validator("question")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank")
        return value.strip()


class ChallengeCreate(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)
    source_record_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=3, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def non_blank_reason(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Challenge reason must not be blank")
        return value.strip()


class Record(BaseModel):
    id: str
    timestamp: datetime
    department: str
    text: str
    tags: list[str]
    restricted: bool = False
    source_group: Optional[str] = None


class DocumentIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)
    department: str = Field(default="Front Office", min_length=1, max_length=100)


class DocumentIngestResponse(BaseModel):
    document_id: str
    sha256: str
    filename: str
    department: str
    ingested_at: datetime
    byte_size: int
    chunk_count: int
    records: list[Record]
    duplicate: bool = False


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

