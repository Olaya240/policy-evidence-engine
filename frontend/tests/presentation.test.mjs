import test from "node:test";
import assert from "node:assert/strict";
import { claimPresentation, CONFIDENCE_DISCLOSURE, evidencePresentation, explanationTraceText, mergeChallengeResponse, recordAvailability } from "../.test-build/presentation.js";

const claim = {
  id: "TIME_PRESSURE",
  hypothesis_id: "TIME_PRESSURE",
  status: "PARTIAL",
  confidence: 0.5,
  evidence_score: -0.5,
  evidence_direction: "AGAINST",
  uncertainty: "Needs review",
  summary: "Partial evidence",
  evidence: [],
  conflicts: [],
  missing_evidence: [],
  dependencies: [],
  version: 2,
  explanation_trace: { status_rule_id: "STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED", confidence_kind: "SIGNED_EVIDENCE_MARGIN_NOT_CALIBRATED_PROBABILITY" },
};

test("claim presentation passes backend status, magnitude, signed score, and direction through unchanged", () => {
  assert.deepEqual(claimPresentation(claim), {
    status: "PARTIAL",
    confidenceMagnitude: 0.5,
    evidenceScore: -0.5,
    evidenceDirection: "AGAINST",
    explanationTrace: claim.explanation_trace,
  });
  for (const status of ["SUPPORTED", "PARTIAL", "CONTRADICTED", "INSUFFICIENT"]) {
    assert.equal(claimPresentation({ ...claim, status }).status, status);
  }
});

test("confidence disclosure rejects probability and calibration interpretations", () => {
  assert.match(CONFIDENCE_DISCLOSURE, /signed evidence margin/);
  assert.match(CONFIDENCE_DISCLOSURE, /not a probability/);
  assert.match(CONFIDENCE_DISCLOSURE, /not a calibrated confidence score/);
});

test("record availability distinguishes loading, empty, and ready states", () => {
  assert.equal(recordAvailability(true, 0), "loading");
  assert.equal(recordAvailability(false, 0), "empty");
  assert.equal(recordAvailability(false, 4), "ready");
});

test("evidence disposition stays separate from stance and semantic relation", () => {
  const evidence = {
    source_record_id: "OPS-12",
    timestamp: "2026-11-02T00:00:00Z",
    quote: "The desk was understaffed.",
    stance: "SUPPORTS",
    review_state: "UNVERIFIED",
    proposed_stance: "CONTRADICTS",
    semantic_relation: "SUPPORTS",
    rationale: "Retained for review",
    stale: false,
    department: "FRONT_DESK",
    source_group: "NIGHT_SHIFT",
    disputed: false,
  };
  assert.deepEqual(evidencePresentation(evidence), {
    disposition: "UNVERIFIED",
    stance: "SUPPORTS",
    proposedStance: "CONTRADICTS",
    semanticRelation: "SUPPORTS",
    sourceGroup: "NIGHT_SHIFT",
  });
  assert.equal(evidencePresentation({ ...evidence, semantic_relation: "BACKEND_UNCLASSIFIED" }).semanticRelation,
    "BACKEND_UNCLASSIFIED");
});

test("trace display preserves object content and handles null or missing legacy traces", () => {
  assert.equal(explanationTraceText(claim.explanation_trace), JSON.stringify(claim.explanation_trace, null, 2));
  assert.equal(explanationTraceText(null), null);
  assert.equal(explanationTraceText(undefined), undefined);
});

test("challenge snapshots update the investigation revision and claim from backend values", () => {
  const investigation = { id: "INV-1", question: "Did time pressure contribute?", preset_id: "handover_omissions", created_at: "2026-11-02T00:00:00Z", version: 2, claims: [claim] };
  const revisedClaim = { ...claim, status: "PARTIAL", version: 3 };
  const updated = mergeChallengeResponse(investigation, { version: 3, reason: "Review request", before: { TIME_PRESSURE: claim }, after: { TIME_PRESSURE: revisedClaim }, recomputed_claim_ids: ["TIME_PRESSURE"] });
  assert.equal(updated.version, 3);
  assert.equal(updated.claims[0].status, "PARTIAL");
  assert.equal(updated.claims[0].version, 3);
  assert.equal(investigation.version, 2);
});
