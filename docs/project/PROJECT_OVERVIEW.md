# Project overview

## Identity and purpose

**Story Connect AI Policy Change & Conflict Investigator** is an offline prototype and a set of evolving policy-analysis specifications. It explores how a reviewer could trace policy comparisons to source passages, represent claims and applicability conditions, challenge evidence, inspect dependencies, and decide what requires reassessment. The business context is hotel operations and policy governance; the demo uses fictional Grand Luminary Hotel materials.

The motivating problem is that a policy change can affect claims whose evidence and applicability are distributed across versions, passages, and dependent conclusions. A plain chatbot answer or basic retrieval-augmented generation (RAG) result can quote a document without showing which claims rely on it, whether the quote entails the claim, or what downstream conclusions need review. The project’s core idea is an auditable evidence-and-dependency model with explicit uncertainty and reviewer challenges.

## Users and expected value

Intended users are policy owners, operations reviewers, and analysts who need to compare policy versions and inspect evidence. The expected value is faster, more traceable review and clearer identification of uncertainty, conflict, and downstream review work. No measured business benefit or production adoption is established.

## Scope

Current project scope includes a synthetic policy comparison demo, a separate synthetic handover investigation prototype, typed policy graph and challenge-planning modules, provider boundaries, evaluation/test fixtures, and persistence governance documents. The demo can show candidate relations and citations; it deliberately leaves semantic correctness and operational impact to human review.

Out of scope are legal/compliance determinations, employee ranking or employment decisions, production integration, real policy ingestion, a real model provider connection, and authorization to persist the policy graph. The handover app has no authentication and is not production-ready.

## What makes this more than a chatbot

The intended unit of reasoning is not just a response. It is a linked set of versioned sources, passages, claims, applicability conditions, relations, conclusions, challenges, and provenance. A challenge should be traceable to affected dependencies and trigger reassessment of relevant conclusions. Exact quotation is evidence of provenance only; it is not proof of semantic support or applicability.

## Implementation status

| Area | Status |
|---|---|
| Handover investigation application | Implemented local prototype with API/UI and SQLite access in source; runtime/database state was not inspected for this documentation. |
| Policy demo UI and demo API | Implemented synthetic demonstration; session history is in process memory. |
| Policy comparison API | Implemented isolated API using `FakePolicyCandidateAdapter`; returns proposal-only, human-review-required, `INCONCLUSIVE` outcomes. |
| Policy graph and challenge planner | Implemented as validated, in-process Python modules; planner is not exposed through an HTTP route. |
| Future policy graph persistence | Contract and vectors are documentation/specification work; database execution is BLOCKED and prototype gate CLOSED. |
| Real external AI integration | Not connected or authorized by the current project documents. |

See [current status](CURRENT_STATUS_AND_GAP_ANALYSIS.md) and [architecture](SYSTEM_ARCHITECTURE.md).
