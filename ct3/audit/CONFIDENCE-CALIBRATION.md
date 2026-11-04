# Confidence calibration — does the number deserve to be read?

Workstream: Confidence Reliability (status *partial*). Question in one sentence: **does
`Decision.confidence` faithfully describe the evidence behind a claim, and where it does not,
what exactly does it say instead?**

Files: `backend/app/decision_table.py` (read, **not changed** — see "Why nothing was fixed"),
`backend/tests/test_confidence_reliability.py` (new, the executed harness),
this document (new).

Run, verbatim:

```
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_confidence_reliability.py
..............                                                           [100%]
14 passed in 0.24s
```

`Decision.confidence` is `abs(Decision.score)` and `score(s, c) = (s - c) / (s + c + 1)` over
counts of independent source groups. Every property below is stated over `score` and re-read
through `confidence`, so nothing here tests a second number that only looks like the first.

Grids, exhaustive rather than sampled, over the default policy `SIGNED_MARGIN_3_TO_1`
(`min_support_groups = 2`, `imbalance_per_group = 3`) — the one proved in `ct3/DecisionTable.v`:

| Grid | Definition | Size |
|---|---|---|
| **U** | `support_groups, contradiction_groups` in `0..6` | 49 configurations |
| **D** | U × `disputed_support, disputed_contradiction` in `0..2` | 441 configurations |
| **steps** | one-group increments inside U (42 up, 42 down) and inside D per dispute offset (378 up, 378 down) | 84 + 756 |

The two non-default policies (`CONTEST_BLOCKS_DECISIVE`, `TWO_TO_ONE`) are deliberately **not**
enumerated: the module states their consequences are unproved, so pinning them here would give
an unratified threshold the appearance of a proved one.

## The enumerated table (U, default policy)

| s | c | score | confidence | status | status rule id | direction | contested |
|---|---|---|---|---|---|---|---|
| 0 | 0 | +0.0000 | 0.0000 | INSUFFICIENT | `STATUS.V2_NO_DIRECTIONAL_EVIDENCE` | NONE | no |
| 0 | 1 | -0.5000 | 0.5000 | CONTRADICTED | `STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT` | AGAINST | no |
| 0 | 2 | -0.6667 | 0.6667 | CONTRADICTED | `STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT` | AGAINST | no |
| 0 | 3 | -0.7500 | 0.7500 | CONTRADICTED | `STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT` | AGAINST | no |
| 0 | 4 | -0.8000 | 0.8000 | CONTRADICTED | `STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT` | AGAINST | no |
| 0 | 5 | -0.8333 | 0.8333 | CONTRADICTED | `STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT` | AGAINST | no |
| 0 | 6 | -0.8571 | 0.8571 | CONTRADICTED | `STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT` | AGAINST | no |
| 1 | 0 | +0.5000 | 0.5000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | no |
| 1 | 1 | +0.0000 | 0.0000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | NONE | yes |
| 1 | 2 | -0.2500 | 0.2500 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 1 | 3 | -0.4000 | 0.4000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 1 | 4 | -0.5000 | 0.5000 | CONTRADICTED | `STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT` | AGAINST | yes |
| 1 | 5 | -0.5714 | 0.5714 | CONTRADICTED | `STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT` | AGAINST | yes |
| 1 | 6 | -0.6250 | 0.6250 | CONTRADICTED | `STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT` | AGAINST | yes |
| 2 | 0 | +0.6667 | 0.6667 | SUPPORTED | `STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION` | FOR | no |
| 2 | 1 | +0.2500 | 0.2500 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 2 | 2 | +0.0000 | 0.0000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | NONE | yes |
| 2 | 3 | -0.1667 | 0.1667 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 2 | 4 | -0.2857 | 0.2857 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 2 | 5 | -0.3750 | 0.3750 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 2 | 6 | -0.4444 | 0.4444 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 3 | 0 | +0.7500 | 0.7500 | SUPPORTED | `STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION` | FOR | no |
| 3 | 1 | +0.4000 | 0.4000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 3 | 2 | +0.1667 | 0.1667 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 3 | 3 | +0.0000 | 0.0000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | NONE | yes |
| 3 | 4 | -0.1250 | 0.1250 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 3 | 5 | -0.2222 | 0.2222 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 3 | 6 | -0.3000 | 0.3000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 4 | 0 | +0.8000 | 0.8000 | SUPPORTED | `STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION` | FOR | no |
| 4 | 1 | +0.5000 | 0.5000 | SUPPORTED | `STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION` | FOR | yes |
| 4 | 2 | +0.2857 | 0.2857 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 4 | 3 | +0.1250 | 0.1250 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 4 | 4 | +0.0000 | 0.0000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | NONE | yes |
| 4 | 5 | -0.1000 | 0.1000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 4 | 6 | -0.1818 | 0.1818 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 5 | 0 | +0.8333 | 0.8333 | SUPPORTED | `STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION` | FOR | no |
| 5 | 1 | +0.5714 | 0.5714 | SUPPORTED | `STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION` | FOR | yes |
| 5 | 2 | +0.3750 | 0.3750 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 5 | 3 | +0.2222 | 0.2222 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 5 | 4 | +0.1000 | 0.1000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 5 | 5 | +0.0000 | 0.0000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | NONE | yes |
| 5 | 6 | -0.0833 | 0.0833 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | AGAINST | yes |
| 6 | 0 | +0.8571 | 0.8571 | SUPPORTED | `STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION` | FOR | no |
| 6 | 1 | +0.6250 | 0.6250 | SUPPORTED | `STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION` | FOR | yes |
| 6 | 2 | +0.4444 | 0.4444 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 6 | 3 | +0.3000 | 0.3000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 6 | 4 | +0.1818 | 0.1818 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 6 | 5 | +0.0833 | 0.0833 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | FOR | yes |
| 6 | 6 | +0.0000 | 0.0000 | PARTIAL | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` | NONE | yes |

`confidence_rule_id` on every row: `CONFIDENCE.V2_ZERO_MARGIN` at (0, 0) only,
`CONFIDENCE.V2_SIGNED_MARGIN` everywhere else — including the disputed rows of D where the
number prices the challenged configuration rather than the counted one (see finding 3).

The 49 rows are the six properties' evidence. Read across a row: the sign says direction, the
magnitude says how lopsided the group counts are, the status says whether a verdict is
withheld, and `contested` says both directions are present.

## The properties, with pass/fail counts

| # | Property | Grid | Cases | Pass | Fail |
|---|---|---|---|---|---|
| 1 | `abs(score) <= 1` and `confidence == abs(score)`, exactly | U | 49 | 49 | 0 |
| 1 | same | D | 441 | 441 | 0 |
| 2 | swapping support and contradiction negates `score` | `score` over U | 49 | 49 | 0 |
| 2 | same, through `decide` with no dispute | U | 49 | 49 | 0 |
| 2 | same with `(ds, dc)` swapped too, through `decide` | D | 441 | **425** | **16** |
| 3 | one more support group never lowers the score | U, 42 up-steps | 42 | 42 | 0 |
| 3 | one more contradiction group never raises it | U, 42 down-steps | 42 | 42 | 0 |
| 3 | same, disputes held fixed | D, 378 up-steps | 378 | **352** | **26** |
| 3 | same, disputes held fixed | D, 378 down-steps | 378 | **358** | **20** |
| 4 | status implies its score band (SUPPORTED ≥ ½, CONTRADICTED ≤ −½, PARTIAL \|score\| ≤ ½, INSUFFICIENT = 0) | U | 49 | 49 | 0 |
| 4 | same | D | 441 | **433** | **8** |
| 4b | no PARTIAL carries a magnitude a SUPPORTED row carries | U | 49 | **48** | **1** — (1, 0) at 0.5 |
| 4b | same | D | 441 | **418** | **23** |
| 4c | SUPPORTED with score 0 does not exist | U | 49 | 49 | 0 (no instance) |
| 4c | same | D | 441 | 441 | 0 (no instance) |
| 5 | zero groups ⇒ score 0, confidence 0, non-committal status | 1 row | 1 | 1 | 0 |
| 6 | permutation of the evidence list yields an equal `Decision` | 5040 orders of a 7-record list | 5040 | 5040 | 0 |
| 6 | same, decisive case | 120 orders of a 5-record list | 120 | 120 | 0 |

Executed by `tests/test_confidence_reliability.py` (14 tests, all green) for the passing rows;
the failing rows are pinned as explicit assertions of the observed behaviour, so a future change
to any of them fails a named test instead of drifting.

### Finding 1 — `PARTIAL` reaches the decisive floor at exactly one row: (1, 0) = 0.5

Undisputed, the floor of the SUPPORTED band is `0.5` (attained first at (4, 1)) and `PARTIAL`
never exceeds it. At (1, 0) the two meet: one supporting group and nothing else scores `0.5`,
which is the same magnitude a SUPPORTED row carries, because `s >= 3c + 1` solved for the
formula is exactly `score >= 1/2` and the corroboration guard is a separate, non-magnitude
premise. Property 4's strict form ("no PARTIAL carries a magnitude a SUPPORTED configuration
could carry") therefore fails on **1 of 49** rows, and `test_only_the_single_source_row_sits_on_the_decisive_floor`
pins it. No other PARTIAL row in U reaches 0.5, and no PARTIAL in U exceeds it.

This sharpens `ct3/W9-proof-gap.md` gap 5, which records the mirror collision `(1, 0)` vs
`(0, 1)` (both 0.5). The collision is not only across direction: at 0.5 the same magnitude is
`PARTIAL` at (1, 0), `SUPPORTED` at (4, 1), and `CONTRADICTED` at (0, 1) — three statuses, one
number.

### Finding 2 — the reported number is not monotone on the disputed path

`decide` excludes a challenged record from the counts but, when the challenge is
decision-relevant, re-prices `score` to the challenged configuration. `ct3/W9-proof-gap.md`
gap 1 already records that this makes the pair `(status, score)` inconsistent, with
`decide(2, 0, disputed_contradiction=1)` as its witness; what is added here is the count. The
switch is not monotone: `decide(1, 0, disputed_contradiction=1)` reports `score(1, 0) = 0.5` (the challenge
cannot move a PARTIAL label, so the number does not move either), while
`decide(2, 0, disputed_contradiction=1)` reports `score(2, 1) = 0.25` — **one more supporting
group, a lower confidence**. 26 of 378 up-steps and 20 of 378 down-steps in D invert, and 8 of
441 PARTIAL rows carry a magnitude above the ½ floor (`(2, 0)` with a challenged contradicted
group reads 0.667). This is the same shape the signed table was introduced to remove from the
undisputed path; on the disputed path it is produced by the as-if pricing rule, which is
deliberate (`tests/test_decision_table_slice9_dispute.py` pins the re-pricing, including
`score == score(s + ds, c + dc)` on every relevant row).

### Finding 3 — one `confidence_rule_id` covers two different meanings

Relevant disputed rows report `CONFIDENCE.V2_SIGNED_MARGIN` while carrying the challenged
configuration's magnitude, and equally report it while carrying the unchanged counted one
(irrelevant dispute). A trace consumer therefore cannot tell from `confidence_rule_id` which
configuration the number describes; only `status_rule_id == STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT`
does. Reported, not changed: the ids are documented as stable trace identifiers for rule set
`story-connect-status-v2`, so reinterpreting one is a reasoning-rule version change, not a
workstream-4 edit.

## Why nothing was fixed

Both structural failures are the dispute rule and the corroboration guard, not the formula, and
neither can be repaired inside `decision_table.py` without moving behaviour that other pinned
tests own:

* capping or rescaling the (1, 0) magnitude makes `score` a function of the *label*, which
  `tests/test_table_differential.py::test_policy_choice_cannot_move_the_score` pins across
  policies (a label-dependent score would differ under `POLICY_TWO_TO_ONE`, where (1, 0) *is*
  SUPPORTED), and `test_the_guard_is_load_bearing` pins `decide(1, 0).score == 0.5` directly. The
  callers that would move are `app/engine.py:187` (`status, confidence = decision.status,
  decision.confidence`), `app/engine.py:215`, and the two claim constructors at
  `app/engine.py:534` (`Claim(confidence=...)`) and `app/engine.py:657` (the challenge path) —
  i.e. every claim's persisted `confidence` field, in the single-source case that is the most
  common real configuration.
* making the disputed path monotone means not pricing the challenged configuration, which
  `tests/test_decision_table_slice9_dispute.py` pins row-by-row (`score == score(s + ds, c + dc)`
  whenever the dispute is decision-relevant). That test file is outside this workstream's
  ownership, so a "fix" here would land as a red suite with no owner.

So the verdict on this workstream is: the number is trustworthy on the undisputed table
(properties 1, 2, 3, 4, 5, 6 hold over every enumerated configuration, 0 failures), and it is
**not** a verdict-strength measure on the disputed path, where it deliberately prices the
challenge. Both limits are now named in code-adjacent tests rather than in prose alone.

## What confidence does not mean

`confidence` is the magnitude of the group imbalance, `|s - c| / (s + c + 1)`, and nothing more.
It is not a probability, a calibrated likelihood, or a percentage of belief: it never sums with
anything, the empty row is 0 rather than 1/4 (the share a uniform choice over the four statuses
would give), and a claim with two support groups and one contradiction (0.25) is not "25%
likely" while a claim with two and none (0.667) is not "67% likely". Nor does a given magnitude
name one state: 0.5 is `PARTIAL` at (1, 0), `SUPPORTED` at (4, 1) and `CONTRADICTED` at
(0, 1), which is why the module ships `direction`, `contested` and `directional_evidence_mass`
beside it and why `app/engine.py:376` labels the field
`SIGNED_EVIDENCE_MARGIN_NOT_CALIBRATED_PROBABILITY`. It also does not measure evidence quality,
freshness margins, department diversity or review state: those are filters (a stale, unverified
or disputed record does not move the number) and separate reported fields, by design. What it
does say, exactly, is how lopsided the counts of independent source groups are, and — read with
`status` — whether that lopsidedness was enough to commit to a verdict. On the disputed path it
additionally says what the margin *would* be if the pending challenge were settled as aimed,
which is why it must never be read there without `status_rule_id`.

## Unrun, and what would move this

* The two non-default policies were not enumerated (unproved by design; nothing to ratify).
* The Coq model `ct3/DecisionTable.v` covers `POLICY_SIGNED_MARGIN` over the two integer counts
  and not the dispute rule; this document does not re-run Coq, so the proof status of the
  disputed path remains as `ct3/W9-proof-gap.md` records it — unchecked here.
* Nothing outside the repository was consulted; no claim here depends on deployment, traffic or
  an external consumer of `confidence`.


## Resolution of finding 2 (monotonicity at a status switch)

**Not a repaired bug — a chosen trade, now measured and pinned.**

`decide` reports the settled configuration's score, except when the challenged configuration
changes the label; then it reports the challenged one. Monotonicity fails exactly at those
switch points, and nowhere else in the undisputed grid:

| configuration | status | score | rule |
|---|---|---|---|
| `decide(1, 0)` | PARTIAL | 0.50 | `STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED` |
| `decide(2, 0)` | SUPPORTED | 0.667 | `STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION` |
| `decide(1, 0, disputed_contradiction=1)` | PARTIAL | 0.50 | balanced |
| `decide(2, 0, disputed_contradiction=1)` | PARTIAL | **0.25** | `STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT` |

More settled support, a lower reported score: 0.50 → 0.25. The pair of desiderata —
*monotone score* and *a withheld verdict never advertises the strength of the evidence under
challenge* — cannot both hold, because the second forces the number to be taken from a
different configuration at the switch while the first compares numbers across it.

**Choice: status integrity wins.** A reader who sees PARTIAL is being told "this is not
settled"; a number that rose with support would contradict that sentence. Restoring
monotonicity requires either (a) reporting the settled configuration always — then a PARTIAL
claim can carry 0.667 and a consumer reading score alone infers SUPPORTED, or (b) making score
a function of the label as well as the counts, which makes it no longer a function of the
evidence. Both are worse for a decision-support tool, so the discontinuity is documented in
`decide`'s docstring and pinned by
`test_the_reported_score_is_discontinuous_exactly_at_a_status_switch`.

**Also measured, unchanged:** one magnitude can carry two statuses — `decide(4, 1)` is
SUPPORTED at 0.50 and `decide(1, 0)` is PARTIAL at 0.50. So `score` never implies a status;
only `status` does. That is a property of the shipped rule, not a defect introduced here.
