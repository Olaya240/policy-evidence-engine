# Deep review of the formal-methods wave (by the coordinator, not by a worker)

Four workers reported success. This file is what survived being re-checked, plus what the
workers could not see because each owned one file.

## D1 — Open defect: a pronominal subject silently deletes an opposing clause  *(pinned)*

```
"The checklist was unavailable, and the checklist was available."        -> None (AMBIGUOUS)
"The checklist was unavailable, and others say it was available."        -> SUPPORTS   <-- wrong
```

The second clause asserts the opposite direction and is dropped, so the sentence certifies the
first. Isolated to the lexical layer: the cue match needs its subject spelled out, and
`compose_all` cannot react to a clause that was never built — the same structural cost the Coq
file proves as `no_public_composition`, now with a measured instance. Pinned as a strict xfail
in `tests/test_stance_algebra_falsification.py` with the repeated-subject neighbour beside it,
so a fix flips XPASS rather than passing quietly.

## D2 — Open defect found and **fixed**: `_cue_prefix_clause` is a prefix, not a clause

The name says "the clause between the last boundary and the cue", and that is exactly what it
returns — text *before* the cue. Every operator reader built on it is therefore blind to
anything after the cue. Measured consequence:

```
"The checklist was probably unavailable."   -> None        (hedge seen)
"The checklist was unavailable, probably."  -> SUPPORTS    (hedge invisible, before the fix)
```

One hedge, two verdicts, decided by word order. The audit's earlier claim that postposed hedges
were "excluded on purpose" was wrong: they were excluded by data flow. Fixed with
`_is_postposed_hedge`, which reads the comma tail after the cue, plus two pins (the hedge
abstains; "…, and probably for good reason" still certifies, because that hedges the reason and
not the cue). All six guard pin files stay green and no benchmark row moved.

**Effect, re-measured on the same 20 000 generated sentences:**

| | before | after |
|---|---|---|
| commits | 10 530 (52.6%) | 9 576 (47.9%) |
| wrong by construction | 2 869 (27.2%) | **1 915 (20.0%)** |
| HEDGE family | 954 | **0** |
| QUANTIFIER family | 1 915 | 1 915 |
| recall / misses / flips | 100% / 0 / 0 | 100% / 0 / 0 |

The "two error families" claim is now one. The regression bounds in that file were written
against the old numbers; they were lowered to the new ones with the reason recorded, and the
"confined to two classes" test now asserts confinement to **one** — a stronger statement, not a
relaxed one.

## D3 — Open gap found and **closed**: the refinement table could drift from its proof

`test_decision_table_refinement.py` reads the committed `ct3/refinement/decision-table.out`; it
does not run `coqc`. Edit `generate_table.v`, forget to regenerate, and 441/441 comparisons keep
passing against a table that no longer describes the model. The audit's trust-base section said
the table was reproducible but nothing enforced it. Added a digest handshake over
`generate_table.v` and `DecisionTable.v`, proven to bite: appending one comment to the `.v`
turned the test red (`1 failed`), restoring it turned it green (`6 passed`).

## D4 — The 27.2% was policy-relative, and that matters for how it is quoted

Sampled the claimed-wrong rows:
- QUANTIFIER ("No one confirmed that the checklist was unavailable" → SUPPORTS) is **genuinely
  wrong** by plain reading. But it is blocked by an explicit corpus decision, not by a missing
  rule: `CU-MATRIX-DID-NOT-SAY` and friends pin a negated reporting verb as *certifying*. So
  the number cannot be reduced without reversing a recorded decision — a decision that should
  now be revisited on the merits, since it costs ~10% of all commits.
- HEDGE was **not** policy: it was the positional bug in D2.

So "20.0% wrong" today means: zero from cheap bugs, 20.0% from one class that is deliberately
pinned the wrong way.

## D5 — The Coq impossibility theorem is not vacuous

Re-read the statement rather than trusting the report: it quantifies over **all** `f : nat ->
nat -> Q` and **all** status functions, assumes `st 2 0 = Supported`, `st 2 1 = Partial`,
`f 1 1 = 1/2`, `f 2 0 = 2/3`, `f 2 1 ∈ {1/4, 2/3}` and concludes the negation of
(monotone ∧ partial-magnitudes-distinct). Two branches, both discharged; the hypotheses are the
shipped numbers, so the theorem is about this table, not a toy.

## D6 — The algebra's tests bite (independent mutation)

`compose(left, right) -> left` (the weakest possible composition bug) fails 8 of the 32
algebra tests; restoring the file returns 32 passed.

## D7 — Things checked and found sound

- `coqc StanceAlgebra.v` exits 0 and `Print Assumptions` prints `Closed under the global
  context` twenty times; the only `admit` string in the file is English in a comment.
- `z3 antisymmetry.smt2` → `unsat`; `z3 switch-point.smt2` → `sat` with `gap = 1/4`.
- 441/441 refinement rows match on status, rule id and exact rational score.
- The guard emits only algebra reason codes across the corpus; `test_semantic_benchmark.py` is
  unchanged at 57/64 dev with 14 strict xfails.

## What this review did not do

No human-labelled corpus, so all semantic numbers remain agent-labelled. No attempt to fix the
QUANTIFIER class, because that requires reversing a decision and re-pinning a corpus, which is a
product call rather than a bug fix. Coverage was measured on subsets for the new modules
(`stance_algebra.py` 91.4% under its own tests); no full-suite per-module figure was recomputed
after the last edits. Suite at the end of this review: **2 376 passed, 15 xfailed, 0 failed.**
