# XFAIL inventory — every strict xfail in `backend/tests/`, re-checked against the guard

Audit window: 2026-11-02, 15:55–16:20Z. Guard: `backend/app/semantic_guard.py`,
rows: `backend/tests/test_semantic_benchmark.py::KNOWN_MISREADS`.
Re-checking test: `backend/tests/test_xfail_inventory.py`.

A strict xfail is a debt plus a claim about *why* the debt exists. The claim is the
part that rots: a fix lands and the reason string keeps asserting a defect that is
gone, or the row fails for a cause the string does not name, and the next reader
spends a turn fixing the wrong line. This inventory re-reads every row, runs one
counterfactual per row (the test the reason string implies: if it says X causes
the failure, removing X must change the reading), and classes the result:

| class | meaning |
|---|---|
| **a** | still the stated defect — row fails, counterfactual confirms the named cause |
| **b** | fixed but the mark is stale — row passes, so the reason now describes nothing (pytest reports a strict XPASS failure) |
| **c** | wrong for a different reason than stated — row fails, counterfactual does **not** move it |
| **d** | the label, not the guard, is wrong — no row in this set |

## Scope actually found

- `backend/tests/test_semantic_benchmark.py::KNOWN_MISREADS` — **14** strict xfails at
  audit start (all 14 this brief names). 8 remained at the end of the window; see
  *Disposition*.
- `backend/tests/test_semantic_holdout_v2.py` — **0** xfails. The holdout rows the
  brief refers to are `KNOWN_MISREADS` entries whose row lives in that file's split
  (`split=holdout`), not marks in that file. `grep -c xfail` returns 0.
- `backend/tests/test_semantic_guard_negation_corpus.py` — 0 live marks:
  `_KNOWN_UNFIXED = {}` with `pytest.mark.xfail` applied only to ids in it. Its module
  docstring still says "Rows whose expectation the guard does not meet are left
  failing on purpose" — doc drift, reported here, not edited.
- `backend/tests/test_attribution_boundary.py` — created this turn by another worker
  (untracked), carries 2 strict xfail marks covering 5 parametrised cases
  (post-verbal negation; coordinated conjunct). **Not audited**: the file was being
  written during this window. Out of scope.

## Inventory

Reading = `reviewed_relation_details(row.sentence, row.hypothesis)`, `None` folded to
`ABSTAIN`; reason code in parentheses.

| # | id | split | label | guard reading | class | stated reason (verbatim) | counterfactual that decides it |
|---|---|---|---|---|---|---|---|
| 1 | quant-d3 | dev | ABSTAIN | SUPPORTS (–) | **a** | `'that' disables the quantifier rule, so a denied sighting certifies SUPPORTS` | "Nobody saw the binder was missing." (no *that*) → ABSTAIN ✔ |
| 2 | temp-d1 | dev | CONTRADICTS | ABSTAIN (CONTRAST_CHANGED_CURRENT_STATE) | **a** | `safe abstention: 'available now' supersedes the cue` | first clause alone → SUPPORTS ✔ |
| 3 | temp-d2 | dev | CONTRADICTS | SUPPORTS (–) | **c** | `unsafe: 'any more' is not the 'anymore' token the current-state pattern reads` | "…not short staffed **anymore**" → SUPPORTS ✘ (still) |
| 4 | temp-d3 | dev | CONTRADICTS | ABSTAIN (CONTRAST_CHANGED_CURRENT_STATE) | **a** | `safe abstention: 'at the desk now' supersedes the cue` | first clause alone → SUPPORTS ✔ |
| 5 | temp-h1 | holdout | CONTRADICTS | ABSTAIN (CONTRAST_CHANGED_CURRENT_STATE) | **a** | `safe abstention: 'working normally today' supersedes the cue` | first clause alone → SUPPORTS ✔ |
| 6 | temp-h2 | holdout | SUPPORTS | CONTRADICTS (–) | **a** | `unsafe: supersession across a semicolon is invisible, so yesterday's state certifies` | same clauses joined by ", but" → ABSTAIN ✔ |
| 7 | hedge-h3 | holdout | ABSTAIN | SUPPORTS (–) | **c** | `residual: a hedge after the cue is outside the pre-cue hedge rule` | "…, **probably**." → ABSTAIN (HEDGED_CUE) ✘ (position is not the cause) |
| 8 | rept-d1 | dev | ABSTAIN | ABSTAIN (ATTRIBUTED_DENIAL) | **b** | `unsafe, pinned by the negation corpus: a negated report certifies the complement` | row now passes; reason describes a closed defect |
| 9 | rept-d2 | dev | ABSTAIN | ABSTAIN (ATTRIBUTED_DENIAL) | **b** | `unsafe, pinned by the negation corpus: a denied claim certifies the complement` | row now passes |
| 10 | rept-d3 | dev | ABSTAIN | ABSTAIN (ATTRIBUTED_DENIAL) | **b** | `unsafe, pinned by the negation corpus: a denied mention certifies the complement` | row now passes |
| 11 | rept-h1 | holdout | ABSTAIN | ABSTAIN (ATTRIBUTED_DENIAL) | **b** | `unsafe, pinned by the negation corpus: a denied report certifies the complement` | row now passes |
| 12 | rept-h2 | holdout | ABSTAIN | ABSTAIN (ATTRIBUTED_DENIAL) | **b** | `unsafe, pinned by the negation corpus: a missing note certifies the complement` | row now passes |
| 13 | cond-h2 | holdout | ABSTAIN | SUPPORTS (–) at audit start | **a** | `unsafe: an inverted subjunctive is certified as if asserted` | "If the ward was short staffed, …" → ABSTAIN (CONDITIONAL_CUE) ✔ |
| 14 | bound-h2 | holdout | SUPPORTS | ABSTAIN (NEGATED_CUE) | **a** | `safe abstention: the quantifier rule reaches across a clause boundary` | "The clerk had seen the binder before, yet …" → SUPPORTS ✔ |

Counts at first full measurement (all 14 marked): **a = 7, b = 5, c = 2, d = 0.**

## Evidence, row by row

1. **quant-d3** — `_is_quantified_negation` returns `False` when an explicit `that`
   sits between quantifier and cue (`semantic_guard.py`, the complementiser guard).
   The only difference between this row and the passing corpus row `CU-NOBODY-SAW`
   is `that`, and dropping it flips the reading to ABSTAIN. Reason is exact.
2–5. **temp-d1 / temp-d3 / temp-h1** — `_has_later_current_change` sees the `but`
   contrast and a current-state marker, so the clause is withheld with
   `CONTRAST_CHANGED_CURRENT_STATE`. The reason calls this "safe abstention" and it
   is: the guard declines to certify either direction where the label certifies the
   current state. Removing the superseding clause restores SUPPORTS in all three,
   which is what the reason says happened. Still owed, reason accurate.
6. **temp-h2** — `_has_later_current_change` looks for `but|however` after the cue
   end; a semicolon supplies neither, so the cue's clause is read as the only
   assertion and the superseded state is certified. Replacing `;` with `, but`
   yields ABSTAIN. Reason accurate, and this is the unsafe direction.
7. **hedge-h3** — the reason blames word order, but a postposed-hedge reader
   (`_POSTPOSED_HEDGE` / `_is_postposed_hedge`) exists and works: "…, probably."
   abstains with `HEDGED_CUE`. The actual cause is that `I think` is in neither
   `_HEDGE_FRAME` nor `_POSTPOSED_HEDGE`, so it also certifies in the **pre-cue**
   position ("I think the checklist was unavailable." → SUPPORTS). See *Worst reason*.
8–12. **rept-d1/d2/d3/h1/h2** — at audit start these certified the complement and
   failed; the in-flight speech-act policy reversal (`app/evidence_frames.py`,
   `withholds()` gaining `SPEECH_ACT_VERBS`, landed 15:58Z) made all five abstain,
   and their marks were deleted at 16:12Z. The reason string was true when written:
   the negation corpus did pin this reading (`CU-NO-ONE-SAID`, `CU-NOBODY-CLAIMED`,
   `SC-NO-ONE-REPORTED`, `CU-MATRIX-SUPERVISOR` were green asserting it) — the pin
   was then reversed in the same change, so the reason became false.
13. **cond-h2** — the reason names exactly what failed: `If the ward was short
    staffed, …` abstains with `CONDITIONAL_CUE`, the inverted form certified. The
    conditional-inversion reader landed during this window: the row now reads
    ABSTAIN and the comment replacing the entry says so. Closed, not stale-but-lying.
14. **bound-h2** — the cue's prefix clause extends back to the sentence start (only
    `.`/`;`/newline bound it, not `, yet`), so `No one` scopes over the cue's verb
    and the clause is withheld with `NEGATED_CUE`. Replacing `No one` with `The
    clerk` certifies. Reason accurate.

## The single most misleading reason string

> `temp-d2`: **"unsafe: 'any more' is not the 'anymore' token the current-state pattern reads"**

It is false about the code and false about the fix. `_CONTRASTING_CURRENT_NEGATION`
(`semantic_guard.py:36-41`) *does* read `anymore` — it is one of the four accepted
trailing markers (`now|anymore|currently|today`). The pattern is anchored `^\s*` and
allows at most one optional auxiliary before `not`, so what it cannot cross is the
explicit subject + auxiliary in **"it is not short staffed anymore"**; the sentence
is not failing on a token spelling at all. The counterfactual proves it: swapping in
`anymore` leaves the row at SUPPORTS, and `… but not short staffed anymore.` (subject
elided) is the form that starts to abstain. A reviewer acting on the reason would
edit the token list, re-run, and see nothing change — the worst failure mode for a
debt note, because it costs a turn and leaves the row where it was.

Runner-up: `hedge-h3` ("a hedge after the cue is outside the pre-cue hedge rule"),
which names a gap that a dedicated rule already closes; its real cause is a missing
hedge phrase, and the pre-cue form fails too.

## What another worker does this turn

- **Speech-act policy** (`app/evidence_frames.py`): fixes rept-d1/d2/d3/h1/h2 =
  entries 8–12. Landed 15:58Z; marks deleted 16:12Z. When it landed, the negation
  corpus's four *CERTIFIES* speech-act rows and its `_KNOWN_UNFIXED`-free docstring
  went red (8 corpus failures observed at 16:00Z) until the corpus was updated too.
- **Conditional-inversion reader** (`app/semantic_guard.py`): fixes cond-h2 =
  entry 13. Landed by 16:10Z, mark deleted, benchmark row green.
- temp-d2 and hedge-h3 (entries 3 and 7) were closed after this window: temp-d2's
  reason was rewritten to the measured cause ("both spellings now abstain: the
  contrast reader accepts a subject and 'any more' as well as 'anymore'") and
  hedge-h3's defect was fixed, so the row is green and its mark is gone. Neither is
  open on the 2026-11-03 tree.

## Re-running the check

```bash
cd backend
PYTHONPATH=. python3 -m pytest tests/test_xfail_inventory.py -q -rs
PYTHONPATH=. python3 -m pytest tests/test_semantic_benchmark.py::test_benchmark_row_matches_label -rxX
```

- Measured 2026-11-03: `12 passed, 6 skipped, 0 failed`. The two fiction classes
  this audit found (temp-d2's wrong reason, hedge-h3's missing hedge phrase) are
  closed; the six skips are entries whose mark is gone (five rept rows, cond-h2),
  each naming which.
- After a **fix**: delete the `KNOWN_MISREADS` entry, then delete the row from
  `AUDIT` and this table (a removed mark whose row still fails fails
  `test_a_removed_mark_does_not_hide_a_live_defect`).
- After a **reason rewrite**: update `AUDIT[rid].reason` too, or
  `test_recorded_reason_matches_what_the_mark_says` fails.
- A **new** strict xfail anywhere in `KNOWN_MISREADS` fails
  `test_every_live_mark_has_an_audit_record` until it is inventoried — that is the
  point: new debt may not arrive without a stated, checked reason.
- The audit is measured against the guard, not against a frozen snapshot; the
  reading/reason-code columns here are what was seen in this window.
