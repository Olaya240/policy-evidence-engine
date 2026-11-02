# Threat-row verification

Every row of `THREAT-MODEL.md` that names a test was checked twice: the function must exist
in `backend/tests/`, and the test must pass when run by itself. Run on 2026-11-01 with
`PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q <ids>`:

```
..................                                                       [100%]
18 passed in 1.13s
```

The eighteen ids below are exactly the ones the model cites; the suite as a whole is
1779 passed, 0 failed, 0 xfailed.

| Row | Control | Test (file::name) | Found | Run |
|---|---|---|---|---|
| H2 | CORS allowlist | `test_threat_controls.py::test_cors_admits_the_local_ui_and_refuses_any_other_origin` | yes | pass |
| H3 | restriction filter on `/api/records` | `test_threat_controls.py::test_no_restricted_text_leaves_through_the_records_endpoint` | yes | pass |
| H4 | no existence oracle | `test_threat_controls.py::test_a_restricted_record_is_indistinguishable_from_an_absent_one` | yes | pass |
| H5 | fixed 503 body on provider fault | `test_threat_controls.py::test_a_provider_fault_never_echoes_record_text` | yes | pass |
| H6 | uninitialised DB is 503 | `test_threat_controls.py::test_an_uninitialised_database_is_a_503_not_a_500` | yes | pass |
| H7 | request validation at the edge | `test_threat_controls.py::test_a_malformed_request_is_refused_before_the_engine_sees_it` | yes | pass |
| H1 | declared posture | `test_threat_controls.py::test_the_health_endpoint_declares_the_posture_it_has` | yes | pass |
| E1 | claim equals its own reassessment | `test_architecture_invariants.py::test_every_claim_equals_a_fresh_summary_of_its_own_evidence` | yes | pass |
| E2 | staleness at every clock | `test_engine_slice6_contracts.py::test_a_future_dated_record_is_not_current_evidence` and `test_engine_slice8_challenge.py::test_challenge_re_evaluates_staleness_at_its_own_clock` | yes | pass |
| E5 | one source is one unit | `test_engine_slice6_contracts.py::test_a_group_with_a_challenged_and_a_clean_record_is_one_source` | yes | pass |
| B1 | projection before the provider | `test_architecture_invariants.py::test_no_restricted_record_reaches_the_provider_request` | yes | pass |
| B4 | proposal cap binds | `test_provider_safety_slice4_contracts.py::test_the_proposal_cap_binds_before_the_byte_cap_can` | yes | pass |
| T2 | close on cancellation | `test_baseten_adapter.py::test_baseten_cancellation_closes_stream_and_transport_and_releases_single_flight` | yes | pass |
| S1 | path guard | `test_store_path_safety.py` (module) | yes | pass (in suite) |
| S2 | revision pinning | `test_store_slices13_14.py::test_a_stale_revision_writes_nothing`, `::test_changed_claims_behind_the_revision_are_stale` | yes | pass |
| S3 | client error not a 503 | `test_store_slices13_14.py::test_a_recomputed_set_that_does_not_match_the_affected_claims_is_refused` | yes | pass |
| S4 | restricted rows unreadable | `test_store_slices13_14.py::test_restricted_records_are_hidden_from_reads` | yes | pass |

## Rows with no test by design

| Row | Why it has none |
|---|---|
| H8 (closed this session) | it now has one — `test_rate_limit_wiring.py`, which is not in the eighteen above because it was added after the model was written; ran green separately (3 passed) |
| B5 / B6 | they are the same external dependency: no recorded live vendor response exists in this repository, so neither a rejection nor a false-rejection can be tested against reality |

## What this check does not establish

- That a passing control test would **fail** if the control were removed. That is proven
  only where a worker mutated the code and watched tests fail: `experiment_control`
  (7 mutations), `mock_provider` (8 mutations), `semantic_guard` (2 mutation probes in the
  slice-18 note). No mutation sweep exists for the HTTP-threat tests, so H2–H7 are proven
  to *pass against the current code*, not proven to be sensitive to its removal.
- That the row's prose matches the test's assertion in every detail; the table records what
  the test is named and that it passes, not a semantic equivalence proof.
