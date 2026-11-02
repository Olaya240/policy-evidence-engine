# Worker 6 — executable model of the disposition renderer

## Files created

- `ct3/frontend/disposition.mjs` — `dispositionText(row)`, `dispositionBadges(rows)`.
- `ct3/frontend/disposition.test.mjs` — 13 dependency-free tests (`node --test`).
- `ct3/W6-frontend-harness.md` — this report.

No source file edited; the app is untouched.

## What this is, precisely

A **parallel implementation**, transcribed from `ct3/frontend-disposition.patch` and the
twenty lines it replaces in `/home/alex/policy-evidence-latest/frontend/src/App.tsx`
(`renderEvidenceDispositions` at `:449`, the pill render at `:994-1003`). It is not an
import of the component. A green run proves the logic; it does not prove the app renders,
and it cannot, because the patch is still unapplied.

## Semantics reproduced

Read from the patch, not assumed:

- array rows: value = `codes.join(", ")` when non-empty, else `disposition`, else
  `UNKNOWN_DISPOSITION`; `reason` appended as ` (reason)` **including** on the unknown
  case, which is what the patch does.
- key = `source_record_id` → `record_id` → `EV-{index+1}`.
- the legacy `Record<string,string>` shape is still rendered via `Object.entries`.
- falsy `dispositions` → `[]`.

## Two deliberate deviations, both documented in code

1. **Non-string `codes` entries are dropped.** The patch does `codes.join(", ")`, which
   would render `"OK, 7, , "` for `["OK", 7, null, ""]`. The backend only emits strings,
   so this is a hardening choice, not a behaviour the app needs.
2. **A bare string passed as the *container*** yields `[]`. The shipped code would take
   `Object.entries("COUNTED_SUPPORT")` and render sixteen single-character badges. A row
   that is a string is rendered verbatim, because the union type permits that.

Both are places where this model is stricter than the patch. If the coordinator wants
byte-for-byte equivalence instead, these are the two tests to change.

## Unrun / unverified

No terminal in this session, so `node --test ct3/frontend/disposition.test.mjs` has not
been executed by me, and neither has the patch against a real build. The one thing most
likely to differ: whether the patch's `dispositionText` signature accepts a `reason` on a
row whose `codes` is an empty array — the patch's ternary treats `[]` as falsy for `base`
via `codes.length > 0`, which I mirrored.

Memory: no `local_memory__*` tool is bound to this worker session (the available tools are
`read_files`, `str_replace`, `write_file`, `code_search`, `glob`, `list_directory`). I did
not attempt a call and am not claiming a write, because a refused or absent call is not a
stored fact.

## Memory candidate for the coordinator to store verbatim

```
s: policy-evidence-engine frontend disposition harness
p: MIRRORS
source: project:verification
o: a parallel transcription of the patched renderer, not an import; a green
   node:test run proves the logic, not that the app renders
```

Durable because it prevents a future reader from treating a passing harness as evidence
that the frontend works — the distinction the whole slice turns on.
