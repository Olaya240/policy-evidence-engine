"""API schemas and typed domain models."""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


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
    confidence: float = Field(ge=0, le=1)
    uncertainty: str
    summary: str
    evidence: list[Evidence]
    conflicts: list[str]
    missing_evidence: list[str]
    dependencies: list[str]
    version: int


class InvestigationCreate(BaseModel):
    question: str = Field(min_length=8, max_length=500)

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


class Investigation(BaseModel):
    id: str
    question: str
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

