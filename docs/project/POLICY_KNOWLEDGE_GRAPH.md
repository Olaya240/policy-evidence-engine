# Policy knowledge graph

## Purpose and status

`backend/policy_dependency_graph.py` defines an immutable, validated in-memory evidence dependency graph. It is not a persisted graph database, and this documentation does not imply that a graph snapshot has been stored. IDs are formed by type-specific helper functions; the graph constructor sorts nodes by `node_id` and edges by `edge_id`, then validates the result. Contract-level canonical JSON serialization is a separate, currently governed design.

## Node types

| Node | Meaning |
|---|---|
| `SourceDocument` | Logical source-document identity. |
| `PolicyVersion` | A version with document/version identity, decoded-source digest and scope/time metadata. |
| `SourcePassage` | Versioned passage with source offsets and digest-backed citation identity. |
| `Claim` | Candidate claim in a comparison, including citations and dependencies. |
| `ApplicabilityCondition` | Scope/applicability state and evidence references for a candidate. |
| `ComparisonRelation` | Proposed relation between compared versions for a candidate. |
| `Conclusion` | Result/epistemic status and uncertainty for a candidate. |
| `ChallengeEvent` | A challenge targeting a passage/source location, with target version/source identity. |

Exact fields and validators are in `policy_dependency_graph.py`; future normalized-row mappings remain unresolved in Phase 20A decisions.

## Edge types and interpretation

The frozen graph declares `CONTAINS`, `SUPPORTS`, `CONTRADICTS`, `APPLIES_TO`, `DEPENDS_ON`, `AFFECTS`, and `DERIVED_FROM`. Edges have IDs, endpoints, type, epistemic status and provenance. Permitted endpoint combinations are constrained by validation code; do not infer additional relationships from names alone.

The graph expresses provenance and dependency. `SUPPORTS` or `CONTRADICTS` edges do not remove the need to distinguish source citation from semantic entailment. A citation can be locally verified as a passage in a source; that proves provenance, not that its content supports a claim or applies to a department.

## Evidence, identity, and uncertainty

Source versions carry decoded-source identity. Original raw bytes are a separate sidecar concept in persistence governance and cannot be reconstructed from decoded text alone. Applicability can be unknown; unknown is not a negative finding. Missing provenance blocks supported conclusions or traversal in cases specified by the validators/planner.

Epistemic statuses and exact node/edge validation rules are defined in source. The graph does not itself prove legal priority, semantic completeness, operational effect, or global independence.

## Persistence boundary

`POLICY_GRAPH_PERSISTENCE_CONTRACT.md`, canonicalization vectors, and RT-01–RT-03 describe a future normalized snapshot contract. The 20A.36 owner status says RT vectors remain incomplete, database execution BLOCKED, and prototype gate CLOSED. No database behavior for this graph is claimed as implemented.
