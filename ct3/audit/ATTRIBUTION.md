# Attribution frames — the evidential/speech-act split, and what it bought

2026-11-02, second wave. The decision you picked (A) plus the first slice of the
typed reader (B). **Suite: 5 127 passed, 0 failed, 14 xfailed** (58.0 s).
`ct3/Attribution.v`: 23 theorems, `coqc` exit 0, all six `Print Assumptions`
closed.

## The defect, stated as one sentence with two spellings

```
"The auditor did not confirm that the checklist was unavailable."   -> abstains
"No one confirmed that the checklist was unavailable."              -> SUPPORTS
```

One construction, two verdicts, decided by which word did the negating. The
regex could see `not`, and could not see `no one`. That single gap was **1 915 of
9 576 commits wrong by construction (20.0%)** on the falsification corpus — the
whole remaining error class in my previous report.

## What replaced the regex

`backend/app/evidence_frames.py`: a typed `Attribution(agent, quantifier,
polarity, verb_class)` read from the verb's own clause, and one total function

```
force(attribution) = WITHHOLDS  when verb_class = evidential and effective negation
                   = ASSERTS    otherwise
effective negation = explicit negation, or a `none` quantifier over the subject
```

and composition as the **meet** over a prefix: one withholding clause withholds the
proposition, `ASSERTS` is the identity, and no frame recognised returns `None`
rather than `WITHHOLDS` — the caller falls back to the lexical reading instead of
abstaining on every sentence whose scaffolding it does not know.

`ct3/Attribution.v` proves the algebra, not the English:

| Theorem | Statement |
|---|---|
| `force_withholds_iff` | the rule as an equation, both directions |
| `quantifier_and_polarity_agree` | `no one confirmed` and `did not confirm` are one rule |
| `force_extensional` | force depends only on class and effective negation |
| `compose_app` | a prefix splits into two prefixes whose forces meet |
| `compose_withholds_iff` | a prefix withholds **iff** some frame in it withholds |
| `compose_is_monotone` | appending clauses can only lose force |
| `withholding_is_not_rescuable` | nothing appended after a denial restores assertion |
| `withdrawn_requires_a_frame` | `None` (no frame) is not `WITHHOLDS` |
| `meet_is_glb` | the meet is the greatest lower bound, so the order is a lattice |

**What is not proved, and must not be read into the file:** that the evidential
class is the right class to withhold on. That split is a product policy — deny an
establishing act, keep a denied speech act certifying — and the corpus still counts
the rows the policy gets wrong.

## Measured

| | before | after |
|---|---|---|
| falsification commits | 9 576 | **8 604** |
| wrong by construction | 1 915 (20.0%) | **943 (11.0%)** |
| recall / misses / flips | 100% / 0 / 0 | **100% / 0 / 0** |
| remaining class | QUANTIFIER (two constructions) | **QUANTIFIER (one: a denied speech act)** |
| dev benchmark | 57/64 | **57/64** |
| old holdout | 34/41 | **34/41** |
| new holdout (uncontested / all) | 54/65 / 55/70 | **54/65 / 55/70** |

The labelled sets did not move. That is the honest reading of this wave: the rule
fixed a construction that the dev and holdout splits do not contain, so it shows up
on the adversarial corpus and nowhere else. Reporting "+0.0 on the holdout, −9
points of error on the hostile set" is the whole result, and dressing the second
number as the first would be the mistake this repository exists to avoid.

## The bug the frame test found in the frame

A worker wrote the module's tests from the spec before the module was wired in, and
found that negation and quantifier were scanned over the **whole prefix** while the
agent was clause-scoped. So

```
"No one said the binder was missing. The auditor documented that the checklist was unavailable."
```

withheld, because sentence one's `No one` was read as governing sentence two's
affirmative evidential frame. Verdict-changing, and exactly the same class of
defect as the one being fixed, one level up. Polarity is now read in the verb's own
clause on sentence boundaries, with a neighbour test that a **fronted adverbial**
(`In the ward, no one confirmed that …`) is still inside the clause — scoping to the
last comma would have lost the quantifier.

## The corpus rows this reversed

| Row | Was | Now | Why |
|---|---|---|---|
| `CU-MATRIX-CONFIRM` ("No one could confirm that …") | CERTIFIES SUPPORTS | `ATTRIBUTED_DENIAL` | denying the establishment denies the establishment |
| `test_the_evidential_rule_does_not_swallow_a_quantified_denial` | asserts neighbour | split into the rule's own row + two neighbours | the old name described a rule that no longer exists |
| benchmark `HEDGE_NEIGHBOURS` entry | SUPPORTS | replaced by `The auditor confirmed that …` | that row was the defect, not a neighbour |

Rows for **denied speech acts** are untouched and still certify by policy:
`CU-MATRIX-DID-NOT-SAY`, `CU-MATRIX-NEVER-CLAIMED`, `SC-NO-ONE-REPORTED`,
`CU-MATRIX-SUPERVISOR`. They are the 943.

## What would remove the other 11%

One rule: a denied speech act stops certifying its complement. It costs four corpus
rows and their neighbours, and it is the same argument as above — *nobody reported
X* is an absence of evidence, and certifying SUPPORTS from silence is the failure
mode a policy-evidence tool exists to prevent. I did not do it, because you picked
the evidential rule and this one changes what the tool claims about reported
evidence, which is a wider promise than "fix the quantifier". Say the word and it is
an hour.

## Reproduce

```bash
cd backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q
coqc ct3/Attribution.v
PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_evidence_frames.py
```
