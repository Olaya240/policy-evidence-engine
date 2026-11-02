# W3 — what the test suite will and will not notice when the decision table changes

Scope: read-only survey of `/home/alex/policy-evidence-fix/backend/tests`. No source edited.
Branch under test: `fix/evidence-decision-table` @ `8c1b808` (same tree as `feature/backend-evidence-engine`).

Everything below is `Read` with a path:line. Nothing here is an execution result — I had no terminal.

---

## 1. Assertions that pin a numeric confidence literal

| path:line | test | evidence shape fed in | pins |
|---|---|---|---|
| `test_engine.py:81` | `test_multiple_independent_departments_support_without_count_alone_as_proof` | 2 supports, Front Office + Housekeeping | `confidence < 1` (**inequality**) |
| `test_engine.py:88` | `test_same_department_independent_records_are_not_treated_as_diverse` | 2 supports, same department | `confidence < .78` (**inequality**) |
| `test_engine.py:135` | `test_stale_contradiction_is_reported_without_being_counted_as_fresh` (2 params) | 1 fresh (support or contradict) + 1 stale **opposite** | `== 0.54` |
| `test_engine.py:175` | `test_stale_unverified_contradiction_does_not_change_supported_status_or_confidence` | 2 accepted supports, 2 departments | `(SUPPORTED, 0.78)` |
| `test_engine.py:190` | `test_stale_unverified_support_does_not_change_contradiction_status_or_confidence` | 1 accepted contradiction | `(CONTRADICTED, 0.58)` |
| `test_engine.py:208` | `test_fresh_unverified_evidence_does_not_change_status_or_confidence_and_is_annotated` (2 params) | 1 accepted support + 1 unverified | `(PARTIAL, 0.55)` |
| `test_engine.py:226` | `test_only_fresh_unverified_evidence_has_same_status_and_confidence_as_no_evidence` (2 params) | 1 unverified, nothing else | `(INSUFFICIENT, 0.2)` |
| `test_engine.py:244` | `test_stale_unverified_only_does_not_change_empty_status_or_confidence` (3 params) | 1 stale unverified | `(INSUFFICIENT, 0.2)` |
| `test_engine.py:274` | `test_stale_accepted_contradiction_behavior_is_unchanged_by_unverified_evidence` (4 params) | 1 fresh accepted support + 1 **stale accepted** contradiction | `(PARTIAL, 0.54)` |
| `test_engine.py:296` | `test_both_unverified_stances_do_not_change_accepted_status_or_confidence` | 1 accepted support + 1 unverified support + 1 unverified contradiction | `(PARTIAL, 0.55)` |
| `test_engine.py:399` | `test_semantic_guard_disabled_accepts_unmatched_proposal_and_default_application_is_guarded` | guard **off**, one accepted support | `confidence == 0.55` |
| `test_engine.py:409` | same test | guard **on**, proposal abstained | `confidence == 0.2` |
| `test_engine.py:561`, `:563` | `test_new_guarded_assessment_serializes_explicit_review_state` (params) | guard-accepts-cue / guard-abstains | `0.55` / `0.2` |
| `test_engine.py:587` | same test | — | `claim["confidence"] == expected_confidence` |
| `test_explanation_trace.py:48` | `test_trace_rule_ids_match_existing_status_branches[parts]` | 1 support + 1 contradiction | `.52` |
| `test_explanation_trace.py:51` | `…[fresh-and-stale]` | 1 fresh support + 1 stale support (120d) | `.54` |
| `test_explanation_trace.py:54` | `…[diverse-support]` | 2 supports, 2 departments | `.78` |
| `test_explanation_trace.py:57` | `…[same-department-support]` | 2 supports, 1 department | `.68` |
| `test_explanation_trace.py:59` | `…[single-support]` | 1 support | `.55` |
| `test_explanation_trace.py:61` | `…[single-contradiction]` | 1 contradiction | `.58` |
| `test_explanation_trace.py:64` | `…[multiple-contradictions]` | 2 contradictions | `.68` |
| `test_explanation_trace.py:66` | `…[stale-only]` | 1 stale support (120d) | `.25` |
| `test_explanation_trace.py:67` | `…[empty]` | `[]` | `.20` |
| `test_explanation_trace.py:70` | `…[neutral-only]` | 1 neutral | `.30` |
| `test_explanation_trace.py:81` | same test | — | `claim["confidence"] == confidence` |
| `test_explanation_trace.py:98` | `test_disputed_branch_has_stable_rule_id_and_original_stale_acceptance_behavior` | 1 support, pre-challenge | `before["confidence"] == .55` |
| `test_explanation_trace.py:100` | same test | same claim, after challenge | `challenged["confidence"] == .48` |
| `test_explanation_trace.py:215` | `test_advisory_coverage_is_separate_from_status_and_confidence` | 1 support | `claim["confidence"] == .55` |
| `test_engine.py:321` | `test_claim_missing_evidence_uses_hypothesis_advisory_without_changing_reasoning` | per-hypothesis support | **no literal** — compares claim to `summarize_status(...)` recomputation |
| `test_engine.py:345` | `test_challenge_recomputation_keeps_coverage_advisory_only` | 1 support then challenge | **no literal** — self-consistent recomputation |
| `test_api.py:936` | `test_…_challenge_…` (multi-claim propagation) | related claim, unverified only | `related_before["confidence"] == 0.2` |
| `test_api.py:955` | same test | — | `related_after == related_before` (relative) |
| `test_api.py:112` | **fixture**, `_investigation_with_review_state` | stored claim stub | `"confidence": 0.68` — a *stored* value that the API echoes; **not** engine-derived, not constrained by a table change |
| `test_engine.py:482` | **fixture**, `_claim_with_challenge_evidence` (def at `:464`) | legacy challenge claim | `"confidence": 0.55` — an input, not an expectation |

No confidence literal is asserted anywhere in `test_api.py` other than `:936`, and none at all in `test_policy_*.py`, `test_provider_safety.py` (its `0.70`/`0.50` are **cost ceilings**, unrelated), `test_protocol_v1.py`, or `test_session_concurrency.py`.

## 2. Assertions that pin a rule id

| path:line | pins |
|---|---|
| `test_explanation_trace.py:48` | `STATUS.FRESH_SUPPORT_AND_CONTRADICTION` + `CONFIDENCE.FIXED_0_52` |
| `test_explanation_trace.py:51` | `STATUS.FRESH_WITH_STALE_CONTEXT` + `CONFIDENCE.FIXED_0_54` |
| `test_explanation_trace.py:54` | `STATUS.MULTI_GROUP_FRESH_SUPPORT` + `CONFIDENCE.FIXED_0_78_DIVERSE_DEPARTMENTS` |
| `test_explanation_trace.py:57` | `STATUS.MULTI_GROUP_FRESH_SUPPORT` + `CONFIDENCE.FIXED_0_68_SAME_OR_MISSING_DEPARTMENT` |
| `test_explanation_trace.py:59` | `STATUS.SINGLE_GROUP_FRESH_SUPPORT` + `CONFIDENCE.FIXED_0_55` |
| `test_explanation_trace.py:61` | `STATUS.FRESH_CONTRADICTION_ONLY` + `CONFIDENCE.FIXED_0_58_SINGLE_CONTRADICTION` |
| `test_explanation_trace.py:64` | `STATUS.FRESH_CONTRADICTION_ONLY` + `CONFIDENCE.FIXED_0_68_MULTIPLE_CONTRADICTIONS` |
| `test_explanation_trace.py:66` | `STATUS.STALE_ONLY` + `CONFIDENCE.FIXED_0_25` |
| `test_explanation_trace.py:67-68` | `STATUS.INSUFFICIENT_NO_DIRECTIONAL_EVIDENCE` + `CONFIDENCE.FIXED_0_20_NO_ACCEPTED_FRESH_EVIDENCE` |
| `test_explanation_trace.py:70-71` | `STATUS.INSUFFICIENT_NO_DIRECTIONAL_EVIDENCE` + `CONFIDENCE.FIXED_0_30_ACCEPTED_NON_DIRECTIONAL_EVIDENCE` |
| `test_explanation_trace.py:101` | `STATUS.ACCEPTED_DISPUTED_EVIDENCE` |
| `test_explanation_trace.py:102` | `CONFIDENCE.FIXED_0_48` |

**Design constraint inside the same test** (`test_explanation_trace.py:86`): `trace["confidence_kind"] == "FIXED_ENGINE_HEURISTIC_NOT_CALIBRATED_PROBABILITY"`. The product states in its own trace that the number is a heuristic, not a probability — so any redesign that keeps one scalar must keep that disclaimer true, and a two-field design that renames the semantics has to change this string deliberately.

Also `test_explanation_trace.py:84`: `reasoning_rule_version == "story-connect-status-v1"` — bumping the table should bump this, and that test will say so.

## 3. Determinism / purity tests, and whether each can see the wall-clock leak

| path:line | what it does | can it catch the impurity? |
|---|---|---|
| `test_explanation_trace.py:181-203` (`test_trace_is_deterministic_except_time_and_does_not_mutate_inputs`) | two `assess_hypothesis` calls, then **nulls** `generated_at` (`:197`), `staleness_policy.decision_evaluated_at` (`:198`) and every `evidence_evaluation_times[*].evaluated_at` (`:199-201`) before `assert first == second` (`:202`) | **No — the test erases the difference by construction.** Its own name admits the exception. It is not wrong, it is silent. |
| `test_evaluation.py:89-90` | `history["passed"] == history["total"] == 7` for both baseline and guarded runs of `deterministic_recomputation_history_consistency` | **Yes.** This is the one that fires today (reported 6/7, `same_input_same_recomputation`). |
| `test_evidence_coverage.py:114-122` | two calls on the *same list in the same order*, plus `items == before` | **No** — nothing permutes, so `matching_evidence` order-dependence is invisible. |
| `test_engine.py:333` (`test_challenge_recomputation_keeps_coverage_advisory_only`) | challenge, then compare claim fields against `summarize_status` of the *returned* evidence | **No** — compares stored-to-stored, no second recomputation, no timestamps in the compared fields. |
| `test_engine.py:508-533` (parametrized, 3 cases) | challenges twice, asserts `review_state` and `status` stability | **No** — field-level, not byte-level. |

So: exactly one test in the suite can currently see the wall-clock impurity, and it is the one that is red.

## 4. Tests that could detect in-place mutation of the caller's claim dict

| path:line | assertion | verdict |
|---|---|---|
| `test_explanation_trace.py:187`, `:202` | `original = deepcopy(record.model_dump(...))` … `assert record.model_dump(mode="json") == original` | deep-copies a **`Record`** (the source), not the claim dict. Does not cover it. |
| `test_engine.py:806`, `:811` | `before_rejected_request = deepcopy(challenged)` … `assert challenged == before_rejected_request` | deep-copies the claim — but only inside `pytest.raises` (`:808-810`), i.e. the **rejected** path. The successful path is never compared. |
| `test_api.py:588, 620, 642, 711, 857, 887` | `client.get(...).json() == before` after a failed challenge | compares the **HTTP response**, re-serialised through the DB. Cannot see a Python-side alias that is committed before the compare. |
| `test_api.py:769`, `:777` | `current_by_id[claim_id] == before[claim_id]`, `history[1]["before"][claim_id] == before[claim_id]` | compares persisted snapshots; same limitation. |
| `test_evidence_coverage.py:122` | `items == before` | coverage input list only. |

**Gap:** no test deep-copies a claim dict, calls `challenge()` **successfully**, and asserts the input dict is unchanged. The mutation is therefore invisible to the whole suite.
**Second gap:** every `POST …/challenge` in `test_api.py` targets an investigation created in the same test (`:387, 482, 582, 614, 637, 677, 706, 729, 735, 742, 756, 796, 804, 841, 850, 871, 880, 939, 989`), so every claim already carries `review_state`. No test challenges a **legacy** stored claim — the exact shape that produces the inferred 409.

## 5. Tests that will need new expectations, ordered by how much they constrain the design

1. `test_explanation_trace.py:77` — `test_trace_rule_ids_match_existing_status_branches`: 10 rows × (status, confidence, `status_rule_id`, `confidence_rule_id`), plus the shared `confidence_kind` (`:86`) and `reasoning_rule_version` (`:84`). **This is the design in executable form**; a table change is a rewrite of this parametrization.
2. `test_explanation_trace.py:89` — disputed branch: `.55 → .48`, plus two rule ids. The only place that pins the *disputed* rung.
3. `test_engine.py:135` and `:274` — `0.54` for "fresh + stale context". Two independent tests pin the same number, one of them via the disputed/stale-accepted route.
4. `test_engine.py:175` / `:190` — `0.78` and `0.58`: the two "clean" rungs.
5. `test_engine.py:208, 296, 399, 561, 587`, `test_explanation_trace.py:215` — `0.55` single-group support, reached five different ways.
6. `test_engine.py:226, 244, 409, 563`, `test_api.py:936` — `0.2` for "no accepted fresh evidence".
7. `test_engine.py:399`/`:409` — the same test pins both `0.55` and `0.2` and additionally asserts the **guard-off vs guard-on** asymmetry; it couples the table to `semantic_guard`.
8. `test_evaluation.py:54-55` — `status_accuracy` `13/17` then `12/17`. Changing which *status* a shape produces moves these counts, not just confidences.
9. `test_evaluation.py:89` — `passed == total == 7`, currently red for the purity reason; it is the regression gate for any purity fix.

**Survives a table change untouched:** `test_engine.py:81` and `:88` (inequalities), `test_engine.py:321`/`:345` and `test_api.py:955` (self-consistent comparisons), `test_api.py:112` and `test_engine.py:482` (fixtures, not expectations).

**Constraints the suite does *not* impose, i.e. free design space:** nothing asserts that two different statuses never share a confidence; nothing asserts monotonicity under an added support; nothing asserts confidence bands are disjoint; nothing permutes confidence inputs; nothing asserts the disputed rung is below the clean rung. Those four properties are unpinned, so a redesign can state and enforce them without fighting an existing expectation.

---

## Not opened

`test_policy_compare.py`, `test_policy_candidate_adapter.py`, `test_policy_demo_api.py`, `test_policy_evidence_demo.py`, `test_policy_dependency_graph.py`, `test_policy_orchestration.py`, `test_policy_proposal_contract.py`, `test_policy_challenge_propagation.py`, `test_protocol_v1.py`, `test_session_concurrency.py`, `test_baseten_adapter.py`, `test_httpx_transport.py`, `test_launcher.py`, `test_store_path_safety.py`, `test_experiment_control.py`, `test_provider_activation.py`, `provider_test_support.py` — grepped only, no confidence or rule-id assertions surfaced in the grep, but I did not read them end to end, so a string-shaped assertion in prose is not excluded.
