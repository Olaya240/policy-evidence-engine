# Worker 1 — policy extraction and one-pass counting

File edited: `backend/app/decision_table.py` only.

## Signatures (unchanged for existing callers)

```python
decide(support_groups, contradiction_groups, *,
       disputed_support=0, disputed_contradiction=0,
       policy=POLICY_SIGNED_MARGIN) -> Decision
decide_evidence(evidence, *, policy=POLICY_SIGNED_MARGIN) -> Decision
directional_groups(evidence) -> (set, set)          # unchanged
disputed_directions(evidence) -> (set, set)         # unchanged
disputed_groups(evidence) -> set                    # unchanged
score(support_groups, contradiction_groups) -> float  # unchanged
```

`Decision` gained one required field, `policy_id`. It is set by `decide` for every
call, so equality comparisons between two `decide` results are unaffected.

## The three policies

| constant | policy_id | min_support_groups | imbalance_per_group | contest_blocks_decisive |
|---|---|---|---|---|
| `POLICY_SIGNED_MARGIN` (default) | `SIGNED_MARGIN_3_TO_1` | 2 | 3 | False |
| `POLICY_CONTEST_BLOCKS` | `CONTEST_BLOCKS_DECISIVE` | 2 | 3 | True |
| `POLICY_TWO_TO_ONE` | `TWO_TO_ONE` | 1 | 2 | False |

Consequences, read off `_label`, not executed:

- `SIGNED_MARGIN_3_TO_1` is today's behaviour: `(4,1)` SUPPORTED, `(2,1)` PARTIAL.
- `CONTEST_BLOCKS_DECISIVE` never returns a decisive label when both directions
  have a group, so `(4,1)` becomes PARTIAL.
- `TWO_TO_ONE` makes a single source decisive: `(1,0)` SUPPORTED and `(0,1)`
  CONTRADICTED, which is exactly what `v2_single_source_is_partial` forbids.

## Proof status — read this before switching the default

`ct3/DecisionTable.v` proves `SIGNED_MARGIN_3_TO_1` only. `TWO_TO_ONE` would
falsify the proved theorem `v2_single_source_is_partial`, and
`CONTEST_BLOCKS_DECISIVE` weakens `(4,1)` without any proof either way. I added
that warning to the module docstring rather than leaving it implicit. Nothing was
switched: `MIN_SUPPORT_GROUPS` and `IMBALANCE_PER_GROUP` now alias the default
policy's values, so any caller reading them still sees 2 and 3.

## One-pass counting

`_count_groups` walks the evidence once and returns
`(support, contradiction, disputed_support, disputed_contradiction, disputed_all)`.
`directional_groups`, `disputed_directions` and `disputed_groups` now delegate to
it. `disputed_all` preserves the old stance-blind behaviour of `disputed_groups`,
including neutral records, which a union of the two disputed sets would have
dropped. No observable result changed.

## Not executed

No terminal: I could not run `pytest`, so the claim "no behaviour change" rests on
reading both implementations, not on a green suite. The specific risk I would
check first is `tests/test_decision_table.py::test_stale_unverified_and_disputed_records_cannot_move_the_counts`,
because it calls `directional_groups` and compares whole tuples — the delegation
must preserve the pair order exactly, which I believe it does.
