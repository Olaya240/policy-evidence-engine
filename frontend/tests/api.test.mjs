import test from "node:test";
import assert from "node:assert/strict";
import { apiRequest, ApiError, formatApiError, readUnreadableRows } from "../.test-build/api.js";

test("unreadable-row headers preserve ids and reconcile missing or malformed counts", () => {
  assert.deepEqual(readUnreadableRows(new Headers({
    "X-Unreadable-Rows": "2",
    "X-Unreadable-Row-Ids": "ROW-1, ROW-2",
  })), { count: 2, ids: ["ROW-1", "ROW-2"] });
  assert.deepEqual(readUnreadableRows(new Headers()), { count: 0, ids: [] });
  assert.deepEqual(readUnreadableRows(new Headers({ "X-Unreadable-Rows": "invalid" })), { count: 0, ids: [] });
  assert.deepEqual(readUnreadableRows(new Headers({ "X-Unreadable-Row-Ids": "ROW-X, ROW-Y" })), {
    count: 2,
    ids: ["ROW-X", "ROW-Y"],
  });
  assert.deepEqual(readUnreadableRows(new Headers({ "X-Unreadable-Rows": "1", "X-Unreadable-Row-Ids": "ROW-X, ROW-Y" })), {
    count: 2,
    ids: ["ROW-X", "ROW-Y"],
  });
});

test("422 validation details retain field paths and readable backend messages", () => {
  const message = formatApiError(422, { detail: [
    { loc: ["body", "quote"], msg: "String should have at most 1000 characters" },
    { loc: ["body", "reason"], msg: "String should have at least 8 characters" },
  ] });
  assert.match(message, /Validation failed \(422\)/);
  assert.match(message, /quote: String should have at most 1000 characters/);
  assert.match(message, /reason: String should have at least 8 characters/);
});

test("API requests preserve method and payload and expose unreadable-row headers", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  let unreadable = null;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify({ id: "INV-1" }), {
      status: 201,
      headers: { "Content-Type": "application/json", "X-Unreadable-Rows": "1", "X-Unreadable-Row-Ids": "BAD-1" },
    });
  };
  try {
    const result = await apiRequest("/investigations", {
      method: "POST",
      body: JSON.stringify({ question: "Did time pressure contribute?", preset_id: "handover_omissions" }),
    }, (response) => { unreadable = readUnreadableRows(response.headers); });
    assert.deepEqual(result, { id: "INV-1" });
    assert.equal(request.url, "/api/investigations");
    assert.equal(request.init.method, "POST");
    assert.deepEqual(JSON.parse(request.init.body), { question: "Did time pressure contribute?", preset_id: "handover_omissions" });
    assert.deepEqual(unreadable, { count: 1, ids: ["BAD-1"] });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("API errors preserve backend 422 messages and status", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Challenge quote must be an exact source substring" }), {
    status: 422,
    headers: { "Content-Type": "application/json" },
  });
  try {
    await assert.rejects(apiRequest("/investigations/INV-1/claims/TIME_PRESSURE/challenge", { method: "POST" }), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 422);
      assert.match(error.message, /exact source substring/);
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("challenge request uses the backend source_record_id field and accepts revision snapshots", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  const payload = { reason: "The quote needs another review.", source_record_id: "OPS-12", quote: "The checklist was unavailable" };
  const responseBody = { version: 3, reason: payload.reason, before: { TIME_PRESSURE: { status: "SUPPORTED" } }, after: { TIME_PRESSURE: { status: "PARTIAL" } }, recomputed_claim_ids: ["TIME_PRESSURE"] };
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return new Response(JSON.stringify(responseBody), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  try {
    const result = await apiRequest("/investigations/INV-1/claims/TIME_PRESSURE/challenge", { method: "POST", body: JSON.stringify(payload) });
    assert.equal(request.url, "/api/investigations/INV-1/claims/TIME_PRESSURE/challenge");
    assert.deepEqual(JSON.parse(request.init.body), payload);
    assert.equal(result.version, 3);
    assert.deepEqual(result.recomputed_claim_ids, ["TIME_PRESSURE"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("history response retains backend revision, event, and changed-claim snapshots", async () => {
  const originalFetch = globalThis.fetch;
  const history = [{
    version: 3,
    created_at: "2026-11-02T12:00:00Z",
    event: "CHALLENGE",
    claim_id: "TIME_PRESSURE",
    reason: "Please review this evidence.",
    before: { TIME_PRESSURE: { status: "SUPPORTED", explanation_trace: null } },
    after: { TIME_PRESSURE: { status: "PARTIAL", explanation_trace: null } },
    evidence_changes: ["OPS-12: exact quote revalidated and claim reassessed"],
    recomputed_claim_ids: ["TIME_PRESSURE"],
  }];
  globalThis.fetch = async () => new Response(JSON.stringify(history), { status: 200, headers: { "Content-Type": "application/json" } });
  try {
    const result = await apiRequest("/investigations/INV-1/history");
    assert.equal(result[0].version, 3);
    assert.equal(result[0].event, "CHALLENGE");
    assert.equal(result[0].before.TIME_PRESSURE.status, "SUPPORTED");
    assert.equal(result[0].after.TIME_PRESSURE.status, "PARTIAL");
    assert.deepEqual(result[0].recomputed_claim_ids, ["TIME_PRESSURE"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
