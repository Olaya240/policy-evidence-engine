/**
 * Executable model of `renderEvidenceDispositions` + `dispositionText` from
 * `frontend/src/App.tsx` (branch frontend-audit-studio, commit bb7a0a8), as
 * patched by `ct3/frontend-disposition.patch`.
 *
 * The patch was only typechecked, so this module exists to run the logic in
 * node:assert without React. It is a PARALLEL implementation, transcribed from
 * the patch and the 20 lines it modifies — not an import of the app. A passing
 * test here proves the logic; it does not prove the app renders.
 *
 * Why this matters at all: the backend emits each row as
 * `{ source_record_id, codes: string[] }` (`app/engine.py::_evidence_dispositions`),
 * while the shipped renderer reads `item.disposition`, which is `undefined` on
 * every backend row. `App.tsx:1003` then calls `.includes` on it, which throws
 * during render.
 */

export const UNKNOWN_DISPOSITION = "UNKNOWN_DISPOSITION";

const isNonEmptyString = (value) => typeof value === "string" && value.length > 0;

/**
 * Display text for one array-shaped disposition row.
 *
 * Precedence matches the patch exactly: `codes` joined > `disposition` >
 * UNKNOWN, with `reason` appended in parentheses when present — including on
 * the unknown case, which is what the patch does.
 */
export function dispositionText(row) {
  if (row === null || row === undefined) return UNKNOWN_DISPOSITION;
  // The union type allows `Record<string, string>`, so a bare string can reach
  // a row position. Rendering it verbatim is the only non-lossy choice.
  if (typeof row === "string") return isNonEmptyString(row) ? row : UNKNOWN_DISPOSITION;
  if (typeof row !== "object") return UNKNOWN_DISPOSITION;

  const codes = Array.isArray(row.codes) ? row.codes.filter(isNonEmptyString) : [];
  const base = codes.length > 0
    ? codes.join(", ")
    : (isNonEmptyString(row.disposition) ? row.disposition : "");

  const text = base.length > 0 ? base : UNKNOWN_DISPOSITION;
  return isNonEmptyString(row.reason) ? `${text} (${row.reason})` : text;
}

function dispositionKey(row, index) {
  if (row && typeof row === "object") {
    if (isNonEmptyString(row.source_record_id)) return row.source_record_id;
    if (isNonEmptyString(row.record_id)) return row.record_id;
  }
  return `EV-${index + 1}`;
}

/**
 * `[{ key, value }]`, matching `renderEvidenceDispositions`.
 *
 * `undefined` and `null` give `[]`; an array is mapped per row; any other
 * object is treated as the legacy `Record<string, string>` map. A bare string
 * is not one of the two declared shapes, so it yields `[]` rather than
 * `Object.entries` of its character indices, which is what the shipped code
 * would silently do.
 */
export function dispositionBadges(rows) {
  if (rows === null || rows === undefined) return [];

  if (Array.isArray(rows)) {
    return rows.map((row, index) => ({
      key: dispositionKey(row, index),
      value: dispositionText(row),
    }));
  }

  if (typeof rows === "object") {
    return Object.entries(rows).map(([key, value]) => ({
      key,
      value: typeof value === "string" ? value : JSON.stringify(value),
    }));
  }

  return [];
}
