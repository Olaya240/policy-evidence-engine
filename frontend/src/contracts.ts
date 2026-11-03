export type ClaimStatus = "SUPPORTED" | "PARTIAL" | "CONTRADICTED" | "INSUFFICIENT";
export type Stance = "SUPPORTS" | "CONTRADICTS" | "NEUTRAL";
export type EvidenceReviewState = "ACCEPTED" | "UNVERIFIED";
export type EvidenceDirection = "FOR" | "AGAINST" | "NONE";
export type InvestigationPreset = "handover_omissions" | "checklist_access" | "desk_coverage" | "property_system";

export type Evidence = {
  source_record_id: string;
  timestamp: string;
  quote: string;
  stance: Stance;
  review_state: EvidenceReviewState;
  proposed_stance: Stance | null;
  semantic_relation: Stance | null;
  rationale: string;
  stale: boolean;
  department: string;
  source_group: string | null;
  disputed: boolean;
};

export type Claim = {
  id: string;
  hypothesis_id: string;
  status: ClaimStatus;
  confidence: number;
  evidence_score: number | null;
  evidence_direction: EvidenceDirection | null;
  uncertainty: string;
  summary: string;
  evidence: Evidence[];
  conflicts: string[];
  missing_evidence: string[];
  dependencies: string[];
  version: number;
  explanation_trace: Record<string, unknown> | null;
};

export type Investigation = {
  id: string;
  question: string;
  preset_id: InvestigationPreset | null;
  created_at: string;
  version: number;
  claims: Claim[];
};

export type ClaimSnapshot = Partial<Claim>;

export type HistoryEntry = {
  version: number;
  created_at: string;
  event: string;
  claim_id: string | null;
  reason: string | null;
  before: Record<string, ClaimSnapshot> | null;
  after: Record<string, ClaimSnapshot> | null;
  evidence_changes: string[];
  recomputed_claim_ids: string[];
};

export type ChallengeResponse = {
  version: number;
  reason: string;
  before: Record<string, Claim>;
  after: Record<string, Claim>;
  recomputed_claim_ids: string[];
};

export type RecordItem = {
  id: string;
  timestamp: string;
  department: string;
  text: string;
  tags: string[];
  restricted: boolean;
  source_group: string | null;
};
