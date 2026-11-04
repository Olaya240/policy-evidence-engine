import assert from "node:assert/strict";
import test from "node:test";
import {
  isChallengeRequestCurrent,
  refreshAfterChallenge,
  runChallengeWorkflow,
} from "../.test-build/challengeWorkflow.js";
import {
  activateAppLifecycle,
  invalidateAppLifecycle,
  isAppLifecycleCurrent,
} from "../.test-build/historyState.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function createHarness() {
  const state = {
    activeInvestigationId: "A",
    latestRequestId: 0,
    challenge: null,
    error: "",
    loading: false,
    detailError: "",
    history: [],
    historyError: "",
  };
  function start(id = state.activeInvestigationId, submit, refresh = async () => null) {
    const identity = { investigationId: id, requestId: ++state.latestRequestId };
    state.loading = true;
    state.error = "";
    const isCurrent = () => isChallengeRequestCurrent(
      identity,
      state.activeInvestigationId,
      state.latestRequestId,
    );
    const completion = runChallengeWorkflow({
      identity,
      isCurrent,
      submit,
      refresh,
      onSuccess: (response) => { state.challenge = response; },
      onFailure: (error) => { state.error = error.message; },
      onSettled: () => { state.loading = false; },
    });
    return { identity, completion };
  }
  return { state, start };
}

test("late success from A cannot change B challenge state or clear B loading", async () => {
  const { state, start } = createHarness();
  const a = deferred();
  const staleA = start("A", () => a.promise);
  state.activeInvestigationId = "B";
  state.challenge = { id: "B-existing" };
  const b = deferred();
  const currentB = start("B", () => b.promise);

  a.resolve({ id: "A-late" });
  await staleA.completion;
  assert.deepEqual(state.challenge, { id: "B-existing" });
  assert.equal(state.error, "");
  assert.equal(state.loading, true);

  b.resolve({ id: "B-result" });
  await currentB.completion;
  assert.deepEqual(state.challenge, { id: "B-result" });
  assert.equal(state.loading, false);
});

test("late failure from A cannot set B error or clear B loading", async () => {
  const { state, start } = createHarness();
  const a = deferred();
  const staleA = start("A", () => a.promise);
  state.activeInvestigationId = "B";
  const b = deferred();
  const currentB = start("B", () => b.promise);

  a.reject(new Error("A failed late"));
  await staleA.completion;
  assert.equal(state.error, "");
  assert.equal(state.loading, true);

  b.resolve({ id: "B-result" });
  await currentB.completion;
  assert.deepEqual(state.challenge, { id: "B-result" });
  assert.equal(state.loading, false);
});

test("a current challenge success runs refresh and settles its own loading state", async () => {
  const { state, start } = createHarness();
  let refreshed = false;
  const request = start("A", async () => ({ id: "A-result" }), async () => {
    refreshed = true;
    return { id: "A-refreshed" };
  });
  await request.completion;
  assert.equal(refreshed, true);
  assert.deepEqual(state.challenge, { id: "A-result" });
  assert.equal(state.loading, false);
  assert.equal(state.error, "");
});

test("a current challenge failure reports its error and settles its own loading state", async () => {
  const { state, start } = createHarness();
  const request = start("A", async () => { throw new Error("Challenge rejected"); });
  await request.completion;
  assert.equal(state.error, "Challenge rejected");
  assert.equal(state.loading, false);
  assert.equal(state.challenge, null);
});

test("an older overlapping request cannot replace or settle the newer request", async () => {
  const { state, start } = createHarness();
  const first = deferred();
  const older = start("A", () => first.promise);
  const second = deferred();
  const latest = start("A", () => second.promise);

  first.resolve({ id: "older" });
  await older.completion;
  assert.equal(state.loading, true);
  assert.equal(state.challenge, null);

  second.resolve({ id: "newer" });
  await latest.completion;
  assert.deepEqual(state.challenge, { id: "newer" });
  assert.equal(state.loading, false);
});

test("an older request completing refresh cannot replace a newer same-investigation result", async () => {
  const { state, start } = createHarness();
  const refresh = deferred();
  const older = start("A", async () => ({ id: "older-response" }), () => refresh.promise);
  await Promise.resolve();

  const latest = start("A", async () => ({ id: "newer-response" }));
  await latest.completion;
  refresh.resolve({ id: "old-refresh" });
  await older.completion;

  assert.deepEqual(state.challenge, { id: "newer-response" });
  assert.equal(state.loading, false);
});

test("detail refresh failure is separate while history can still succeed", async () => {
  const { state, start } = createHarness();
  const request = start("A", async () => ({ id: "challenge-ok" }), () => refreshAfterChallenge({
    isCurrent: () => true,
    loadInvestigation: async () => { throw new Error("detail unavailable"); },
    loadHistory: async () => [{ version: 4 }],
    onInvestigation: () => assert.fail("no detail should be applied"),
    onInvestigationError: (error) => { state.detailError = error.message; },
    onHistoryStart: () => {},
    onHistory: (history) => { state.history = history; },
    onHistoryError: (error) => { state.historyError = error.message; },
  }));
  await request.completion;
  assert.deepEqual(state.challenge, { id: "challenge-ok" });
  assert.equal(state.error, "");
  assert.equal(state.detailError, "detail unavailable");
  assert.deepEqual(state.history, [{ version: 4 }]);
  assert.equal(state.historyError, "");
});

test("history refresh failure stays separate from challenge and detail success", async () => {
  const { state, start } = createHarness();
  let detail;
  const request = start("A", async () => ({ id: "challenge-ok" }), () => refreshAfterChallenge({
    isCurrent: () => true,
    loadInvestigation: async () => ({ id: "A", version: 5 }),
    loadHistory: async () => { throw new Error("history unavailable"); },
    onInvestigation: (value) => { detail = value; },
    onInvestigationError: (error) => { state.detailError = error.message; },
    onHistoryStart: () => {},
    onHistory: () => assert.fail("history should fail"),
    onHistoryError: (error) => { state.historyError = error.message; },
  }));
  await request.completion;
  assert.deepEqual(state.challenge, { id: "challenge-ok" });
  assert.deepEqual(detail, { id: "A", version: 5 });
  assert.equal(state.error, "");
  assert.equal(state.detailError, "");
  assert.equal(state.historyError, "history unavailable");
});

test("stale detail refresh cannot apply detail or start history retrieval", async () => {
  const detail = deferred();
  const applied = [];
  let historyStarted = false;
  let current = true;
  const refresh = refreshAfterChallenge({
    isCurrent: () => current,
    loadInvestigation: () => detail.promise,
    loadHistory: async () => [],
    onInvestigation: (value) => applied.push(value),
    onInvestigationError: (error) => applied.push(error),
    onHistoryStart: () => { historyStarted = true; },
    onHistory: () => {},
    onHistoryError: () => {},
  });
  current = false;
  detail.resolve({ id: "A" });
  await refresh;
  assert.deepEqual(applied, []);
  assert.equal(historyStarted, false);
});

test("stale history success or failure cannot update after investigation changes", async () => {
  for (const outcome of ["success", "failure"]) {
    const history = deferred();
    const applied = [];
    let current = true;
    const refresh = refreshAfterChallenge({
      isCurrent: () => current,
      loadInvestigation: async () => ({ id: "A" }),
      loadHistory: () => history.promise,
      onInvestigation: () => {},
      onInvestigationError: (error) => applied.push(error),
      onHistoryStart: () => {},
      onHistory: (value) => applied.push(value),
      onHistoryError: (error) => applied.push(error),
    });
    await Promise.resolve();
    await Promise.resolve();
    current = false;
    if (outcome === "success") history.resolve([{ version: 2 }]);
    else history.reject(new Error("stale history failure"));
    await refresh;
    assert.deepEqual(applied, []);
  }
});

test("App lifecycle invalidation suppresses challenge success, failure, and settled callbacks", async () => {
  for (const outcome of ["success", "failure"]) {
    const lifecycle = { mounted: false, epoch: 0 };
    const epoch = activateAppLifecycle(lifecycle);
    const submission = deferred();
    const callbacks = [];
    const identity = { investigationId: "A", requestId: 1 };
    const request = runChallengeWorkflow({
      identity,
      isCurrent: () => isAppLifecycleCurrent(lifecycle, epoch),
      submit: () => submission.promise,
      refresh: async () => null,
      onSuccess: (result) => callbacks.push(["success", result]),
      onFailure: (error) => callbacks.push(["failure", error.message]),
      onSettled: () => callbacks.push(["settled"]),
    });
    invalidateAppLifecycle(lifecycle, epoch);
    if (outcome === "success") submission.resolve({ id: "late" });
    else submission.reject(new Error("late challenge failure"));
    await request;
    assert.deepEqual(callbacks, []);
  }
});

test("App lifecycle invalidation during detail refresh blocks detail errors and history start", async () => {
  for (const outcome of ["success", "failure"]) {
    const lifecycle = { mounted: false, epoch: 0 };
    const epoch = activateAppLifecycle(lifecycle);
    const detail = deferred();
    const callbacks = [];
    const refresh = refreshAfterChallenge({
      isCurrent: () => isAppLifecycleCurrent(lifecycle, epoch),
      loadInvestigation: () => detail.promise,
      loadHistory: async () => [],
      onInvestigation: (value) => callbacks.push(["detail", value]),
      onInvestigationError: (error) => callbacks.push(["detail-error", error.message]),
      onHistoryStart: () => callbacks.push(["history-start"]),
      onHistory: (value) => callbacks.push(["history", value]),
      onHistoryError: (error) => callbacks.push(["history-error", error.message]),
    });
    invalidateAppLifecycle(lifecycle, epoch);
    if (outcome === "success") detail.resolve({ id: "A" });
    else detail.reject(new Error("late detail failure"));
    await refresh;
    assert.deepEqual(callbacks, []);
  }
});

test("App lifecycle invalidation during history refresh blocks history success and failure", async () => {
  for (const outcome of ["success", "failure"]) {
    const lifecycle = { mounted: false, epoch: 0 };
    const epoch = activateAppLifecycle(lifecycle);
    const history = deferred();
    const historyStarted = deferred();
    const callbacks = [];
    const refresh = refreshAfterChallenge({
      isCurrent: () => isAppLifecycleCurrent(lifecycle, epoch),
      loadInvestigation: async () => ({ id: "A" }),
      loadHistory: () => history.promise,
      onInvestigation: (value) => callbacks.push(["detail", value]),
      onInvestigationError: (error) => callbacks.push(["detail-error", error.message]),
      onHistoryStart: () => { callbacks.push(["history-start"]); historyStarted.resolve(); },
      onHistory: (value) => callbacks.push(["history", value]),
      onHistoryError: (error) => callbacks.push(["history-error", error.message]),
    });
    await historyStarted.promise;
    invalidateAppLifecycle(lifecycle, epoch);
    if (outcome === "success") history.resolve([{ version: 2 }]);
    else history.reject(new Error("late history failure"));
    await refresh;
    assert.deepEqual(callbacks, [["detail", { id: "A" }], ["history-start"]]);
  }
});
