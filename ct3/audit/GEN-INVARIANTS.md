# Generative architecture invariants

Status: **all four invariants hold on every generated corpus. No counterexample.**
File: `backend/tests/test_architecture_invariants_generative.py`
Owner of this file only; nothing under `app/` and no other test was touched.

The seed module `backend/tests/test_architecture_invariants.py` checks the four
architecture properties on one hand-written fixture. This module re-checks them
on seeded random corpora so a predicate cannot pass merely because the fixture
happens to suit it.

## How to run

```bash
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_architecture_invariants_generative.py
```

## Verbatim output (this run)

```text
........................................................................ [ 59%]
.................................................                        [100%]
121 passed in 0.47s
```

Exit status: `0`. 121 = 30 seeds × 4 invariants + 1 generator-coverage test.
Wall clock for the command including interpreter startup: 0.70 s (budget was ~15 s).

## Seed list (fixed, verbatim from the module)

```python
SEEDS = [
    0, 1, 2, 3, 5, 8, 11, 13, 17, 21,
    23, 29, 34, 41, 55, 68, 89, 111, 144, 177,
    233, 301, 377, 465, 610, 774, 987, 1234, 1597, 2584,
]
```

## What a generated corpus contains

Per seed, `random.Random(seed)` draws:

| Dimension | Draw |
|---|---|
| size | `0..12` records; seed `0` pins 0, seed `1` pins 12, the rest random |
| records | a sample of `POOL` (14 ids the mock provider maps to a stance), one text variant each |
| source groups | `1..4` names from `NIGHT-A/DAY-B/SWING-C/NIGHT-D`, plus one fixed group (`OPS-112` → `OPS-105`) |
| stance | derived by `mock_provider.assess_pair` from `(record id, hypothesis)` |
| review state | derived by the phrase-cue guard from the chosen text: cue match → ACCEPTED, mismatch or no cue → UNVERIFIED |
| staleness | fresh `0..88 d`, stale `91..800 d`, exact boundaries `90 d`/`91 d`, future, naive-tz, and exactly `clock` |
| disputes | only via `challenge` (invariant 3), never set directly |
| restricted | ~20 % of non-empty corpora carry `RESTRICTED-CANARY-001`; it never reaches the provider |

The clock is `2026-11-15T09:00Z + (seed % 23) days + a seeded minute offset`, and
is injected into the engine, so reproducibility is a property of the corpus, not
of wall-clock time.

## The four invariants and what each one actually compares

1. **Claim equals a fresh summary of its own evidence.**
   `_summarize_status_decision(Evidence.model_validate(e))` over the claim's own
   persisted rows must reproduce `status`, `confidence` and `evidence_score`.
2. **Same corpus, same clock, same claim.**
   Two independently constructed engines investigate the identical record list
   and must return equal claim lists (whole dicts, explanation traces included).
3. **A challenged claim equals its own reassessment.**
   `challenge` must increment `version`, must not rewrite any quote/source/stance,
   must mark a row disputed, and the result must equal a fresh summary of its own
   evidence *and* the table's label for it.
4. **Score bounds and table label.**
   `evidence_score ∈ [-1, 1]`, `confidence = |evidence_score| ∈ [0, 1]`, and
   `app.decision_table.decide` — fed support/contradiction/disputed group counts
   **recomputed independently in the test** from the persisted rows — must
   reproduce `status`, `evidence_score` and `evidence_direction`.

## Counterexample

**None.** No generated corpus broke any invariant, so there is nothing to keep as
a failing case. The failure path is nevertheless built for it: every check calls
`fail(seed, clock, records, …)`, which prints the seed, the clock, and the exact
record set (`id`, ISO timestamp, department, text, tags, source group, restricted)
as JSON, then the offending claim. The generator is never shrunk to make a failure
disappear; a breaking corpus would be frozen by its printed seed and records.

## Non-vacuity evidence

A green check that cannot fail is not a check, so each assertion path was driven
with a deliberately corrupted claim in a throwaway run (no repository edit):

```text
using seed 1 records 12 claim CHECKLIST_UNAVAILABLE evidence 7
inv1 confidence drift: FAILED as it must (Failed); corpus in message=True
inv4 status vs table: FAILED as it must (Failed); corpus in message=True
inv4 out-of-range score: FAILED as it must (Failed); corpus in message=True
inv4 confidence != |score|: FAILED as it must (Failed); corpus in message=True
inv2 non-determinism: FAILED as it must (Failed); corpus in message=True
inv3 reassessment drift: FAILED as it must (Failed); corpus in message=True
real challenge rows: 7 disputed: 1
```

## Coverage actually reached (observed on the committed seed list)

| Measure | Value |
|---|---|
| claims checked | 150 (30 seeds × 5 hypotheses) |
| corpus sizes | 0 ×3, 1 ×6, then 3..12; 12 ×3 |
| claim labels | INSUFFICIENT 116, PARTIAL 19, CONTRADICTED 13, SUPPORTED 2 |
| evidence rows by (stance, review state) | SUPPORTS/ACCEPTED 39, CONTRADICTS/ACCEPTED 24, NEUTRAL/ACCEPTED 5, SUPPORTS/UNVERIFIED 22, CONTRADICTS/UNVERIFIED 39, NEUTRAL/UNVERIFIED 149 |
| stale evidence rows | 104 (rows, so a record repeats across hypotheses) |
| challenged claims | 105 |
| challenged claims carrying disputed groups | 34 |
| groups holding both a disputed and an undisputed row | 1 |

The last row matters: it exercises the `disputed_support - support` subtraction
that `decide` relies on, where one group is one unit of independent evidence.

`test_the_generator_is_not_degenerate` fails if the draw ever stops producing
ACCEPTED and UNVERIFIED rows, a stale record, at least three labels, a zero score,
and at least one claim with no evidence — i.e. if the invariants would become
vacuous.

## What this does not cover

- **`challenge`'s unassessed-source path.** `MockProvider` proposes for every
  record it can assess, and `_claim` keeps every proposal, so no assessable record
  is ever outside a claim's evidence. That branch of `challenge` is unreachable
  through the provider boundary and is therefore not asserted here; only the
  matched-dependency path is. Reaching it would need a provider override that
  deliberately omits a record.
- **`SUPPORTED` is thin: 2 of 150 claims.** The pool gives every hypothesis a
  competing contradiction record, so the 3:1 margin the table needs for a decisive
  support label rarely appears (2 in 600 over seeds 0..119). Decisive labels are
  better covered by `tests/test_decision_table.py`; this module checks that
  whatever label is produced agrees with the table.
- **One provider, one semantic-guard setting.** No `assessment_overrides`,
  `assessment_sequences`, provider failures, or `semantic_guard=False` runs.
- **No concurrency, no HTTP layer, no persistence.** `investigate` and `challenge`
  are exercised in-process with injected records and an injected clock.
- **Restricted records** are drawn but, by construction, never reach the provider,
  so the invariants say nothing about redaction beyond that separation holding.

Measured, not inferred: the numbers above come from iterating `SEEDS` with the
module's own `generate`/`corpus` helpers in the same interpreter as the test run.
