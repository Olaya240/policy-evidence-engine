import assert from "node:assert/strict";
import test from "node:test";
import {
  initialPolicyDemoAsyncState,
  loadOnceWhilePending,
  loadScenarioAndCreateSession,
  loadScenarioMetadata,
  policyDemoAsyncReducer,
} from "../.test-build/policyDemoState.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject; });
  return { promise, resolve, reject };
}

const scenario = (state, generation, scenarioId) => policyDemoAsyncReducer(state, { type: "scenarioChanged", generation, scenarioId });
const session = (state, generation, scenarioId, sessionId) => policyDemoAsyncReducer(state, { type: "sessionCreated", generation, scenarioId, sessionId });
const identity = (state) => ({ generation: state.generation, scenarioId: state.scenarioId, sessionId: state.sessionId });
const startChallenge = (state, requestId = 1) => policyDemoAsyncReducer(state, { type: "challengeStarted", identity: identity(state), requestId });
const challengeSuccess = (state, requestId, result) => policyDemoAsyncReducer(state, { type: "challengeSucceeded", identity: identityFor("A", "session-A", 1), requestId, result });
const identityFor = (scenarioId, sessionId, generation) => ({ scenarioId, sessionId, generation });

function activeA() {
  return session(scenario(initialPolicyDemoAsyncState, 1, "A"), 1, "A", "session-A");
}

test("StrictMode replay shares one pending scenario request and only the current effect creates a session", async () => {
  const response = deferred();
  const inFlight = new Map();
  let fetchCount = 0;
  const load = () => loadOnceWhilePending(inFlight, "scheduling", () => {
    fetchCount += 1;
    return response.promise;
  });
  let firstCurrent = true;
  const accepted = [];
  const sessionRequests = [];
  const options = (isCurrent) => ({
    isCurrent,
    loadScenario: load,
    createSession: async (item) => { sessionRequests.push(item); return { session_id: "session" }; },
    onSuccess: (...values) => accepted.push(values),
  });
  const firstEffect = loadScenarioAndCreateSession(options(() => firstCurrent));
  firstCurrent = false;
  const replayedEffect = loadScenarioAndCreateSession(options(() => true));
  await Promise.resolve();
  assert.equal(fetchCount, 1);
  response.resolve({ scenario_id: "scheduling" });
  await Promise.all([firstEffect, replayedEffect]);
  assert.equal(fetchCount, 1);
  assert.equal(sessionRequests.length, 1);
  assert.equal(accepted.length, 1);
});

test("failed shared scenario request clears pending entry so a later load can retry", async () => {
  const inFlight = new Map();
  let attempts = 0;
  const load = () => loadOnceWhilePending(inFlight, "scheduling", async () => {
    attempts += 1;
    if (attempts === 1) throw new Error("offline");
    return "loaded";
  });
  await assert.rejects(load(), /offline/);
  assert.equal(await load(), "loaded");
  assert.equal(attempts, 2);
});

test("scenario switch invalidates a pending A challenge and clears A state", () => {
  const pending = startChallenge(activeA());
  const switched = session(scenario(pending, 2, "B"), 2, "B", "session-B");
  const late = policyDemoAsyncReducer(switched, { type: "challengeSucceeded", identity: identityFor("A", "session-A", 1), requestId: 1, result: { ok: "A" } });
  assert.equal(late, switched);
  assert.equal(late.scenarioId, "B");
  assert.equal(late.challenge, null);
});

test("delayed A challenge success cannot update B", () => {
  const b = session(scenario(activeA(), 2, "B"), 2, "B", "session-B");
  const next = policyDemoAsyncReducer(b, { type: "challengeSucceeded", identity: identityFor("A", "session-A", 1), requestId: 1, result: { ok: "A" } });
  assert.equal(next, b);
});

test("delayed A challenge error cannot update B", () => {
  const b = session(scenario(activeA(), 2, "B"), 2, "B", "session-B");
  const next = policyDemoAsyncReducer(b, { type: "challengeFailed", identity: identityFor("A", "session-A", 1), requestId: 1, error: "A failed" });
  assert.equal(next.challengeError, "");
  assert.equal(next, b);
});

test("delayed A history success cannot update B", () => {
  const b = session(scenario(activeA(), 2, "B"), 2, "B", "session-B");
  const next = policyDemoAsyncReducer(b, { type: "historySucceeded", identity: identityFor("A", "session-A", 1), requestId: 1, events: [{ scenario: "A" }] });
  assert.deepEqual(next.historyEvents, []);
});

test("delayed A history error cannot update B", () => {
  const b = session(scenario(activeA(), 2, "B"), 2, "B", "session-B");
  const next = policyDemoAsyncReducer(b, { type: "historyFailed", identity: identityFor("A", "session-A", 1), requestId: 1, error: "A history failed" });
  assert.equal(next.historyError, "");
});

test("session reset changes request identity and rejects old-session results", () => {
  const old = activeA();
  const reset = policyDemoAsyncReducer(old, { type: "sessionResetStarted", previous: identity(old), generation: 2 });
  const stale = policyDemoAsyncReducer(reset, { type: "challengeSucceeded", identity: identityFor("A", "session-A", 1), requestId: 1, result: { ok: "old" } });
  const staleHistoryError = policyDemoAsyncReducer(reset, { type: "historyFailed", identity: identityFor("A", "session-A", 1), requestId: 1, error: "old history" });
  assert.equal(stale, reset);
  assert.equal(staleHistoryError, reset);
  assert.equal(stale.generation, 2);
  assert.equal(stale.sessionId, "session-A");
});

test("session recreation rejects results from the previous session", () => {
  const newSession = session(scenario(activeA(), 2, "A"), 2, "A", "session-A2");
  const stale = policyDemoAsyncReducer(newSession, { type: "historySucceeded", identity: identityFor("A", "session-A", 1), requestId: 1, events: [{ stale: true }] });
  const staleChallengeError = policyDemoAsyncReducer(newSession, { type: "challengeFailed", identity: identityFor("A", "session-A", 1), requestId: 1, error: "stale challenge" });
  assert.deepEqual(stale.historyEvents, []);
  assert.equal(staleChallengeError.challengeError, "");
  assert.equal(stale.sessionId, "session-A2");
});

test("history failure after successful challenge stays a history error", () => {
  let state = startChallenge(activeA());
  state = challengeSuccess(state, 1, { id: "successful-challenge" });
  const current = identity(state);
  state = policyDemoAsyncReducer(state, { type: "historyStarted", identity: current, requestId: 1 });
  state = policyDemoAsyncReducer(state, { type: "historyFailed", identity: current, requestId: 1, error: "History unavailable" });
  assert.equal(state.challengeStatus, "success");
  assert.deepEqual(state.challenge, { id: "successful-challenge" });
  assert.equal(state.challengeError, "");
  assert.equal(state.historyStatus, "error");
  assert.equal(state.historyError, "History unavailable");
});

test("challenge and history success populate the active session", () => {
  let state = startChallenge(activeA());
  state = challengeSuccess(state, 1, { id: "challenge-A" });
  const current = identity(state);
  state = policyDemoAsyncReducer(state, { type: "historyStarted", identity: current, requestId: 1 });
  state = policyDemoAsyncReducer(state, { type: "historySucceeded", identity: current, requestId: 1, events: [{ scenario: "A" }] });
  assert.equal(state.challengeStatus, "success");
  assert.equal(state.historyStatus, "ready");
  assert.equal(state.historyEvents[0].scenario, "A");
});

test("older error response cannot replace a newer success within one session", () => {
  let state = session(scenario(activeA(), 2, "A"), 2, "A", "session-A2");
  const current = identity(state);
  state = policyDemoAsyncReducer(state, { type: "historyStarted", identity: current, requestId: 4 });
  state = policyDemoAsyncReducer(state, { type: "historySucceeded", identity: current, requestId: 4, events: [{ current: true }] });
  const afterOldError = policyDemoAsyncReducer(state, { type: "historyFailed", identity: current, requestId: 3, error: "stale" });
  assert.equal(afterOldError, state);
});

test("scenario metadata response after effect cleanup is ignored", async () => {
  const response = deferred();
  let active = true;
  const accepted = [];
  const load = loadScenarioMetadata({ isCurrent: () => active, load: () => response.promise, onSuccess: (value) => accepted.push(value) });
  active = false;
  response.resolve([{ id: "stale" }]);
  await load;
  assert.deepEqual(accepted, []);
});

test("older metadata request cannot overwrite a newer response", async () => {
  const oldResponse = deferred();
  const newResponse = deferred();
  let latestRequest = 1;
  const accepted = [];
  const oldLoad = loadScenarioMetadata({
    isCurrent: () => latestRequest === 1,
    load: () => oldResponse.promise,
    onSuccess: (value) => accepted.push(value),
  });
  const newLoad = loadScenarioMetadata({
    isCurrent: () => latestRequest === 2,
    load: () => newResponse.promise,
    onSuccess: (value) => accepted.push(value),
  });
  latestRequest = 2;
  newResponse.resolve([{ id: "new" }]);
  await newLoad;
  oldResponse.resolve([{ id: "old" }]);
  await oldLoad;
  assert.deepEqual(accepted, [[{ id: "new" }]]);
});

test("metadata response after unmount is not accepted and current metadata populates selector", async () => {
  const accepted = [];
  await loadScenarioMetadata({ isCurrent: () => true, load: async () => [{ id: "current" }], onSuccess: (value) => accepted.push(value) });
  await loadScenarioMetadata({ isCurrent: () => false, load: async () => [{ id: "unmounted" }], onSuccess: (value) => accepted.push(value) });
  assert.deepEqual(accepted, [[{ id: "current" }]]);
});

test("scenario prerequisite failure prevents session creation", async () => {
  let sessionRequests = 0;
  await assert.rejects(loadScenarioAndCreateSession({
    isCurrent: () => true,
    loadScenario: async () => { throw new Error("scenario unavailable"); },
    createSession: async () => { sessionRequests++; return { sessionId: "unused" }; },
    onSuccess: () => assert.fail("failed scenario must not be accepted"),
  }), /scenario unavailable/);
  assert.equal(sessionRequests, 0);
});

test("stale session response cannot become active after generation changes", async () => {
  const sessionResponse = deferred();
  let generation = 4;
  const accepted = [];
  const load = loadScenarioAndCreateSession({
    isCurrent: () => generation === 4,
    loadScenario: async () => ({ scenarioId: "A" }),
    createSession: () => sessionResponse.promise,
    onSuccess: (scenarioValue, sessionValue) => accepted.push([scenarioValue, sessionValue]),
  });
  await Promise.resolve();
  generation = 5;
  sessionResponse.resolve({ sessionId: "stale-session" });
  await load;
  assert.deepEqual(accepted, []);
});

test("current scenario and session load is accepted", async () => {
  const accepted = [];
  await loadScenarioAndCreateSession({
    isCurrent: () => true,
    loadScenario: async () => ({ scenarioId: "A" }),
    createSession: async () => ({ sessionId: "session-A" }),
    onSuccess: (scenarioValue, sessionValue) => accepted.push([scenarioValue, sessionValue]),
  });
  assert.deepEqual(accepted, [[{ scenarioId: "A" }, { sessionId: "session-A" }]]);
});
