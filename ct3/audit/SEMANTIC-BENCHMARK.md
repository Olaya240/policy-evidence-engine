# Semantic guard benchmark — what the accuracy number actually is

Workstream: the phrase cue guard's accuracy was **unmeasured**. The only figure in the tree
was 2 of 3 committed verdicts on a 12-row table (`ct3/audit/W9-negation-corpus.md`); nothing
said what the guard does across the shapes that routinely appear in record quotes.

This document is the measurement, the one fix the measurement justified, and the list of
misreads left in place with reasons.

Files:

* `backend/tests/test_semantic_benchmark.py` — **new**: 105 labelled sentences, the frozen
  dev/holdout split, the scoring helper, the neighbour pins, and the defect register.
* `backend/app/semantic_guard.py` — **changed**: one rule (`_HEDGE_FRAME`, `_is_hedged`, the
  `HEDGED_CUE` reason code). Nothing else in the module was touched.
* this document — **new**.

Question in one sentence: **when the guard certifies `SUPPORTS` or `CONTRADICTS` from a
quote, how often is that the direction a careful reviewer would certify, and when it
abstains, how often should it have certified?**

The answer turns on two sub-questions, and both are measured below:

1. How often does it **certify a direction for a sentence that asserts none** — a question, a
   conditional, a hedge, a negated report?
2. How often does it **abstain on a sentence that does assert one** — contrast, temporal
   supersession, a cue reached only through a negated other clause?

## 1. The benchmark

| Property | Value |
|---|---|
| Rows | **105** |
| Dev | **64** (61.0%) |
| Holdout | **41** (39.0%) |
| Phenomena | **18** tags: the twelve named classes plus plain assertion, plain negation, quoted speech, clause-boundary negation, neutral cue, polarity list |
| Rows per tag | ≥ 3, and every named class appears on **both** splits |

Every row carries: `id`, `split`, `tag`, `sentence`, `hypothesis`, `expected`
(`SUPPORTS` / `CONTRADICTS` / `ABSTAIN`), and a one-line `justification` a reader can
disagree with. The rows are in `ROWS` in the test module, in file order.

### Labelling protocol

A row is directional only when the sentence **asserts** the hypothesis's cue proposition (or
its denial) about the world, under three charter rules:

1. **Assertion, not mention.** A question, conditional, hedge, or negated report does not
   assert the proposition → `ABSTAIN`.
2. **No flipping.** A sentence whose cue is negated is `ABSTAIN`, not the opposite direction.
   The guard's charter is that it never infers a flip; where a human could reason the flip
   out, the label still records what the guard may certify.
3. **One direction.** Two opposite cues in one sentence, or a cue whose scope over the clause
   is undecidable from the words → `ABSTAIN`.

`ABSTAIN` means a careful reviewer would not certify a direction.

**`NEUTRAL` is folded into `ABSTAIN` for scoring.** The guard can return its explicit
`NEUTRAL` relation for the "says nothing about availability" cues; that certifies no
direction, so it scores as `ABSTAIN`. Three rows (`neut-d1`, `neut-d2`, `neut-h1`) are scored
this way; no other row reaches `NEUTRAL`.

### The split was frozen before any measurement

The `split` field is part of each row and was committed in the same edit that wrote the
labels, before the guard was executed against any of them. `test_benchmark_is_large_enough_and_the_split_is_frozen`
pins the exact counts (64 / 41). The holdout half has been measured **once**, after the fix
in §3. It was not re-split, re-labelled, or tuned against.

### One thing the benchmark does not cover

Every row must match a committed cue phrase (`test_every_row_matches_a_cue`). That is
deliberate — the benchmark measures the guard's **reading**, not its cue inventory's coverage
of paraphrase — but it means the 105 rows say nothing about the share of real quotes that
contain no cue at all. That share is a separate, unmeasured quantity.

## 2. Dev, before and after the fix

Measurement command:

```
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_semantic_benchmark.py
```

The numbers below come from `format_report()`, the same code path the pin executes.

| Split | Correct / total | Accuracy |
|---|---|---|
| dev, before the fix | 45 / 64 | **0.703** |
| dev, after the fix | 50 / 64 | **0.781** |
| holdout, measured once after the fix | 31 / 41 | **0.756** |

The pre-fix dev row is a reconstruction against the same row set: the new predicate was
disabled (`semantic_guard._is_hedged = lambda clause: False`) and the rest of the guard left
alone. The first dev run, before one row was corrected, gave 46/64 = 0.719; that row
(`q-d4`) was spelled "Was the checklist available…", which matched **no cue** and therefore
abstained for the wrong reason (`NO_CUE_MATCH`), and `test_every_row_matches_a_cue` caught
it. It was re-spelled to "Was anyone told that the checklist was unavailable?" — same
phenomenon, cue actually present — and the pre-fix figure recomputed. 45/64 is the number to
quote.

### Confusion matrices

Dev, before the fix:

| expected \ observed | SUPPORTS | CONTRADICTS | ABSTAIN |
|---|---:|---:|---:|
| SUPPORTS (18) | 18 | 0 | 0 |
| CONTRADICTS (13) | 1 | 10 | 2 |
| ABSTAIN (33) | 15 | 1 | 17 |

Dev, after the fix:

| expected \ observed | SUPPORTS | CONTRADICTS | ABSTAIN |
|---|---:|---:|---:|
| SUPPORTS (18) | 18 | 0 | 0 |
| CONTRADICTS (13) | 1 | 10 | 2 |
| ABSTAIN (33) | 10 | 1 | 22 |

Holdout, after the fix (single measurement):

| expected \ observed | SUPPORTS | CONTRADICTS | ABSTAIN |
|---|---:|---:|---:|
| SUPPORTS (15) | 13 | 1 | 1 |
| CONTRADICTS (5) | 0 | 4 | 1 |
| ABSTAIN (21) | 7 | 0 | 14 |

### Per-class precision and recall

| Split | SUPPORTS precision | SUPPORTS recall | CONTRADICTS precision | CONTRADICTS recall | ABSTAIN precision | ABSTAIN recall |
|---|---|---|---|---|---|---|
| dev before | 0.53 (18/34) | 1.00 (18/18) | 0.91 (10/11) | 0.77 (10/13) | 0.89 (17/19) | 0.52 (17/33) |
| dev after | 0.62 (18/29) | 1.00 (18/18) | 0.91 (10/11) | 0.77 (10/13) | 0.92 (22/24) | 0.67 (22/33) |
| holdout | 0.65 (13/20) | 0.87 (13/15) | 0.80 (4/5) | 0.80 (4/5) | 0.88 (14/16) | 0.67 (14/21) |

Read the holdout `CONTRADICTS` row with its denominator: **five** labelled rows. It is a
precision figure, not a ranking, and the benchmark is too small to move it on its own.

## 3. The fix: the highest-frequency misread class on dev

**Class: `hedge` — 5 of 64 dev rows, 5 misreads, all in the dangerous direction.**

| Row | Sentence | Label | Pre-fix output |
|---|---|---|---|
| hedge-d1 | Perhaps the checklist was unavailable during the ward round. | ABSTAIN | SUPPORTS |
| hedge-d2 | It is possible the system timed out during the save. | ABSTAIN | SUPPORTS |
| hedge-d3 | Probably the ward was short staffed that evening. | ABSTAIN | SUPPORTS |
| hedge-d4 | It seems that the checklist was unavailable. | ABSTAIN | SUPPORTS |
| hedge-d5 | Presumably the colleague was unsure about the medication round. | ABSTAIN | SUPPORTS |

A sentence-initial epistemic adverbial proposes the proposition; it does not assert it. The
guard read the cue and certified the direction, so a **possibility became a finding** — the
one error shape that can flip a verdict downstream.

The fix is `_HEDGE_FRAME` / `_is_hedged` in `app/semantic_guard.py`: markers
`perhaps | possibly | probably | maybe | presumably | apparently | conceivably`,
`it seems / it appears`, `it is (was) possible / likely / probable`, read **in the cue's own
comma segment, to the left of the cue only**. A rejected cue reports `HEDGED_CUE`.

Scope is deliberately narrow, and each boundary is a reason it does not widen:

* **Not `may` / `might`.** They almost always sit *inside* the fixed phrase ("may have been
  unavailable"), which breaks cue contiguity and already abstains as `NO_CUE_MATCH`.
* **Not bare `could`.** `could` is a cue word — "could not review every open item" is a
  `TIME_PRESSURE` `SUPPORTS` cue.
* **Not across a comma.** "Perhaps the ward was busy, and the checklist was unavailable"
  still certifies: the hedge is in the previous clause, not over the cue.
* **Not after the cue.** A postposed hedge is outside the rule. `hedge-h3`
  ("The checklist was unavailable, I think.") is left in the benchmark as a **known
  residual** rather than removed from the measurement.

### Neighbour pins (must NOT abstain)

Six rows in `HEDGE_NEIGHBOURS`, each asserted to certify a direction:

| Sentence | Hypothesis | Must certify |
|---|---|---|
| The team could not review every open item before the deadline. | TIME_PRESSURE | SUPPORTS |
| The shift had enough time to review every open item. | TIME_PRESSURE | CONTRADICTS |
| No one could confirm that the checklist was unavailable. | CHECKLIST_UNAVAILABLE | SUPPORTS |
| Perhaps the ward was busy, and the checklist was unavailable. | CHECKLIST_UNAVAILABLE | SUPPORTS |
| The checklist was unavailable, though perhaps the binder was at the desk. | CHECKLIST_UNAVAILABLE | SUPPORTS |
| There is no doubt the binder was missing. | CHECKLIST_UNAVAILABLE | SUPPORTS |

The last one is the "no doubt" neighbour: an explicit certainty must not be read as a hedge.
A seventh pin,
`test_a_hedged_row_abstains_with_its_own_reason_and_still_cites_the_cue`, asserts that a
hedged row abstains with `HEDGED_CUE` and still cites the cue it read — an abstention that
matched nothing would be safe for the wrong reason.

## 4. Holdout, measured once, as it came out

**31 / 41 = 0.756.** Ten misreads:

| Row | Tag | Expected | Seen | Direction |
|---|---|---|---|---|
| temp-h1 | temporal-change | CONTRADICTS | ABSTAIN | safe |
| temp-h2 | temporal-change | SUPPORTS | CONTRADICTS | **unsafe** |
| hedge-h3 | hedge | ABSTAIN | SUPPORTS | **unsafe** (declared residual of this fix) |
| q-h1 | cue-in-question | ABSTAIN | SUPPORTS | **unsafe** |
| q-h2 | cue-in-question | ABSTAIN | SUPPORTS | **unsafe** |
| rept-h1 | negated-reporting-verb | ABSTAIN | SUPPORTS | **unsafe** |
| rept-h2 | negated-reporting-verb | ABSTAIN | SUPPORTS | **unsafe** |
| cond-h1 | conditional | ABSTAIN | SUPPORTS | **unsafe** |
| cond-h2 | conditional | ABSTAIN | SUPPORTS | **unsafe** |
| bound-h2 | clause-boundary-negation | SUPPORTS | ABSTAIN | safe |

The holdout figure is **lower** than dev (0.756 vs 0.781) and is reported that way.

That gap is not a sign the fix was fitted to dev, and the discriminator is the composition of
what is left: **12 of 64 dev rows (18.8%)** and **8 of 41 holdout rows (19.5%)** are *unsafe*
misreads — the guard certifying a direction the label does not. Counted separately, 2 dev and
2 holdout rows are *safe* abstentions (the guard declines where the label certifies). The one
rule this wave added — the pre-cue hedge frame — also fixed both pre-cue hedge rows on
holdout (`hedge-h1`, `hedge-h2`), which were never run before the fix. The residual unsafe
rate is the same on both halves because the *unfixed* classes are the same classes, not
because holdout rewarded dev.

## 5. Misreads not fixed, with reasons

| Class | Dev | Holdout | Why not fixed |
|---|---:|---:|---|
| cue-in-question | 4 | 2 | **Next-largest unsafe class; deferred.** Fixing it needs a second rule (interrogative clause detection), and this wave committed to one fix so that the single holdout measurement tests that fix. Listed as the next action, not as a pass. |
| conditional | 3 | 2 | **Deferred.** `if` / `unless` / inverted-subjunctive detection is a second rule with its own neighbour set; same reason as above. |
| negated-reporting-verb | 3 | 2 | **Cannot be fixed without contradicting three committed pins.** `test_semantic_guard_negation_corpus.py` deliberately pins the opposite reading with a written rationale: `CU-MATRIX-DID-NOT-SAY` ("did not say the binder was at the desk" → CONTRADICTS), `CU-MATRIX-NEVER-CLAIMED` (→ CONTRADICTS), `SC-NO-ONE-REPORTED` (→ SUPPORTS). Those rows assert that a negated speech-act verb negates the *saying*, not the complement, and therefore still certifies the cue. This benchmark's charter rule 1 says a negated report asserts nothing, so it labels the same shape `ABSTAIN`. **The two readings disagree and both are written down.** I reported the conflict and did not edit the corpus rows; these five rows stay as strict xfails. |
| temporal-change | 3 | 3 | Two shapes. (a) **Safe abstention** (`temp-d1`, `temp-d3`, `temp-h1`): the later clause supersedes the cue and the guard abstains where the label certifies the current state. Fixing this means making the guard *flip* to the current direction, which its charter forbids. (b) **Unsafe** (`temp-d2`, `temp-h2`): the two-word "any more" is not the `anymore` token the current-state pattern reads, and supersession across a semicolon is invisible. That is a lexical gap in a rule that already exists, on 2 rows — below the class fixed here, and left alone so the wave's holdout test stayed a test of one change. |
| quantifier-negation | 1 | 0 | `quant-d3` ("Nobody saw **that** the binder was missing") — the complementiser `that` disables the quantifier rule, and the sentence is certified SUPPORTS. The `that` test is what protects the deliberate "No one said **that** X" reading, so narrowing it for one row would trade a written design choice for one row of accuracy. |
| hedge (post-cue) | 0 | 1 | `hedge-h3` is the declared scope boundary of this wave's own fix (§3). |

Totals: 14 dev misreads (12 unsafe, 2 safe), 10 holdout misreads (8 unsafe, 2 safe).

## 6. What was re-run, and what it says

The four committed guard pin files, re-run after the change:

```
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_semantic_guard_negation_corpus.py tests/test_semantic_guard_slice18.py tests/test_attack_surfaces_guard_reading.py tests/test_semantic_guard_verb_negation.py
........................................................................ [ 59%]
..................................................                       [100%]
122 passed in 0.36s
```

The corpus list holds 53 rows; with the module's other tests the four files contribute 122
tests, all passing and unchanged.

The guard-adjacent suites (they call `reviewed_relation` through the engine):

```
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_engine.py tests/test_engine_slice8_trace.py tests/test_evaluate_contracts.py tests/test_explanation_trace.py
........................................................................ [ 50%]
.......................................................................  [100%]
143 passed in 1.43s
```

The whole backend suite:

```
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q
2166 passed, 24 xfailed, 1 warning in 34.39s
```

1959 passed before this wave; the delta is this module's 207 passing tests, and the 24 xfailed
are the benchmark's own known misreads (§5). They are `strict=True` xfails: if a later fix makes
one pass, pytest fails on the XPASS and the marker has to be deleted with the defect, so the
register cannot go quiet.

## 7. What this does not establish

* **The labels are one author's.** 105 synthetic sentences, one justification each, all
  arguable. A reader who disagrees with a row can see exactly which row and why.
* **The holdout denominator is 41**, of which `CONTRADICTS` is 5. Precision and recall on
  that class are reported with their denominators because they are thin.
* **No real record quotes.** The benchmark does not estimate performance on the corpus the
  product actually ingests, and it says nothing about the share of quotes with no cue at all.
* **It scores the guard, not the verdict.** Whether a certified direction wrongly flips a
  policy decision downstream is `decision_table`'s behaviour, and this document makes no
  claim about it.
* **No property or fuzz testing of the new regex.** The hedge frame is pinned by 8 hedge rows
  and 7 neighbours, which is coverage, not proof.


## Correction (same day, after `CUE_IN_QUESTION` and `CONDITIONAL_CUE`)

The figures above were measured **before** two abstention rules existed in
`app/semantic_guard.py`, and they no longer describe the module in the tree. Re-measured
numbers, same rows, same split:

| | before the two rules | after |
|---|---|---|
| dev accuracy | 50/64 = 0.781 | **57/64 = 0.891** |
| holdout accuracy | 31/41 = 0.756 | **34/41 = 0.829** |
| strict xfails | 24 | **14** |

Deleted xfail markers, each because its row now abstains for the right reason (the cue is
still cited, the reason code is `CUE_IN_QUESTION` or `CONDITIONAL_CUE`, not `NO_CUE_MATCH`):
`q-d1 q-d2 q-d3 q-d4 q-h1 q-h2 cond-d1 cond-d2 cond-d3 cond-h1`. `cond-h2` ("Were the ward
short staffed, agency staff would cover the shift") stays xfail: an unmarked subjunctive
inversion has no `if/when/unless` marker, so the stated rule does not reach it.

The holdout column above is reported, not used: no rule was chosen by looking at it.

## A second, independent holdout

A fresh 70-row set was written after the holdout above had been read, with its own digest and
its own scorer (`tests/test_semantic_holdout_v2.py`, `SEMANTIC-HOLDOUT-V2.md`). Headline,
contested rows excluded: **53/65 = 81.5%**. All 70 rows: 54/70 = 77.1%. Five rows are
contested and are reported separately rather than folded into the number.

The number that belongs beside 81.5%: **an always-abstain guard scores 38/65 = 58.5%** on that
set, because the phenomenon list is abstention-heavy. Accuracy alone therefore flatters a
conservative guard; the unsafe-misread rate is the figure to watch, and it is 15/65 ≈ 23% on
that set.

Independence is qualified in the v2 artifact: reading the older benchmark's structure exposed
five of its tags before the new rows were written. Thirteen of eighteen tags are clean.
