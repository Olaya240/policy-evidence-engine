import test from "node:test";
import assert from "node:assert/strict";

import {
  UNKNOWN_DISPOSITION,
  dispositionBadges,
  dispositionText,
} from "./disposition.mjs";

// The shape the backend actually emits (app/engine.py::_evidence_dispositions).
const backendRow = {
  source_record_id: "OPS-101",
  codes: ["COUNTED_SUPPORT", "EXACT_SUBSTRING_VERIFIED"],
};

test("backend rows render from codes, not disposition", () => {
  assert.equal(dispositionText(backendRow), "COUNTED_SUPPORT, EXACT_SUBSTRING_VERIFIED");
});

test("codes take precedence over disposition when both exist", () => {
  assert.equal(
    dispositionText({ source_record_id: "R", codes: ["A", "B"], disposition: "LEGACY" }),
    "A, B",
  );
});

test("legacy rows still render disposition with reason", () => {
  assert.equal(
    dispositionText({ source_record_id: "R", disposition: "EXCLUDED", reason: "PHRASE_CUE" }),
    "EXCLUDED (PHRASE_CUE)",
  );
});

test("backend rows with a reason keep the reason", () => {
  assert.equal(
    dispositionText({ source_record_id: "R", codes: ["DISPUTED"], reason: "CHALLENGED" }),
    "DISPUTED (CHALLENGED)",
  );
});

test("an empty codes array is not treated as text", () => {
  assert.equal(dispositionText({ source_record_id: "R", codes: [] }), UNKNOWN_DISPOSITION);
});

test("missing every field is UNKNOWN, never undefined", () => {
  for (const row of [{ source_record_id: "R" }, {}, null, undefined, { codes: null }]) {
    const text = dispositionText(row);
    assert.equal(typeof text, "string");
    assert.ok(text.length > 0);
  }
  assert.equal(dispositionText({}), UNKNOWN_DISPOSITION);
  assert.equal(dispositionText(null), UNKNOWN_DISPOSITION);
});

test("an unknown row keeps its reason, matching the patch", () => {
  assert.equal(
    dispositionText({ source_record_id: "R", reason: "NO_RULE" }),
    `${UNKNOWN_DISPOSITION} (NO_RULE)`,
  );
});

test("non-string codes entries are dropped rather than stringified", () => {
  assert.equal(
    dispositionText({ source_record_id: "R", codes: ["OK", 7, null, ""] }),
    "OK",
  );
});

test("a bare string row renders verbatim (the union allows it)", () => {
  assert.equal(dispositionText("COUNTED_SUPPORT"), "COUNTED_SUPPORT");
  assert.equal(dispositionText(""), UNKNOWN_DISPOSITION);
});

test("badges keep the record id as key and fall back to EV-n", () => {
  const badges = dispositionBadges([
    backendRow,
    { record_id: "OPS-102", codes: ["X"] },
    { codes: ["Y"] },
  ]);
  assert.deepEqual(badges.map((b) => b.key), ["OPS-101", "OPS-102", "EV-3"]);
  assert.deepEqual(badges.map((b) => b.value), [
    "COUNTED_SUPPORT, EXACT_SUBSTRING_VERIFIED",
    "X",
    "Y",
  ]);
});

test("the legacy map shape is still rendered", () => {
  const badges = dispositionBadges({
    "REC-101": "COUNTED_SUPPORTS (EXACT_SUBSTRING_VERIFIED)",
  });
  assert.deepEqual(badges, [
    { key: "REC-101", value: "COUNTED_SUPPORTS (EXACT_SUBSTRING_VERIFIED)" },
  ]);
});

test("undefined dispositions produce no badges", () => {
  assert.deepEqual(dispositionBadges(undefined), []);
  assert.deepEqual(dispositionBadges(null), []);
});

test("a malformed container yields no badges instead of throwing", () => {
  // Neither declared shape; the shipped code would iterate character indices.
  assert.deepEqual(dispositionBadges("COUNTED_SUPPORT"), []);
  assert.deepEqual(dispositionBadges(42), []);
  assert.deepEqual(dispositionBadges([]), []);
});

test("rendering a badge never throws on any backend row", () => {
  const rows = [
    backendRow,
    { source_record_id: "R", codes: [] },
    { source_record_id: "R", disposition: "DISPUTED" },
    { source_record_id: "R", codes: ["EXCLUDED_UNVERIFIED"] },
    {},
    null,
  ];
  for (const badge of dispositionBadges(rows)) {
    assert.equal(typeof badge.key, "string");
    assert.equal(typeof badge.value, "string");
    // This is the exact call that throws in the unpatched app.
    assert.doesNotThrow(() => badge.value.includes("DISPUTED"));
    assert.doesNotThrow(() => badge.value.includes("EXCLUDED"));
  }
});
