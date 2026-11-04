# Stale references to the v1 decision numbers

Scope: `/home/alex/policy-evidence-fix`, searched 2026-11-01. Rule set is now
`story-connect-status-v2`.

Caveat that changes how to read the line numbers: sibling workers are editing
`backend/app/decision_table.py`, `backend/app/models.py` and `backend/app/engine.py`
in parallel right now. The quotes below were read from the tree in that state,
and `decision_table.py` already contains a threshold-policy block
(`min_support_groups`, and a comment at lines 79-81 about a stricter
"any contradiction keeps PARTIAL" variant) that did not exist when the
coordinator last read it.

## (a) Live code that still tells the old story

**a1. `frontend/src/App.tsx` — the number is rendered without its direction.**

- `App.tsx:7` — the client type is `confidence: number`; there is no
  `evidence_score` and no `evidence_direction`, although
  `backend/app/models.py` now carries both (`:94` onward).
- `App.tsx:147` — `<span>{Math.round(selected.confidence * 100)}% confidence · review estimate</span>`

Why this is a defect now and was only a smell before: `confidence` is
`abs(score)`. A claim with one source against it computes `score = -0.5` and
`confidence = 0.5`, so the panel reads "50% confidence · review estimate" for a
refuted claim. Under v1 the same sentence read "58%", which was at least a
distinct number from the 55% of a single supporting source. The magnitude is no
longer comparable across directions and the UI gives the reader no sign.

This is the only live consumer I found on this branch. Note that the trace
consumer (the panel that crashed on `evidence_dispositions`) lives on
`frontend-audit-studio`, not here, so it is outside this search.

## (b) Test expectations that were already migrated — fine

`grep` for `FIXED_|story-connect-status-v1` outside `ct3/` returns **zero**
matches (search run with `-g !ct3/** -g !*.json -g !*.lock`). So no test still
pins an old rule id. Confirmed in passing:

- `tests/test_explanation_trace.py` parametrisation now expects
  `STATUS.V2_*` / `CONFIDENCE.V2_*`, `2 / 3`, `0.5`, `0.0`.
- `tests/test_engine.py` single-source expectations are `0.5`.
- `tests/test_api.py` uses `SIGNED_EVIDENCE_MARGIN_NOT_CALIBRATED_PROBABILITY`.

## (c) Documentation and comments that describe history

None of these are wrong today, but a reader arriving cold can take the first
one as current. Each needs a "v1" label, not a deletion.

- `backend/app/decision_table.py:4-5` — "the shipped table assigns one
  non-negative number … `0.68` is both SUPPORTED and CONTRADICTED". Accurate and
  explicitly about the table it replaces, but it is the first paragraph a reader
  sees; suggest prefixing "Before v2," so it cannot be mistaken for the current
  behaviour.
- `ct3/W2-contract.md:101`, `ct3/W3-tests.md:55-68`, `ct3/WC-critique.md:262-287`
  — these quote `FIXED_0_68_*`, `FIXED_0_52`, `FIXED_ENGINE_HEURISTIC_NOT_CALIBRATED_PROBABILITY`.
  They are pre-migration evidence files. Anyone grepping the repo for the old ids
  will hit these three first, which is exactly the "reviewer believes 0.68 is
  still current" risk. Suggest a one-line header in each:
  "Written before the v2 migration; every rule id below is v1 history."
- `ct3/DecisionTable.v:55` — "v1 with one stale accepted support present:
  STATUS.FRESH_WITH_STALE_CONTEXT". Correct, already says v1.
- `docs/project/FRONTEND_DOCUMENTATION.md:14` — "The handover UI describes
  confidence as a review estimate; it is not a calibrated probability." Still
  true, now incomplete: the number is a *signed-margin magnitude* and the
  direction is a separate field. One clause would stop a reader assuming
  `confidence` alone can be compared across claims.

## (d) Similar-looking numbers that are not stale

- `frontend/package-lock.json` — `0.25.12` is the esbuild version. Unrelated.
- `backend/tests/test_api.py:112` — `"confidence": 0.68` inside
  `investigation-legacy`, a deliberately stored v1 payload. Correct as a
  round-trip fixture; a `# v1 record, retained on purpose` comment would stop the
  next audit re-flagging it.
- `backend/tests/test_engine.py:494` — `"confidence": 0.55` inside
  `_claim_with_challenge_evidence`, same story: a legacy claim shape, not an
  expectation of the current engine.
- `backend/POLICY_*` documents — "confidence intervals" and
  "semantic-support `SUPPORTED`" belong to the evaluation protocol vocabulary,
  not to `Claim.status`.
- `backend/app/provider_safety.py:557` — a prompt string listing "claim status,
  confidence, dependencies"; still accurate, no rule ids in it.

## Recommended order of work

1. (a1) `App.tsx`: add `evidence_score` / `evidence_direction` to the type and
   render direction with the number, or hide the percentage when direction is
   `AGAINST`. This is the only place a user is currently misled.
2. (c) Label the three `ct3/` evidence files and tighten the one doc sentence.
3. (d) Comment the two legacy fixtures so a later search does not re-litigate them.

Nothing here was edited: this slice is read-only.
