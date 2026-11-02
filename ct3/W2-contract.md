# W2 — explanation_trace contract: does the frontend agree with the backend?

**Question.** Does any frontend read `explanation_trace.evidence_dispositions`, and does its shape match what the engine emits?

**Verdict.** Two branches each hold half of the contract and **neither has ever run against the other**. On the branch under review (`8c1b808`) the trace has **no consumer at all**. The only consumer that exists — `origin/frontend-audit-studio` (`bb7a0a8`, checked out at `/home/alex/policy-evidence-latest`) — expects a different shape, and against this backend it does not degrade to a blank badge: it throws.

---

## 1. Backend emits (Read)

`backend/app/engine.py:234`

```python
dispositions.append({"source_record_id": item.source_record_id, "codes": codes})
```

Two keys only. `codes` is a `list[str]` drawn from the nine documented values in `evidence_disposition_semantics` (`engine.py:298-308`: `COUNTED_SUPPORT`, `COUNTED_CONTRADICTION`, `NEUTRAL_NOT_DIRECTIONAL`, `UNVERIFIED_EXCLUDED`, `STALE_HISTORICAL_CONTEXT`, `STALE_NON_DIRECTIONAL_CONTEXT`, `DISPUTED_REVIEW_REQUIRED`, `DEPENDENT_SOURCE_GROUP`, `UNCLASSIFIED_REVIEW_REQUIRED`). Emitted unconditionally at `engine.py:309`, one row per evidence item, so **every** claim with evidence has rows.

`Claim.explanation_trace: Optional[dict]` (`backend/app/models.py:94`) — untyped, so no schema enforcement on either side of the wire.

## 2. Consumers that exist

### 2a. Branch under review — none (Read)

`/home/alex/policy-evidence-fix/frontend/src/` contains `App.tsx`, `main.tsx`, `PolicyDemoPage.tsx`, `styles.css`. Searching all of `frontend/` for `evidence_dispositions|explanation_trace|ExplanationTrace|disposition` returns **zero matches**. Its `type Claim` (`App.tsx:7`) has no trace field. Nothing on this branch can break from the trace shape, because nothing reads it.

### 2b. `origin/frontend-audit-studio` — the only consumer, and it mismatches (Read)

The branch exists. I could not run `git branch -a` (no terminal), so this is established from the ref files the coordinator can re-check in one command:

- `.git/refs/remotes/origin/frontend-audit-studio` → `bb7a0a8fd71cc7633ddefca4b5487f2cdf8c48dc`
- `/home/alex/policy-evidence-latest/HEAD` is detached at `bb7a0a8` (reported by `git worktree list` earlier in the session)

So "the sibling worktree could not be found" was a false negative: the worktree is `/home/alex/policy-evidence-latest` and it is that branch.

Its type, `frontend/src/App.tsx:12-19`:

```ts
type ExplanationTrace = {
  status_rule_id?: string;
  confidence_rule_id?: string;
  evidence_dispositions?: Record<string, string> | Array<{ source_record_id?: string; record_id?: string; disposition: string; reason?: string }>;
  rules_triggered?: ExplanationTraceRule[];
  notes?: string[];
};
```

Its renderer, `App.tsx:449-466`:

```ts
return dispositions.map((item, idx) => ({
  key: item.source_record_id || item.record_id || `EV-${idx + 1}`,
  value: item.reason ? `${item.disposition} (${item.reason})` : item.disposition,
}));
```

Backend rows have `source_record_id` (so `key` survives) and **no** `disposition` and **no** `reason`, so `value` is `undefined`.

## 3. Correction to the earlier claim (Inferred — not run)

The prior worker said the panel "silently loses one badge per record rather than failing loudly". That is wrong in the direction that matters. The consumer at `App.tsx:1002` is:

```tsx
tone={d.value.includes("DISPUTED") || d.value.includes("EXCLUDED") ? "orange" : "green"}
```

`d.value` is `undefined`, so `.includes` throws `TypeError` **during render**, which unmounts the tree rather than dropping a badge. TypeScript will not catch it either: the array branch declares `disposition: string` (required), so `item.disposition` type-checks as `string` and the runtime `undefined` is invisible to the compiler.

This is predicted from the two artifacts above; I have no terminal and did not execute it. The falsifier is one line in a browser console against the merged build.

## 4. Why it has never been observed: the UI has never seen a real trace (Read)

At `bb7a0a8`, `backend/app/models.py:57-69` — `class Claim` has **no** `explanation_trace` field. So the wire never carried one, and every trace the audit UI has ever displayed came from the hard-coded `FALLBACK_INVESTIGATION` at `App.tsx:167+`, whose dispositions are the `Record<string,string>` arm (`{"REC-101": "COUNTED_SUPPORTS (EXACT_SUBSTRING_VERIFIED)"}`) and whose rule ids are strings the engine never emits (`STATUS_SUPPORTED_BY_ACCEPTED_EVIDENCE`, `CONF_BASE_PLUS_CORROBORATION`).

A second fabricated path survives the merge only by accident: `App.tsx:1026` renders `STATUS_RULE: DERIVED_${selected.status}` when there is no trace, under an unconditional `DETERMINISTIC ENGINE AUTHORITY` pill (`App.tsx:972`). On the merged system every claim carries a trace, so that branch becomes dead — it is not *fixed*, just unreachable.

## 5. Minimal fixes

**Source of truth:** the backend. `codes` is the engine's own adjudication, documented key-by-key in the trace, and it is what the audit record should preserve. The frontend union is legacy demo scaffolding.

**Option A — frontend only, ~8 lines (recommended).** In `renderEvidenceDispositions`, make the array arm shape-tolerant and null-safe:

```ts
return dispositions.map((item, idx) => {
  const key = item.source_record_id || item.record_id || `EV-${idx + 1}`;
  const value = "codes" in item && Array.isArray(item.codes)
    ? item.codes.join(", ")
    : item.disposition ?? "UNCLASSIFIED_REVIEW_REQUIRED";
  return { key, value: String(value) };
});
```

and widen `disposition` to optional plus `codes?: string[]`. One file, no backend change, no test churn, renders both the old demo data and the new trace.

**Option B — backend only, 1 line (rejected).** Adding `"disposition": ", ".join(codes)` to `engine.py:234` fixes the display but (i) denormalises the audit record so `codes` and `disposition` can disagree, (ii) leaves the frontend's non-null `disposition` requirement in place so the next engine change re-breaks it, and (iii) breaks existing assertions — `backend/tests/test_explanation_trace.py:129` and `:151` compare `evidence_dispositions` **lists of dicts** for exact equality, so the added key fails both.

**Option C — cleanup after A (not this turn).** Delete the `Record<string,string>` arm and the `record_id`/`reason` alternatives once the fallback demo data is gone; then the type can be the backend shape verbatim.

## 6. Out of scope, reported not acted on

- `frontend/src/App.tsx:147` (branch under review) prints `Math.round(selected.confidence * 100)}% confidence · review estimate`, while the backend declares `confidence_kind: "FIXED_ENGINE_HEURISTIC_NOT_CALIBRATED_PROBABILITY"` (`engine.py:299`). A fixed heuristic rendered as a percentage is the same class of defect as the 0.68 collision, and this is a live consumer on the feature branch.
- `rules_triggered` and `notes` are in the frontend type and rendered (`App.tsx:1013`), and are never emitted by this engine.

## 7. Unknown

- Whether the two branches are intended to merge, and in which order — that determines whether §3 is a today-problem or a next-merge problem.
- No TypeScript build and no browser run. §3's crash is inferred, not observed.
