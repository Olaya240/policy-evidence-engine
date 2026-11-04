# Threshold ratification brief — the 4:1 judgement

Status: **not ratified**. The rule is proved; the *choice of threshold* is a policy
decision the maths cannot make. This file exists so the choice costs one line plus one
recompile, not a redesign.

## The rule as shipped

`backend/app/decision_table.py`:

```
MIN_SUPPORT_GROUPS = 2
IMBALANCE_PER_GROUP = 3

SUPPORTED     s >= 2  and  s >= 3c + 1
CONTRADICTED  c >= 3s + 1
INSUFFICIENT  s = c = 0
PARTIAL       otherwise
score(s, c) = (s - c) / (s + c + 1)
```

`s` and `c` are independent source **groups**, not records. The threshold `s >= 3c + 1`
is exactly `score >= 1/2`:

```
2(s - c) >= s + c + 1   <=>   2s - 2c >= s + c + 1   <=>   s >= 3c + 1
```

That is the whole justification for 3 and not 2: the label flips where the signed score
crosses one half. Nothing else in the design depends on the number 3.

## Consequence tables, s, c in 0..6

Legend: `S` SUPPORTED, `P` PARTIAL, `C` CONTRADICTED, `I` INSUFFICIENT.
Rows are `s`, columns are `c`.

### (a) current — 3:1

```
c=0 1 2 3 4 5 6
s=0  I C C C C C C
s=1  P P P P C C C
s=2  S P P P P P P
s=3  S P P P P P P
s=4  S S P P P P P
s=5  S S P P P P P
s=6  S S P P P P P
```

### (b) stricter — any contested claim is PARTIAL

```
c=0 1 2 3 4 5 6
s=0  I C C C C C C
s=1  P P P P P P P
s=2  S P P P P P P
s=3  S P P P P P P
s=4  S P P P P P P
s=5  S P P P P P P
s=6  S P P P P P P
```

### (c) looser — 2:1

```
c=0 1 2 3 4 5 6
s=0  I C C C C C C
s=1  P P P C C C C
s=2  S P P P P C C
s=3  S S P P P P P
s=4  S S P P P P P
s=5  S S S P P P P
s=6  S S S P P P P
```

## Rows that actually differ from (a)

### (b) versus (a) — six rows

| shape | (a) | (b) | score |
|---|---|---|---|
| (4,1) | SUPPORTED | PARTIAL | +0.500 |
| (5,1) | SUPPORTED | PARTIAL | +0.571 |
| (6,1) | SUPPORTED | PARTIAL | +0.625 |
| (1,4) | CONTRADICTED | PARTIAL | −0.500 |
| (1,5) | CONTRADICTED | PARTIAL | −0.571 |
| (1,6) | CONTRADICTED | PARTIAL | −0.625 |

Within 0..6 that is the complete list; beyond it the pattern is every contested shape
with a 3:1-quality imbalance, i.e. everything `(a)` labels decisively while contested.

### (c) versus (a) — six rows

| shape | (a) | (c) | score |
|---|---|---|---|
| (3,1) | PARTIAL | SUPPORTED | +0.400 |
| (5,2) | PARTIAL | SUPPORTED | +0.375 |
| (6,2) | PARTIAL | SUPPORTED | +0.444 |
| (1,3) | PARTIAL | CONTRADICTED | −0.400 |
| (2,5) | PARTIAL | CONTRADICTED | −0.375 |
| (2,6) | PARTIAL | CONTRADICTED | −0.444 |

### Arithmetic, three rows, checked twice

1. **(3,1) under (a).** `3*1 + 1 = 4`, and `s = 3 < 4`, so not SUPPORTED.
   `c = 1 >= 3*3 + 1 = 10`? No. So PARTIAL. Under (c): `2*1 + 1 = 3`, and `3 >= 3`,
   so SUPPORTED. Score `(3-1)/(3+1+1) = 2/5 = 0.400`.
2. **(2,5) under (a).** `5 >= 3*2 + 1 = 7`? No. `s = 2 >= 3*5 + 1 = 16`? No. PARTIAL.
   Under (c): `5 >= 2*2 + 1 = 5`, so CONTRADICTED. Score `(2-5)/(2+5+1) = -3/8 = -0.375`.
3. **(4,1) under (b).** Contested by definition, so PARTIAL. Under (a):
   `3*1 + 1 = 4 <= 4`, so SUPPORTED. Score `(4-1)/(4+1+1) = 3/6 = 0.500`.

Exclusivity survives (c): `s >= 2c+1` and `c >= 2s+1` give `s >= 2(2s+1)+1 = 4s+3`,
impossible for `s >= 0`. It does not need a new idea, only a changed constant.

## The one-line change, and what it breaks

| policy | change in `decision_table.py` | proof impact | tests that change |
|---|---|---|---|
| (b) | replace the two threshold tests with `if s > 0 and c > 0: return PARTIAL, ...` before them | `ct3/DecisionTable.v::v2Status` changes shape; exclusivity becomes trivial, so the model must be rewritten and recompiled | grid tests below, plus every expectation on a contested decisive shape |
| (c) | `IMBALANCE_PER_GROUP = 3` → `2` | constants inside `DecisionTable.v` (`3 * c + 1` → `2 * c + 1`); exclusivity still provable with `lia` | grid tests below |

Tests that hardcode the threshold rather than importing it:

- `backend/tests/test_decision_table.py`, `test_labels_are_exclusive` — `s >= 3 * c + 1`
- `backend/tests/test_decision_table.py`, `test_status_matches_the_thresholds` — same literal

Under (c), any fixture with one of the six differing shapes also changes. I checked the
120-line parametrisation in `tests/test_explanation_trace.py` (largest shape: two items)
and it is unaffected. I did **not** enumerate the evidence counts of the seeded presets in
`tests/test_engine.py` / `tests/test_api.py`, so a preset holding three supports and one
contradiction would change under (c) and is not accounted for here.

## The arguments, honestly

**(a) 3:1.** A 4-support-1-contradiction claim is told SUPPORTED with a score of 0.50 —
half strength, and `contested: true`. The reader is told four independent sources said yes
and one said no. **Against:** the rule cannot see seriousness. A trivial contradiction
("the binder was on the second shelf") and a grave one ("I was in the room, the checklist
was completed and signed") are one count each. Four mediocre sources outvote one
first-hand account, and nothing in the label says so.

**(b) any contest blocks.** Defensible to an auditor in one sentence: *nothing contested is
ever presented as decided.* **Against:** it is not a threshold at all. Ten independent
sources against one stray note is PARTIAL, identical to two against two, so the ranking
signal — the reason a number exists — is thrown away, and reviewers learn to ignore
PARTIAL because everything lands there.

**(c) 2:1.** Closest to "more said yes than no". **Against:** (3,1) is SUPPORTED at 0.40,
below the one-half that motivated the whole rule; the label and the number then disagree
about how settled the claim is, which is the class of defect this work removed.

**The observation none of them can make:** seriousness. If that matters, it belongs in a
`severity` field on the record, not in the count threshold — otherwise the threshold is
being asked to do a job the data does not support.

## Recommendation

**Keep (a)**, and make `contested: true` unmissable wherever a score is shown, so a
contested SUPPORTED never reads as settled. Rationale: (b) destroys the ranking that the
score exists to provide, and (c) lets the label contradict its own number. (a) is the only
one whose label and score agree by construction, which is exactly the property the proof
enforces.

**Defeater — the one observation that should flip this:** if human review overturns
contested SUPPORTED claims at a materially higher rate than uncontested SUPPORTED claims,
then (a) is mislabelling and (b) is correct despite the ranking loss. That measurement
needs the challenge history already stored in `history` (`event = CHALLENGE`), grouped by
whether `contested` was true at the time. Until that number exists, the choice is a
judgement, and this brief is the argument for the judgement, not evidence for it.

— worker 8 of 10. Every label in the three grids was derived from the thresholds by hand
and re-checked; the (c) grid's `(2,5)` and `(2,6)` rows were found on the second pass and
are the two most likely to be miscopied if this file is edited later.
