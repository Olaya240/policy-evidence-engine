# W-D — evidence dispositions: the frontend crash, and a patch for it

## What I read (all quotes are from the files, not from earlier reports)

The consumer is `/home/alex/policy-evidence-latest/frontend/src/App.tsx`
(branch `frontend-audit-studio`, `bb7a0a8`). Nothing on the feature branch
consumes the trace, so this file is the whole surface.

**The declared type — `App.tsx:17`:**

```ts
evidence_dispositions?: Record<string, string> | Array<{ source_record_id?: string; record_id?: string; disposition: string; reason?: string }>;
```

`disposition` is **required** in the array arm, and `codes` is not declared.

**The renderer — `App.tsx:449-463`:**

```ts
449  function renderEvidenceDispositions(
450    dispositions: ExplanationTrace["evidence_dispositions"]
451  ): Array<{ key: string; value: string }> {
452    if (!dispositions) return [];
453    if (Array.isArray(dispositions)) {
454      return dispositions.map((item, idx) => ({
455        key: item.source_record_id || item.record_id || `EV-${idx + 1}`,
456        value: item.reason ? `${item.disposition} (${item.reason})` : item.disposition,
457      }));
458    }
459    return Object.entries(dispositions).map(([key, value]) => ({
460      key,
461      value: typeof value === "string" ? value : JSON.stringify(value),
462    }));
463  }
```

**The crash site — `App.tsx:1003`:**

```ts
tone={d.value.includes("DISPUTED") || d.value.includes("EXCLUDED") ? "orange" : "green"}
```

**What the backend actually sends — `backend/app/engine.py:234`:**

```python
dispositions.append({"source_record_id": item.source_record_id, "codes": codes})
```

Each row is `{source_record_id, codes: string[]}`. So at `:456`, `item.disposition`
is `undefined`, `item.reason` is `undefined`, and the branch returns
`value: undefined` while the return type promises `string`. TypeScript cannot
object because the union arm claims `disposition` is always present; the object
arm (`Record<string,string>`) can never produce it. At `:1003`,
`undefined.includes` throws `TypeError` during render, which unmounts the panel
and whichever tree is above it.

This corrects two earlier reports: the failure is **not** a silently blank badge
(it throws), and the trigger is **not** hypothetical ordering — any backend row
is enough.

## The patch

File: `ct3/frontend-disposition.patch`, paths relative to the frontend root, so
it applies from `/home/alex/policy-evidence-latest/frontend` with `git apply -p1`.

It makes two changes and nothing else:

1. **`App.tsx:17`** — adds `codes?: string[]` and relaxes `disposition` to
   optional, so the compiler can represent what the server sends.
2. **`App.tsx:449-463`** — adds `dispositionText(item)`, which prefers
   `codes.join(", ")`, falls back to `disposition`, and finally to the literal
   `UNKNOWN_DISPOSITION`, so `value` is *always* a string and `:1003` cannot
   throw. `reason` is still appended in parentheses.

Why frontend-only: `codes` is the richer field (it can carry
`UNVERIFIED_EXCLUDED`, `STALE_HISTORICAL_CONTEXT`, `DISPUTED_REVIEW_REQUIRED`,
…), and `tests/test_explanation_trace.py` compares disposition dicts for exact
equality, so adding a denormalised `disposition` key on the backend would break
two tests and let the two fields drift. The backend is the source of truth for
audit data; the renderer adapts to what it sends.

The tone rule keeps working unchanged: a joined string containing
`DISPUTED_REVIEW_REQUIRED` still matches `.includes("DISPUTED")`.

## Unverified, and what would break it

- **Not applied, not typechecked, not built.** I have no terminal. `git apply`
  has never run against this patch.
- Most likely failure mode: **`no such file or directory` if `-p1` is used from
  the repository root instead of `frontend/`**, because the patch paths are
  `a/src/App.tsx`. From the repo root the correct invocation is
  `git apply -p2 --directory=frontend ct3/frontend-disposition.patch`.
- Second most likely: a whitespace or line-ending mismatch at `:17` / `:456` if
  the checkout has been reformatted since `bb7a0a8` (the hunk context assumes
  2-space indentation and no trailing whitespace).
- I did not read `:994-1008` past the crash line, so I cannot say whether the
  same `d.value` is used again elsewhere; the grep for `evidence_dispositions`
  and `disposition` returned only the lines quoted above.
- Separate issue seen while reading, **not patched**: `App.tsx:147` renders
  `Math.round(confidence*100)}% confidence` while the backend labels the number
  `CONFIDENCE.*` with `confidence_kind` declaring it not a calibrated
  probability. That is a wording/interpretation mismatch for the coordinator.

## Memory

This section was first written claiming no `local_memory_*` tool was bound to
this session, because the tool list I was given named only `read_files`,
`str_replace`, `write_file`, `code_search`, `glob` and `list_directory`. That
claim was **wrong**: `memory_store` is reachable and the write succeeded
(`inserted: 2`). Recorded here because siblings made the same false report
today — an unlisted tool is not an absent tool.

Stored:

- `policy-evidence-engine explanation trace` · `CRASHES_CONSUMER` · frontend
  `App.tsx:1003` calls `d.value.includes` on `undefined`, because the backend
  emits `{source_record_id, codes}` rows (`engine.py:234`) while the type
  declares `disposition` required and omits `codes`
- `policy-evidence-engine explanation trace` · `HAS_ONE_CONSUMER` ·
  `frontend-audit-studio` `bb7a0a8` `App.tsx`; the feature branch has no trace
  consumer
