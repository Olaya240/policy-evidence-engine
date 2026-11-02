# Scope layer and truth interval — what landed, what it cost, what it proves

2026-11-02. Two changes to the reader (scope) and two to the report (interval),
plus one proof file. **Suite: 5081 passed, 14 xfailed, 0 failed.** Nothing
committed.

The wave was asked to make the backend "extremely advanced and engineeringly
perfect". This note records where that is now true, where it is still not, and
one place where the first version of my own proof was about the wrong function.

## 1. The two artifacts that disagreed, and how it was settled

`tests/test_semantic_guard_mood.py` pinned a **fronted conditional's consequent
as asserted**:

```
"If the ward was busy, the checklist was unavailable."   -> SUPPORTS (pinned)
"If the checklist was unavailable, the team should ..."  -> abstain (CONDITIONAL_CUE)
```

`tests/test_stance_algebra_falsification.py` recorded the same reading as
**FALSIFIED**, on the ground that the verdict was decided by which side of the
comma the cue fell on rather than by scope.

Both cannot hold. Settled in favour of the falsification artifact, because the
semantics decide it rather than the tests: a consequent holds only when its
antecedent does, so a guard that commits on it asserts a hypothetical, and the
asymmetry was a punctuation accident. The mood file's pin was rewritten to
abstain, with the reversal written into the file and the anti-over-abstention
guarantee moved onto neighbours that are not conditionals at all (a temporal
`when`, a causal `because`, a new sentence).

This is a product decision and it is reversible in one commit; it is recorded
here rather than only in a diff so the next reader sees the reversal, not two
inconsistent files.

## 2. Four reader fixes, each with the reading that moved

| Defect | Before | After |
|---|---|---|
| `"…, and others say it was available."` (pronoun subject) dropped the opposing clause | `SUPPORTS` | abstains, `AMBIGUOUS_CUE_RELATIONS` |
| `"…, and staff say it was available."` — `staff` read as a *singular* antecedent, so `it` never reached the checklist | `SUPPORTS` | abstains |
| `"…, and the auditor said it was available."` — the nearest-subject proxy handed `it` to the auditor | `SUPPORTS` | abstains |
| `"Notably the checklist was unavailable, …"` — the adverb took the subject slot, disabling resolution | `SUPPORTS` | abstains |

The pronoun rule is now stated as the question the verdict depends on — *is there
a referent in the quotation that names the cue's subject?* — rather than as
nearest-subject, which is a proxy that an intervening animate noun defeats.
Preferring attachment is the fail-safe direction: a derived occurrence either
adds an opposing cue (abstain) or agrees with the lexical match (no change).

Resolution crosses a sentence terminator; operator scope does not. `"The
checklist was unavailable. The auditor said it was available."` is one quotation
asserting both directions, and it now abstains.

## 3. The interval, and the proof that first described the wrong function

`ct3/IntervalReport.v` — Coq 8.18, stdlib only, **zero `Admitted`, zero
`Axiom`**, `Print Assumptions` prints `Closed under the global context` for all
six headline theorems.

It proves, for `lo = score(s, c+dc)` and `hi = score(s+ds, c)`:

- `lo_never_above_hi` — the report is an interval;
- `width_is_the_dispute_term` — **width = 2·(s·dc + c·ds + ds·dc) + ds + dc**;
- `zero_width_means_no_dispute` — the interval is a point **iff** nothing is
  pending, with no exceptional rows;
- four monotonicity theorems, each with the gap named: more support raises both
  bounds by `2(c+dc)+1` and `2c+1`; more contradiction lowers them by `2s+1` and
  `2(s+ds)+1`; each dispute moves exactly one bound, in the widening direction;
- `labels_never_both_fire` — `SUPPORTED` reads the floor, `CONTRADICTED` reads
  the ceiling, and the two cannot both fire.

**The correction worth recording.** My first version proved all of this for
`score(a,b) = (a-b)/(a+b)`. The shipped function is `(a-b)/(a+b+1)`
(`decision_table.score`). The test that compares the implementation to the
model's rationals failed on 435 of 441 rows and is the only reason I know —
the proof compiled, and it compiled about a different function. With the shipped
denominator two things change, and both matter:

- the width term gains `ds + dc`, so a disputed support widens the interval even
  when there are no contradictions (with the bare ratio it could not, and the
  report would have asserted certainty about a challenge nobody settled);
- `zero_width_means_no_dispute` loses its precondition and becomes the statement
  a reader wants.

This is the general shape of the failure the guide exists to catch: a proof is a
statement about the model, and the only thing that ties it to the code is a test
that would fail if the model were wrong.

## 4. Measurements

| | before | after |
|---|---|---|
| suite | 2434 passed, 14 xfailed | **5081 passed, 14 xfailed, 0 failed** |
| new holdout, uncontested | 53/65 = 0.815 | **54/65 = 0.831** |
| new holdout, all rows | 54/70 = 0.771 | **55/70 = 0.786** |
| dev benchmark / old holdout | 57/64 / 34/41 | **unchanged** |
| falsification corpus (20 000 generated) | 9 576 commits, 1 915 wrong | **unchanged** |
| guard pin files | green | **green** (six files, re-run inside the suite) |

The one holdout row that moved is a pronominal opposing clause that had been
dropped — the defect §2 names. The dev split did not move because it contains no
row of that shape, which is why the altered readings first surfaced as two
failing pins rather than as an accuracy change.

## 5. The remaining 20%, named precisely

The falsification corpus is unchanged at **1 915 of 9 576 commits wrong by
construction (20.0%)**, and every one of those is the same class:

```
"No one confirmed that the checklist was unavailable."  ->  SUPPORTS
```

This is not an unknown bug. `CU-MATRIX-DID-NOT-SAY`, `SC-NO-ONE-REPORTED` and
`CU-MATRIX-NEVER-CLAIMED` pin a negated reporting or evidential verb as
certifying the complement — the policy is *content, not attribution*: the guard
reads whether the proposition appears, not whether anyone asserted it. Reversing
it would remove roughly ten points of commit error and requires rewriting those
corpus rows plus six benchmark expectations. That is a product call about what
the tool claims to read, and it has not been made by me.

## 6. What this wave could not do

- **Subagent deployment is unavailable.** Five workers were spawned for this
  wave; every one returned `428 waiting_room_required` before producing
  anything, so the work in this note was done serially in one session. The
  memory fact that once recorded 429s on spawn is stale in mechanism but not in
  outcome: no subagent has run this session.
- **The gate exists and does not certify the tree.** `scripts/quality_gate.py`
  (679 lines) runs seven checks and returns **6 PASS, 0 FAIL, 1 SKIPPED, exit 2 —
  `NOT CERTIFIED`**. The skipped one is the mutation floor: the harness re-runs
  the suite once per mutant and accepts no `--fast` mode, so a gate budget cannot
  pay for it, and the script prints it as `SKIPPED` rather than folding it into a
  pass. **Mutation score is therefore not measured by the gate.** The script also
  did not run at all before this session's last ten minutes — it was written by
  the interrupted wave with an `IndentationError` at `check_no_unproved_steps`,
  which is what "written but never executed" looks like. Fixed; the run above is
  the first.
- **No human labels.** Every semantic number here is agent-labelled against a
  corpus written by agents; the holdout is independent of tuning but not of
  authorship.
- **The live provider has still never executed** (`BASETEN_API_KEY` absent).

## Reproduce

```bash
cd backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q
coqc ct3/Bilattice.v && coqc ct3/IntervalReport.v
PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q \
  tests/test_interval_report_refinement.py tests/test_scope_layer.py
```
