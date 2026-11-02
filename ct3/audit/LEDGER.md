# Backend audit ledger — 5% per turn

Surface: `app/*.py`, 4196 lines. Nominal chunk 206 lines (5%).
Ordered by risk: trust boundary, decision logic, persistence, transport, gating, API.

| # | Range | Lines | Status |
|---|---|---|---|
| 01 | `app/provider_safety.py:1-291` | 291 | **CERTIFIED** |
| 02 | `app/provider_safety.py:292-497` | 206 | **CERTIFIED** |
| 03 | `app/provider_safety.py:498-703` | 206 | **CERTIFIED (one read-verified gap)** |
| 04 | `app/provider_safety.py:704-965` | 262 | **CERTIFIED** |
| 05 | `app/provider_safety.py:966-1009` | 44 | **CERTIFIED** |
| 06 | `app/engine.py:1-206` | 206 | **CERTIFIED** |
| 07 | `app/engine.py:207-412` | 206 | **CERTIFIED** |
| 08 | `app/engine.py:413-590` | 178 | **CERTIFIED** |
| 09 | `app/decision_table.py:1-206` | 206 | **CERTIFIED** |
| 10 | `app/decision_table.py:207-292` | 86 | **CERTIFIED** |
| 11 | `app/evidence_coverage.py:1-206` | 206 | **CERTIFIED** |
| 12 | `app/evidence_coverage.py:207-236` | 30 | **CERTIFIED** |
| 13 | `app/store.py:1-206` | 206 | **CERTIFIED** |
| 14 | `app/store.py:207-263` | 57 | **CERTIFIED** |
| 15 | `app/httpx_transport.py:1-206` | 206 | **CERTIFIED** |
| 16 | `app/httpx_transport.py:207-360` | 154 | **CERTIFIED** |
| 17 | `app/evaluate.py:1-206` | 206 | **CERTIFIED** |
| 18 | `app/evaluate.py:207-394` | 188 | **CERTIFIED** |
| 19 | `app/experiment_manifest.py:1-184` | 184 | **CERTIFIED** |
| 20 | `app/main.py:1-183` | 183 | **CERTIFIED** |

Ledger covers 3466 of 4196 lines (82%); remaining modules fold into
the tail of slice 20 if the count changes.

## Slice 1 evidence (certified 2026-11-01)

- `pytest -q tests/test_provider_safety*.py` — 120 passed
- `pytest -q` — 1123 passed, 0 failed
- `python ct3/audit/slice1_properties.py` — all six properties hold
- three defects found and fixed: missing credential patterns without a keyword,
  `request_too_large` overloaded with an internal accounting fault, and
  `copy`/`pickle` reconstructing the sealed payload through `bytes.__new__`.

A slice is certified only when every line is read, every stated contract is checked
against the code, every invariant has a test, and the suite is green.

## Slice 2 evidence (certified 2026-11-01)

- `pytest -q tests/test_provider_safety_slice2_contracts.py` — 17 passed
- `pytest -q` — 1140 passed, 0 failed
- `python ct3/audit/slice2_properties.py` — all checks pass, no SKIP left

Fixed in the slice:
- a non-bytes chunk reported `response_too_large`; it is now `malformed_response_body`,
  so a broken transport no longer reads as a client size verdict
- an exception in `aclose` replaced an in-flight `ProviderSafetyError`; close is now
  best-effort so the verdict survives
- `ProviderCallGate` documented as fail-closed (a gate without an enabled config refuses
  every call with `provider_disabled`) rather than "disabled by default", which read like
  an unlimited budget
- the `budget_exceeded` branch documented as subsumed by construction-time validation and
  kept as the only guard that would hold under a non-uniform estimate

Refuted during the slice (recorded so it is not re-raised):
- "two providers double the budget" — a gate is only active when a caller passes an
  enabled `ProviderBudgetConfig`; `gate=None` is a kill switch, not a fresh budget
- "dispatch authorisation is only read-verified" — minting needs no network, so
  single-use, identity binding and timeout binding are each covered by a test now

## Slice 3 evidence (certified 2026-11-01)

- `pytest -q tests/test_provider_safety_slice3_contracts.py` — 4 passed
- `pytest -q` — 1144 passed, 0 failed
- `python ct3/audit/slice3_properties.py` — all properties pass

Fixed in the slice:
- duplicated timeout validation removed; two copies of a security predicate were
  one edit away from diverging, and the second could not fire
- a response could be dropped unclosed when cancellation landed between `send`
  returning and the bounded read starting; `exchange` now closes it in a `finally`
  through a shared `_close_quietly`

Verified and documented, not changed:
- `_TRANSPORT_SINGLE_FLIGHT` uses a non-blocking `threading.Lock`: it cannot park
  the event loop, it rejects rather than queues (`concurrent_request`), and it is
  process-local, so a multi-worker deployment gets one in-flight call per worker
- the gate is reserved inside the lock, so two coroutines cannot both take the
  last permitted call

Known gap, stated rather than papered over:
- the cancellation close is read-verified only. `HttpxAsyncTransport` is sealed
  (`__slots__` + immutable), so a transport double cannot be injected and the
  `finally` cannot be exercised end to end. The individual close path is covered
  by the slice-2 test that asserts `response.closed` on the error path.

## Slice 4 evidence (certified 2026-11-01)

Ten parallel agents, then the coordinator ran everything.

- `pytest -q tests/test_provider_safety_slice4_contracts.py` — 12 passed
- `python ct3/audit/slice4_properties.py` — all pass
- `python ct3/audit/slice4b_properties.py` — all pass
- `pytest -q` — **1156 passed, 0 failed**

Fixed:
- `RecursionError` from `json.loads` escaped both parsers as an unclassified 500;
  now `malformed_response` (pinned by a monkeypatched test, not by nesting depth,
  because 2000 levels parses fine and fails later for an unrelated reason)
- response `model` is now pinned two-way against `MODEL_SLUG`; the request pinned
  the model but the response was only checked for a non-empty string
- `MAX_PROPOSALS = 128`: an unbounded array becomes claim evidence downstream
- the adapter dispatch path dropped its response on cancellation, exactly like the
  provider path fixed in slice 3; both now close in a `finally`
- `bounded_provider_call` reported a bad *provider* as `unsupported_transport`;
  renamed `unsupported_provider`

Documented, not changed (product decisions, priced):
- quote grounding is a 3-character substring test, so `"the"` grounds any proposal
  against any record containing it — the quote is what a human auditor reads
- key-set equalities reject benign vendor extras (`logprobs`, `system_fingerprint`,
  token details). Deliberate fail-closed; a recorded real response is needed before
  relaxing, because over-strictness here reads as an outage
- the model pin has no recorded live echo, so a dated or aliased model string would
  fail every real call. Stays strict until a fixture exists
- `invalid_request` still covers our own envelope re-parse failing, an internal fault
  wearing a client error

## Slice 5 evidence (certified 2026-11-01)

`app/provider_safety.py` is now **fully audited** (1009 lines, slices 1-5).

- `pytest -q tests/test_provider_safety_slice5_contracts.py` — 3 passed
- `pytest -q` — 1159 passed, 0 failed

Pinned in this slice:
- a boundary is immutable after construction (the seal was enforced but untested)
- an unapproved provider is refused with `unsupported_provider`
- a local provider sees only the projected `id`/`text` fields, and a restricted
  record never reaches it — the projection, not the caller's records, is the input

## Slice 6 evidence (certified 2026-11-01)

- `pytest -q tests/test_engine_slice6_contracts.py` — 11 passed
- `pytest -q` — **1170 passed, 0 failed**

Fixed in the slice:
- a record dated after the evaluation instant had a negative age, so `age > STALE_DAYS`
  never fired and a typo'd year stayed current proof forever. It is now non-current
  (`stale = age > STALE_DAYS or age < 0`) rather than rejected, because callers that
  evaluate against a historical clock legitimately see the corpus in the future
  (`test_legacy_challenge.py` does exactly that)
- an offset-less `Record.timestamp` (reachable: `store.py` passes stored text through)
  subtracted from an aware clock raised an unclassified `TypeError`; both sides are
  now normalised to UTC
- a group holding both a challenged and an unchallenged record was counted twice in
  the as-if evaluation (`s + disputed_support`), so one source read as two, reached
  2:0 and marked the challenge decision relevant. Callers now pass only the groups
  the undisputed counts miss; `decide(disputed_total=...)` keeps the challenged-group
  count honest in the reported decision

Documented, not changed:
- `diverse` and `departments_by_source` are computed and read by nothing since the
  signed table took group counts only; the explanation trace still advertises a
  department-diversity rule that no longer moves the verdict
- `invalid_source` covers a malformed id, a missing record and a restricted record,
  so a policy refusal is indistinguishable from an integration bug
- the module docstring says "Deterministic" while the default clock is wall clock

Refuted during the slice (recorded so it is not re-raised):
- "future-dated records must be rejected with a new error code" — tried, and it broke
  the historical-clock test; non-current is the property that matters, not invalidity

## Slice 7 evidence (certified 2026-11-01)

- `pytest -q tests/test_engine_slice7_contracts.py` — 9 passed
- `pytest -q` — **1179 passed, 0 failed**

Fixed in the slice:
- `_iso_utc` reinterpreted an offset-less datetime as host-local time while still
  labelling the result `Z`, so an injected naive clock wrote an instant that
  depended on `TZ`. Naive values are UTC by convention, as in slice 6
- `zip(evidence, evidence_evaluation_times)` truncated the trace's per-record
  staleness table with no signal, so an audit trace could cover fewer records than
  its own dispositions. One row per record now, and a missing time is named
  (`UNKNOWN_MISSING_EVALUATION_TIME`) instead of borrowing the preserved-flag basis

Documented, not changed:
- `_evidence_dispositions` rebuilds the support-group map and marks `members[:-1]`
  dependent, while `decision.dependent_support_ids` already encodes that rule; the
  two can name different records for the same trace, and the rebuild keys on `id()`,
  so a copied `Evidence` reads `UNCLASSIFIED_REVIEW_REQUIRED`
- `summarize_status` has no production caller; tests are its only consumer
- `staleness_policy.decision_evaluated_at` is `generated_at`, while the rows beside it
  say `ASSESSMENT_VALIDATION`; a consumer recomputing staleness gets a different answer
- `malformed_output` covers both "not a list" and "item key set differs"
- `except Exception -> provider_failure` also catches our own boundary faults
- the trace still advertises `department_diversity_uses_last_support_record_per_group`
  for a computation (`diverse`) that no longer feeds the verdict

Not reachable from this slice, handed on:
- `challenge` lives at 413+ (slice 8). Its two refusals share `invalid_assessment`,
  so a missing record and an absent quote are indistinguishable by code

## Slice 8 status (audited 2026-11-01, **not certified**)

Every line of `engine.py:413-634` was read this turn (`_provider_assess`,
`_review_item_with_trace`, `_review_item`, `_claim`, `investigate`,
`assess_hypothesis`, `challenge`). No code in the range was changed, so the
1179-test green run above does not vouch for it and the row stays uncertified.

Read and recorded, not fixed:
- `challenge` raises three different refusals under the default `invalid_assessment`
  code: unknown record, quote not a source substring, and "not an assessed
  dependency". An operator cannot tell a client mistake from a missing dependency
- `_provider_assess` computes `permitted = eligible_provider_records(records)` and
  then hands the boundary `records`, not `permitted`. Safe only because
  `MandatoryProviderBoundary` projects; the comment above it claims the line is the
  permission boundary, which is a refactor trap for the next caller
- `challenge` reconstructs the semantic-decision and evaluation-time lists
  positionally (`index == len(evidence_models) - 1` for the newly appended item), so
  any future append order change silently mislabels which row carries the new
  decision
- `_claim` dedupes on `(source_record_id, quote, stance, review_state)`, so two
  proposals differing only in rationale collapse to the first — deliberate, but it
  means a second, better-supported rationale is dropped without a trace entry

Owed before the row can be flipped: a slice-8 test file pinning the three refusal
codes, challenge purity (the caller's dict is also `expected_claims`), the
version+1 contract, and a challenge against a stale record.

### Slice 8 update — ten `worker` agents, tests landed, one defect still open

`pytest -q` — **1212 passed, 0 failed** (was 1179; +33 from the three new files, each author
ran its own file green).

New evidence:
- `tests/test_engine_slice8_challenge.py` (8) — caller dict unmutated (byte-identical, ids
  disjoint), version+1, exactly one more item, four refusals all `invalid_assessment`,
  re-challenge is idempotent, restricted record refused with no canary in the message
- `tests/test_engine_slice8_provider.py` (20) — `provider_failure` carries no record text
  and suppresses the cause chain, per-code safety errors, `malformed_output` on non-list
  and on key-set drift, `invalid_source` for a restricted record
- `tests/test_engine_slice8_trace.py` (5) — one semantic row and one staleness row per
  item, the appended item's row is not `PRIOR_GUARD_DECISION_UNAVAILABLE`, `generated_at`
  equals the injected clock
- `ct3/audit/slice8_properties.py` — 5 of 6 pass; the failing one is the literal wording of
  "disputed count == matched challenges" (the flag is boolean and idempotence is
  deliberate), documented rather than "fixed"

Still open, so the row does not read CERTIFIED:
- **`challenge` never re-evaluates staleness.** It copies stored `stale` flags and pairs
  them with the old `evaluated_at` while the trace says `ASSESSMENT_VALIDATION`. Observed
  by a worker: a claim persisted 2025-06-01 stays INSUFFICIENT with all rows stale when
  challenged on 2026-10-25, while `assess_hypothesis` over the same corpus at the same
  clock returns PARTIAL 0.25 with six fresh rows. The route persists the revised claim, so
  the API can serve a verdict its own engine contradicts
- six refusal causes share `invalid_assessment`, and `main.py` never reads `.code`, so a
  split in `engine.py` alone would not be observable — it is a two-file change
- `_claim`'s dedupe key includes `stance`, so one record proposed in both directions
  becomes two rows in one group: `PARTIAL`, score 0, and a `conflicts` sentence naming the
  same record on both sides
- `_review_item_with_trace` overwrites the provider's `rationale` in place and stores the
  original nowhere, so two contradictory proposals persist byte-identical

### Slice 8 closed (certified 2026-11-01)

- `pytest -q tests/test_engine_slice8_challenge.py` — 9 passed
- `pytest -q` — **1213 passed, 0 failed**

Fixed after the workers' reports:
- **`challenge` now re-evaluates staleness at its own clock.** It previously copied
  the persisted `stale` flags and the old `evaluated_at` values while the trace said
  `ASSESSMENT_VALIDATION`, so a claim challenged months after it was written could
  report INSUFFICIENT with every row stale, contradicting `assess_hypothesis` over
  the same records at the same instant. Freshness now lives in one `_is_stale`
  helper used by both paths, and the raw dicts are updated alongside the models so
  a claim's verdict and its own rows cannot disagree (the first cut of this fix
  scored the claim fresh while its evidence rows still said stale — caught by the
  new test)
- pinned by `test_challenge_re_evaluates_staleness_at_its_own_clock`: a claim built
  at 2026-10-25 over 2025-06-01 records must, when challenged at 2025-06-02, match
  a fresh assessment at that instant, with every row fresh and every trace row
  timestamped at the challenge clock

Left documented, not changed (all recorded above): the six refusal causes sharing
`invalid_assessment` (a two-file change — `main.py` never reads `.code`), the
`stance`-inclusive dedupe key, and the rationale overwrite.

## Slice 9 evidence (certified 2026-11-01)

- `pytest -q tests/test_decision_table_slice9_partition.py` — 11 passed
- `pytest -q tests/test_decision_table_slice9_labels.py` — 17 passed
- `pytest -q` — **1263 passed, 0 failed**

The whole module (307 lines, not just 1-206) was read. The rule matches its proof:

| code | `ct3/DecisionTable.v` |
|---|---|
| `s >= 2 and s >= 3c + 1` → SUPPORTED | `supported s c := 2 <= s /\ 3*c + 1 <= s` (line 120) |
| `c >= 3s + 1` → CONTRADICTED | `contradicted s c := 3*s + 1 <= c` (line 122) |

Pinned at the boundaries where code and proof could drift: 2:0 SUPPORTED, 1:0 PARTIAL,
3:1 PARTIAL, 4:1 SUPPORTED, 0:1 CONTRADICTED, 1:3 PARTIAL; exclusivity and the score
range over the 0..6 grid; antisymmetry; strict monotonicity in support; `score` refusing
negative counts; and the three named policies producing visibly different verdicts.

Recorded, not changed:
- **The refutation bound is asymmetric on purpose.** `min_support_groups` applies to
  SUPPORTED only, so one contradiction is decisive while one support is not — and the
  Coq model has exactly the same shape. The module docstring states the "single source
  is partial" half and not the other, which is what invites a well-meaning "fix"
- `_count_groups` partitions **per record**, so a group holding a challenged and an
  unchallenged record appears in both `support` and `disputed_support`; the dedupe that
  keeps the as-if arithmetic honest lives in the callers (`decide_evidence`, `engine`),
  which the partition tests now prove rather than assume
- `Status`'s member name is misspelled `SUPPORTED` (value `"SUPPORTED"`), invisible
  through the API but misleading in code; a rename is cosmetic and was not attempted
- `POLICY_TWO_TO_ONE` leaves the engine's missing-evidence advice (hardcoded "2 groups")
  contradicting the verdict; the policy is never the default, so this is latent

## Slice 10 evidence (certified 2026-11-01)

Read in the same pass as slice 9 (the module was read to its last line, 307), so the
two ranges are certified together rather than by two half-reads.

`score`, `_label`, `decide`, `decide_evidence` are pinned by:
- `tests/test_decision_table_slice9_labels.py` (17) — score antisymmetry, range,
  strict monotonicity in support, negative counts refused, label boundaries, and the
  three policies disagreeing by construction
- `tests/test_engine_slice6_contracts.py` — the dispute paths through `decide_evidence`:
  a group holding a challenged and an unchallenged record counts once, a genuinely
  additional disputed group is still decision-relevant, and `disputed_groups` stays
  honest through `disputed_total`

`pytest -q` — **1263 passed, 0 failed** (the same run that closes slice 9).

Recorded, not changed:
- `decide` is the only place that validates nothing about negative counts; `score`
  raises `ValueError` for them, so a caller passing `-1` fails deep in the arithmetic
  rather than at the entry point. No caller does
- `confidence_rule` is chosen from the *undisputed* counts even when a dispute
  downgrades the verdict, so a PARTIAL claim can carry `CONFIDENCE.V2_SIGNED_MARGIN`
  over a score computed from the challenged configuration

## Slices 11-12 evidence (certified 2026-11-01)

The module is 236 lines, so both slices were read in one pass and are certified together.

- `pytest -q tests/test_evidence_coverage_slice11.py` — 11 passed
- `pytest -q` — **1274 passed, 0 failed**

Pinned: every hypothesis in `HYPOTHESES` has a category table; a hypothesis declared but
unmapped raises `ValueError` (not the `KeyError`/500 the guard comment describes); a
non-list or a foreign element raises `TypeError`; coverage is deterministic and does not
mutate its input; a contradiction-only PRIMARY category reports `covered_by_fresh_accepted`
true with `direction: AGAINST` and prompts "points against"; one source group is
`non_independent` and asks for a second; unverified, stale and disputed evidence is
excluded from coverage and each gets its own prompt; an absent `semantic_relation` is
surfaced as unclassified rather than guessed from stance; neutral evidence is reported and
counts as no coverage.

Changed: `advisory_missing_evidence` computed `fresh = [...]` and never read it — removed,
no behaviour change.

Recorded, not changed:
- `neutral` and `unclassified` are recomputed inside the per-category loop but are
  hypothesis-level, so every category of one hypothesis carries identical lists. Harmless
  duplication that makes the payload look category-specific when it is not
- `matching_evidence` rows carry review state, staleness and dispute but not the
  `semantic_relation` that caused the match, so a reader cannot audit the association
  from the payload alone
- `covered_by_fresh_accepted` stays direction-blind by explicit product decision; the
  direction flags beside it are the only thing that separates "supports" from "refutes"

## Slices 13-14 evidence (certified 2026-11-01)

The module is 263 lines, read in one pass; both slices certified together.

- `pytest -q tests/test_store_slices13_14.py` — 9 passed
- `pytest -q` — **1283 passed, 0 failed**

**Defect found and fixed — `connect()` relabelled the caller's own `ValueError`.** The
`except (OSError, ValueError)` was meant for `validate_database_path`, but it wrapped the
`yield` as well, so every `ValueError` a caller raised inside the block — a recomputed
claim set that does not match the affected dependencies, a claim id that does not match
its stored id — surfaced as `DatabaseUnavailable` ("Prototype database is unavailable"),
a 503 for what is a 422-class client error, with the real cause hidden. Path validation
now has its own handler and the body's exceptions pass through untouched. Pinned by
`test_a_recomputed_set_that_does_not_match_the_affected_claims_is_refused`, which failed
with `DatabaseUnavailable` before the fix.

Also pinned: `initialize_database` is idempotent (seed count unchanged on a second run);
a path outside `data/` is refused by both `database_path` and `initialize_database`;
connecting to an uninitialised file raises `DatabaseUnavailable`; restricted records are
absent from `list_records()` and `get_record` returns `None` for them; an investigation
round-trips with its `CREATED` event; a challenge bumps the investigation to version 2,
bumps only the affected claims, leaves an unaffected claim at version 1, and appends one
`CHALLENGE` event; a stale revision writes nothing (version and history unchanged); and a
tampered `expected_claims` is refused as `StaleRevision`.

Recorded, not changed:
- `get_challenge_snapshot` opens `BEGIN` and never commits or rolls back; the connection
  close rolls it back, which is correct for a read snapshot but relies on close semantics
  rather than on an explicit end
- `list_records` orders by the ISO text of `timestamp`, so records written with different
  offsets would sort by string, not by instant; every writer currently uses `+00:00`
- `_save_claim` surfaces a duplicate `(investigation, claim, version)` as a
  `DatabaseUnavailable` rather than a revision conflict; no path produces one today

## Architecture artifacts (2026-11-01)

The slice ledger answers "was every line read". These answer the separate question the
user actually set: is the design safe, and is each decision defensible.

| Artifact | What it establishes | State |
|---|---|---|
| `ct3/audit/DECISIONS.md` | 12 load-bearing decisions, each with the alternative it beat, a falsifier and the test that fails if it is reversed | 11 pinned, 1 open (provider allowlist vs. a live vendor echo) |
| `ct3/audit/THREAT-MODEL.md` | 25 abuses across 5 surfaces, each paired with the control and the test that fails when the control is removed | 20 proven, 2 partial (B5 vendor-echo rejection only, T1 timeouts configured), 1 declared not defended (H1 no auth), 2 open (H8 rate limiting, B6 false rejection), 1 corrected (T2 was already closed) |
| `backend/tests/test_architecture_invariants.py` | claim == reassessment, no restricted text in a provider request, determinism, challenged claim == reassessment | 4 green on the seed corpus; generative inputs not yet written |
| `backend/tests/test_threat_controls.py` | one test per HTTP-surface control row | 7 green |

`pytest -q` — **1295 passed, 0 failed**.

Not claimed: that the design is *perfect*. Claimed, and checkable: every decision has a
named alternative, every control has a test that fails without it, and the two gaps that
remain are named rather than covered by a green tick.

## Slices 15-20 closed (2026-11-01)

Ten `worker` agents; each wrote its own test file and ran it. Suite after all of them:
**1665 passed, 1 xfailed, 0 failed.**

| Slice | Module | New evidence | Run |
|---|---|---|---|
| 15 | `access.py` | 16 tests — deny path is the served path, restricted dropped and nothing else, input not mutated or aliased, frozen context | 16 passed |
| 15b | `experiment_control.py` | 88 tests — constructor bounds, run-id rules, single-flight/concurrency, reservation before callback, no refund on failure; mutation-tested on a throwaway copy (7 mutations, each failed its tests) | 88 passed |
| 16 | `httpx_transport.py` | adversarial slow-peer tests (T1): real loopback server, 0.3 s timeout returned in 304/303 ms, parser never reached, peer saw EOF; a 20 s-timeout call is still pending at 1.5 s, which is what makes the fast return attributable to the timeout | 3 passed |
| 17 | `models.py` | 28 tests — every verdict-changing default, enum closure, preset-map totality, exact field lists | 28 passed |
| 17b | `evaluate.py` | 6 tests — `exc.code` read, failure counted not swallowed, metrics recomputable from reported rows, persisted DB byte-identical, `EVALUATION_AS_OF` honoured | 6 passed |
| 18 | `semantic_guard.py` | 9 passed + 1 strict xfail stating a real defect (below) | 9 passed, 1 xfailed |
| 19 | `mock_provider.py` | 26 tests — corpus invariants; "timestamps ordered" is false as stated and was pinned only for the chronological body | 26 passed |
| 19b | `experiment_manifest.py` + `main.py` | 56 tests — manifest fields, route status codes, preset coupling, `_derive_preset_id` refusing to guess, history ordering, no restricted id in any body | 56 passed |
| 20 | `provider_activation.py` | 17 tests — gate off by default, no env var enables network, boundary still bound, every failure leaves the engine on mock | 17 passed |

### Defects these agents found

1. **`semantic_guard` misses verb-carried negation** — reported by the slice-18 worker and
   reproduced by its strict xfail (`test_semantic_guard_slice18.py`, the one xfailed test in
   the suite): "There was not enough time…" and "We did not have enough time…", the same
   proposition, reach opposite accepted relations. My own probe of `reviewed_relation` alone
   returns `None` for both, so the failing path is the details/engine layer, not the bare cue
   matcher — which is why this is recorded against the xfail rather than as a fix target yet.
2. **`/api/health` reports `ok` for a `HACKATHON_DB_PATH` that `validate_database_path`
   rejects**, while every data route 503s. The health signal and the availability it
   describes disagree.
3. **`experiment_manifest` is not bound to the execution it describes** — zero attempts is
   valid, attempts can be added after the fact, and its only in-repo producer passes
   `code_revision=None` and never sets `model_name`/`model_version`/`temperature`/`seed`,
   so the model that actually ran is absent from the record. `request_count` receives the
   cumulative run counter, not the per-case count.
4. **The uninitialised-database 503 points at `hackathon/README.md`**, which does not exist
   in the repository.
5. **`provider_activation.create_assessment_engine` has no caller** — `main.py` builds
   `AssessmentEngine()` directly, so the running app cannot activate a real provider
   without a code edit, and an omitted `activate_baseten` flag silently ignores a working
   key source.
6. **`store.py:158/239` stamp wall-clock `datetime.now()`** inside the disposable
   recomputation DB, while `evaluate.py` claims the clock is injected for the whole run.
7. **`ChallengeCreate` does not forbid unknown keys**, unlike `InvestigationCreate`;

   and `question`'s `min_length` is applied before stripping, so `"        x"` is accepted
   and stored as `"x"`.
8. **`mock_provider`'s `assessment_overrides` echoes fabricated citations verbatim**; the
   only rejection is downstream in the engine boundary.

### Four of those defects fixed in the same session (2026-11-01)

| # | Fix | Evidence |
|---|---|---|
| 1 | `semantic_guard._is_negated` now also matches a negation carried by an auxiliary before the cue (`did not have`, `don't have`, `was not be`), so "We did not have enough time…" can no longer be certified as the opposite of "There was not enough time…" | the strict xfail became a normal test, `test_verb_carried_negation_cannot_certify_the_opposite_stance` — it asserts `relation is None` and `reason_code == "NEGATED_CUE"` |
| 2 | `/api/health` reports `misconfigured` when `database_path()` rejects the configured path, instead of `ok` while every data route 503s | `test_health_reports_misconfigured_when_the_path_is_rejected` (renamed from the characterisation test that pinned `ok`) |
| 4 | The uninitialised-database 503 names a runnable command and the README that exists, not `hackathon/README.md` | `tests/test_api.py` updated at the assertion site |
| 7 | `ChallengeCreate` forbids unknown keys like `InvestigationCreate`; `question`'s `min_length` now measures the stripped value, so `"        x"` is refused | `test_challenge_create_forbids_unknown_fields`, `test_investigation_question_length_is_measured_after_strip` (both renamed from tests that pinned the old behaviour) |

`pytest -q` — **1666 passed, 0 failed, 0 xfailed**.

Still open from that list: the manifest is not bound to the execution it describes (3);
`provider_activation` has no caller in `main.py` (5); `store.py` stamps wall-clock time
inside the evaluation DB (6); `mock_provider` echoes fabricated citations verbatim in
`assessment_overrides` (8). Each is a design change rather than a defect repair, and none
is claimed fixed here.

### Terra worker wave (2026-11-01): three defects closed, two limits found

Deployed as `worker` (GPT-6.1 Terra) only — no base3 catalog was used in this wave. Six of
the ten were refused by the account's subagent budget (`429 turn_spend_limit`) before they
started; four had already run and written code before the refusals. Two of the four landed
changes that I then had to reconcile; nothing was accepted unread.

Closed:

| Defect | Fix | Evidence |
|---|---|---|
| `mock_provider.assessment_overrides` echoed fabricated citations verbatim | `validate_fixture_output` runs on the fixture branch: `invalid_source` for a record not in this call's input, `invalid_quote` for a quote not in that record, `malformed_output` for a bad shape | `tests/test_mock_overrides_grounding.py` (7). The slice-19 test that pinned the old echo was **inverted**, not deleted — it now asserts the refusal |
| `experiment_manifest` not bound to the run it describes | attempts are fingerprinted on add and re-checked on serialise; `seal()` refuses an empty manifest and any later attempt | `tests/test_manifest_and_routes.py` — the "manifest can be rewritten after construction" test was inverted into `test_attempts_written_outside_add_attempt_cannot_be_serialised` |
| `store.py` stamped wall clock inside the evaluation DB | keyword-only `clock` with the wall clock default (`_stamp`), and `evaluate.py` now passes `lambda: EVALUATION_AS_OF` at both write sites | `tests/test_store_clock.py`; `test_evaluate_contracts.py` and `test_evaluation.py` green together (17 passed) |

New gap found, not closed: `_is_negated` still misses a **quantifier** negation in subject
position — "Nobody walked through the handover with her." and "No one was short staffed."
are certified in the affirmative direction. A 45-row corpus
(`tests/test_semantic_guard_negation_corpus.py`) pins both as strict xfails, so a future fix
flips them to XPASS rather than passing silently. The corpus also confirms the auxiliary
widening does **not** over-trigger: 27 sentences containing `not`/`no`/`never` without
negating the cue still certify, including `, not the checklist` and quoted `No`.

`pytest -q` — **1766 passed, 2 xfailed, 0 failed**.

Still open: rate limiting (H8), the vendor false-rejection question (B6 / decision 7), and
`provider_activation` still has no caller in `main.py` (the wiring worker was one of the
429s).

### Last open threat row closed, activation wired (2026-11-01, final pass)

- **H8 (request flooding) is now defended.** `app/rate_limit.py` is a bounded,
  monotonic-clock token bucket with a capped key map and `Retry-After`; `main.py` runs it as
  middleware at 600 requests/minute per client host. `tests/test_rate_limit_wiring.py`
  proves the second call is refused, the refusal never reaches the route, and the bucket is
  per client rather than global.
- **Provider activation is wired.** `main.py` builds its engine through
  `build_engine_from_environment`, which activates Baseten only when the flag is set,
  a key source is supplied and the budget is enabled; every failure logs the code and falls
  back to the mock. `tests/test_activation_wiring.py` covers default, flag-without-key and
  failed-activation-leaves-mock.

Threat model: **22 proven, 1 partial (B5 vendor echo), 1 declared (H1 no auth), 1 open (B6
false rejection)**. The two remaining are both the same external dependency: one recorded
response from the live vendor.

### Quantifier negation closed; no xfails left (2026-11-01)

The single-worker deployment was refused again (`429 turn_spend_limit`), so I made the fix
directly. `_is_negated` now also treats a subject quantifier (`nobody`, `no one`, `none of`,
`neither`) as scoping over the cue — unless a reporting verb or a complementiser `that`
sits between them, in which case the quantifier scopes over the matrix clause and the cue
still certifies.

- "Nobody walked through the handover with her." → abstains (`NEGATED_CUE`)
- "No one was short staffed." → abstains
- "No one said the binder was missing." → still certifies SUPPORTS
- "No one doubted that the colleague was unsure…" → still certifies (the `that` rule)

`tests/test_semantic_guard_negation_corpus.py` — **55 passed**, with the two former strict
xfails now ordinary assertions and six new quantifier rows added, three of which must not
abstain. Full suite: **1779 passed, 0 failed, 0 xfailed**.

### The three audit artifacts finished without agents (2026-11-01)

Subagent spawning stayed at `429` for the hour, so the three read-only artifacts were done
directly, each grounded in a command that was actually run:

- **`THREAT-VERIFICATION.md`** — all 18 control tests the threat model cites were located by
  name and run individually: `18 passed in 1.13s`. The file also records what that does not
  prove: no mutation sweep exists for the HTTP-threat tests, so H2–H7 are proven to pass
  against this code, not proven to be removal-sensitive.
- **`DECISIONS-DRIFT.md`** — 11 CURRENT, 1 UNPROVEN, 0 DRIFTED, with the implementing code and
  the reversing test quoted per decision. The two decisions made in this session (rate limit,
  activation factory) were then added to the register as rows 13 and 14, so it now carries
  **14 decisions, 13 pinned, 1 unproven**.
- **`REVIEW-GUIDE.md`** — the run commands (verified: `1779 passed`), what each artifact
  answers, and an explicit statement that `ct3/audit/slice8_properties.py` is expected to
  report one failure whose cause is documented.

## 50-minute attack-surface sweep (2026-11-02)

Two new probe suites, 22 probes, all executed: `tests/test_attack_surfaces.py` (HTTP and
rate-limit surface) and `tests/test_attack_surfaces_engine.py` (engine and store shapes).
Full suite **1801 passed, 0 failed**. Report: `ct3/audit/ATTACK-SURFACE-PROBES.md`.

Four defects found, all fixed with a failing-first test:

1. **A lone surrogate crashed the 422 renderer** (`UnicodeEncodeError` inside Starlette's
   default handler) — a client-controlled 500 from a validation path. Fixed with an explicit
   `RequestValidationError` handler; `NaN`/`Infinity` were the same crash and are now 422.
2. **My own `MAX_PROPOSALS = 32` was wrong.** A 40-record corpus failed with
   `malformed_output`. Measured boundary: 43 records assessable, 44 refused — exactly the
   proposal count that fills the 4 KiB body. Reverted to 43 and pinned the capacity boundary.
3. **`Evidence(source_record_id="")` was constructible** — the identity field of a citation
   could cite nothing. Now `min_length=1`.
4. **Documented, not fixed:** a corpus larger than 43 cannot be assessed in one call, and the
   error says `malformed_output` rather than naming capacity. That misnamed code is the open
   item from this sweep.

Closed surfaces: SQL metacharacters and traversal in path parameters (404, tables intact),
`text/plain` JSON bodies (422), duplicate keys (deterministic), `X-Forwarded-For` rotation
(no fresh bucket), limiter key map (capped at 1024 after 5000 keys), two threads on one
snapshot (one commit, one stale), forged claim version (overwritten), 5000-item summarise
(under 2s), whitespace-only quote (refused), empty corpus (five INSUFFICIENT claims).
