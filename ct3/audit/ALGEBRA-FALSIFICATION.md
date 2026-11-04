# Algebra falsification — what the composition cannot see

`backend/tests/test_stance_algebra_falsification.py`, 11 tests, all passing.
Harness: `backend/app/semantic_guard.py` at HEAD, `backend/app/stance_algebra.py`
at HEAD. Written as worker 4 of 4, after the algebra and its tests existed.

The other tests of this algebra prove things about the model: join is
commutative and idempotent, `ABSTAIN_INFO` is the identity, a permuted list of
clause verdicts composes to the same value. All of that is true here too — 0
violations on 20 000 generated sentences. None of it is the interesting result.

The interesting result is that **a clause verdict is not a function of the
clause's own scope**, so three ordinary English sentences get a clause verdict
that no composition rule can correct. Measured cost on the generated set: of
10 530 committed directions, 2 869 are wrong by construction.

---

## 1. The generative search

Grammar, built from the guard's own inventory (imported as
`app.semantic_guard._CUES` at runtime — no phrase is copied into the test):

| dimension | values |
|---|---|
| hypotheses | 5, read from `_CUES` |
| directional cue phrases | 27 (SUPPORTS + CONTRADICTS; NEUTRAL excluded, see §5.4) |
| scope-operator classes | 10: PLAIN, NEGATION, HEDGE, QUESTION, CONDITIONAL, QUANTIFIER, EVIDENCE_ABOUTNESS, EVIDENTIAL, CONTRAST, CONCESSION |
| sentence templates | 21, each ordinary English for its class |
| lead-in adverbials | 8 (scope-neutral: time, place, attribution) |
| trailing coordinates | 5 (scope-neutral) |

Product: 22 680 sentences. Sampled without replacement to exactly **20 000** with
`random.Random(20261102)`; the same seed reproduces the same 20 000. Each
sentence's intended polarity is known by construction, because the generator
chose the operator that produces it.

### 1.1 Is the generator non-trivial?

Required before any "0 violations" can mean anything.

| | count | share |
|---|---|---|
| sentences where a cue matched at all | 20 000 | 100% |
| committed a direction | 10 530 | 52.6% |
| abstained | 9 470 | 47.4% |
| — of which `NO_CUE_MATCH` | **0** | 0% |

Verdict distribution: SUPPORTS 7 027, CONTRADICTS 3 503, abstain 9 470.
Abstention reasons: `NEGATED_CUE` 2 844, `CONDITIONAL_CUE` 1 901,
`CUE_IN_QUESTION` 1 900, `HEDGED_CUE` 1 886, `EVIDENCE_ABOUTNESS_FRAME` 939.

No sentence in the sample lost its cue, and every abstention carries a reason
code. The generator reaches ten operator classes and five distinct rejection
paths, so a clean invariant pass on it is a fact about the guard and not an
artifact of an empty input set.

### 1.2 The four invariants

| invariant | checks | violations | smallest counterexample |
|---|---:|---:|---|
| determinism (same sentence, two calls) | 20 000 | 0 | — |
| order independence under clause permutation | 540 | 0 | — |
| idempotence under clause repetition | 50 | 0 | — |
| `ABSTAIN_INFO` never changes a committed direction | 10 530 | 0 | — |

Permutation families: independent clauses about different hypotheses (2- and
3-clause, all orders), two agreeing cues for one hypothesis, two opposing cues
for one hypothesis. 540 checks over 210 permuted sentences, 3 lead-ins.

**Zero violations. That is a pass, and it is also the weaker half of this
document**: the guard is a pure function of the string, so determinism is
near-free; and the three attack sentences in §3 are *not* permutations of the
clauses they break, so these invariants are silent about them.

---

## 2. The measurement

Intended polarity known by construction. "wrong" = the guard committed a
direction for a sentence that does not assert the cue.

| operator class | n | committed | wrong | missed |
|---|---:|---:|---:|---:|
| PLAIN | 1 928 | 1 928 | 0 | 0 |
| EVIDENTIAL | 1 940 | 1 940 | 0 | 0 |
| CONTRAST | 1 904 | 1 904 | 0 | 0 |
| CONCESSION | 1 889 | 1 889 | 0 | 0 |
| EVIDENCE_ABOUTNESS | 939 | 0 | 0 | 0 |
| NEGATION | 1 889 | 0 | 0 | 0 |
| CONDITIONAL | 1 901 | 0 | 0 | 0 |
| QUESTION | 1 900 | 0 | 0 | 0 |
| **HEDGE** | 2 840 | 954 | **954** | 0 |
| **QUANTIFIER** | 2 870 | 1 915 | **1 915** | 0 |
| **total** | **20 000** | **10 530** | **2 869** | **0** |

Two error families, both 100% of their class's commits:

- **HEDGE 954** — the postposed form `"The auditor said <cue>, probably"`. The
  hedge is to the right of the cue, and the guard reads hedges only in the cue's
  left context. This residual is already recorded in
  `ct3/audit/SEMANTIC-BENCHMARK.md` as an uncertified case; it is measured here
  at 954/2 840 of the class (33.6%).
- **QUANTIFIER 1 915** — `"No one confirmed that <cue>"` and `"None of the staff
  reported that <cue>"`: 1 915/2 870 (66.7%). `_is_quantified_negation`
  (`semantic_guard.py:163`) returns `False` when a reporting verb or a
  complementiser sits between the quantifier and the cue, by design. The cue is
  then certified as if it had been asserted.

### 2.1 What committing buys, against the always-abstain baseline

Same 20 000 sentences, same denominators.

| | committed | wrong | wrong / 20 000 | recall on the 7 661 asserting rows |
|---|---:|---:|---:|---:|
| guard at HEAD | 10 530 | 2 869 | 14.3% | 7 661 / 7 661 = 100% |
| always abstain | 0 | 0 | 0% | 0 / 7 661 = 0% |

Committing buys 7 661 correct directions and costs 2 869 false ones. Against
abstain-all, the guard is wrong on 14.3% of sentences instead of 38.3% (the
7 661 asserting rows abstain-all has to refuse), and its 2 869 errors are all
false directions rather than missing ones.

Two caveats on that 100% recall, stated plainly: the 7 661 asserting rows are
clean single-clause assertions, so 100% is a floor the grammar was built to
allow, not an achievement; and 27.2% of the guard's commits (2 869/10 530) are
wrong, which is the number to quote when the question is "can I use a committed
direction without reading the clause".

---

## 3. Three minimal counterexamples

Every verdict below is asserted by a characterisation test in the suite, so the
table is executable, not transcribed.

| # | sentence | guard | should be |
|---|---|---|---|
| A | `The checklist, as it happens, was unavailable.` | `None / NO_CUE_MATCH` | SUPPORTS |
| A′ | `The checklist\nwas unavailable.` | `SUPPORTS` | SUPPORTS |
| B | `If the ward was busy, the checklist was unavailable.` | `SUPPORTS` | `None` |
| B′ | `If the checklist was unavailable, the team should have escalated.` | `None / CONDITIONAL_CUE` | `None` |
| C | `The team did not report that the checklist was unavailable.` | `SUPPORTS` | `None` |
| C′ | `The auditor did not confirm the checklist was unavailable.` | `None / NEGATED_CUE` | `None` |

### A. A cue spanning a clause boundary — a silent recall hole

`"The checklist, as it happens, was unavailable"` asserts exactly the cue. Cue
words are joined with `\s+` (`semantic_guard.py:416`), so a *newline* inside the
phrase matches (A′) and a *comma* does not (A). The guard reports
`NO_CUE_MATCH`, its "this quote says nothing about the hypothesis" value, and
the composition is told there is no evidence where there is a direct assertion.

This one is wrong in the safe direction — it abstains — which is why it is more
dangerous than a false commit: nothing downstream can tell it apart from a quote
that genuinely does not mention the checklist. `NO_CUE_MATCH` and "the matcher
could not see it" are the same element.

### B. An operator whose scope is the sentence — a false commit

`"If the ward was busy, the checklist was unavailable"` asserts nothing about
the checklist's availability: a conditional's consequent is proposed, not
claimed. The guard commits SUPPORTS (B) and abstains when the same construction
puts the cue in the *antecedent* (B′). One operator, two treatments, decided by
which side of the comma the cue lands on.

The clause type has the concept and cannot receive it: `Clause.modality` is
computed by `_modality(quote, found.start(), final_clause)` — from the cue's left
context only (`semantic_guard.py:426`) — and `Modality.CONDITIONAL` needs the
conditional to *open* the cue's clause (`_CONDITIONAL_CLAUSE_OPENING` at
`:150`). The conditional's scope is the sentence; there is no field for it.

### C. A negation with two attachment sites — a false commit

`"The team did not report that the checklist was unavailable"` has two
readings: negation on the reporting verb (they did not say it — asserted nothing
about the checklist) and negation on the complement (they said it was not so).
The dominant reading asserts nothing; the guard commits SUPPORTS.

The asymmetry is inside one file. Negation over an *evidential* verb withholds
(`_EVIDENTIAL_VERB` at `:96`, so C′ → `NEGATED_CUE`); negation over a *reporting*
verb does not, because `report` is not in that list. And the same verb that
blocks under "did not confirm" is treated as a complement-taking verb by the
quantifier rule (`_REPORTING_VERB` at `:156` contains `confirmed`), which is why
C′ abstains while `"No one confirmed that the checklist was unavailable"`
certifies. The two regexes disagree about the same construction, and the
measured 1 915 QUANTIFIER errors in §2 are that disagreement at scale.

### Why the algebra cannot express any of these

The composition's input is a clause verdict. In this carrier
`ABSTAIN_INFO` is the empty join, i.e. the identity
(`stance_algebra.py:17`, `:32`), and `Clause.verdict()` returns it both for "no
cue" and for "cue withheld" (`:302-307`) — the module's own docstring says the
lattice "does not distinguish the two ways to reach `ABSTAIN_INFO`" (`:349`).

So a sentence-scope operator, however faithfully it is detected, is typed as
*withheld*, and withholding composes to the identity. `compose_all([ABSTAIN_INFO,
SUPPORTS]) == SUPPORTS` is a theorem of the carrier, not an oversight — the suite
asserts it in `test_algebra_cannot_express_the_scope_the_attacks_need`. The only
element that dominates a direction is `ABSTAIN_CONFLICT`, which means "two
directions are supported", a different fact. Detecting B is therefore not
available as a composition rule: it has to happen before the clause is typed, in
the span that `_modality` is given.

---

## 4. The proof and the shipped carrier

The Coq development is careful and it already names this collapse. From
`ct3/StanceAlgebra.v`: the carrier keeps `NoClause` (nothing was said, identity)
and `NoInfo` (something was said and could not be read, absorbing) as *distinct*
elements (`:121-122`, `compose` at `:151`), and proves `unreadable_absorbs`
(`:457`) and `no_direction_from_unreadable` (`:460`). `ct3/StanceAlgebra_facts.md`
states the cost directly — "collapsing the abstentions costs composing"
(`:44-45`) — and makes it a theorem, `no_public_composition` (`:19`).

That collapse is not a discovery of mine, and the facts document records it in
advance: A3 maps the Coq's `Conflict` and `NoInfo` onto the same Python value
`None` and says so ("now with its cost attached"), and A4 says absence and
unreadability "are already merged in the artifact". What §3 depends on is the
carrier-level form of that merge: `Clause.verdict()` returns the *same* element
for a withheld clause and for a clause with no direction, and that element is
the join's identity. So the sentence-scope operator in B, however faithfully it
is detected, is typed as withheld and then composed away — which is what
`no_public_composition` prices in the abstract and what the 2 869 measured
commits pay for in practice.

So the Coq file is not evidence about this Python module's inputs. It proves
properties of a five-element carrier whose extra element the guard never
constructs, under an order the facts document itself marks as a choice (A5).
Everything proved there about unreadability is conditional on a modelling
assumption the shipped code declines.

What the collapse buys in practice is measurable and small: 9 470 of 9 470
abstentions in §1.1 are withheld *with* a reason, so under this carrier every
one of them is the identity. A sentence whose only clause is withheld still
abstains (the guard maps `ABSTAIN_INFO` to `None`), but the moment any clause in
the sentence certifies, every withheld neighbour is composable away. In the
20 000-sentence set all sentences are single-clause, so no composition
amplification occurs there; B is the same defect in a sentence where it does.

---

## 5. What the proofs do not cover

Blunt, in order of how much it costs.

1. **Every proof starts at `compose`, given clause verdicts.** Not one of them
   says the clause verdict was computed from the right span of text. All three
   findings in §3 are failures of that span. `compose` being correct is
   orthogonal: the counterexamples enter as `SUPPORTS`.
2. **Order independence is proved for the list, not for the guard.** The guard
   stops at the first certifying clause for a stance
   (`semantic_guard.py:433-434`), so which *withheld* clauses survive in the
   list — and therefore which reason codes `combine_reasons` sees — depends on
   inventory iteration order. `compose_all_perm` cannot notice, because it
   permutes whatever list it is handed. My 540 permutation checks compared
   `(relation, reason_code)` and found no case; that is a measurement over three
   families, not a theorem.
3. **Section 1's parity machinery has no caller.** `_negation_scope` returns a
   recording enum (`NONE / ADJACENT / FRAME / VERB_SEPARATED`); a negated clause
   is withheld, never flipped.   `flip`, `act`, `neg_involution` and
   `act_depends_on_parity_only` are proved about a pipeline the guard does not
   run. `StanceAlgebra_facts.md` A6 says this; it stays true after the algebra
   landed.
4. **The inventory is not modelled, and my generator cannot test it.** No proof
   says the cue lists are adequate or complete, and my search draws from the
   same lists — it can only find misuse of a cue that exists, never a missing
   one. A would be found by any parser that handles parentheticals; it was found
   here by hand, not by the generator. NEUTRAL phrases are excluded from the
   grammar for this reason (they are meta-statements, so they do not slot into
   the frames), which leaves the neutral path untested.
5. **My intended-polarity labels are judgements.** For the 12 339
   abstain-expected rows I encode "this operator blocks assertion". The
   debatable forms were kept out of the measurement on purpose — anything where
   a narrow-scope reading is available (a `Perhaps` over a coordination, a
   negation over a reporting verb) lives in §3, not in §2. A reader who accepts
   `"said <cue>, probably"` as an assertion will reject 954 of the 2 869.
6. **Nothing beyond one sentence.** Document headers, cross-sentence anaphora
   ("it was unavailable"), multi-quote composition, and `engine.py`'s per-item
   aggregation are outside every claim here, including mine.

---

## 6. Reproduce

```
cd backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python \
  -m pytest -q tests/test_stance_algebra_falsification.py
...........                                                              [100%]
11 passed in 10.98s
```

The measurement table is recomputed by `_score()` in that module; the numbers in
§1–§2 are its output at the commit this file was written against. The whole file
runs in ~7–11 s depending on machine load (2 guard calls × 20 000 sentences plus
540 permutation checks).
