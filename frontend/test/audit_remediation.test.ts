import test from "node:test";
import assert from "node:assert";
import {
  parseAdvisoryCoverageCategories,
  getEvidenceMarginMagnitude,
  parseEvidenceDispositions,
  parseUnreadableRows,
  dispositionTone,
  formatEvidenceMarginMagnitude,
  formatProposedStance,
  extractDemoError,
  unreadableRowsWarning,
  POLICY_DEMO_PROPOSAL_LABEL,
  STATIC_VISUAL_NOTICE,
  type ExplanationTrace,
  type Claim,
  type History,
  type Investigation,
} from "../src/auditParsers.ts";

test("Finding A: parseAdvisoryCoverageCategories reads coverage_state first (COVERED)", () => {
  const backendAdvisory: ExplanationTrace["advisory_coverage"] = {
    advisory_only: true,
    formal_evidence_sufficiency: false,
    categories: [
      {
        category_id: "checklist_access_context",
        coverage_state: "COVERED",
        covered_by_fresh_accepted: true,
        matching_evidence_ids: ["SOURCE-A"],
        fresh_accepted_support_ids: ["SOURCE-A"],
        fresh_accepted_contradiction_ids: [],
        neutral_evidence_ids: [],
        unclassified_evidence_ids: [],
        independent_source_groups: ["ORIGINAL"],
      },
      {
        category_id: "independent_checklist_support",
        coverage_state: "NOT_COVERED",
        covered_by_fresh_accepted: false,
        matching_evidence_ids: [],
        fresh_accepted_support_ids: [],
        fresh_accepted_contradiction_ids: [],
        neutral_evidence_ids: [],
        unclassified_evidence_ids: [],
        independent_source_groups: [],
      },
    ],
  };

  const parsed = parseAdvisoryCoverageCategories(backendAdvisory);
  assert.strictEqual(parsed.length, 2);
  assert.strictEqual(parsed[0].name, "checklist_access_context");
  assert.strictEqual(parsed[0].state, "COVERED");
  assert.deepStrictEqual(parsed[0].matchingIds, ["SOURCE-A"]);
  assert.deepStrictEqual(parsed[0].freshSupportIds, ["SOURCE-A"]);
  assert.deepStrictEqual(parsed[0].independentGroups, ["ORIGINAL"]);

  assert.strictEqual(parsed[1].name, "independent_checklist_support");
  assert.strictEqual(parsed[1].state, "NOT_COVERED");
  assert.deepStrictEqual(parsed[1].matchingIds, []);
});

test("Finding A: falls back to covered_by_fresh_accepted or status when coverage_state is absent", () => {
  const fallbackAdvisory: ExplanationTrace["advisory_coverage"] = {
    categories: [
      {
        category_id: "cat_1",
        covered_by_fresh_accepted: true,
      },
      {
        category: "cat_2",
        status: "COVERED",
      },
      {
        id: "cat_3",
        covered: false,
      },
    ],
  };

  const parsed = parseAdvisoryCoverageCategories(fallbackAdvisory);
  assert.strictEqual(parsed[0].state, "COVERED");
  assert.strictEqual(parsed[1].state, "COVERED");
  assert.strictEqual(parsed[2].state, "NOT_COVERED");
});

test("Finding A: handles dictionary/record format safely", () => {
  const recordAdvisory: ExplanationTrace["advisory_coverage"] = {
    categories: {
      itemA: {
        coverage_state: "COVERED",
        matching_evidence_ids: ["REC-1"],
      },
      itemB: "NOT_COVERED",
    },
  };

  const parsed = parseAdvisoryCoverageCategories(recordAdvisory);
  assert.strictEqual(parsed.length, 2);
  assert.strictEqual(parsed[0].name, "itemA");
  assert.strictEqual(parsed[0].state, "COVERED");
  assert.strictEqual(parsed[1].name, "itemB");
  assert.strictEqual(parsed[1].state, "NOT_COVERED");
});

test("Confidence: reads the backend evidence-margin magnitude from confidence", () => {
  const claim: Partial<Claim> = {
    confidence: 0.65,
  };
  assert.strictEqual(getEvidenceMarginMagnitude(claim), 0.65);
});

test("Confidence: reports unavailable when the backend omits confidence", () => {
  assert.strictEqual(getEvidenceMarginMagnitude({}), null);
});

test("Confidence: evidence direction stays separate from magnitude", () => {
  const claim: Partial<Claim> = {
    confidence: 0.55,
    evidence_score: -0.55,
    evidence_direction: "AGAINST",
  };
  assert.strictEqual(getEvidenceMarginMagnitude(claim), 0.55);
  assert.strictEqual(claim.evidence_direction, "AGAINST");
});

test("Finding C: evidence dispositions parsed without confusing claim status", () => {
  const dispositions: ExplanationTrace["evidence_dispositions"] = [
    { source_record_id: "REC-A", codes: ["COUNTED_SUPPORT", "DEPENDENT_SOURCE_GROUP"] },
    { source_record_id: "REC-B", codes: ["DISPUTED_REVIEW_REQUIRED"] },
    { source_record_id: "REC-C", codes: ["UNVERIFIED_EXCLUDED"] },
  ];

  const parsed = parseEvidenceDispositions(dispositions);
  assert.strictEqual(parsed.length, 3);
  assert.strictEqual(parsed[0].recordKey, "REC-A");
  assert.deepStrictEqual(parsed[0].codes, ["COUNTED_SUPPORT", "DEPENDENT_SOURCE_GROUP"]);
  assert.strictEqual(parsed[1].recordKey, "REC-B");
  assert.deepStrictEqual(parsed[1].codes, ["DISPUTED_REVIEW_REQUIRED"]);
});

test("Unreadable rows: parses headers while preserving identifiers", () => {
  const result = parseUnreadableRows(new Headers({
    "X-Unreadable-Rows": "2",
    "X-Unreadable-Row-Ids": "row-a, row-b",
  }));
  assert.deepStrictEqual(result, { count: 2, ids: ["row-a", "row-b"] });
  assert.deepStrictEqual(parseUnreadableRows(new Headers()), { count: 0, ids: [] });
  assert.match(unreadableRowsWarning(result, 11) ?? "", /partially available: 2 unreadable row\(s\)/);
  assert.match(unreadableRowsWarning(result, 11) ?? "", /row-a, row-b/);
});

test("Evidence dispositions receive distinct tones for backend codes", () => {
  const tones = [
    dispositionTone("COUNTED_SUPPORT"),
    dispositionTone("COUNTED_CONTRADICTION"),
    dispositionTone("NEUTRAL_NOT_DIRECTIONAL"),
    dispositionTone("STALE_HISTORICAL_CONTEXT"),
    dispositionTone("STALE_NON_DIRECTIONAL_CONTEXT"),
    dispositionTone("UNVERIFIED_EXCLUDED"),
    dispositionTone("DISPUTED_REVIEW_REQUIRED"),
    dispositionTone("DEPENDENT_SOURCE_GROUP"),
    dispositionTone("UNCLASSIFIED_REVIEW_REQUIRED"),
  ];
  assert.deepStrictEqual(tones, ["green", "red", "muted", "orange", "orange", "gold", "gold", "navy", "gold"]);
  assert.strictEqual(dispositionTone("FUTURE_UNKNOWN_CODE"), "muted");
});

test("Unverified evidence does not infer a proposed stance from actual stance", () => {
  assert.strictEqual(formatProposedStance(undefined), "NOT PROPOSED BY BACKEND");
  assert.strictEqual(formatProposedStance(null), "NOT PROPOSED BY BACKEND");
  assert.strictEqual(formatProposedStance("SUPPORTS"), "SUPPORTS");
});

test("Confidence margin formatting is a magnitude, never a percentage", () => {
  assert.strictEqual(formatEvidenceMarginMagnitude(0.654321), "0.654321");
  assert.strictEqual(formatEvidenceMarginMagnitude(null), "Unavailable");
});

test("Backend nullable trace and history fields accept null", () => {
  const claim: Partial<Claim> = { explanation_trace: null };
  const history: Partial<History> = { claim_id: null, reason: null, before: null, after: null };
  const investigation: Partial<Investigation> = { preset_id: null };
  assert.strictEqual(claim.explanation_trace, null);
  assert.strictEqual(history.before, null);
  assert.strictEqual(investigation.preset_id, null);
});

test("Nested API errors extract detail and retain HTTP status", () => {
  assert.strictEqual(extractDemoError({ error: "invalid_request", detail: { message: "bad scenario" } }, 422),
    "HTTP 422: invalid_request: bad scenario");
  assert.strictEqual(extractDemoError({ detail: [{ loc: ["body", "id"], msg: "field required" }] }, 422),
    "HTTP 422: body.id: field required");
});

test("Policy demo clearly labels deterministic proposals and static mask visuals", () => {
  assert.match(POLICY_DEMO_PROPOSAL_LABEL, /DETERMINISTIC.*NOT AI INFERENCE/);
  assert.match(STATIC_VISUAL_NOTICE, /static frontend visual/);
  assert.match(STATIC_VISUAL_NOTICE, /not generated by SAM, returned by the API/);
});
