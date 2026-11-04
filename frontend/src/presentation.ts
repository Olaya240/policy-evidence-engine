import type { ChallengeResponse, Claim, Evidence, Investigation } from "./contracts";

export const CONFIDENCE_DISCLOSURE = "This is the magnitude of a signed evidence margin. It is not a probability. It is not a calibrated confidence score.";

export function recordAvailability(loading: boolean, count: number): "loading" | "empty" | "ready" {
  if (loading) return "loading";
  return count === 0 ? "empty" : "ready";
}

/** A display-only projection of backend fields; it performs no decision logic. */
export function claimPresentation(claim: Pick<Claim, "status" | "confidence"> & {
  evidence_score?: number | null;
  evidence_direction?: Claim["evidence_direction"];
  explanation_trace?: unknown;
}) {
  return {
    status: claim.status,
    confidenceMagnitude: claim.confidence,
    evidenceScore: claim.evidence_score,
    evidenceDirection: claim.evidence_direction,
    explanationTrace: claim.explanation_trace,
  };
}

/** Keep the backend disposition distinct from its proposed and accepted stance. */
export function evidencePresentation(evidence: Pick<Evidence, "stance" | "source_group"> & {
  review_state?: Evidence["review_state"];
  proposed_stance?: Evidence["proposed_stance"] | string | null;
  semantic_relation?: string | null;
}) {
  return {
    disposition: evidence.review_state,
    stance: evidence.stance,
    proposedStance: evidence.proposed_stance,
    semanticRelation: evidence.semantic_relation,
    sourceGroup: evidence.source_group,
  };
}

export function explanationTraceText(trace: Record<string, unknown> | null | undefined): string | null | undefined {
  return trace === null ? null : JSON.stringify(trace, null, 2);
}

/** Apply the backend's returned revision and recomputed claim snapshots verbatim. */
export function mergeChallengeResponse(investigation: Investigation, response: ChallengeResponse): Investigation {
  return {
    ...investigation,
    version: response.version,
    claims: investigation.claims.map((claim) => response.after[claim.id] ?? claim),
  };
}
