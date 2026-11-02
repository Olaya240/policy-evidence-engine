# W9 — negation corpus for `_is_negated` (`app/semantic_guard.py`)

Worker 9 of 10. Owned file: `backend/tests/test_semantic_guard_negation_corpus.py`
(47 tests: 45 corpus rows + 2 corpus-shape tests). No `app/` file or other test
file was touched.

Decision this feeds: whether the widened `_is_negated` — a second regex
(`_NEGATED_AUXILIARY_SUFFIX`) matching a negation carried by an auxiliary
(`did not have`, `don't have`, `was not be`) — may ship. The fix is only good if
it abstains on true clause negation **and** never suppresses a cue that a
`not`/`no`/`never` elsewhere in the sentence does not actually negate.

## Verdict

The widening is correct on this corpus in both directions: **no over-trigger was
found.** All 27 non-negation rows still certify their cue's stance with no reason
code, and 16 of the 18 true negation rows abstain with `NEGATED_CUE` — including
all 7 auxiliary-carried ones (`did not have`, `don't have`, `didn’t have`,
`does not have`, `never had`), which is exactly the shape the widening was
added for.

Two rows fail, and both are a **different, pre-existing** gap, not the widening:
a negation carried by *quantifier over the cue's subject* (`Nobody walked
through …`, `No one was short staffed`) is not adjacent to the cue, so the clause
suffix still looks un-negated and the cue is **certified in the affirmative
direction the sentence denies**. That is a false certification of a negated cue
— the opposite failure mode from over-triggering, and it predates this fix
(`_NEGATION_SUFFIX` alone has the same behaviour; the widening neither causes nor
covers it). The two failing assertions are left as-is.

## Run (verbatim)

```
$ cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_semantic_guard_negation_corpus.py
..................FF...........................                          [100%]
=================================== FAILURES ===================================
__________________ test_negation_corpus_row[TG-NOBODY-WALKED] __________________

sentence = 'Nobody walked through the handover with her.'
hypothesis_id = 'TRAINING_GAP', expected_relation = None
expected_reason = 'NEGATED_CUE', kind = 'NEGATED'

    @pytest.mark.parametrize(
        "sentence,hypothesis_id,expected_relation,expected_reason,kind", _CASES
    )
    def test_negation_corpus_row(sentence, hypothesis_id, expected_relation,
                                 expected_reason, kind):
        detail = reviewed_relation_details(sentence, hypothesis_id)
>       assert detail["relation"] == expected_relation, (
            f"{kind} row expected relation {expected_relation!r} for {sentence!r}; "
            f"got {detail['relation']!r} with reason {detail['reason_code']!r} "
            f"and cues {detail['cue_ids']!r}"
        )
E       AssertionError: NEGATED row expected relation None for 'Nobody walked through the handover with her.'; got <Stance.SUPPORTS: 'SUPPORTS'> with reason None and cues ['TRAINING_GAP.SUPPORTS.walked_through_the_handover']
E       assert <Stance.SUPPORTS: 'SUPPORTS'> == None

tests/test_semantic_guard_negation_corpus.py:175: AssertionError
___________________ test_negation_corpus_row[SC-NO-ONE-WAS] ____________________

sentence = 'No one was short staffed.', hypothesis_id = 'STAFFING_CONSTRAINTS'
expected_relation = None, expected_reason = 'NEGATED_CUE', kind = 'NEGATED'

    @pytest.mark.parametrize(
        "sentence,hypothesis_id,expected_relation,expected_reason,kind", _CASES
    )
    def test_negation_corpus_row(sentence, hypothesis_id, expected_relation,
                                 expected_reason, kind):
        detail = reviewed_relation_details(sentence, hypothesis_id)
>       assert detail["relation"] == expected_relation, (
            f"{kind} row expected relation {expected_relation!r} for {sentence!r}; "
            f"got {detail['relation']!r} with reason {detail['reason_code']!r} "
            f"and cues {detail['cue_ids']!r}"
        )
E       AssertionError: NEGATED row expected relation None for 'No one was short staffed.'; got <Stance.SUPPORTS: 'SUPPORTS'> with reason None and cues ['STAFFING_CONSTRAINTS.SUPPORTS.short_staffed']
E       assert <Stance.SUPPORTS: 'SUPPORTS'> == None

tests/test_semantic_guard_negation_corpus.py:175: AssertionError
=========================== short test summary info ============================
FAILED tests/test_semantic_guard_negation_corpus.py::test_negation_corpus_row[TG-NOBODY-WALKED]
FAILED tests/test_semantic_guard_negation_corpus.py::test_negation_corpus_row[SC-NO-ONE-WAS]
2 failed, 45 passed in 0.19s
```

Exit status: **1** (2 failed, 45 passed). Command output above is verbatim from
`/tmp/w9-run2.txt`; the `EXIT:1` line came from the wrapping shell.

## The two wrong rows

| case id | sentence | expected | actual | why the guard is wrong |
|---|---|---|---|---|
| `TG-NOBODY-WALKED` | `Nobody walked through the handover with her.` | `None` / `NEGATED_CUE` | `SUPPORTS` / `None` | The negated predicate *is* the cue. A reader takes the sentence to deny the handover walkthrough; the guard certifies `TRAINING_GAP.SUPPORTS` and the engine can accept evidence that inverts the sentence. Cause: `_NEGATION_SUFFIX` matches the word `no` only on a word boundary, so `Nobody` is invisible, and no token is adjacent to `walked through the handover`. |
| `SC-NO-ONE-WAS` | `No one was short staffed.` | `None` / `NEGATED_CUE` | `SUPPORTS` / `None` | Same shape: `no one` scopes over the cue subject, the cue itself is denied. The guard certifies `STAFFING_CONSTRAINTS.SUPPORTS` from `No one was short staffed`, which states the opposite. |

Neither row is an auxiliary-carried negation, so neither is evidence against the
widening; both are evidence that "negation token somewhere in the clause" is not
the same property as "cue negated". Suggested direction for a follow-up (not
attempted here — out of this worker's file scope): treat
`no one|nobody|none of|neither … nor` as clause negation when they occupy the
pre-cue subject position, and add the two rows above to whatever pins that.

## What the widening does and does not over-trigger (measured)

Aux-adjacent non-negations that could plausibly have been swallowed, all
passing:

- `CU-AUX-TO-GUESS` — `The staff did not have to guess whether the checklist was unavailable.`
  (`did not have` in the same clause, cue asserted) → `SUPPORTS`.
- `CU-AUX-OTHER-CLAUSE` — `The staff did not have training, the checklist was unavailable.`
  (`did not have` one comma-clause away) → `SUPPORTS`.
- `PMS-AUX-TO-BE-TOLD` — `The staff did not have to be told twice: the system timed out.`
  (`did not have … be` in the clause) → `SUPPORTS`.

The regex needs `not/never/no/without` + `have|has|had|be|been|being|do|does|did|get|got`
immediately before the cue, so every wording I could build that satisfies it also
negates the cue. The over-trigger risk is therefore in the clause-boundary and
contrast logic, not here — the corpus pins the boundary cases on both sides
(contrast `, not the checklist`, matrix negation with the cue in the complement,
quoted `No`, negation inside a `NEUTRAL` cue's own wording, one cue negated while
a second certifies).

## Corpus (45 rows, generated from the file's `CORPUS` table)

| # | case id | kind | sentence | hypothesis | expected relation | expected reason | actual relation | actual reason | ok |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | `TP-AUX-PLAIN` | NEGATED | We did not have enough time to review every open item. | `TIME_PRESSURE` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 2 | `TP-AUX-CONTRACTED` | NEGATED | They don't have enough time to review every open item. | `TIME_PRESSURE` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 3 | `TP-AUX-CURLY` | NEGATED | We didn’t have enough time to review every open item. | `TIME_PRESSURE` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 4 | `TP-AUX-DOES` | NEGATED | The shift does not have enough time to review every open item. | `TIME_PRESSURE` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 5 | `TP-AUX-NEVER-HAD` | NEGATED | We never had time pressure on that shift. | `TIME_PRESSURE` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 6 | `TP-PLAIN-NO` | NEGATED | There was no time pressure during the shift. | `TIME_PRESSURE` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 7 | `TP-PLAIN-NO-TRAILING` | NEGATED | There was no time pressure at all. | `TIME_PRESSURE` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 8 | `TP-WITHOUT` | NEGATED | The shift ran the handover without time pressure. | `TIME_PRESSURE` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 9 | `TP-NEVER-RAN-OUT` | NEGATED | We never ran out of time before the inspection. | `TIME_PRESSURE` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 10 | `SC-NO-SUBJECT` | NEGATED | No colleague was absent that morning. | `STAFFING_CONSTRAINTS` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 11 | `SC-NOT-UNDERSTAFFED` | NEGATED | The ward was not understaffed during the night shift. | `STAFFING_CONSTRAINTS` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 12 | `SC-NEVER-SHORT` | NEGATED | It was never short staffed on the late shift. | `STAFFING_CONSTRAINTS` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 13 | `SC-NOT-ENOUGH-PEOPLE` | NEGATED | There were not enough people on duty at midnight. | `STAFFING_CONSTRAINTS` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 14 | `SC-AUX-NEVER-HAD` | NEGATED | The team never had enough people on duty. | `STAFFING_CONSTRAINTS` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 15 | `SC-AUX-DOES-NOT-HAVE` | NEGATED | The shift does not have enough people on duty tonight. | `STAFFING_CONSTRAINTS` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 16 | `TG-NO-SUBJECT` | NEGATED | No colleague was unsure about the handover. | `TRAINING_GAP` | None | NEGATED_CUE | None | NEGATED_CUE | yes |
| 17 | `TG-NOBODY-WALKED` | NEGATED | Nobody walked through the handover with her. | `TRAINING_GAP` | None | NEGATED_CUE | SUPPORTS | — | **NO** |
| 18 | `SC-NO-ONE-WAS` | NEGATED | No one was short staffed. | `STAFFING_CONSTRAINTS` | None | NEGATED_CUE | SUPPORTS | — | **NO** |
| 19 | `CU-CONTRAST-ITEM` | CERTIFIES | The binder was missing, not the checklist. | `CHECKLIST_UNAVAILABLE` | SUPPORTS | — | SUPPORTS | — | yes |
| 20 | `CU-MATRIX-NO-ONE` | CERTIFIES | No one said the binder was missing. | `CHECKLIST_UNAVAILABLE` | SUPPORTS | — | SUPPORTS | — | yes |
| 21 | `CU-WEATHER-WHEN` | CERTIFIES | It was not raining when the binder was missing. | `CHECKLIST_UNAVAILABLE` | SUPPORTS | — | SUPPORTS | — | yes |
| 22 | `CU-MATRIX-CONFIRM` | CERTIFIES | No one could confirm that the checklist was unavailable. | `CHECKLIST_UNAVAILABLE` | SUPPORTS | — | SUPPORTS | — | yes |
| 23 | `CU-MATRIX-SUPERVISOR` | CERTIFIES | No supervisor said the binder was missing. | `CHECKLIST_UNAVAILABLE` | SUPPORTS | — | SUPPORTS | — | yes |
| 24 | `CU-QUOTED-NO` | CERTIFIES | 'No,' the auditor said, 'the binder was missing.' | `CHECKLIST_UNAVAILABLE` | SUPPORTS | — | SUPPORTS | — | yes |
| 25 | `CU-AUX-TO-GUESS` | CERTIFIES | The staff did not have to guess whether the checklist was unavailable. | `CHECKLIST_UNAVAILABLE` | SUPPORTS | — | SUPPORTS | — | yes |
| 26 | `CU-LATER-NO-ONE` | CERTIFIES | The checklist was unavailable but no one complained. | `CHECKLIST_UNAVAILABLE` | SUPPORTS | — | SUPPORTS | — | yes |
| 27 | `CU-AUX-OTHER-CLAUSE` | CERTIFIES | The staff did not have training, the checklist was unavailable. | `CHECKLIST_UNAVAILABLE` | SUPPORTS | — | SUPPORTS | — | yes |
| 28 | `CU-CONTRAST-OPPOSITE` | CERTIFIES | The checklist opened normally, not the binder. | `CHECKLIST_UNAVAILABLE` | CONTRADICTS | — | CONTRADICTS | — | yes |
| 29 | `CU-MATRIX-NEVER-CLAIMED` | CERTIFIES | We never claimed the checklist was available. | `CHECKLIST_UNAVAILABLE` | CONTRADICTS | — | CONTRADICTS | — | yes |
| 30 | `CU-MATRIX-DID-NOT-SAY` | CERTIFIES | The auditor did not say the binder was at the desk. | `CHECKLIST_UNAVAILABLE` | CONTRADICTS | — | CONTRADICTS | — | yes |
| 31 | `CU-NEUTRAL-OWN-NOT` | CERTIFIES | The note does not address checklist availability. | `CHECKLIST_UNAVAILABLE` | NEUTRAL | — | NEUTRAL | — | yes |
| 32 | `CU-NEUTRAL-SAYS-NOTHING` | CERTIFIES | The report says nothing about checklist availability. | `CHECKLIST_UNAVAILABLE` | NEUTRAL | — | NEUTRAL | — | yes |
| 33 | `SC-MIXED-NEGATED-FIRST` | CERTIFIES | The ward was not understaffed, the colleague was absent. | `STAFFING_CONSTRAINTS` | SUPPORTS | — | SUPPORTS | — | yes |
| 34 | `SC-MATRIX-DOUBT` | CERTIFIES | There is no doubt that the colleague was absent. | `STAFFING_CONSTRAINTS` | SUPPORTS | — | SUPPORTS | — | yes |
| 35 | `SC-MATRIX-NOT-CLEAR` | CERTIFIES | It is not clear why the colleague was absent. | `STAFFING_CONSTRAINTS` | SUPPORTS | — | SUPPORTS | — | yes |
| 36 | `TP-MATRIX-NO-ONE-DISPUTED` | CERTIFIES | No one disputed that the shift had enough time. | `TIME_PRESSURE` | CONTRADICTS | — | CONTRADICTS | — | yes |
| 37 | `TP-CONTRAST-BUT-NOT` | CERTIFIES | There was enough time to review every open item, but not for the checklist. | `TIME_PRESSURE` | CONTRADICTS | — | CONTRADICTS | — | yes |
| 38 | `TP-MATRIX-NO-ONE-SAID` | CERTIFIES | No one said time pressure caused the miss. | `TIME_PRESSURE` | SUPPORTS | — | SUPPORTS | — | yes |
| 39 | `PMS-LEADING-CUE` | CERTIFIES | The system timed out, not the printer. | `PMS_SYSTEM_ISSUE` | SUPPORTS | — | SUPPORTS | — | yes |
| 40 | `PMS-TRAILING-NOT-ONLY` | CERTIFIES | The system was unavailable, not only slow. | `PMS_SYSTEM_ISSUE` | SUPPORTS | — | SUPPORTS | — | yes |
| 41 | `PMS-MATRIX-NO-ONE-REPORTED` | CERTIFIES | No one reported that the system was unavailable. | `PMS_SYSTEM_ISSUE` | SUPPORTS | — | SUPPORTS | — | yes |
| 42 | `PMS-MATRIX-NOTHING-SAYS` | CERTIFIES | Nothing in the notes says the system worked normally. | `PMS_SYSTEM_ISSUE` | CONTRADICTS | — | CONTRADICTS | — | yes |
| 43 | `PMS-AUX-TO-BE-TOLD` | CERTIFIES | The staff did not have to be told twice: the system timed out. | `PMS_SYSTEM_ISSUE` | SUPPORTS | — | SUPPORTS | — | yes |
| 44 | `TG-MATRIX-NO-ONE-DOUBTED` | CERTIFIES | No one doubted that the colleague was unsure about the handover. | `TRAINING_GAP` | SUPPORTS | — | SUPPORTS | — | yes |
| 45 | `TG-MATRIX-NOT-OBVIOUS` | CERTIFIES | It was not obvious that she needed guidance on the handover. | `TRAINING_GAP` | SUPPORTS | — | SUPPORTS | — | yes |

counts: rows=45 negated=18 certifies=27

`negated` rows must abstain (`relation=None`, `reason_code="NEGATED_CUE"`);
`certifies` rows must return the stated relation with `reason_code=None`.
`ok=**NO**` marks a kept failing assertion.

## Coverage notes / limits

- `CHECKLIST_UNAVAILABLE` and `PMS_SYSTEM_ISSUE` contribute no *true* negative row:
  every affirmative cue in those inventories begins with its own subject
  (`binder was missing`, `system timed out`), so there is no grammatical way to
  put a negative token directly before the cue without also breaking the cue
  match (`The binder was not missing.` matches no cue at all and abstains with
  `NO_CUE_MATCH`, a different path). Their coverage is therefore all
  non-negation rows.
- `CONTRAST_CHANGED_CURRENT_STATE`, `AMBIGUOUS_CUE_RELATIONS` and `NO_CUE_MATCH`
  are exercised elsewhere (`tests/test_semantic_guard_slice18.py`) and are out of
  scope for this corpus, which asserts only `None` and `NEGATED_CUE` as reason
  codes.
- One row (`PMS-*`, originally phrased `Not only was the system unavailable …`) was
  corrected before the reported run: that draft did not contain the literal cue
  string, so it abstained with `NO_CUE_MATCH`. The expectation was not changed,
  only the wording, to what `test_every_corpus_row_actually_matches_a_cue`
  (`detail["cue_ids"]` non-empty) requires. That check exists so no row can
  "pass" a `NEGATED_CUE` expectation for the wrong reason.
- The corpus is a hand-written fixture set, not sampled from real quotes: it
  bounds the guard's behaviour only on the phrasings written here, and it says
  nothing about recall over arbitrary text (the module docstring already disclaims
  general NLP).
