# Backend grade — what was measured, and the weighting that turns it into a letter

Method: every percentage below is a ratio over a denominator this file names, produced by a
command run today on `/home/alex/policy-evidence-fix/backend` with
`/home/alex/policy-evidence-latest/.venv/bin/python`. Where a ratio rests on a small
denominator, the denominator is printed next to it, because 2/3 and 240/360 are not the same
claim.

Suite at time of measurement: **1883 passed, 0 failed, 0 xfailed** in 35.8 s.

## The taxonomy

| # | Dimension | Measurement | Value | Denominator | Weight |
|---|---|---|---|---|---|
| 1 | Control-removal sensitivity | mutated copies of 11 safety controls, full suite each; kill = a *test failure* on the mutated copy, with an unmutated control run green first | **100.0%** (11/11) | 11 mutations | 25% |
| 2 | Hostile-input containment | executed probes across 13 batches, plus defects found during probing and whether each was fixed with a failing-first test | **100.0%** (103 assertions pass, 0 fail; 5 defects found, 5 fixed) | 103 probes / 5 defects | 20% |
| 3 | Threat-model proof coverage | rows in `THREAT-MODEL.md` whose status is a proven variant vs rows total | **92.3%** (24/26) | 26 rows | 15% |
| 4 | Semantic decision precision | committed verdicts (SUPPORTS/CONTRADICTS issued) that match a careful reading, on 12 adversarial-but-grammatical sentences | **66.7%** (2/3 committed; 9 abstain) | 3 committed verdicts | 15% |
| 5 | Decision traceability | registered decisions with a reversing test vs registered decisions | **92.9%** (13/14) | 14 decisions | 10% |
| 6 | Statement coverage | executable statements hit, `app/*.py`, measured with `sys.monitoring` LINE events over the full suite | **91.8%** (2428/2645) | 2645 statements | 10% |
| 7 | Enforced limits | documented bounds confirmed by an executed probe vs bounds claimed | **100.0%** (7/7) | 7 bounds | 5% |

Weighted sum: `0.25×100.0 + 0.20×100.0 + 0.15×92.3 + 0.15×66.7 + 0.10×92.9 + 0.10×91.8 + 0.05×100.0 = 92.32`
(recomputed by command: `round(0.25*100+0.20*100+0.15*92.3+0.15*66.7+0.10*92.9+0.10*91.8+0.05*100, 2) → 92.32`).

**Composite: 92.3%.**

## Bands, and where this lands

Stated before the number was computed, so the band cannot be chosen to fit:

| Band | Range |
|---|---|
| A | ≥ 90 |
| A− | 87.0 – 89.9 |
| B+ | 83.0 – 86.9 |
| B | 80.0 – 82.9 |
| C+ | 77.0 – 79.9 |
| C | 70.0 – 76.9 |
| D | 60.0 – 69.9 |
| F | < 60 |

**Result: A (92.3)**, with one dimension that would not pass on its own: semantic decision
precision at 66.7%, a C in isolation. The composite does not hide that — the row is visible and
weighted 15%.

Sensitivity, because the weighting is the arguable part: for a *verdict* system the semantic
layer is the product, so move 10 points of weight from control-removal sensitivity (25 → 15)
to semantic precision (15 → 25) and the composite becomes `15 + 20 + 13.845 + 16.675 + 9.29 +
9.18 + 5 = 88.99` → **A− (89.0)**. Two defensible weightings, two adjacent bands; both are
printed so the choice is visible rather than buried.

## What the numbers mean, in the order they matter

- **The suite is sensitive, not merely green.** Eleven controls were deleted in throwaway
  copies and every deletion broke a test: source-group normalisation, the two-independent-groups
  rule, the proposal cap, the request byte cap, rate limiting, the restricted filter on reads,
  the restricted filter on challenges, the negated-frame rule, quantifier scoping, fixture
  citation validation, and quote grounding. `mutation-results.json` holds the per-mutation
  detail. This is the dimension a green suite cannot fake.
- **Coverage is 91.8% and is the weakest *number* that looks strong.** A line executed is not a
  behaviour checked. It is in the table at 10% weight for that reason, and it does not
  contribute evidence to any other row.
- **The semantic layer is the real weakness, and the measurement is thin.** 3 committed
  verdicts out of 12 sentences: 2 right, 1 questionable ("No evidence the checklist was
  available" certifies CONTRADICTS when a reader would abstain). One row swings this figure by
  33 points, so treat 66.7% as "the guard commits rarely and is not reliably right when it
  does", not as a precise accuracy estimate.
- **24 of 26 threat rows are proven**, one is a declared posture (no authentication, by product
  decision), one is open because it needs a recorded live vendor response. Nothing in this
  repository can close that last row.
- **7/7 enforced limits were confirmed by execution**, not by reading: 16 KiB request budget,
  43-proposal ceiling (44 refused), 600 req/min per peer, `Retry-After ≥ 1`, two-group
  threshold, restricted-record exclusion from both read and challenge, `MAX_PROPOSALS` refusal
  distinct from malformed output.

## What is not measured, and would move the grade

1. **The live provider path has never run.** Everything above is against the mock. A single
   recorded vendor response closes decision 7 and threat row B5/B6; until then the real path is
   ungraded, not graded well.
2. **Mutation breadth is 11 targeted controls, not an exhaustive sweep.** A 100% kill rate over
   11 chosen controls says the chosen controls are pinned; it does not say every line is.
3. **No load or concurrency testing beyond six threads and one client.** Throughput, latency
   under load, and multi-writer behaviour are unmeasured.
4. **The semantics corpus is 12 sentences.** A real paraphrase benchmark (hundreds of rows with
   agreed readings) would turn 66.7% into a number worth quoting.

Re-weighting is legitimate and shown above: the same measurements land at 92.3 (A) or 89.0
(A−) depending on how much the semantic layer is worth. The percentages are measurements; the
letter is a weighting decision, printed so it can be disagreed with.

## Delta after the four workstreams (2 Nov, same day)

Re-measured after Document Ingestion, Semantic Guard, Dependency Graph and Confidence
Reliability landed. Suite: **1959 passed, 0 failed, 0 xfailed** (was 1883; +76 tests: ingest 6,
verb-negation corpus 45, dependency graph 11, confidence reliability 14).

| Dimension | Before | After | Why it moved |
|---|---|---|---|
| Statement coverage | 91.8% (2428/2645) | **91.4% (2552/2792)** | Six new modules of surface to cover; `ingest.py` 85.0%, `dependency_graph.py` 84.6% are the thin spots |
| Decision traceability | 92.9% (13/14) | **94.4% (17/18)** | Rows 15–17 pinned to tests; row 18 registered as open because the confidence finding is real |
| Semantic decision precision | 66.7% (2/3 committed) | **not re-measured** | The 12-sentence table now has 4 committed rows, not 3; a like-for-like figure needs the corpus re-run and re-read |
| Threat proof coverage | 92.3% (24/26) | unchanged | No threat row was closed; the live-vendor row is still the only open one |

Composite does not move materially (−0.04 coverage contribution, +0.15 traceability
contribution). **A (92.3) stands**, with the same caveat: the semantic layer is the weakest
dimension and its denominator is small.
