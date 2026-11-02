# W5 — differential test for the decision table

**File created (only file touched):** `backend/tests/test_table_differential.py`

## What it does

An independent reference implementation of the rule, written in a different shape from
the module (cross-multiplied score comparison `2(s-c) >= s+c+1` instead of the integer
threshold `s >= 3c+1`), then differential assertions:

1. status, score (12 dp) and direction agree over `s, c ∈ 0..14`;
2. the cross-multiplied identity holds exactly — `2(s-c) >= s+c+1` is true iff SUPPORTED
   *and* `s >= MIN_SUPPORT_GROUPS`, and `2(c-s) >= s+c+1` is true iff CONTRADICTED. This
   is the arithmetic `ct3/DecisionTable.v` turns on, so a divergence means the proof no
   longer describes the code. A separate test proves `s >= 3c+1` and `2(s-c) >= s+c+1` are
   the same predicate;
3. `test_the_guard_is_load_bearing` pins the one place the two forms are *not*
   interchangeable: at (1,0) the bare threshold fires with equality and the corroboration
   guard is what stops SUPPORTED;
4. dispute handling enumerated over `s, c ∈ 0..4`, `ds, dc ∈ 0..2` against
   "PARTIAL iff counting the disputed record would change the label";
5. the policy surface introduced mid-slice: the default is `POLICY_SIGNED_MARGIN` and
   reports `SIGNED_MARGIN_3_TO_1`; `POLICY_CONTEST_BLOCKS` demotes every contested shape;
   `POLICY_TWO_TO_ONE` makes one source decisive and treats 2-v-1 as a tie; and policy
   choice may never move `score`.

## Mid-slice change I had to absorb

My first read of `app/decision_table.py` predated another worker's edit. By the time I
finished, the module had grown `ThresholdPolicy`, three named policies, a `policy_id` field
on `Decision`, and `_label(s, c, policy)`. I re-read the file and adapted rather than
assuming: the differential is against the default policy, and section 5 pins the policy
surface. **Anyone re-reading this should check `decision_table.py` again**, because it was
being edited concurrently.

## Honest limits

- **Unrun.** No terminal in this session; none of these tests has been executed. The
  coordinator must run `pytest -q tests/test_table_differential.py`.
- **Partly derived from the code.** The status names, the `s >= 2` guard and the
  `disputed_support`/`disputed_contradiction` keywords come from reading the module. Only
  the score arithmetic and the two threshold inequalities are an independent derivation.
  A reference that shared nothing with the code would need the specification document, not
  the module.
- **No memory write.** `local_memory__memory_store` is not among the tools bound to this
  session, so I cannot claim one; recording this slice is the coordinator's to do.
- Nothing here tests `engine.py`; the trace fields and the `Claim` wiring are another
  worker's slice.
