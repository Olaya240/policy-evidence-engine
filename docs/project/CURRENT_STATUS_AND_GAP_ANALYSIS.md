# Current status and gap analysis

## Status matrix

| Area | Current status | Evidence boundary / remaining gap |
|---|---|---|
| Legacy handover workflow | Implemented prototype | UI/API/store source exists; no auth; database state not reviewed. |
| Policy demo UI/API | Implemented, synthetic, in-memory | Scenario challenge and history exist; not durable. |
| Policy comparison API | Implemented isolated service | Fake candidate only; not connected to demo page; result remains inconclusive/proposal-only. |
| Typed policy graph | Implemented internal module | No graph persistence or service integration established. |
| Challenge propagation | Implemented internal bounded planner | No API/UI exposure, state mutation, or reassessment execution. |
| Real provider / Meta Model | Proposed only | No runtime connection, credentials, or authorization. |
| Embeddings/vector retrieval | Not identified / not implemented | No such component found in inspected source inventory. |
| Policy graph persistence | Documentation/specification only | RT-01–03 incomplete; database execution BLOCKED; prototype gate CLOSED. |
| Authentication/production deployment | Not implemented | No production role/security boundary evidenced. |

## Key dependencies

1. Owner decisions and contract amendments are needed before exact normalized-row mappings, sidecar rules, and complete round-trip vectors can be fixed.
2. Full RT fixtures and equality/rejection oracles depend on scope keys, mappings, canonical node bytes, and any sidecar values.
3. Separate governance and authorization would be required for any real source capture/retention, provider integration, persistence execution, or prototype gate transition.
4. Generic challenge UI/API integration depends on a defined workflow connecting graph planning to reassessment and audit state.
5. Any production use depends on authentication, authorization, privacy/retention design, deployment controls and appropriate validation.

## Governance status retained

D30-01 is OWNER-APPROVED Option A for set-like-array normalization at decision level; contract amendment and implementation remain separate. D30-02/D30-10 methodology is approved only; no field mapping or NULL is approved. D30-03 through D30-09 and D30-11 remain as registered. D34-11 is awaiting owner decision; other D34 decisions retain their register status. RT-01/02/03 remain INCOMPLETE; Phase 20A sequencing remains Option B, database execution BLOCKED and prototype gate CLOSED.

These are summaries of existing records, not new status updates.
