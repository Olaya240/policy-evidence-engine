# W3 — Claim carries the sign

**File edited:** `backend/app/engine.py` (only file touched).

## Changes

1. **New helper `_score_direction(score: float) -> str`**, inserted immediately before
   `def _build_explanation_trace(`. Returns `FOR` / `AGAINST` / `NONE` from the sign. A module
   helper rather than a second inline ternary, so the trace and the claim cannot disagree about
   the direction of the same number.

2. **`_build_explanation_trace`** — the three-way ternary under the `"evidence_direction"` trace
   key is replaced with `_score_direction(decision.evidence_score)`. The trace key set is
   unchanged: same names, same values, one implementation.

3. **`_claim`** — the `Claim(...)` construction now also passes
   `evidence_score=status_decision.evidence_score` and
   `evidence_direction=_score_direction(status_decision.evidence_score)`, placed directly after
   `confidence` / before `uncertainty`. `confidence` still receives
   `status_decision.confidence`, which is `abs(score)` and therefore still a magnitude.

4. **`challenge`** — the final `raw.update(...)` (the dict path; this function does not build a
   `Claim` object) gains the same two keys next to `confidence`. A challenged claim is therefore
   signed the same way as a freshly investigated one.

No other call site constructs a claim: `investigate` and `assess_hypothesis` both return
`self._claim(...)`, so they inherit the change.

## Left open / worth checking

- **Assumes worker 2's model fields exist** with exactly the names `evidence_score` and
  `evidence_direction`. I did not read `models.py` (not my slice) and could not import anything,
  so if the field names or their optionality differ, `Claim(...)` will raise a validation error on
  every investigation. That is the single most likely failure.
- Claims loaded from older rows have neither field. Nothing in this file reads them back —
  `challenge` copies `current` and overwrites via `raw.update`, so a legacy dict is upgraded on its
  next revision and a legacy claim is never dereferenced. If a downstream consumer does
  `claim["evidence_score"]` on an old row it will now get `None` (worker 2's default), not a crash
  from this file.
- Not run: no pytest, no import, no typecheck in this session, so none of the above is observed.

## Memory

No `local_memory_*` tool is bound to this worker session — my tool list is `read_files`,
`str_replace`, `write_file`, `code_search`, `glob`, `list_directory`. I am therefore not claiming
a memory write. The durable fact is recorded here instead: **`policy-evidence-engine Claim`
`CARRIES_SIGN` — `evidence_score` and `evidence_direction`, populated in `_claim` and in
`challenge`'s `raw.update`, from one `_score_direction` helper shared with the trace.**
