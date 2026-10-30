# Testing and verification inventory

This is a source inventory only. Tests were not run and no unexecuted test is described as passing.

## Test groups present

| Group / location | Documented or apparent coverage | Result status here |
|---|---|---|
| `backend/tests/test_api.py`, `test_engine.py`, `test_store_path_safety.py`, `test_session_concurrency.py`, `test_provider_safety.py`, `test_httpx_transport.py`, `test_experiment_control.py` | Legacy API, deterministic assessment, path guard, session concurrency, provider-boundary/transport and experiment accounting. | Files exist; not run or independently verified. |
| `backend/tests/test_policy_compare.py`, `test_policy_candidate_adapter.py`, `test_policy_api.py`, `test_policy_orchestration.py`, `test_policy_proposal_contract.py`, `test_policy_mock_provider_runner.py` | Strict synthetic input, passage/citation behavior, fake adapter, API bounds/errors, orchestration, proposal contract and mock runner. | Files exist; not run. |
| `backend/tests/test_policy_dependency_graph.py`, `test_policy_challenge_propagation.py` | Node/edge/graph validation, provenance, and bounded impact plan invariants. | Files exist; not run. |
| `backend/tests/test_policy_demo_api.py`, `test_policy_demo_session.py`, `test_policy_evidence_demo.py` | Scenario/API/session/challenge behavior and demo logic. | Files exist; not run. |
| `backend/tests/test_launcher.py` | Launcher lifecycle/process identity behavior. | File exists; not run. |
| `backend/tests/test_protocol_v1.py`, `backend/evaluation/protocol_v1.py`, `backend/evaluation/gold_cases.json` | Protocol/evaluation artifacts and synthetic gold cases. The evaluator is a separate harness. | Artifacts exist; evaluation not run. |
| Frontend package scripts | `typecheck`, `build`, `dev` scripts declared. | Not run. |

## Limits of this inventory

File presence confirms only that test/evaluation artifacts exist. It does not prove they pass, cover all invariants, or authorize evaluation. README describes the legacy evaluation as a 21-case synthetic regression harness, not a general performance estimate; provider docs further distinguish semantic protocol cases and fixed denominators. Those reported historical values are not freshly reproduced here.

No application, test runner, evaluator, health check, database, or service was executed/accessed for this documentation package.
