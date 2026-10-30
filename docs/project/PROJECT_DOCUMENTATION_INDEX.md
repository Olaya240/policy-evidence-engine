# Project documentation index

This package summarizes project behavior and governance using source/document inspection. It does not supersede implementation, contracts, owner decisions, or status registers.

| Document | Purpose |
|---|---|
| [Project overview](PROJECT_OVERVIEW.md) | Problem, value, scope and implementation status. |
| [Functional requirements](FUNCTIONAL_REQUIREMENTS.md) | Requirements and implementation classifications. |
| [System architecture](SYSTEM_ARCHITECTURE.md) | Services, modules, boundaries and data flow. |
| [Frontend documentation](FRONTEND_DOCUMENTATION.md) | Pages, UI behavior, state and API calls. |
| [Backend and API documentation](BACKEND_AND_API_DOCUMENTATION.md) | HTTP services/routes and internal-only modules. |
| [Policy knowledge graph](POLICY_KNOWLEDGE_GRAPH.md) | Nodes, edges, evidence, identity and semantics. |
| [Challenge and reassessment engine](CHALLENGE_AND_REASSESSMENT_ENGINE.md) | Challenge workflow and bounded planner limits. |
| [Data and persistence design](DATA_AND_PERSISTENCE_DESIGN.md) | Current storage split and future graph persistence contract. |
| [AI and evidence processing](AI_AND_EVIDENCE_PROCESSING.md) | Fake/mock provider roles and semantic limits. |
| [Demo and user workflows](DEMO_AND_USER_WORKFLOWS.md) | Scenarios and implemented versus conceptual workflow. |
| [Security and trust model](SECURITY_AND_TRUST_MODEL.md) | Authentication, provider, provenance and isolation boundaries. |
| [Testing and verification](TESTING_AND_VERIFICATION.md) | Static test inventory; no results claimed. |
| [Current status and gap analysis](CURRENT_STATUS_AND_GAP_ANALYSIS.md) | Components, gaps, dependencies and preserved gates. |
| [Roadmap and next phases](ROADMAP_AND_NEXT_PHASES.md) | Dependency-aware future sequence without authorization. |
| [Glossary](GLOSSARY.md) | Shared terminology. |

## Governing project references

- `hackathon/README.md` — handover prototype setup, behavior, evaluation description and limits.
- `hackathon/POLICY_DEMO_WALKTHROUGH.md` — policy demo launch and scenario walkthrough.
- `hackathon/AI_PROVIDER_BOUNDARY.md` and `hackathon/SEMANTIC_PROVIDER_EXPERIMENT.md` — provider boundaries and experiment design/results already documented.
- `hackathon/POLICY_GRAPH_PERSISTENCE_CONTRACT.md` — operative graph persistence contract.
- `hackathon/PHASE_20A_30_OWNER_DECISION_REGISTER.md`, `PHASE_20A_36_OWNER_DECISION_STATUS.md`, and Phase 20A.33–36 evidence — current decision and gate summaries.

## Reading caution

“Implemented” means source declares a component or flow; this package did not execute it. Historical test/evaluation reports are not freshly verified. The policy graph persistence database remains BLOCKED; prototype gate remains CLOSED.
