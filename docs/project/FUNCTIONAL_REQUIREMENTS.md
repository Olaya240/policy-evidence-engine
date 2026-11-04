# Functional requirements and status

Statuses describe evidence in the current source and governance documentation, not an approval to extend the project.

| ID | Requirement | Status | Evidence and boundary |
|---|---|---|---|
| FR-01 | Accept policy versions and validate identifiers, text, scope, dates, and passages. | IMPLEMENTED | `backend/policy_compare.py` validates a synthetic pair and derives passages. No document-ingestion service is evidenced. |
| FR-02 | Compare two policy versions and produce candidate relation(s). | PARTIALLY IMPLEMENTED | `compare_candidate` and orchestration validate/propose relations; semantics remain abstained/unverified in the isolated API. |
| FR-03 | Preserve source and passage attribution for cited evidence. | PARTIALLY IMPLEMENTED | Local code-point offsets and hashes are checked; provenance does not establish semantic support. |
| FR-04 | Represent source documents, versions, passages, claims, applicability, comparison relations, conclusions, and challenges as typed graph nodes. | IMPLEMENTED | `policy_dependency_graph.py`; graph is in-memory and validated. |
| FR-05 | Represent evidence and dependency relations explicitly. | IMPLEMENTED | Typed edges and graph validation exist; see graph documentation. |
| FR-06 | Determine department applicability from adequate grounding. | PARTIALLY IMPLEMENTED | Demo explicitly abstains when evidence is insufficient; no general external grounding service exists. |
| FR-07 | Produce a conclusion with epistemic status and uncertainty. | PARTIALLY IMPLEMENTED | Demo and policy API return inconclusive/human-review results; no authoritative policy decision engine is established. |
| FR-08 | Submit a challenge and preserve a review trail. | PARTIALLY IMPLEMENTED | Demo API records challenge events in an in-memory session. Legacy handover API has a separate challenge workflow with SQLite persistence in source. |
| FR-09 | Analyze downstream impact of a challenge. | PARTIALLY IMPLEMENTED | Bounded internal graph planner produces impact states; it is not HTTP-exposed and does not itself recompute conclusions. |
| FR-10 | Reassess affected conclusions after a challenge. | PARTIALLY IMPLEMENTED | Demo workflow recomputes its limited scenario assessment; generic graph planner does not perform reassessment. |
| FR-11 | Require human review where semantics, applicability, or impact are uncertain. | IMPLEMENTED | Explicit in policy API/demo contracts and user-facing limitations. |
| FR-12 | Maintain auditability and traceable revisions. | PARTIALLY IMPLEMENTED | Session audit trail is ephemeral in the policy demo; legacy handover app has version/history records. Durable policy-graph audit storage is design-only. |
| FR-13 | Persist canonical policy graph snapshots with deterministic round trips. | BLOCKED | Persistence contract and vectors exist; RT-01–RT-03 incomplete, database execution BLOCKED, prototype gate CLOSED. |
| FR-14 | Connect a real model or Meta Model provider for semantic interpretation. | PARTIALLY IMPLEMENTED | The handover backend has an optional, explicitly activated Meta Muse Spark adapter; `MockProvider` remains the default. The policy demo and comparison API remain synthetic/fake, and this is not HR policy Q&A or document retrieval. |
| FR-15 | Retrieve policy passages using embeddings or vector search. | NOT IMPLEMENTED | No embedding or vector-search component was found in the inspected source inventory. |
| FR-16 | Authenticate users and enforce production roles. | NOT IMPLEMENTED | The handover README explicitly says no authentication; no production identity system is evidenced. |

The detailed policy persistence requirements remain governed by `POLICY_GRAPH_PERSISTENCE_CONTRACT.md` and Phase 20A decisions; this table does not update their statuses.
