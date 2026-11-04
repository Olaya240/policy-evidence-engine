# Refinement proof: Coq's table → Python's table

`ct3/DecisionTable.v` proves properties of a *model* of the decision table. That
is worth nothing if `backend/app/decision_table.py` computes a different function.
This note records the mechanical bridge that closes the gap, and — more
importantly — exactly how far the bridge carries.

| Artifact | Role |
|---|---|
| `ct3/refinement/generate_table.v` | Coq model of `decide`, computes the whole grid, prints it |
| `ct3/refinement/decision-table.out` | the generated table: 441 rows, 10 numeric columns each |
| `ct3/refinement/legend.out` | the status/rule numbering, in constructor order |
| `backend/tests/test_decision_table_refinement.py` | asserts every row equals `decide` |
| `ct3/refinement/antisymmetry.smt2` / `.out` | z3 `unsat` for the negation of antisymmetry |
| `ct3/refinement/switch-point.smt2` / `.out` | z3 `sat` + model for the non-monotone pair |

Reproduce (`coqc` 8.18.0, `z3` 4.8.12, both installed on this machine):

```
cd ct3/refinement && coqc -Q .. "" generate_table.v   # writes decision-table.out, legend.out
cd ../.. && z3 ct3/refinement/antisymmetry.smt2
           z3 ct3/refinement/switch-point.smt2
cd backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python \
    -m pytest -q tests/test_decision_table_refinement.py
```

Verbatim, this run:

```
$ coqc -Q .. "" generate_table.v
coqc exit=0                      (no output; no Admitted, no admit)

$ z3 ct3/refinement/antisymmetry.smt2
unsat

$ z3 ct3/refinement/switch-point.smt2
sat
(
  (define-fun gap () Real
    (/ 1.0 4.0))
)

$ pytest -q tests/test_decision_table_refinement.py
.....                                                                    [100%]
5 passed
```

## 1. What is machine-checked end to end

The chain has three links, and each is a different strength of evidence.

**Link 1 — Coq model → printed table (computed, partly kernel-checked).**
`decide_cell` is `decide` minus the fields listed in §4. `cells` is
`decide_cell` applied to all 441 points of `0..6 × 0..6 × 0..2 × 0..2`, and
`table` is `cells` printed by `Eval vm_compute`. Twelve theorems/lemmas are
kernel-checked, including:

* `label_matches_v2` — this file's `_label` **is** `v2_status` from
  `ct3/DecisionTable.v`, translated (`Supported → TSupported`,
  `Mixed → TPartial`, …). If either file's threshold is edited alone, `coqc`
  fails. This is the link to the proved model, and it is a proof obligation, not
  a comment.
* `grid_is_the_full_product` — the coordinates the model was run on are exactly
  the 441-point product, in a pinned order. A row dropped, duplicated or
  reordered by an edit to `grid` breaks this.
* `grid_size = 441`, `table_size = 441`.
* `score_antisymmetric` — `(s-c)(c+s+1) = -((c-s)(s+c+1))` by `ring`, the same
  identity z3 discharges.
* `score_den_positive` — the denominator is `> 0`, so the cross-multiplied
  comparisons really are order-preserving.
* `dispute_relevant_is_partial` — a decision-relevant challenge can never yield a
  decisive label.
* `status_is_label_or_partial` — the dispute rule never *promotes* a verdict.
* `undisputed_cell_is_the_label` — with nothing challenged, the cell is the label
  and the formula.
* `switch_point_is_not_monotone`, `switch_point_values` — `decide(2,0,dc=1)` is
  `1/4` and `decide(1,0,dc=1)` is `1/2`, so more support reports a smaller number.

**Link 2 — printed table → Python (`Eval` output read by a test).** The test
parses the integers Coq printed, checks the row count is 441 and the coordinates
are the documented nesting order, then for each of the 441 rows compares against
`decide(s, c, disputed_support=ds, disputed_contradiction=dc)`:

* the status (`Status` member), and the `status_rule_id` string;
* the score **as an exact rational** — `Fraction(num, den)`, checked to equal
  `(eff_s - eff_c) / (eff_s + eff_c + 1)`;
* `decision.score` compared with `==` to `float(Fraction(num, den))`;
* `app.decision_table.score(eff_s, eff_c)` compared with `==` to the same float,
  so the module's own arithmetic is covered too, not just `decide`'s routing.

Result: **441 rows, 0 mismatches.** The same test reports the disagreement count
in its failure message and prints the disagreeing rows, so the number is the
assertion, not a claim in prose.

**The check is not vacuous.** Two controls were run and are recorded here because
a passing comparison proves nothing if it cannot fail:

* one cell of `decision-table.out` was edited (`rule` code of row `(0,0,0,0)`
  changed `2 → 3`); the test failed with
  `1 of 441 rows disagree … (s=0, c=0, ds=0, dc=0) -> ['rule: coq STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED != python STATUS.V2_NO_DIRECTIONAL_EVIDENCE']`,
  and the table was restored from a byte-identical copy.
* the z3 queries were re-run against mutated copies: dropping the re-pricing rule
  from `switch-point.smt2` makes the query `unsat` (`(error "model is not
  available")` from `get-model`, as expected), and making `f` asymmetric
  (`(s + 1 - c)/(s + c + 1)`) makes `antisymmetry.smt2` `sat`. Both queries
  therefore discriminate.

The table reaches every label and every rule, so a mix-up in either cannot hide:
`SUPPORTED 42, PARTIAL 353, CONTRADICTED 45, INSUFFICIENT 1`, and
`SUPPORT_OUTWEIGHS 42, CONTRADICTION_OUTWEIGHS 45, NO_DIRECTIONAL 1,
DIRECTIONAL_EVIDENCE_BALANCED 265, DISPUTED_EVIDENCE_DECISION_RELEVANT 88`.
Exactly one row is `INSUFFICIENT` — `(0,0,0,0)`; every other `(0,0,·,·)` row has
a challenge that changes the label, so it is downgraded to `PARTIAL`.

**Link 3 — z3 (oracle, not a proof assistant).** `antisymmetry.smt2` asserts the
negation of `f(s,c) = -f(c,s)` for `s, c ≥ 0` over the reals and gets `unsat`;
`switch-point.smt2` asserts `reported(2,0,0,1) < reported(1,0,0,1)` with the
label arms and the re-pricing rule encoded, and gets `sat` with `gap = 1/4`.
Both agree with the Coq side, which is the useful part: they are an *independent*
encoding of the same arithmetic, so a transcription slip in one is unlikely to be
mirrored by the other.

## 2. Trust base — where the chain is not kernel-checked

**`coqc` version.** `coqc --version` → `The Coq Proof Assistant, version 8.18.0`,
`compiled with OCaml 4.14.1`. The twelve theorems have no `Admitted`/`admit`;
`grep -n "Admitted\|admit" ct3/refinement/generate_table.v` finds nothing.

**The printed table is not re-checked by the kernel.** The 441 rows come out of
`Eval vm_compute`, i.e. they are *computed* by the Coq VM and printed. The kernel
checks the twelve theorems above (including that the grid is the full product and
that the two switch-point rows are `1/2` and `1/4`), but it does not verify the
printed list value-by-value. This is honest rather than fatal, for one reason: the
table is one *side* of a comparison, not a trusted input. If printing corrupted a
row, the Python comparison would disagree about that row — unless both sides were
wrong in the same way, which they cannot be, because Python computes the decision
independently of Coq. The artifact is also reproducible: regenerating from a clean
state (`rm generate_table.vo decision-table.out legend.out && coqc …`) produced a
byte-identical file (`diff` clean).

**The prompt's `signed_margin` does not exist.** The workstream named
`decide` and `signed_margin`; `grep -rn "signed_margin" --include=*.py` over the
repository returns nothing. The arithmetic core is `Decision.score` / the
module-level `score()` (`(s - c) / (s + c + 1)`), and both are what the SMT files
encode and what the test compares. No symbol was renamed or added.

**`z3` is an oracle, not a proof assistant.** No proof object is produced, and no
independent checker consumes one (z3 emits no verifiable proof here; `get-model`
is a model, not a derivation). `unsat` is z3's answer, on trust in z3 4.8.12. Two
further consequences:

* the SMT encoding of `_label` and of the re-pricing rule is **hand-transcribed**
  from `backend/app/decision_table.py`. Nothing machine-checks it against the Coq
  definitions or against the Python. The encoding's correctness rests on the
  reader comparing ~10 lines of SMT-LIB with ~10 lines of Python, and on the fact
  that the same two claims are *also* proved in Coq (`score_antisymmetric`,
  `switch_point_values`, `switch_point_is_not_monotone`) — so z3 is confirming,
  not establishing.
* `switch-point.smt2` is one concrete instance, not a quantified claim about every
  switch. `test_confidence_reliability.py` counts 26 support inversions and 20
  contradiction inversions on the disputed grid; that count is a test assertion,
  not an SMT result.

**Comparison semantics: rational vs float.** Coq never touches a float: the score
is carried as `num : Z` and `den : Z` for the whole pipeline, and the emitted
numerator is biased by 8 (range `-8..8`) only because Coq 8.18 core has no
integer-to-string conversion, so every printed number is a `nat`.

The Python side *does* return a float, so the comparison has to be stated
carefully. `Fraction(decision.score)` is **not** the model's rational — it is the
exact binary value of the double:

```
score            = 0.6666666666666666
float(2/3)       = 0.6666666666666666
exact     equal  = True
Fraction(score)  = 6004799503160661/9007199254740992
Fraction equal   = False
```

So the test asserts `decision.score == float(Fraction(num, den))`: exact equality
between the double and the correctly rounded image of the model's rational.
`float(Fraction)` rounds correctly, and `score()` performs one division of exact
small integers, which is correctly rounded too, so `==` is the right relation and
a one-ulp drift fails. There is no `pytest.approx` and no tolerance anywhere in
`test_decision_table_refinement.py`; the rational itself is compared with
`Fraction` equality against `(eff_s - eff_c) / (eff_s + eff_c + 1)`.

**The grid is bounded.** `0..6 × 0..6` for the two counts and `0..2 × 0..2` for
the two disputed counts: 441 rows. This is **exhaustive over the modelled domain**
and says nothing about `s > 6`, `c > 6`, `ds > 2` or `dc > 2`. It is not a proof
over all natural numbers. The all-ℕ statements in this repository are the Coq
theorems in `ct3/DecisionTable.v` (exclusivity, monotonicity of the undisputed
formula, staleness and order invariance, the single-source guard), which are
about the counts and the record lists, not about the dispute rule.

## 3. What is still hand-written prose

Nothing below is checked by Coq, z3 or pytest; each is a claim a reader has to
accept or re-derive.

* **The code→name dictionaries.** `generate_table.v` emits integers for the label
  and the rule; `STATUS_BY_CODE` / `RULE_BY_CODE` in the test attach the Python
  names. This is the one place where a rename could pass unnoticed — mitigated by
  `legend.out`, which carries the same codes in constructor order and is asserted
  to equal `[0,1,2,3]` and `[0,1,2,3,4]`, so a renumbering on the Coq side fails
  the legend test instead of silently renaming a verdict.
* **The model's faithfulness as a *reading* of the code.** `decide_cell`
  reproduces `decide`'s branch order (label → as-if label → downgrade and
  re-price). That both are the *same function* is what the 441-row comparison
  shows; that the function means what its docstring says is prose.
* **Everything outside the counts.** `_count_groups`, `group_key` (NFC
  normalisation, zero-width stripping), the `Evidence`/`Decision` data classes,
  `contested`, `disputed_groups`, `confidence_rule_id` are out of scope here.
  `test_confidence_reliability.py` and `test_table_differential.py` cover parts of
  the records→counts step; this bridge starts at the counts, as the Coq model
  does.
* **The other two policies.** `POLICY_CONTEST_BLOCKS` and `POLICY_TWO_TO_ONE` are
  unproved by design. No row for them appears in the table, so no theorem is
  implied about them.
* **The SMT transcription** of `_label` and of the re-pricing rule, as described
  in §2.
* **This note.** Row counts, mismatch counts and version strings above are real
  outputs of the commands shown, but the prose around them is not a check.

## 4. The model, stated exactly

For `s, c` the undisputed group counts and `ds, dc` the challenged counts:

```
label(s,c)      = SUPPORTED      if s >= 2 and s >= 3c + 1
                = CONTRADICTED   else if c >= 3s + 1
                = INSUFFICIENT   else if s = 0 and c = 0
                = PARTIAL        otherwise

relevant        = (ds + dc) != 0 and label(s,c) != label(s+ds, c+dc)

decide(s,c,ds,dc) = (label(s,c),        score(s,c))            if not relevant
                  = (PARTIAL, DISPUTED_EVIDENCE_DECISION_RELEVANT,
                     score(s+ds, c+dc))                          if relevant

score(a,b)      = (a - b) / (a + b + 1)
```

The re-pricing is the known cost pinned by
`test_confidence_reliability.py::test_the_reported_score_is_discontinuous_exactly_at_a_status_switch`:
two independently ordered configurations meet at the switch, so the reported
number is not monotone in the undisputed support. `switch_point.smt2` and
`switch_point_values` say the same thing about the same pair of rows, one by an
SMT model and one by kernel computation.
