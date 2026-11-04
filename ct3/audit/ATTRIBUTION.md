# Attribution frames — the negative-frame rule, what it bought, and what it costs

2026-11-02, second wave; the rule was extended to denied speech acts and the
numbers below were re-measured on 2026-11-03. **Suite: 5 202 passed, 0 failed,
15 xfailed** (gate run, 2026-11-03). `ct3/Attribution.v`: **26 theorems**, `coqc`
exit 0, all six `Print Assumptions` closed, no axioms.

## The defect, stated as one sentence with two spellings

```
"The auditor did not confirm that the checklist was unavailable."   -> abstains
"No one confirmed that the checklist was unavailable."              -> SUPPORTS
```

One construction, two verdicts, decided by which word did the negating. The
regex could see `not`, and could not see `no one`. That single gap was **1 915 of
9 576 commits wrong by construction (20.0%)** on the falsification corpus — the
whole remaining error class in the previous report.

## What replaced the regex

`backend/app/evidence_frames.py`: a typed `Attribution(agent, quantifier,
polarity, verb_class)` read from the verb's own clause, and one total function

```
force(attribution) = WITHHOLDS  when the frame is effectively negated
                   = ASSERTS    otherwise
effective negation = explicit negation, or a `none` quantifier over the subject
```

The class is still recorded on the frame but **plays no part in the rule**. That
is the policy decision this wave made: denying a speech act denies it as surely
as denying an evidential, so both withhold. It costs recall — four corpus rows
and their neighbours that used to certify now abstain — and the corpus prices it
below.

Composition is the **meet** over a prefix: one withholding clause withholds the
proposition, `ASSERTS` is the identity, and no frame recognised returns `None`
rather than `WITHHOLDS` — the caller falls back to the lexical reading instead of
abstaining on every sentence whose scaffolding it does not know.

`ct3/Attribution.v` proves the algebra, not the English:

| Theorem | Statement |
|---|---|
| `force_withholds_iff` | the rule as an equation, both directions |
| `force_asserts_iff` | the complement case, both directions |
| `quantifier_and_polarity_agree` | `no one confirmed` and `did not confirm` are one rule |
| `class_is_inert` | the speech-act class changes no force |
| `denied_speech_act_withholds` | the shipped rule, on the class that used to certify |
| `the_class_split_is_unreachable` | the retired evidential-only split cannot be reached |
| `force_extensional` | force depends on the effective negation alone |
| `compose_app` | a prefix splits into two prefixes whose forces meet |
| `compose_withholds_iff` | a prefix withholds **iff** some frame in it withholds |
| `compose_is_monotone` | appending clauses can only lose force |
| `withholding_is_not_rescuable` | nothing appended after a denial restores assertion |
| `withdrawn_requires_a_frame` | `None` (no frame) is not `WITHHOLDS` |
| `meet_is_glb` | the meet is the greatest lower bound, so the order is a lattice |

**What is not proved, and must not be read into the file:** which English shapes
get a frame at all. The proof fixes the algebra over typed frames; recognition
lives in `evidence_frames.py` and is defended by the behavioural tests and the
corpus. The file used to model the narrower evidential-only rule and stated
`force denied_speech_act = Asserts`; that model is gone, not merely annotated.

## Measured (2026-11-03, after the four reader repairs below)

| | before the rule | now |
|---|---|---|
| falsification commits | 9 576 of 20 000 | **7 661 of 20 000 (38.3%)** |
| wrong by construction | 1 915 (20.0%) | **0** |
| recall / misses / flips | 100% / 0 / 0 | **100% / 0 / 0** |
| remaining wrong class | QUANTIFIER | **empty** |
| dev benchmark | 57/64 | **60/64 = 0.938** |
| old holdout | 34/41 | **38/41 = 0.927** |
| new holdout v2 (uncontested / all) | 54/65 / 55/70 | **56/65 = 0.862 / 59/70 = 0.843** |

The corpus number at zero is the honest headline and also a warning: the
generator no longer discriminates, so it now measures agreement with itself. The
labelled sets are the live measurement.

## The four reader defects fixed on 2026-11-03

The corpus did not contain any of these, so it did not move; the unit tests and
the labelled rows are what defend them.

| Defect | Sentence that flipped | Was | Now |
|---|---|---|---|
| fronted adverbial read as a negated frame | "Without the key, the auditor confirmed the checklist was unavailable." | ABSTAIN `ATTRIBUTED_DENIAL` | SUPPORTS |
| past-perfect coordination read as an inversion | "The checklist was unavailable and had been reported to the supervisor." | ABSTAIN `CONDITIONAL_CUE` | SUPPORTS |
| negated subject with a determiner missed | "No staff member confirmed the checklist was unavailable." | SUPPORTS | ABSTAIN `ATTRIBUTED_DENIAL` |
| establishing verbs outside the lexicon | "Nobody found that the binder was missing." | SUPPORTS | ABSTAIN |

The first two are the cost of the earlier fixes: sentence-boundary scoping that
kept "In the ward, no one confirmed …" in one clause could not tell a fronted
adverbial from a negated subject, and the inversion detector treated `and had
been moved` as `Had … been`. Both are now distinguished by shape (comma-scoped
negation for the first; a perfect chain after the auxiliary is not a subject for
the second), with the pinned neighbours kept.

## The bug the frame test found in the frame

A worker wrote the module's tests from the spec before the module was wired in, and
found that negation and quantifier were scanned over the **whole prefix** while the
agent was clause-scoped. So

```
"No one said the binder was missing. The auditor documented that the checklist was unavailable."
```

withheld, because sentence one's `No one` was read as governing sentence two's
affirmative evidential frame. Polarity is now read in the verb's own clause on
sentence boundaries, with a neighbour test that a **fronted adverbial**
(`In the ward, no one confirmed that …`) is still inside the clause.

## What would move the labelled sets

The residual benchmark misses are one family: temporal-change rows
(`temp-d1..3`, `temp-h1..2`) plus `quant-d3` and `bound-h2`. A temporal-change
reader is the next rule worth writing; it is not a tuning exercise and the
holdout has not been consulted to write it.

## Reproduce

```bash
cd backend && PYTHONPATH=. python3 -m pytest -q
cd .. && coqc ct3/Attribution.v
cd backend && PYTHONPATH=. python3 -c "import sys; sys.path.insert(0,'tests'); import test_semantic_benchmark as b; print(b.format_report())"
cd .. && PYTHONPATH=. python3 scripts/quality_gate.py    # 7 PASS, exit 0
```
