# Decisions register — drift check

Re-read of `DECISIONS.md` against the working tree on 2026-11-01, after this session's
fixes. For each decision: the code that implements it now, the test that would fail if it
were reversed, and whether the register still describes reality.

**Result: 11 CURRENT, 1 UNPROVEN (decision 7, unchanged), 0 DRIFTED.**

| # | Decision | Code now | Reversing test | Status |
|---|---|---|---|---|
| 1 | Signed margin table | `decision_table.py` `_label`: `s >= 2 and s >= 3c+1` → SUPPORTED; `c >= 3s+1` → CONTRADICTED | `tests/test_decision_table_slice9_labels.py` (boundaries 2:0, 1:0, 3:1, 4:1) | CURRENT |
| 2 | Refutation asymmetric | same file: no minimum on the contradiction side, matching `ct3/DecisionTable.v:120-122` | `test_a_single_contradiction_is_decisive_while_a_single_support_is_not` | CURRENT |
| 3 | Challenged group counted once | `decision_table.py:303` `disputed_support=len(disputed_support - support)`; `engine.py:185` passes `disputed_total` | `test_a_group_with_a_challenged_and_a_clean_record_is_one_source` | CURRENT |
| 4 | Challenge re-evaluates freshness | `engine.py` `_is_stale(record.timestamp, now)` in the challenge path, applied to models **and** the raw dicts | `test_challenge_re_evaluates_staleness_at_its_own_clock` | CURRENT |
| 5 | Future-dated = non-current | `engine.py:18` `_is_stale`: `age > STALE_DAYS or age < 0` | `test_a_future_dated_record_is_not_current_evidence` | CURRENT |
| 6 | Provider sees a projection | `provider_safety.py` `MandatoryProviderBoundary.assess` → `eligible_provider_records` → `serialize_provider_request` | `test_no_restricted_record_reaches_the_provider_request` | CURRENT |
| 7 | Closed response allowlist | `_parse_response` key-set equality; rejects `logprobs`, `system_fingerprint`, dated model echo | `test_baseten_response_parser_fails_closed_on_unsupported_or_empty_shapes` (asserts a refusal, not a code) | **UNPROVEN** — no live vendor response has ever been seen, so strictness is untested against reality |
| 8 | Proposals quote their own record | `_validate_provider_proposals` grounding; `MockProvider.validate_fixture_output` now applies the same rule to fixtures | `tests/test_mock_overrides_grounding.py`, `tests/test_engine.py` (`invalid_quote`) | CURRENT |
| 9 | Coverage is advisory, direction-blind | `evidence_coverage.py` returns flags and prompts; nothing in `engine.py` reads them into a verdict | `tests/test_evidence_coverage_slice11.py` | CURRENT |
| 10 | Optimistic challenge persistence | `store.py` `BEGIN IMMEDIATE` + revision and claim comparison inside the transaction | `test_a_stale_revision_writes_nothing` | CURRENT |
| 11 | Restricted filtered twice | `store.py:146` list filter and `:151` `restricted=0` in `get_record`; the engine and boundary refuse it again | `test_restricted_records_are_hidden_from_reads` | CURRENT |
| 12 | Proposal cap binds | `provider_safety.py:25` `MAX_PROPOSALS = 32`, measured below the 43 that fit a 4 KiB body | `test_the_proposal_cap_binds_before_the_byte_cap_can` | CURRENT |

## What changed since the register was written

- Decision 12 moved from OPEN to CURRENT by measurement (43 fit, cap set to 32), as recorded
  in the register itself.
- Decision 8 gained the fixture-side check this session; the register's row described only
  the engine check, and has been updated to name both.
- Nothing else drifted. No decision was quietly reversed by a later fix.

## Two decisions the register does not yet contain

Both were made in this session and are load-bearing:

1. **Rate limiting at 600 requests/minute per client host** (`app/rate_limit.py`, wired as
   middleware), chosen as a runaway-loop guard for a single-user local prototype rather
   than as a shared-service quota. Falsifier: a legitimate client pattern that exceeds 600
   a minute. Test: `tests/test_rate_limit_wiring.py`.
2. **Provider activation through the environment factory** (`build_engine_from_environment`),
   activating only with flag + key source + enabled budget, falling back to mock on every
   failure. Falsifier: an activation path that reaches the network without all three.
   Test: `tests/test_activation_wiring.py`.

Both were added to the register as rows 13 and 14 after this check, so the register now
carries **14 decisions, 13 pinned and 1 unproven**.
