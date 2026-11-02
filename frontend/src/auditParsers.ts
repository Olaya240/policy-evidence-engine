/**
 * auditParsers.ts
 *
 * Types and parsing utilities aligned with the Policy Evidence Engine contract.
 * - Finding A: Advisory Coverage parsing priority (coverage_state first).
 * - Confidence is rendered as the backend's evidence-margin magnitude, not a probability.
 * - Finding C: Separation of claim status, evidence dispute, and trace disposition codes.
 * - Finding F: Explanation trace structure (confidence_kind, confidence_fields, semantic_guard).
 */

export type Status = "SUPPORTED" | "PARTIAL" | "CONTRADICTED" | "INSUFFICIENT";
export type Stance = "SUPPORTS" | "CONTRADICTS" | "NEUTRAL";
export type EvidenceReviewState = "ACCEPTED" | "UNVERIFIED";

export type EvidenceDispositionItem = {
  source_record_id?: string;
  record_id?: string;
  codes?: string[];
  disposition?: string;
  reason?: string;
};

export type AdvisoryCoverageCategory = {
  category_id?: string;
  category?: string;
  id?: string;
  name?: string;
  label?: string;
  coverage_state?: "COVERED" | "NOT_COVERED" | string;
  status?: "COVERED" | "NOT_COVERED" | string;
  state?: "COVERED" | "NOT_COVERED" | string;
  covered_by_fresh_accepted?: boolean;
  covered?: boolean;
  fresh_accepted_count?: number;
  total_evidence_count?: number;
  details?: string;
  description?: string;
  matching_evidence_ids?: string[];
  fresh_accepted_support_ids?: string[];
  fresh_accepted_contradiction_ids?: string[];
  neutral_evidence_ids?: string[];
  unclassified_evidence_ids?: string[];
  independent_source_groups?: string[];
  source_groups?: string[];
  source_record_ids?: string[];
};

export type ExplanationTraceRule = {
  rule_id: string;
  description?: string;
  applied?: boolean;
  weight?: number;
};

export type SemanticGuardDecision = {
  source_record_id?: string;
  review_state?: string;
  proposed_stance?: string;
  semantic_relation?: string | null;
  guard_enabled?: boolean;
  cue_ids?: string[];
  reason_code?: string;
  decision_source?: string;
};

export type ExplanationTrace = {
  trace_schema_version?: string;
  reasoning_rule_version?: string;
  generated_at?: string;
  status_rule_id?: string;
  confidence_rule_id?: string;
  confidence_kind?: string;
  evidence_score?: number;
  evidence_direction?: "FOR" | "AGAINST" | "NONE";
  confidence_fields?: Record<string, unknown> | string[];
  evidence_dispositions?:
    | Record<string, { codes?: string[]; disposition?: string; reason?: string } | string[] | string>
    | EvidenceDispositionItem[];
  semantic_guard?: {
    rule_set_version?: string;
    enabled?: boolean;
    decisions?: SemanticGuardDecision[];
  };
  source_group_analysis?: {
    independence_rule?: string;
    independent_support_group_count?: number;
    independent_support_groups?: string[];
    dependent_support_record_ids?: string[];
  };
  staleness_policy?: {
    policy_id?: string;
    threshold_days?: number;
    comparison?: string;
    timezone?: string;
  };
  advisory_coverage?: {
    advisory_only?: boolean;
    formal_evidence_sufficiency?: boolean;
    hypothesis_id?: string;
    categories?:
      | AdvisoryCoverageCategory[]
      | Record<string, AdvisoryCoverageCategory | "COVERED" | "NOT_COVERED" | string>;
    note?: string;
    disclaimer?: string;
  };
  // Optional / backward-compatibility fields
  rules_triggered?: ExplanationTraceRule[];
  notes?: string[];
};

export type Evidence = {
  source_record_id: string;
  timestamp: string;
  quote: string;
  stance: Stance;
  review_state?: EvidenceReviewState;
  proposed_stance?: Stance | null;
  semantic_relation?: string | null;
  source_group: string | null;
  rationale: string;
  stale: boolean;
  disputed: boolean;
  department: string;
};

export type Claim = {
  id: string;
  hypothesis_id: string;
  status: Status;
  // Dual confidence metrics (Finding B)
  confidence: number;
  evidence_score?: number | null;
  evidence_direction?: "FOR" | "AGAINST" | "NONE" | null;
  uncertainty: string;
  summary: string;
  evidence: Evidence[];
  conflicts: string[];
  missing_evidence: string[];
  dependencies: string[];
  version: number;
  explanation_trace: ExplanationTrace | null;
};

export type Investigation = {
  id: string;
  question: string;
  created_at: string;
  version: number;
  preset_id: string | null;
  claims: Claim[];
};

export type History = {
  version: number;
  created_at: string;
  event: string;
  claim_id: string | null;
  reason: string | null;
  before: Record<string, Claim> | null;
  after: Record<string, Claim> | null;
  evidence_changes: string[];
  recomputed_claim_ids: string[];
};

export type ParsedCoverageCategory = {
  name: string;
  state: "COVERED" | "NOT_COVERED" | string;
  details?: string;
  matchingIds: string[];
  freshSupportIds: string[];
  freshContradictionIds: string[];
  neutralEvidenceIds: string[];
  unclassifiedEvidenceIds: string[];
  independentGroups: string[];
  freshAcceptedCount?: number;
  totalEvidenceCount?: number;
};

export type ParsedEvidenceDisposition = {
  recordKey: string;
  codes: string[];
  note?: string;
};

/**
 * Finding A: Parse advisory coverage categories checking coverage_state first.
 * Correctly preserves COVERED and NOT_COVERED states and category metadata.
 */
export function parseAdvisoryCoverageCategories(
  advisory: ExplanationTrace["advisory_coverage"]
): ParsedCoverageCategory[] {
  if (!advisory || !advisory.categories) return [];
  const raw = advisory.categories;
  const toStrArray = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

  if (Array.isArray(raw)) {
    return raw.map((item, idx) => {
      const name = item.category_id || item.category || item.id || item.name || item.label || `CATEGORY_${idx + 1}`;
      // Priority: coverage_state first, then status, state, covered_by_fresh_accepted, covered
      const state =
        item.coverage_state ||
        item.status ||
        item.state ||
        (typeof item.covered_by_fresh_accepted === "boolean"
          ? (item.covered_by_fresh_accepted ? "COVERED" : "NOT_COVERED")
          : typeof item.covered === "boolean"
          ? (item.covered ? "COVERED" : "NOT_COVERED")
          : "NOT_COVERED");

      return {
        name: String(name),
        state: String(state).toUpperCase(),
        details: item.details || item.description,
        matchingIds: toStrArray(item.matching_evidence_ids ?? item.source_record_ids),
        freshSupportIds: toStrArray(item.fresh_accepted_support_ids),
        freshContradictionIds: toStrArray(item.fresh_accepted_contradiction_ids),
        neutralEvidenceIds: toStrArray(item.neutral_evidence_ids),
        unclassifiedEvidenceIds: toStrArray(item.unclassified_evidence_ids),
        independentGroups: toStrArray(item.independent_source_groups ?? item.source_groups),
        freshAcceptedCount: typeof item.fresh_accepted_count === "number" ? item.fresh_accepted_count : undefined,
        totalEvidenceCount: typeof item.total_evidence_count === "number" ? item.total_evidence_count : undefined,
      };
    });
  }

  return Object.entries(raw).map(([key, val]) => {
    if (typeof val === "string") {
      return {
        name: key,
        state: val.toUpperCase(),
        matchingIds: [],
        freshSupportIds: [],
        freshContradictionIds: [],
        neutralEvidenceIds: [],
        unclassifiedEvidenceIds: [],
        independentGroups: [],
      };
    }
    if (val && typeof val === "object") {
      const state =
        val.coverage_state ||
        val.status ||
        val.state ||
        (typeof val.covered_by_fresh_accepted === "boolean"
          ? (val.covered_by_fresh_accepted ? "COVERED" : "NOT_COVERED")
          : typeof val.covered === "boolean"
          ? (val.covered ? "COVERED" : "NOT_COVERED")
          : "NOT_COVERED");
      return {
        name: val.category_id || val.category || val.id || val.name || val.label || key,
        state: String(state).toUpperCase(),
        details: val.details || val.description,
        matchingIds: toStrArray(val.matching_evidence_ids ?? val.source_record_ids),
        freshSupportIds: toStrArray(val.fresh_accepted_support_ids),
        freshContradictionIds: toStrArray(val.fresh_accepted_contradiction_ids),
        neutralEvidenceIds: toStrArray(val.neutral_evidence_ids),
        unclassifiedEvidenceIds: toStrArray(val.unclassified_evidence_ids),
        independentGroups: toStrArray(val.independent_source_groups ?? val.source_groups),
        freshAcceptedCount: typeof val.fresh_accepted_count === "number" ? val.fresh_accepted_count : undefined,
        totalEvidenceCount: typeof val.total_evidence_count === "number" ? val.total_evidence_count : undefined,
      };
    }
    return {
      name: key,
      state: "NOT_COVERED",
      matchingIds: [],
      freshSupportIds: [],
      freshContradictionIds: [],
      neutralEvidenceIds: [],
      unclassifiedEvidenceIds: [],
      independentGroups: [],
    };
  });
}

/**
 * Read the backend's evidence-margin magnitude (legacy field name: confidence).
 */
export function getEvidenceMarginMagnitude(
  claim: { confidence?: number | null } | null | undefined
): number | null {
  if (!claim) return null;
  if (typeof claim.confidence === "number") return claim.confidence;
  return null;
}

export function formatEvidenceMarginMagnitude(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "Unavailable";
}

export type UnreadableRows = { count: number; ids: string[] };

export function parseUnreadableRows(headers: Pick<Headers, "get">): UnreadableRows {
  const rawCount = headers.get("X-Unreadable-Rows");
  const parsedCount = rawCount === null ? 0 : Number(rawCount);
  const count = Number.isSafeInteger(parsedCount) && parsedCount > 0 ? parsedCount : 0;
  const ids = (headers.get("X-Unreadable-Row-Ids") ?? "")
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean);
  return { count: Math.max(count, ids.length), ids };
}

export function unreadableRowsWarning(rows: UnreadableRows, available: number): string | null {
  if (rows.count <= 0) return null;
  const ids = rows.ids.length ? ` Row IDs: ${rows.ids.join(", ")}` : "";
  return `Corpus is partially available: ${rows.count} unreadable row(s). The backend omitted unreadable rows; ${available} returned record(s) remain visible.${ids}`;
}

export const POLICY_DEMO_PROPOSAL_LABEL = "DETERMINISTIC POLICY DEMO PROPOSAL · NOT AI INFERENCE";
export const STATIC_VISUAL_NOTICE = "Illustrative static frontend visual. The mask shapes, coordinates, and IoU value are fixture artwork; they are not generated by SAM, returned by the API, or evidence of policy meaning.";

export type DispositionTone = "green" | "red" | "muted" | "orange" | "navy" | "gold";

export function dispositionTone(code: string): DispositionTone {
  switch (code) {
    case "COUNTED_SUPPORT": return "green";
    case "COUNTED_CONTRADICTION": return "red";
    case "NEUTRAL_NOT_DIRECTIONAL": return "muted";
    case "STALE_HISTORICAL_CONTEXT":
    case "STALE_NON_DIRECTIONAL_CONTEXT": return "orange";
    case "DEPENDENT_SOURCE_GROUP": return "navy";
    case "UNVERIFIED_EXCLUDED":
    case "DISPUTED_REVIEW_REQUIRED":
    case "UNCLASSIFIED_REVIEW_REQUIRED": return "gold";
    default: return "muted";
  }
}

export function formatProposedStance(proposed: string | null | undefined): string {
  return proposed ?? "NOT PROPOSED BY BACKEND";
}

export function extractDemoError(body: unknown, status: number): string {
  const prefix = `HTTP ${status}`;
  if (typeof body === "string" && body.trim()) return `${prefix}: ${body}`;
  if (body && typeof body === "object") {
    const obj = body as Record<string, unknown>;
    const error = typeof obj.error === "string" ? obj.error : "";
    const detail = obj.detail;
    let message = "";
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) {
      message = detail.map((item) => {
        if (!item || typeof item !== "object") return String(item);
        const issue = item as Record<string, unknown>;
        return [issue.loc && Array.isArray(issue.loc) ? issue.loc.join(".") : "", issue.msg]
          .filter((part) => typeof part === "string" && part)
          .join(": ");
      }).filter(Boolean).join("; ");
    } else if (detail && typeof detail === "object") {
      const d = detail as Record<string, unknown>;
      message = typeof d.message === "string" ? d.message : typeof d.msg === "string" ? d.msg : "";
    }
    const result = [error, message].filter(Boolean).join(": ");
    if (result) return `${prefix}: ${result}`;
  }
  return `Policy Demo API request failed (${prefix})`;
}

/**
 * Priority 1: Parse evidence dispositions strictly from backend codes array.
 */
export function parseEvidenceDispositions(
  dispositions: ExplanationTrace["evidence_dispositions"]
): ParsedEvidenceDisposition[] {
  if (!dispositions) return [];

  if (Array.isArray(dispositions)) {
    return dispositions.map((item, idx) => {
      const recordKey = item.source_record_id || item.record_id || `EV-${idx + 1}`;
      const codes = Array.isArray(item.codes)
        ? item.codes.map(String)
        : item.disposition
        ? [String(item.disposition)]
        : [];
      return { recordKey, codes, note: item.reason };
    });
  }

  return Object.entries(dispositions).map(([key, val]) => {
    if (Array.isArray(val)) {
      return { recordKey: key, codes: val.map(String) };
    }
    if (val && typeof val === "object") {
      const obj = val as { codes?: unknown; disposition?: unknown; reason?: unknown };
      const codes = Array.isArray(obj.codes)
        ? obj.codes.map(String)
        : typeof obj.disposition === "string"
        ? [obj.disposition]
        : [];
      return {
        recordKey: key,
        codes,
        note: typeof obj.reason === "string" ? obj.reason : undefined,
      };
    }
    return { recordKey: key, codes: [String(val)] };
  });
}
