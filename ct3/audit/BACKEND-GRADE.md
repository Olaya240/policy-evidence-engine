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
| Decision traceability | 92.9% (13/14) | **94.4% (17/18)** | Rows 15–17 pinned to tests and row 18 pinned as a *policy with a named cost*, so only row 7 (live vendor response) remains open |
| Semantic decision precision | 66.7% (2/3 committed) | **not re-measured** | The 12-sentence table now has 4 committed rows, not 3; a like-for-like figure needs the corpus re-run and re-read |
| Threat proof coverage | 92.3% (24/26) | unchanged | No threat row was closed; the live-vendor row is still the only open one |

Recomputed with the after-values: `0.25×100 + 0.20×100 + 0.15×92.3 + 0.15×66.7 + 0.10×94.4 +
0.10×91.4 + 0.05×100 = 92.25` → **A (92.3)** unchanged. (An earlier line in this section kept
the before-figure composite while changing the inputs; that inconsistency is what a reviewer
caught.) **A (92.3) stands**, with the same caveat: the semantic layer is the weakest
dimension and its denominator is small.


## Mutation sensitivity, corrected (19 controls)

The harness now covers 19 controls; the first run gave **17 kills by test failure, 1 survivor
and 1 hang** (89.5%), because a hang is not a failure and a mutation the suite cannot see is
not a kill. Both gaps were closed in the same session and verified by applying the mutation
directly:

| former non-kill | what it exposed | now |
|---|---|---|
| restricted rows not excluded from the ingest dedupe lookup | the seeded restricted row had no `source_group`, so the filter never mattered | `test_a_restricted_row_is_never_a_duplicate_target` gives the restricted row the identical `(text, department, source_group)`; with the filter dropped, that test **fails** (measured) |
| dependency-graph cycle guard removed | the suite reacted by *hanging*, so nothing failed | `test_the_cycle_guard_terminates_within_a_bounded_time` bounds the call with `SIGALRM`; with the guard removed the test **fails in 1 s** instead of hanging (measured) |

Both mutations were applied to `app/store.py` and `app/dependency_graph.py` directly, the two
tests run, the files restored from backup, and the pair re-run green (19 passed). So 19 of 19
controls are now covered by a test that fails when the control is removed — 17 demonstrated by
the harness in one sweep, 2 by the targeted runs above. The harness itself has not been re-run
end to end since; that figure would be the cleaner artifact and has not been produced.

## Final state after the confidence pass

| | value | artifact |
|---|---|---|
| suite | **2324 passed, 14 xfailed, 0 failed** (57.9 s) at tree fingerprint `8000e428b39b4e46` | command run |
| statement coverage | **91.3% (2806/3074, 20 modules)** | `sys.monitoring` over the full suite |
| mutation controls covered by a failing test | **19 of 19** (17 by harness sweep, 2 by targeted runs) | `mutation-results.json`, this file |
| decisions | **17 of 18 pinned**, 1 open (live vendor response) | `DECISIONS.md` |
| semantic dev / old holdout / new holdout | 0.891 (57/64) / 0.829 (34/41) / 0.815 (53/65, contested excluded) — **new holdout since re-measured at 0.831 (54/65)**, see `REVIEW-scope-interval.md` | `SEMANTIC-BENCHMARK.md`, `SEMANTIC-HOLDOUT-V2.md` |
| always-abstain baseline on the new holdout | 58.5% (38/65) — the floor every semantic number must beat | `SEMANTIC-HOLDOUT-V2.md` |
| unsafe misreads, new holdout | 15 of 65 ≈ 23% | `SEMANTIC-HOLDOUT-V2.md` |
| xfails remaining | 14, all `strict=True`, each a named unfixed misread class | `test_semantic_benchmark.py` |

Recomputed composite with these inputs: `0.25×100 + 0.20×100 + 0.15×92.3 + 0.15×66.7 +
0.10×94.4 + 0.10×91.3 + 0.05×100 = 92.24` → **A (92.2)**.

**What is now true that was not true this morning:** a verdict over a corpus with an unreadable
row is refused rather than computed over a silently shorter corpus (503, list still degrades and
reports `X-Unreadable-Rows`); control characters are refused in every client-settable string
field, tags and `source_group` included; the two mutations that used to survive or hang are
caught by tests that fail within a second; the semantic figure has a denominator, a baseline and
a second holdout that was not used to tune anything.

**What is still not true:** the live provider has never run (`BASETEN_API_KEY` absent), so row 7
stays open and every provider claim is about the mock; 23% of adversarial sentences on the new
holdout still get a stance they should not; the confidence score is still discontinuous at a
status switch by policy; and 14 known misread classes are pinned as xfails rather than fixed.

## After the formal-methods wave: is it "advanced" now?

The critique was that the semantic layer is "phrase matching over a closed cue inventory", with
discipline but no sophistication. Four workers attacked that, three of them with a proof tool.

| Claim | Status | Artifact |
|---|---|---|
| The composition step is a **law-verified lattice**, not an if-ladder | **proved + implemented** | `app/stance_algebra.py` (powerset join-semilattice on two direction atoms), `tests/test_stance_algebra.py` — 32 tests: table *derived* from the order, not written down; least-upper-bound property checked on all 16 pairs, associativity on all 64 triples, idempotence, `ABSTAIN_INFO` identity, monotone refinement over 240 clause shapes |
| The algebra's laws hold **in Coq**, with no axioms | **machine-checked** | `ct3/StanceAlgebra.v`: 58 theorems, `coqc` exits 0, `Print Assumptions` prints `Closed under the global context` ×20 |
| The shipped decision table **is** the proved model | **machine-checked, exhaustive on the modelled domain** | `ct3/refinement/generate_table.v` emits 441 rows; `tests/test_decision_table_refinement.py` compares all 441 against `decide` on status, rule id and exact rational score — **0 mismatches**, and the test was shown to fail (1/441) when one rule code is edited |
| The score's arithmetic is antisymmetric and the switch is genuinely non-monotone | **SMT-discharged** | `z3 antisymmetry.smt2` → `unsat`; `z3 switch-point.smt2` → `sat` with `gap = 1/4` |
| The impossibility claim in `decide`'s comment | **now a theorem, not prose** | `no_policy_keeps_monotonicity_and_integrity` (Coq), targeted at `decision_table.py:282-289` |
| The phrase matcher's three-valued public carrier can be composed at all | **disproved** | `no_public_composition`: no operation on `{supports, contradicts, abstain}` makes the projection a homomorphism. Merging "no cue matched" with "cues conflicted" costs the ability to compose, not just a label |

**So: yes on mechanism, no on coverage.** The composition is now mathematics — a free
join-semilattice with a proved refinement, cross-checked against Coq row by row, with the one
claim the code used to make in a comment now a theorem. What is still phrase matching is the
**lexical** layer: which cue a clause contains, and in what scope. That layer is where the
falsification wave did its damage.

**The falsification numbers, which belong in every summary of this system:**

- 20 000 generated sentences from the cue inventory itself, seed 20261102: invariants held —
  determinism 0/20 000, permutation 0/540, idempotence 0/50, `ABSTAIN_INFO`-identity 0/10 530.
- **52.6% of sentences commit a direction; 27.2% of those commits are wrong by construction**
  (2 869 / 10 530), i.e. 14.3% of all generated sentences. Recall on the 7 661 labelling rows
  is 100%, with 0 flips.
- Zero-false-commits is not free: an always-abstain guard is wrong on 38.3% of the same set, so
  committing buys real recall and pays for it at 27%.
- All 2 869 errors sit in two classes: **postposed hedges** (`…, probably`) and **quantified
  reports** (`No one confirmed that …`), the second being the disagreement between
  `_EVIDENTIAL_VERB` and `_REPORTING_VERB` about the same construction.
- Three properties the algebra **cannot express**, with executable counterexamples: a cue that
  spans a clause boundary; a scope operator applied to the whole sentence rather than its
  clause (`If the ward was busy, the checklist was unavailable.` → SUPPORTS, while the same
  operator with the cue in the antecedent abstains); and a negation with two possible
  attachment sites.

That last row is the honest limit of this wave: `Clause.verdict()` returns one element for both
"withheld" and "no direction", and that element is the join's identity, so a sentence-scope
operator is composed away by construction. `ct3/StanceAlgebra_facts.md` prices this as
`no_public_composition`; the falsification file measures it. The algebra is right; the interface
between the lexical layer and the algebra is where the errors live.

**Suite after this wave: 2372 passed, 14 xfailed, 0 failed** (57.1 s). Behaviour delta: an
explicit neutral cue plus a committed direction now resolves to that direction instead of
abstaining — 0 of the 105 benchmark rows contain that shape, so no pinned number moved.

## After the scope and interval wave

Added 2026-11-02. The table above describes the tree at the confidence pass and is
kept as history. What changed since:

| | value | artifact |
|---|---|---|
| suite | **5081 passed, 14 xfailed, 0 failed** (57.5 s) | command run |
| new holdout, uncontested | **54/65 = 0.831** (was 53/65) | `SEMANTIC-HOLDOUT-V2.md`, re-measured |
| new holdout, all rows | 55/70 = 0.786 | same |
| falsification corpus | 9 576 commits, **1 915 wrong (20.0%)** — unchanged, one class | `test_stance_algebra_falsification.py` |
| truth-interval laws | proved: ordering, width = 2(s·dc + c·ds + ds·dc) + ds + dc, four monotonicity gaps, labels never both fire | `ct3/IntervalReport.v`, six `Print Assumptions` closed |
| interval ↔ code bridge | 441 rows × 6 relations, implementation compared to exact rationals | `tests/test_interval_report_refinement.py` |
| scope reader | 22 unit tests; four pronoun/conditional defects closed | `tests/test_scope_layer.py`, `tests/test_semantic_guard_mood.py` |

The gate, run end to end on this tree:

```
[1/7] proofs-build PASS   5 .v files compiled in 8.0s
[2/7] no-unproved  PASS   0 unproved steps in 5 .v files
[3/7] refinement   PASS   2 of 2 recorded digests match
[4/7] suite        PASS   5081 passed, 0 failed, 14 xfailed, 0 errors
[5/7] xfail        PASS   2 strict sites covering 14 rows, 0 violations
[6/7] hostile-5xx  PASS   12 hostile requests, 0 unexpected 5xx
[7/7] mutation-floor SKIPPED  harness has no --fast mode
--- 6 PASS, 0 FAIL, 1 SKIPPED ---  result: NOT CERTIFIED  (exit 2)
```

So the standard is executable now, and **it does not yet certify the tree: the
mutation score is not measured by the gate.** One thing this wave deliberately
did not do is reverse the negated-reporting-verb pin, which is the whole of the
remaining 20% and is a product decision (`REVIEW-scope-interval.md` §5).
