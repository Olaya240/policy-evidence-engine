# Proof/implementation gap audit — `DecisionTable.v` vs `decision_table.py`

Read line by line: `ct3/DecisionTable.v` (416 lines) against
`backend/app/decision_table.py` (196 lines). Every row below is a place where the
code does something no Coq statement constrains.

Classification: **(i)** provable by a small addition to the .v file · **(ii)**
provable only under a different model · **(iii)** presentation choice, not a proof
obligation.

## Ranked gaps

### 1. Dispute handling is entirely unmodelled, and it breaks the label/score invariant — risk: high — (i)

`decide()` has a second labelling pass (`decision_table.py:150-160`) that the Coq
file never mentions: the table is re-run with disputed groups counted, and the
result is forced to `PARTIAL` when the two labels differ. `Inductive status` has
no notion of a dispute anywhere in the .v file.

Consequence: after a downgrade the label no longer follows the thresholds that
*are* proved. `v2_status` and `supported`/`contradicted` describe a state machine
with one transition; the code has two.

| concrete input | code | what the proof says |
|---|---|---|
| `decide(2, 0, disputed_contradiction=1)` | `PARTIAL`, `score = +0.6667` | nothing — `(2,0)` is `Supported` under `v2_status`, and no theorem allows `Mixed` with a `score` above `1/2` |
| `decide(4, 1, disputed_contradiction=6)` | `PARTIAL` (label(4,7) ≠ Supported), `score = +0.5000` | nothing |
| `decide(1, 0, disputed_support=1)` | status stays `PARTIAL`, but `status_rule_id` becomes `STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT` | nothing — and note the status did *not* change, so the rule id claims the dispute was decision-relevant while the decision is identical |

The first row is the one to care about: `SUPPORTED` implies `score ≥ 1/2 ∧ s ≥ 2`
in the proved model, and that implication is **false** in the code as soon as a
dispute exists. Any consumer that infers a label from `score` and `s` will
disagree with the emitted `status`.

Smallest closing proof: extend the model to `(s, c, ds, dc)`, define
`decide_with_disputes`, and prove (a) the downgrade is monotone (it can only move
`Supported`/`Contradicted` → `Mixed`, never the reverse), (b) after a downgrade
`status = Mixed`, (c) `score` is unchanged by the dispute — which is what makes
the pair `(status, score)` inconsistent, so the theorem should state the
inconsistency deliberately rather than leave it implied.

### 2. The two constants are not tied to the proof — risk: high — (i)

`MIN_SUPPORT_GROUPS = 2` and `IMBALANCE_PER_GROUP = 3` (`decision_table.py:57-66`)
reach the code as identifiers. In the .v file the same numbers appear as literals
inside `supported` (`2 <= s`, `3 * c + 1 <= s`) and `contradicted`.

Change either constant and the .v file still compiles, still proves
`v2_states_exclusive`, and now describes a rule the code does not implement. The
proof is not parameterised, so it cannot catch the edit.

Concrete: set `IMBALANCE_PER_GROUP = 1` and the code makes `decide(2,1)`
`SUPPORTED` (2 ≥ 3·1+1 → 2 ≥ 2), while `v2_status 2 1 = Mixed` remains "proved".

Closing proof: parameterise — `supported k s c := 2 <= s /\ k * c + 1 <= s` and
prove exclusivity for all `k`, then add one lemma per constant binding the code's
value (`k = 3`) to the parameter. Exclusivity for all `k ≥ 1` is provable with the
same `lia` argument.

### 3. Record counting vs group counting diverges in the *label*, not just in strength — risk: high — (ii)

`counts` (`DecisionTable.v:339-341`) is `length (filter … l)` over `item` records;
the `group : nat` field is declared at `:318` and **never read**. The code
deduplicates by group (`directional_groups`, `decision_table.py:99-118`).

The module docstring calls this "one step weaker". It is more specific than that:
for two records in one group the code and the model disagree about the status.

| input | code | model |
|---|---|---|
| two `SUPPORTS` records, same `source_group="A"` | `s = 1` → `PARTIAL`, `score = 0.5` | `counts = (2,0)` → `Supported`, `score = 2/3` |

So `v2_stale_ignored` and `v2_order_irrelevant` are true statements about a count
the code does not compute. Their *conclusions* (stale and order cannot move the
result) do hold for groups, but that is currently a test
(`test_records_sharing_a_group_are_one_unit`), not a theorem.

Closing proof requires a deduplicating model — e.g. `nodup` lists or a
`FSet`-like structure — which is (ii): stdlib-only Coq has `List.nodup` and
`incl`, but proving `length (nodup …)` invariance under append-permutation is
markedly more work than the current 6-line lemma.

### 4. `direction` / sign is not proved at all — risk: medium-high — (i)

`direction` (`decision_table.py:83-90`) is derived from the sign of the float
`score`. The Coq file defines `score_num`/`score_den` and proves monotonicity, but
no theorem states

  `supported s c → 0 < score_num s c` and `contradicted s c → score_num s c < 0`.

That is the entire mechanism by which the v1 collision is claimed to be fixed, and
it is currently asserted in prose and checked only by the Python grid test.

Closing proof is two lines: `supported` gives `3c+1 ≤ s` hence `c < s`; `lia`
finishes both.

### 5. `confidence` collision persists and is not stated — risk: medium — (i)

`confidence` is `abs(score)`, so `decide(1,0)` and `decide(0,1)` both report
`0.5`. The code documents this honestly; the .v file does not mention
`confidence` at all. A reader who treats the .v file as the specification will
conclude the collision is gone.

Closing proof: state it, do not hide it — `forall s c, confidence s c = confidence c s`,
which is true by construction and is exactly the limitation. Turning a known
weakness into a theorem is cheaper than leaving it to prose.

### 6. `review_state` filtering is unmodelled — risk: medium — (i)

Both `directional_groups` and `disputed_directions` skip anything whose
`review_state` is not `ACCEPTED`. The Coq `item` record has `stance`, `stale`,
`group` and no review state.

Concrete: one `ACCEPTED` support and one `UNVERIFIED` support in different groups
→ code `s = 1` → `PARTIAL`; the model has no way to express it and would count 2.
No theorem says unverified evidence cannot move the number; only
`test_review_state_filter_is_the_only_source_of_trust` does.

Closing proof: add `reviewed : bool` to `item` and filter on it, mirroring
`stale`. Same shape as `filter_app_single`, so (i) and cheap.

### 7. Negative counts: the code is partial where the model is total — risk: low-medium — (i)

`score()` raises `ValueError` for negative input, but `decide()` calls `_label`
first. `decide(-1, 0)`: `_label` sees `0 >= 3*(-1)+1 = -2` → `CONTRADICTED`, then
`score(-1, 0)` raises. So `decide` has a domain where it throws, and the exception
is a 500 if it ever escapes.

The Coq model is over `nat`, so negatives are unrepresentable and no theorem can
be violated — but nothing in the proof says the code's inputs are non-negative
either. Today every caller passes `len(...)`, so this is latent.

Closing proof: state `0 <= s -> 0 <= c ->` on the theorems that matter (the
existing ones are already over `nat`, so this is a documentation fix plus a guard
test rather than new machinery), and validate in `decide` before `_label`.

### 8. The stated range `(-1, 1)` is false in floating point — risk: low — (iii) presentation

`score_num/score_den` is exactly bounded by ±1 in the model. The Python docstring
claims the same range for the float. At `s = 2**53, c = 0` the denominator
`2**53 + 1` is not representable as a double and rounds to `2**53`, so the
division returns exactly `1.0`.

`confidence = 1.0` is still inside `Claim.confidence`'s `le=1`, so nothing breaks;
but the range claim, and therefore the "`< 1`" part of every argument built on it,
is a float statement nobody has proved. Classify as presentation unless a consumer
starts relying on strict inequality.

### 9. Rule ids are unmodelled, including one that is overwritten without a state change — risk: low — (iii)

`status_rule_id`/`confidence_rule_id` are persisted in the trace and are the only
machine-readable record of *why* a label was chosen. No theorem mentions them.
The specific wart is gap 1, third row: a downgrade is recorded even when the
status did not change.

Classify (iii) as a proof matter, but note that persisted ids are data, so a
future rule-id change is a migration question rather than a refactoring.

### 10. v1 transcription fidelity — risk: low, but it weakens the published defects — (iii)

`v1_score` collapses the diversity branch (`78`) into `68`, and omits the
stale-only (`25`), disputed (`48`) and accepted-non-directional (`30`) arms. The
file scopes this honestly ("restricted to the branches reachable from (s, c)"),
but `v1_collision_is_structural` then reads as "the shipped table returns 68 for
any two-support claim", which is false when the two supports sit in different
departments.

The three defects survive the restriction — they are not artefacts of it — but
any quotation of these theorems should carry the restriction with them.

## Summary

| # | gap | class | risk |
|---|---|---|---|
| 1 | dispute branch unmodelled; label/score invariant broken after a downgrade | (i) | high |
| 2 | constants `2` and `3` not parameterised | (i) | high |
| 3 | record counts vs group counts changes the label | (ii) | high |
| 4 | `supported ⇒ score > 0` not proved | (i) | medium-high |
| 5 | `confidence` collision unstated | (i) | medium |
| 6 | `review_state` filter unmodelled | (i) | medium |
| 7 | negative counts: partial function | (i) | low-medium |
| 8 | float range claim | (iii) | low |
| 9 | rule ids unmodelled; downgrade id without state change | (iii) | low |
| 10 | v1 transcription restricted | (iii) | low |

Five of the ten are cheap: gaps 4 and 5 are a few lines each, 6 mirrors the
existing `stale` filter, 2 is a parameterisation of two lemmas, and 7 needs a
hypothesis and a guard rather than new machinery. Gaps 1 and 3 are the two that
genuinely cost work, and gap 1 is the one that can produce a wrong answer today.

## Left undone

- I did not edit `DecisionTable.v`; every recommendation above is a sketch, not a
  compiled proof. Nothing here was checked by a compiler.
- The concrete rows were computed by reading the code by hand, not by running it.
  `decide(2, 0, disputed_contradiction=1)` and the `2**53` division are the two
  worth executing first if the coordinator wants them upgraded from Inferred to
  Observed.
- I did not audit `engine.py`'s wiring of `_label` beyond the three fields it
  passes (`support_groups`, `contradiction_groups`, disputed counts), so a
  divergence introduced at the call site is outside this table.
