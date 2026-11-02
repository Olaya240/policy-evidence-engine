# WC — adversarial review of the v2 decision table

Read-only review. I did not edit any source file. No terminal in this session, so
every v2 number below is **hand-evaluated** from the Read thresholds in
`backend/app/decision_table.py:96-140`; the v1 column is Read from
`backend/app/engine.py:129-170`. One `pytest -q tests/test_decision_table.py`
confirms the table.

Headline: the proposal fixes all three reported defects *in `score`*, and then
reintroduces the collision in `confidence` — the field the shipped UI actually
draws. That is the one finding that must be resolved before wiring.

---

## The outputs, side by side

`score(s,c) = (s-c)/(s+c+1)`; SUPPORTED iff `s ≥ 2 ∧ s ≥ 3c+1`; CONTRADICTED iff
`c ≥ 3s+1`; INSUFFICIENT iff `s=c=0`; else PARTIAL
(`decision_table.py:96-140`).

| evidence (independent groups, for / against) | v1 (shipped) | v2 status | v2 `score` | v2 `confidence` = abs |
|---|---|---|---|---|
| 1 / 0 | PARTIAL 0.55 | PARTIAL | **+0.500** | **0.500** |
| 0 / 1 | CONTRADICTED 0.58 | CONTRADICTED | **−0.500** | **0.500** |
| 2 / 0 | SUPPORTED 0.68 | SUPPORTED | +0.667 | 0.667 |
| 2 / 1 | PARTIAL 0.52 | PARTIAL | +0.250 | 0.250 |
| 4 / 1 | PARTIAL 0.52 | **SUPPORTED** | +0.500 | 0.500 |
| 0 / 2 | CONTRADICTED 0.68 | CONTRADICTED | −0.667 | 0.667 |
| one accepted **disputed** support | PARTIAL 0.48 | **INSUFFICIENT** | 0 | 0 |
| stale support only | INSUFFICIENT 0.25 | INSUFFICIENT | 0 | 0 |
| accepted neutral only | INSUFFICIENT 0.30 | INSUFFICIENT | 0 | 0 |

---

## Attack 1 — CRITICAL: the collision moves into `confidence`, which the UI renders

**Shape.** `(1,0)` — one fresh accepted supporting group, nothing against.
`(0,1)` — one fresh accepted contradicting group, nothing for.

**v2 output.** Both produce `confidence == 0.500`, with opposite `status`
(`decision_table.py:62-64` returns `abs(self.score)`; `decide(1,0)` is PARTIAL
`+0.5`, `decide(0,1)` is CONTRADICTED `−0.5`).

**What the product tells a human.** The shipped audit UI renders
`{claim.status} · {pct}% est.` and a meter whose width is `pct`
(`frontend/src/App.tsx:919,925`, `pct` from `claim.confidence` at `:898`). So a
half-full meter and "50% est." now appear on a claim that is *supported by one
source* and on a claim that is *refuted by one source*. That is the exact defect
the proposal was written to remove (`0.68` meaning two opposite things), moved
from a field nobody renders into the field everybody renders. It is *worse* than
v1 for these two shapes, because v1 at least separated them (0.55 vs 0.58).

**Why it slipped through.** `tests/test_decision_table.py::test_v2_collision_is_fixed`
asserts `corroborated.score != refuted.score` and never touches `confidence`.
The test pins the field the design cares about, not the field the consumer reads.

**Cheapest mitigation.** Two changes, both small: (a) keep `confidence` for the
Claim only if it is status-banded — e.g. emit `confidence` as `|score|` *within a
status-specific interval* so no two statuses overlap; or (b) stop exposing a
scalar to the UI at all for v2 and render status plus counts ("2 independent
sources for, 1 against"). (b) is smaller and removes the class of bug rather than
this instance.

**Discriminating observation.** Under the current proposal, sorting the claim
list by `confidence` interleaves PARTIAL and CONTRADICTED claims at identical
values. Under a banded or count-based display, no PARTIAL claim can share a
visual rank with a CONTRADICTED one. One UI screenshot or one sorted list
separates them.

---

## Attack 2 — HIGH: the Coq model counts items, the implementation counts groups

**Shape.** Append a second supporting record that shares `source_group` with an
existing one: `[{SUPPORTS, group=a}, {SUPPORTS, group=a}]`.

**v2 output.** `directional_groups` (`decision_table.py:73-93`) returns `s = 1`,
so `score` is unchanged at `+0.5`. The proved theorem `v2_support_raises`
(`ct3/DecisionTable.v`, "one more independent support group strictly raises the
score") is stated over `counts`, and `counts` (`DecisionTable.v:233-236`) filters
*items* and takes their length — `group` is a field of `record item` that the
function never reads.

**What the product tells a human.** Nothing wrong on screen; the problem is
epistemic. `decision_table.py:24-40` advertises the Coq properties as re-checked
against this implementation, and `tests/test_decision_table.py:96-104` re-checks
them against `score`, a function of two ints. So the strict-monotonicity claim is
verified for a model that is *not* the function the engine would call. Adding a
duplicate-group record is a no-op in Python and a strict increase in the proof.

**Is it worse than today?** Not behaviourally — v1 also counts groups for support
(`engine.py:125`) — but it is a soundness gap in the deliverable that says
"proved". A reviewer who trusts the docstring will believe something false about
`decide_evidence`.

**Cheapest mitigation.** Restate the property at the level the code implements:
"adding a record from a **new** group strictly raises the score; adding one from
an existing group leaves both counts unchanged", and prove both in Coq by making
`counts` dedupe `group` (an extra `nodup`/`filter` over group ids). Failing that,
correct the docstring and add a Python test that exercises `decide_evidence`, not
`score`, so the gap cannot hide.

**Discriminating observation.** Extend `counts` in Coq with group dedup and
recompile: if the two theorems still close, the model matches the code; if
`v2_support_raises` becomes unprovable as stated, the model was item-level all
along.

---

## Attack 3 — HIGH: challenging evidence erases it

**Shape.** One accepted record that supports the hypothesis, and the user
challenges it (`disputed=True`), with nothing else available.

**v2 output.** `directional_groups` skips disputed items
(`decision_table.py:82-84`), so `s = c = 0` → INSUFFICIENT, `score 0.0`,
`contested False`.
v1 has a dedicated arm for exactly this: PARTIAL 0.48,
`STATUS.ACCEPTED_DISPUTED_EVIDENCE` (`engine.py:136-139`).

**What the product tells a human.** "No admissible, relevant evidence
establishes support or contradiction" — on a claim where a human is mid-dispute
about a specific record. The dispute itself becomes invisible in the verdict: the
status regresses from PARTIAL to INSUFFICIENT, and because `contested` is derived
from the directional counts (`decision_table.py:127`), it does not fire either.
Challenge an assertion and the tool reports the assertion was never evidenced.

**Is it worse than today?** Yes, unambiguously. v1's behaviour is the right one:
keep the claim contested, do not let the challenge silently delete the record's
existence.

**Cheapest mitigation.** Add a `challenged` count (accepted disputed records,
per group) and a rule: any challenged directional record and no other decisive
evidence → PARTIAL with score 0 and `contested: true`; challenged records never
enter `s` or `c`. That is one extra field and one rule, and it restores the v1
guarantee without reintroducing a number.

**Discriminating observation.** `decide_evidence([disputed support])` today
returns INSUFFICIENT; if it returns PARTIAL with `contested: true` and `score 0`,
the regression is closed. One assertion.

---

## Attack 4 — MEDIUM: 4-for-1 is SUPPORTED at 50%

**Shape.** Four independent support groups, one independent contradiction group.

**v2 output.** `4 ≥ 3·1+1 = 4` → SUPPORTED, `score +0.5`, `contested: true`
(`decision_table.py:99-111`). v1: PARTIAL 0.52.

**What the product tells a human.** "SUPPORTED — 50% est." with a half-full
meter, while a *single-source* support claim reads PARTIAL 55% today and 50% under
v2. So the strongest positive label in the system carries the same number as the
weakest positive evidence, and a *lower* number than today's single-source
PARTIAL. The `contested` flag that is supposed to rescue this is not in the
Claim, only in the module — nothing in `engine.py` reads it, so unless the wiring
adds it to the payload, the reader never sees it.

**Is it worse than today?** Judgement call, but the burden is on the proposal: v1
refuses to call a contested claim supported at all. A domain auditor is likely to
agree with v1 — a single contradiction means somebody with an independent source
says the opposite.

**Cheapest mitigation.** Gate SUPPORTED on `c == 0`, keeping the signed score for
strength. That is one conjunct, and it removes the label flip entirely while
leaving monotonicity intact (it only changes labels, not order).

**Discriminating observation.** Ask the domain owner one question — "may a claim
with one independent contradiction ever read SUPPORTED?" If no, the conjunct is
correct and v2's threshold should be `supported ∧ c = 0`. If yes, `contested`
must be a first-class Claim field, not a module-only flag.

---

## Attack 5 — MEDIUM: (2,1) at 25% is a second inversion-shaped reading

**Shape.** Two independent supports and one contradiction.

**v2 output.** PARTIAL, `score +0.25`, `confidence 0.25`. One support and nothing
against is `0.50`. So *more* evidence (three groups instead of one) yields half
the displayed confidence, while the status is identical (PARTIAL both).

**What the product tells a human.** "PARTIAL · 25% est." next to "PARTIAL · 50%
est." — the reader infers the first claim is worse evidenced, when it has two
independent supporters. The status is the same, so nothing on screen explains the
drop.

**Is it worse than today?** Partly. v1 has the same shape (0.55 for `(1,0)` vs
0.52 for `(2,1)`) but the gap is 0.03, not 0.25. v2 amplifies a real modelling
choice — the score is a *net margin*, not an evidence volume — into something a
reader will read as a bug.

**Cheapest mitigation.** Report volume next to margin: `directional_evidence_mass`
already exists (`decision_table.py:66-71`). Render "3 sources (2 for, 1 against)"
rather than a percentage, and the margin can stay as the sort key.

**Discriminating observation.** If the UI shows counts, the `(2,1)` vs `(1,0)`
comparison reads correctly under either score. If it shows only a percentage,
the reader cannot tell them apart in kind.

---

## Attack 6 — MEDIUM: 0.0 means two different things, and the pair is not what is rendered

**Shape.** `(0,0)` versus `(2,2)`.

**v2 output.** Both `score 0.0`; `directional_evidence_mass` 0 vs 4;
`contested` False vs True. The module argues the pair is injective
(`decision_table.py:66-71`), which is true of the pair and false of the thing
shipped: `Claim.confidence` is a single float and the UI's meter is a single
width (`App.tsx:925`).

**Is it worse than today?** Technically v1 separates them (0.20 vs 0.52). So yes,
for these two shapes, unless the wiring carries mass and contested into the
payload.

**Cheapest mitigation.** Same as attack 5: the display must show counts, or
`confidence` must be banded so a contested claim can never render identically to
an empty one.

**Discriminating observation.** Two investigations, one empty and one perfectly
balanced; if the rendered artifacts are byte-identical apart from text, the pair
injectivity bought nothing.

---

## Attack 7 — LOW/MEDIUM: department diversity is dropped, and the trace loses its disclosure

**Shape.** Two independent support groups from *different* departments.

**v2 output.** `score = 0.667` regardless of departments; v1 gives 0.78 for
diverse and 0.68 for same-department (`engine.py:150-151`). The
`department_diversity_uses_last_support_record_per_group` trace flag is still
computed from `independent_groups` in the engine, but nothing in `decision_table`
consumes diversity, so the number no longer reflects it.

**What the product tells a human.** Two records from the same team and two from
different teams now look identical. For an audit tool, "independent" usually
means "not the same team"; losing the distinction is a real loss of the
independence signal.

**Is it worse than today?** Mildly. v1's 0.68 vs 0.78 is a small, disclosed
difference; v2 silently removes it.

**Cheapest mitigation.** Keep diversity out of the score (it breaks the arithmetic
story) but emit `department_diverse: bool` and surface it in the trace and the
conflict text. If it must affect the verdict, make it a **status guard** on
SUPPORTED for high-stakes claims, not a score term.

**Discriminating observation.** If the trace still reports the diversity flag and
the UI shows it, no information is lost; if the number was the only place it
appeared, it is gone.

---

## Attack 8 — LOW: the audit trail collapses to one confidence rule id

**Shape.** Any of the twelve v1 shapes.

**v2 output.** A single `CONFIDENCE.V2_SIGNED_MARGIN`
(`decision_table.py:100-121`), where v1 emitted
`FIXED_0_68_SAME_OR_MISSING_DEPARTMENT`, `FIXED_0_68_MULTIPLE_CONTRADICTIONS`,
`FIXED_0_52`, `FIXED_0_54`, `FIXED_0_25`, `FIXED_0_20`, `FIXED_0_30`, … The v1
pair of ids is how the collision was *disclosed* in the trace; v2 removes both the
collision and the disclosure.

**Is it worse than today?** Not for honesty — one id for one rule is correct —
but any consumer that keys on the old ids (audit exports, the frontend's fallback
strings, `docs/`) breaks. `tests/test_explanation_trace.py:77-92` pins those ids
by name, so this is a deliberate, visible break, not a silent one.

**Cheapest mitigation.** Bump `reasoning_rule_version` to `story-connect-status-v2`
(the test already asserts v1, `test_explanation_trace.py:91`) and keep the
per-shape `status_rule_id` distinction, which still carries the *why* even when
the confidence id is uniform.

**Discriminating observation.** Grep for `CONFIDENCE.FIXED_` outside tests: if
only tests and docs reference them, the break is contained.

---

## Attack 9 — LOW: `confidence_kind` versus a signed score

**Shape.** Any.

**v2 output.** `confidence_kind` still says
`FIXED_ENGINE_HEURISTIC_NOT_CALIBRATED_PROBABILITY` (`engine.py:300`), while the
new number is a normalised difference in `(-1,1)` — the functional form of a phi
coefficient. A reader who sees `-0.5` will read it as a correlation, and a
product that shows it as a percentage invites a probability reading the string
explicitly denies.

**Cheapest mitigation.** Either keep the number internal (sort key only) or rename
it `evidence_margin` in the payload so the name does not promise calibration.

**Discriminating observation.** If no surface renders `score` as a percentage,
the risk is theoretical; the percentage surfaces read `confidence`
(`App.tsx:898,919,955`), so the risk is contained to the abs field.

---

## What the proposal gets right, stated so it is not lost

- The inversion is genuinely gone *at the score level*: `score(s+1,c) > score(s,c)`
  for every pair, proved and re-checked (`ct3/DecisionTable.v`,
  `test_decision_table.py:96-104`).
- Stale evidence cannot move the number, proved over a list
  (`v2_stale_ignored`) — this is the correct repair of the 0.54 demotion.
- Order cannot move it (`v2_order_irrelevant`), which the v1 department and
  `matching_evidence` logic both violate.
- Single source can never be SUPPORTED (`v2_single_source_is_partial`) — matches
  v1's instinct, now proved.
- The label set is exclusive by construction (`v2_states_exclusive`).

## What I could not check

- No execution: all v2 outputs are hand-evaluated from the thresholds. The
  coordinator should run `pytest -q tests/test_decision_table.py` and a
  `decide_evidence` probe for the disputed shape.
- I did not read the transport or coverage modules; attacks here are scoped to the
  decision table.
- I did not check `docs/` for rule-id references (attack 8's blast radius).
- Memory: no `local_memory_*` tool is bound to this worker session, so the two
  durable findings are recorded here rather than stored —
  `policy-evidence-engine decision_table` · `COLLIDES_IN_CONFIDENCE` (0.5 for both
  a single supporting and a single refuting group), and
  `policy-evidence-engine DecisionTable.v` · `COUNTS_ITEMS_NOT_GROUPS` (the Coq
  model ignores `group`, so strict monotonicity does not apply to
  `decide_evidence`).

## Smallest amendment that makes the proposal safe

1. `confidence` must not collide across statuses (band it, or stop rendering it).
2. `SUPPORTED` requires `c = 0`, unless `contested` becomes a first-class Claim
   field.
3. Challenged evidence keeps its claim at PARTIAL and sets `contested`.
4. Fix the Coq model to dedupe `group`, or correct the docstring claim.
5. Emit counts and diversity in the payload so a reader never has to infer them
   from a scalar.
