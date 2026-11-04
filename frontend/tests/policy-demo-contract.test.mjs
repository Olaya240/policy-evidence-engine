import assert from "node:assert/strict";
import test from "node:test";
import {
  validateScenarioResult,
  validateSessionCreatedResponse,
} from "../.test-build/policyDemoContract.js";
import { loadScenarioAndCreateSession } from "../.test-build/policyDemoState.js";

const validScenario = {
  comparison_id: "cmp-1", request_id: "req-1", proposed_relation: "UNCHANGED", candidate_id: "cand-1",
  reasoning: "Evidence supports review.", status: "PROPOSAL_ONLY", semantic_support: "NOT_VERIFIED",
  human_review_required: true, core_classification: "INCONCLUSIVE", core_proposed_classification: "UNCHANGED",
  uncertainty_reasons: ["QUOTE_PROVENANCE_ONLY"], official_policy_mutated: false, impact_status: "INCONCLUSIVE",
  provenance_details: [{ side: "OLDER", passage_id: "p1", passage_ordinal: null, start_cp: 0, end_cp: 8,
    quote: "Example.", source_sha256: "a".repeat(64), verified_locally: true }],
  provenance_limitation_notice: "Excerpt only.", scenario_id: "scheduling",
};
const validSession = {
  session_id: "a".repeat(32), scenario_id: "scheduling", created_at_iso: "2026-11-03T10:25:30.123456+00:00",
};

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function validatedLoad(rawScenario, options = {}) {
  const requests = [];
  const accepted = [];
  const run = loadScenarioAndCreateSession({
    isCurrent: options.isCurrent ?? (() => true),
    loadScenario: async () => {
      if (options.failScenario) throw new Error("scenario unavailable");
      return validateScenarioResult(rawScenario, options.expectedScenarioId ?? "scheduling");
    },
    createSession: async (scenario) => {
      requests.push({ scenario_id: scenario.scenario_id });
      const response = options.sessionResponse ?? { ...validSession, scenario_id: scenario.scenario_id };
      return validateSessionCreatedResponse(response, scenario.scenario_id);
    },
    onSuccess: (scenario, session) => accepted.push([scenario, session]),
  });
  return { run, requests, accepted };
}

test("valid scenario and session contracts accept backend values", () => {
  assert.deepEqual(validateScenarioResult(validScenario, "scheduling"), validScenario);
  assert.deepEqual(validateSessionCreatedResponse(validSession, "scheduling"), validSession);
  assert.deepEqual(validateSessionCreatedResponse({ session_id: "b".repeat(32), scenario_id: "scheduling" }, "scheduling"),
    { session_id: "b".repeat(32), scenario_id: "scheduling" });
  assert.deepEqual(validateSessionCreatedResponse({
    session_id: "c".repeat(32), scenario_id: "scheduling", created_at: "2026-11-03T10:25:30+00:00",
  }, "scheduling").scenario_id, "scheduling");
});

test("scenario validator rejects missing, null, blank, mismatched, wrong-type, and malformed nested values", () => {
  const invalid = [
    Object.fromEntries(Object.entries(validScenario).filter(([key]) => key !== "scenario_id")),
    { ...validScenario, comparison_id: null },
    { ...validScenario, comparison_id: " \t " },
    { ...validScenario, reasoning: "   " },
    { ...validScenario, scenario_id: " " },
    { ...validScenario, scenario_id: "lounge_access" },
    { ...validScenario, human_review_required: "true" },
    { ...validScenario, official_policy_mutated: null },
    { ...validScenario, uncertainty_reasons: ["OK", "  "] },
    { ...validScenario, uncertainty_reasons: [null] },
    { ...validScenario, provenance_details: [null] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], side: "BOTH" }] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], passage_id: " " }] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], quote: "\t" }] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], source_sha256: "A".repeat(64) }] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], source_sha256: "abc" }] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], passage_ordinal: "1" }] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], start_cp: -1 }] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], end_cp: 0 }] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], end_cp: 7 }] },
    { ...validScenario, provenance_details: [{ ...validScenario.provenance_details[0], verified_locally: 1 }] },
    null,
  ];
  for (const value of invalid) {
    assert.throws(() => validateScenarioResult(value, "scheduling"), /invalid scenario response/, JSON.stringify(value));
  }
});

test("valid scenario triggers exactly one session request bound to its scenario ID", async () => {
  const result = validatedLoad(validScenario);
  await result.run;
  assert.deepEqual(result.requests, [{ scenario_id: "scheduling" }]);
  assert.equal(result.accepted.length, 1);
  assert.equal(result.accepted[0][1].scenario_id, "scheduling");
});

test("missing, empty, whitespace, malformed, or mismatched scenario never creates a session", async () => {
  for (const raw of [
    Object.fromEntries(Object.entries(validScenario).filter(([key]) => key !== "scenario_id")),
    { ...validScenario, scenario_id: "" },
    { ...validScenario, scenario_id: "  " },
    { ...validScenario, provenance_details: [{}] },
    { ...validScenario, scenario_id: "lounge_access" },
  ]) {
    const result = validatedLoad(raw);
    await assert.rejects(result.run, /invalid scenario response/);
    assert.equal(result.requests.length, 0);
    assert.equal(result.accepted.length, 0);
  }
});

test("failed scenario request never creates a session", async () => {
  const result = validatedLoad(validScenario, { failScenario: true });
  await assert.rejects(result.run, /scenario unavailable/);
  assert.equal(result.requests.length, 0);
});

test("stale generation before allocation prevents session creation", async () => {
  const response = deferred();
  let current = true;
  const requests = [];
  const run = loadScenarioAndCreateSession({
    isCurrent: () => current,
    loadScenario: () => response.promise.then((value) => validateScenarioResult(value, "scheduling")),
    createSession: async (scenario) => { requests.push(scenario.scenario_id); return validSession; },
    onSuccess: () => assert.fail("stale scenario must not be accepted"),
  });
  current = false;
  response.resolve(validScenario);
  await run;
  assert.deepEqual(requests, []);
});

test("stale session response cannot become active", async () => {
  const response = deferred();
  let current = true;
  const accepted = [];
  const run = loadScenarioAndCreateSession({
    isCurrent: () => current,
    loadScenario: async () => validateScenarioResult(validScenario, "scheduling"),
    createSession: () => response.promise.then((value) => validateSessionCreatedResponse(value, "scheduling")),
    onSuccess: (...values) => accepted.push(values),
  });
  await Promise.resolve();
  current = false;
  response.resolve(validSession);
  await run;
  assert.deepEqual(accepted, []);
});

test("session validation rejects missing, blank, malformed IDs, scenario mismatch, and bad timestamps", () => {
  for (const value of [
    { scenario_id: "scheduling" },
    { ...validSession, session_id: "" },
    { ...validSession, session_id: "  " },
    { ...validSession, session_id: "not-a-uuid" },
    { ...validSession, scenario_id: " " },
    { ...validSession, scenario_id: "lounge_access" },
    { ...validSession, created_at_iso: "2026-11-03T10:25:30Z" },
    { ...validSession, created_at_iso: "2026-02-30T10:25:30+00:00" },
    { ...validSession, created_at: null },
  ]) assert.throws(() => validateSessionCreatedResponse(value, "scheduling"), /invalid session response/);
});

test("session creation accepts a valid current scenario/session pair and session mismatch is rejected", async () => {
  const accepted = validatedLoad(validScenario);
  await accepted.run;
  assert.equal(accepted.accepted.length, 1);

  const mismatched = validatedLoad(validScenario, {
    sessionResponse: { ...validSession, scenario_id: "lounge_access" },
  });
  await assert.rejects(mismatched.run, /invalid session response/);
  assert.equal(mismatched.accepted.length, 0);
});
