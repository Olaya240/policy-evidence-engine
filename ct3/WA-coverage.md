# WA — direction-aware coverage flags

## Mechanism, confirmed by reading

`backend/app/evidence_coverage.py`:

- `:124` `relevant = [item for item in evidence if item.semantic_relation in definition["relations"]]`
- every PRIMARY definition declares `"relations": (Stance.SUPPORTS, Stance.CONTRADICTS)`
- `:135` `fresh_contradiction = [...]` — so the fresh accepted set genuinely contains
  refuting records
- `:141` `covered = bool(fresh_accepted)` for PRIMARY roles

So a category whose only fresh accepted record contradicts the hypothesis is
reported `covered_by_fresh_accepted: true` and `coverage_state`-equivalent
COVERED. The CORROBORATION definitions declare `"relations": (Stance.SUPPORTS,)`,
so they cannot be reached by a contradiction at all; the defect is PRIMARY-only.

## What changed

Additive only, at `:149`–`:160` and in the emitted category dict:

| key | value |
|---|---|
| `covered_by_fresh_support` | `bool(fresh_support)` |
| `covered_by_fresh_contradiction` | `bool(fresh_contradiction)` |
| `direction` | `FOR` / `AGAINST` / `CONTESTED` / `NONE` |

`covered_by_fresh_accepted`, `non_independent`, `coverage_state` and every
existing id list are untouched. `advisory_missing_evidence` already had a
contradiction-only prompt branch, so prompts are unchanged.

## Can COVERED still be reached by a contradiction-only set?

Yes — deliberately. Changing that boolean changes the meaning of a field the
dashboard and the tests already read, and the coordinator did not authorise it.
The truthful signal now travels beside it: `direction: "AGAINST"` with
`covered_by_fresh_support: false`. A consumer that wants "covered *and* pointing
the right way" must read `covered_by_fresh_support`, not `covered_by_fresh_accepted`.

## Tests

`backend/tests/test_coverage_direction.py` — 10 cases: contradiction-only
(`AGAINST`, and the legacy boolean still true so the behaviour is pinned rather
than silently changed), support-only (`FOR`), both (`CONTESTED`), empty
(`NONE`), unverified, stale, disputed, neutral, corroboration needs two groups,
corroboration ignores contradictions, plus a key-shape regression.

## Memory

`local_memory__memory_store` **is** bound to this worker session — an earlier line in
the conversation of this slice claimed otherwise and was wrong. Stored:

- `policy-evidence-engine evidence_coverage` · `EMITS_DIRECTION` — the three new keys.
- `policy-evidence-engine evidence_coverage` · `PRESERVES_COVERED` — COVERED still
  reachable from a contradiction-only set; `direction` is the only truthful signal added.

## Not verified

No terminal in this session, so nothing here was executed. Two assumptions are
unchecked: that `Evidence` accepts `semantic_relation=` as a constructor keyword,
and that `HYPOTHESES` still contains `CHECKLIST_UNAVAILABLE` with category id
`checklist_access_context`. Both were inferred from the module under edit; the
coordinator should run `pytest tests/test_coverage_direction.py`.
