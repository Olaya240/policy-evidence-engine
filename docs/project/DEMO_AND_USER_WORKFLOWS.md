# Demo and user workflows

## Scenario context

The policy demo uses fictional luxury-hotel policy data for Grand Luminary Hotel. `policy_evidence_demo.py` supplies three scenarios; the UI offers scenario selection. They are synthetic examples, not real policy analysis.

| Scenario | Relation illustrated | Details |
|---|---|---|
| `scheduling` | `COMPATIBLE_CHANGE` proposal | Version 1 requires 48 hours' shift-change notice; version 2 requires 24 hours. |
| `uniform_grooming` | `CONTRADICTION` proposal | Incompatible mandatory emblem placement (left vs right lapel). |
| `lounge_access` | `SCOPE_OR_TIME_DIFF` proposal | Disjoint property collections and non-overlapping effective dates. |

## Available demo path

The current interactive demo lets a reviewer select a scenario, inspect policy versions and citations, create an in-memory session, submit a department challenge, and inspect recomputed result and audit history. The expected system assessment is `INCONCLUSIVE` when no external grounding establishes applicability. A quote match only establishes citation provenance. The output therefore requires human review.

## Conceptual versus implemented workflow

| Step | Status |
|---|---|
| Review policy versions and exact synthetic text | Implemented in demo. |
| Inspect citations and local offsets/digests | Implemented for demo fixtures; this is not semantic verification. |
| Identify affected claims | Partially implemented in scenario workflow; general graph dependency review is internal planner capability. |
| Challenge evidence/applicability | Implemented for demo scenarios with in-memory events. |
| Analyze impact through arbitrary graph dependencies | Internal bounded planner exists; not exposed in UI/API integration. |
| Reassess all affected conclusions and persist a durable audit | Scenario-limited recomputation exists; generic persisted reassessment is not implemented. |
| Approve a policy interpretation | Human responsibility; not automated by prototype. |

The walkthrough documents launching commands, but they were not run for this review. Session limits and reset behavior are described in `POLICY_DEMO_WALKTHROUGH.md`.
