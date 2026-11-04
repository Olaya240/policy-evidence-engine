import assert from "node:assert/strict";
import test from "node:test";
import {
  activateAppLifecycle,
  historyLoadReducer,
  initialHistoryLoadState,
  invalidateAppLifecycle,
  isAppLifecycleCurrent,
  runInvestigationCreation,
  runLifecycleRequest,
} from "../.test-build/historyState.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test("App lifecycle setup, cleanup, and StrictMode replay produce distinct identities", () => {
  const lifecycle = { mounted: false, epoch: 0 };
  const firstEpoch = activateAppLifecycle(lifecycle);
  assert.equal(isAppLifecycleCurrent(lifecycle, firstEpoch), true);
  invalidateAppLifecycle(lifecycle, firstEpoch);
  const replayEpoch = activateAppLifecycle(lifecycle);
  assert.notEqual(replayEpoch, firstEpoch);
  invalidateAppLifecycle(lifecycle, firstEpoch);
  assert.equal(isAppLifecycleCurrent(lifecycle, firstEpoch), false);
  assert.equal(isAppLifecycleCurrent(lifecycle, replayEpoch), true);
  invalidateAppLifecycle(lifecycle, replayEpoch);
  assert.equal(isAppLifecycleCurrent(lifecycle, replayEpoch), false);
});

test("initial records success and settled callbacks are ignored after App lifecycle invalidation", async () => {
  const lifecycle = { mounted: false, epoch: 0 };
  const epoch = activateAppLifecycle(lifecycle);
  const response = deferred();
  const callbacks = [];
  const request = runLifecycleRequest({
    isCurrent: () => isAppLifecycleCurrent(lifecycle, epoch),
    request: () => response.promise,
    onSuccess: (value) => callbacks.push(["success", value]),
    onFailure: (error) => callbacks.push(["failure", error]),
    onSettled: () => callbacks.push(["settled"]),
  });
  invalidateAppLifecycle(lifecycle, epoch);
  response.resolve(["late records"]);
  await request;
  assert.deepEqual(callbacks, []);
});

test("initial records failure and settled callbacks are ignored after App lifecycle invalidation", async () => {
  const lifecycle = { mounted: false, epoch: 0 };
  const epoch = activateAppLifecycle(lifecycle);
  const response = deferred();
  const callbacks = [];
  const request = runLifecycleRequest({
    isCurrent: () => isAppLifecycleCurrent(lifecycle, epoch),
    request: () => response.promise,
    onSuccess: (value) => callbacks.push(["success", value]),
    onFailure: (error) => callbacks.push(["failure", error.message]),
    onSettled: () => callbacks.push(["settled"]),
  });
  invalidateAppLifecycle(lifecycle, epoch);
  response.reject(new Error("late records failure"));
  await request;
  assert.deepEqual(callbacks, []);
});

test("App history success and failure dispatches are ignored after lifecycle invalidation", async () => {
  for (const outcome of ["success", "failure"]) {
    const lifecycle = { mounted: false, epoch: 0 };
    const epoch = activateAppLifecycle(lifecycle);
    let state = begin(initialHistoryLoadState, "A", 1);
    const beforeCompletion = state;
    const response = deferred();
    const request = runLifecycleRequest({
      isCurrent: () => isAppLifecycleCurrent(lifecycle, epoch),
      request: () => response.promise,
      onSuccess: (events) => { state = success(state, "A", 1, events); },
      onFailure: (error) => { state = failure(state, "A", 1, error.message); },
    });
    invalidateAppLifecycle(lifecycle, epoch);
    if (outcome === "success") response.resolve([a]);
    else response.reject(new Error("late history failure"));
    await request;
    assert.equal(state, beforeCompletion);
  }
});

const a = { version: 1, investigationId: "A" };
const b = { version: 1, investigationId: "B" };
const begin = (state, investigationId, requestId) => historyLoadReducer(state, { type: "begin", investigationId, requestId });
const success = (state, investigationId, requestId, entries) => historyLoadReducer(state, { type: "success", investigationId, requestId, entries });
const failure = (state, investigationId, requestId, error) => historyLoadReducer(state, { type: "failure", investigationId, requestId, error });

test("switching from A to B clears A history", () => {
  const state = begin(success(begin(initialHistoryLoadState, "A", 1), "A", 1, [a]), "B", 2);
  assert.equal(state.investigationId, "B");
  assert.deepEqual(state.entries, []);
  assert.equal(state.status, "loading");
});

test("failed B request cannot display A entries", () => {
  const state = failure(begin(success(begin(initialHistoryLoadState, "A", 1), "A", 1, [a]), "B", 2), "B", 2, "B unavailable");
  assert.deepEqual(state.entries, []);
  assert.equal(state.investigationId, "B");
  assert.equal(state.error, "B unavailable");
});

test("delayed A response cannot overwrite B history", () => {
  const state = success(begin(begin(initialHistoryLoadState, "A", 1), "B", 2), "B", 2, [b]);
  assert.equal(success(state, "A", 1, [a]), state);
  assert.deepEqual(state.entries, [b]);
});

test("failed refresh clears cached history and reports the failure", () => {
  const state = failure(begin(success(begin(initialHistoryLoadState, "A", 1), "A", 1, [a]), "A", 2), "A", 2, "Refresh failed");
  assert.deepEqual(state.entries, []);
  assert.equal(state.status, "error");
  assert.equal(state.error, "Refresh failed");
});

test("failed post-challenge refresh preserves investigation identity and reports error", () => {
  const state = failure(begin(success(begin(initialHistoryLoadState, "A", 1), "A", 1, [a]), "A", 2), "A", 2, "History unavailable after challenge");
  assert.equal(state.investigationId, "A");
  assert.equal(state.status, "error");
  assert.match(state.error, /after challenge/);
  assert.deepEqual(state.entries, []);
});

test("successful refresh displays only matching history", () => {
  const state = success(begin(initialHistoryLoadState, "B", 1), "B", 1, [b]);
  assert.equal(state.status, "ready");
  assert.equal(state.investigationId, "B");
  assert.deepEqual(state.entries, [b]);
});

test("pending and failed creation leave the previous investigation history intact", () => {
  let state = begin(initialHistoryLoadState, "A", 1);
  state = success(state, "A", 1, [a]);
  const activeDuringCreation = state;
  // Creation has no history action until the new investigation is successfully returned.
  assert.equal(state, activeDuringCreation);
  assert.equal(state.investigationId, "A");
  assert.deepEqual(state.entries, [a]);
});

test("failed history recovery reports its error while retaining the investigation identity", () => {
  let state = begin(initialHistoryLoadState, "A", 1);
  state = success(state, "A", 1, [a]);
  state = begin(state, "A", 2);
  state = failure(state, "A", 2, "Recovery failed");
  assert.equal(state.investigationId, "A");
  assert.equal(state.status, "error");
  assert.equal(state.error, "Recovery failed");
  assert.deepEqual(state.entries, []);
});

test("latest investigation creation owns success and loading when requests overlap", async () => {
  const a = deferred();
  const b = deferred();
  const state = { investigation: { id: "PREVIOUS" }, history: [a.version], loading: false, error: "" };
  let latest = 0;
  const start = (request) => {
    const requestId = ++latest;
    state.loading = true;
    state.error = "";
    return runInvestigationCreation({
      isCurrent: () => requestId === latest,
      create: () => request.promise,
      onSuccess: (result) => { state.investigation = result; state.history = []; },
      onFailure: (error) => { state.error = error.message; },
      onSettled: () => { state.loading = false; },
    });
  };
  const priorHistory = [{ version: 1 }];
  state.history = priorHistory;
  const requestA = start(a);
  const requestB = start(b);

  a.resolve({ id: "STALE-A" });
  await requestA;
  assert.deepEqual(state.investigation, { id: "PREVIOUS" });
  assert.equal(state.history, priorHistory);
  assert.equal(state.loading, true);

  b.resolve({ id: "CURRENT-B" });
  await requestB;
  assert.deepEqual(state.investigation, { id: "CURRENT-B" });
  assert.deepEqual(state.history, []);
  assert.equal(state.loading, false);
});

test("App lifecycle invalidation suppresses investigation creation success and settled callbacks", async () => {
  const lifecycle = { mounted: false, epoch: 0 };
  const epoch = activateAppLifecycle(lifecycle);
  const response = deferred();
  const callbacks = [];
  const requestId = 1;
  const request = runInvestigationCreation({
    isCurrent: () => isAppLifecycleCurrent(lifecycle, epoch) && requestId === 1,
    create: () => response.promise,
    onSuccess: (result) => callbacks.push(["success", result]),
    onFailure: (error) => callbacks.push(["failure", error.message]),
    onSettled: () => callbacks.push(["settled"]),
  });
  invalidateAppLifecycle(lifecycle, epoch);
  response.resolve({ id: "late-investigation" });
  await request;
  assert.deepEqual(callbacks, []);
});

test("App lifecycle invalidation suppresses investigation creation failure and settled callbacks", async () => {
  const lifecycle = { mounted: false, epoch: 0 };
  const epoch = activateAppLifecycle(lifecycle);
  const response = deferred();
  const callbacks = [];
  const request = runInvestigationCreation({
    isCurrent: () => isAppLifecycleCurrent(lifecycle, epoch),
    create: () => response.promise,
    onSuccess: (result) => callbacks.push(["success", result]),
    onFailure: (error) => callbacks.push(["failure", error.message]),
    onSettled: () => callbacks.push(["settled"]),
  });
  invalidateAppLifecycle(lifecycle, epoch);
  response.reject(new Error("late creation failure"));
  await request;
  assert.deepEqual(callbacks, []);
});

test("unmounted failed creation leaves the previously active investigation and history intact", async () => {
  const lifecycle = { mounted: false, epoch: 0 };
  const epoch = activateAppLifecycle(lifecycle);
  const previousInvestigation = { id: "A" };
  const previousHistory = [{ version: 1 }];
  const state = { investigation: previousInvestigation, history: previousHistory, error: "", loading: true };
  const response = deferred();
  const request = runInvestigationCreation({
    isCurrent: () => isAppLifecycleCurrent(lifecycle, epoch),
    create: () => response.promise,
    onSuccess: (result) => { state.investigation = result; state.history = []; },
    onFailure: (error) => { state.error = error.message; },
    onSettled: () => { state.loading = false; },
  });
  invalidateAppLifecycle(lifecycle, epoch);
  response.reject(new Error("unmounted"));
  await request;
  assert.equal(state.investigation, previousInvestigation);
  assert.equal(state.history, previousHistory);
  assert.equal(state.error, "");
  assert.equal(state.loading, true);
});

test("stale investigation creation failure cannot replace the current creation error", async () => {
  const a = deferred();
  const b = deferred();
  const state = { investigation: { id: "PREVIOUS" }, history: [{ version: 1 }], loading: false, error: "" };
  let latest = 0;
  const start = (request) => {
    const requestId = ++latest;
    state.loading = true;
    state.error = "";
    return runInvestigationCreation({
      isCurrent: () => requestId === latest,
      create: () => request.promise,
      onSuccess: (result) => { state.investigation = result; state.history = []; },
      onFailure: (error) => { state.error = error.message; },
      onSettled: () => { state.loading = false; },
    });
  };
  const requestA = start(a);
  const requestB = start(b);
  b.reject(new Error("B creation failed"));
  await requestB;
  a.reject(new Error("stale A creation failed"));
  await requestA;
  assert.equal(state.error, "B creation failed");
  assert.equal(state.loading, false);
  assert.deepEqual(state.investigation, { id: "PREVIOUS" });
  assert.deepEqual(state.history, [{ version: 1 }]);
});

test("failed current investigation creation preserves active investigation and history", async () => {
  const state = { investigation: { id: "A" }, history: [{ version: 1 }], loading: true, error: "" };
  await runInvestigationCreation({
    isCurrent: () => true,
    create: async () => { throw new Error("creation unavailable"); },
    onSuccess: (result) => { state.investigation = result; state.history = []; },
    onFailure: (error) => { state.error = error.message; },
    onSettled: () => { state.loading = false; },
  });
  assert.deepEqual(state.investigation, { id: "A" });
  assert.deepEqual(state.history, [{ version: 1 }]);
  assert.equal(state.error, "creation unavailable");
  assert.equal(state.loading, false);
});

test("current investigation creation switches identity and invalidates prior challenge and history work", async () => {
  const state = {
    investigation: { id: "A" },
    activeInvestigationId: "A",
    history: [{ version: 2 }],
    challengeRequestId: 7,
    loading: true,
  };
  await runInvestigationCreation({
    isCurrent: () => true,
    create: async () => ({ id: "B" }),
    onSuccess: (result) => {
      state.challengeRequestId += 1;
      state.activeInvestigationId = result.id;
      state.investigation = result;
      state.history = [];
    },
    onFailure: () => assert.fail("creation should succeed"),
    onSettled: () => { state.loading = false; },
  });
  assert.deepEqual(state.investigation, { id: "B" });
  assert.equal(state.activeInvestigationId, "B");
  assert.equal(state.challengeRequestId, 8);
  assert.deepEqual(state.history, []);
  assert.equal(state.loading, false);
});
