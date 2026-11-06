export type ProvenanceDetail = {
  side: "OLDER" | "NEWER";
  passage_id: string;
  passage_ordinal: number | null;
  start_cp: number;
  end_cp: number;
  quote: string;
  source_sha256: string;
  verified_locally: boolean;
};

export type ScenarioResult = {
  comparison_id: string;
  request_id: string;
  proposed_relation: string;
  candidate_id: string;
  reasoning: string;
  status: string;
  semantic_support: string;
  human_review_required: boolean;
  core_classification: string;
  core_proposed_classification: string;
  uncertainty_reasons: string[];
  official_policy_mutated: boolean;
  impact_status: string;
  provenance_details: ProvenanceDetail[];
  provenance_limitation_notice: string;
  scenario_id: string;
  proposal_id: string;
  provider_attribution: { provider: "synthetic" | "baseten" | "meta"; model: string | null; request_id?: string; usage?: Record<string, number> };
};

export type SessionCreatedResponse = {
  session_id: string;
  scenario_id: string;
  proposal_id: string;
  created_at_iso?: string;
  created_at?: string;
};

export type PolicyDemoProviderSource = "synthetic" | "baseten" | "meta" | "unknown";

/** Attribute results only from explicit response metadata; never infer from configuration. */
export function policyDemoProviderSource(value: unknown): PolicyDemoProviderSource {
  if (!isObject(value)) return "unknown";
  return value.provider === "synthetic" || value.provider === "baseten" || value.provider === "meta"
    ? value.provider
    : "unknown";
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasStringFields(value: Record<string, unknown>, fields: string[]): boolean {
  return fields.every((field) => isNonEmptyString(value[field]));
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isBackendIsoTimestamp(value: unknown): value is string {
  if (!isNonEmptyString(value)) return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{6}))?\+00:00$/.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, 0);
  return month >= 1 && month <= 12 && day >= 1 &&
    date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day &&
    hour <= 23 && minute <= 59 && second <= 59;
}

function isProvenanceDetail(value: unknown): value is ProvenanceDetail {
  if (!isObject(value)) return false;
  return (value.side === "OLDER" || value.side === "NEWER") &&
    hasStringFields(value, ["passage_id", "quote", "source_sha256"]) &&
    /^[0-9a-f]{64}$/.test(value.source_sha256 as string) &&
    (value.passage_ordinal === null || (typeof value.passage_ordinal === "number" && Number.isInteger(value.passage_ordinal))) &&
    typeof value.start_cp === "number" && Number.isInteger(value.start_cp) && value.start_cp >= 0 &&
    typeof value.end_cp === "number" && Number.isInteger(value.end_cp) && value.end_cp > value.start_cp &&
    value.end_cp - value.start_cp === Array.from(value.quote as string).length &&
    typeof value.verified_locally === "boolean";
}

/** Validate the backend scenario shape before any session can be allocated. */
export function validateScenarioResult(value: unknown, expectedScenarioId: string): ScenarioResult {
  if (!isObject(value) || !hasStringFields(value, [
    "comparison_id", "request_id", "proposed_relation", "candidate_id", "reasoning", "status",
    "semantic_support", "core_classification", "core_proposed_classification", "impact_status",
    "provenance_limitation_notice", "scenario_id", "proposal_id",
  ]) ||
    !isNonEmptyString(expectedScenarioId) || value.scenario_id !== expectedScenarioId ||
    !/^[a-f0-9]{32}$/.test(value.proposal_id as string) ||
    typeof value.human_review_required !== "boolean" ||
    typeof value.official_policy_mutated !== "boolean" ||
    !Array.isArray(value.uncertainty_reasons) || !value.uncertainty_reasons.every(isNonEmptyString) ||
    !Array.isArray(value.provenance_details) || !value.provenance_details.every(isProvenanceDetail)) {
    throw new Error("Policy Demo returned an invalid scenario response.");
  }
  if (!isObject(value.provider_attribution) ||
    (value.provider_attribution.provider !== "synthetic" &&
      value.provider_attribution.provider !== "baseten" &&
      value.provider_attribution.provider !== "meta") ||
    !(value.provider_attribution.model === null || isNonEmptyString(value.provider_attribution.model))) {
    throw new Error("Policy Demo returned invalid provider attribution.");
  }
  return value as unknown as ScenarioResult;
}

export function validateSessionCreatedResponse(
  value: unknown, expectedScenarioId: string, expectedProposalId: string,
): SessionCreatedResponse {
  if (!isObject(value) || !hasStringFields(value, ["session_id", "scenario_id", "proposal_id"]) ||
    !/^[a-f0-9]{32}$/.test(value.session_id as string) ||
    !isNonEmptyString(expectedScenarioId) || value.scenario_id !== expectedScenarioId ||
    !/^[a-f0-9]{32}$/.test(expectedProposalId) || value.proposal_id !== expectedProposalId ||
    (value.created_at_iso !== undefined && !isBackendIsoTimestamp(value.created_at_iso)) ||
    (value.created_at !== undefined && !isBackendIsoTimestamp(value.created_at))) {
    throw new Error("Policy Demo returned an invalid session response.");
  }
  return value as unknown as SessionCreatedResponse;
}
