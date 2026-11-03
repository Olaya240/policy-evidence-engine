# Backend and API documentation

The service inventory below comes from route declarations and current project documents; no service was launched for this review.

## Policy demo API — `backend/policy_demo_api.py`

FastAPI service, documented launcher port 8083, offline synthetic demo. Uses `policy_evidence_demo.py` and `InMemoryDemoSessionManager`; no database or provider is used by this path. Request parsing is bounded (32 KiB in the walkthrough). Routes:

| Method and route | Purpose |
|---|---|
| `GET /demo-api/health` | Fixed offline readiness metadata. |
| `GET /demo-api/scenarios` | List synthetic scenario metadata. |
| `GET /demo-api/scenario?id=...` | Return a scenario (scheduling default). |
| `POST /demo-api/session/new` | Create a session. |
| `GET /demo-api/session/{session_id}/history` | Read in-memory audit history. |
| `POST /demo-api/session/{session_id}/reset` | Reset session state. |
| `POST /demo-api/challenge` | Submit a reviewer challenge and return recomputation. |

Exact request schemas are defined by Pydantic models in that module. The demo produces inconclusive determinations when grounding is absent; see walkthrough. Sessions are bounded/ephemeral.

### Scenario loading and in-memory session lifecycle

The frontend loads and validates the selected scenario response before requesting a new session; failed or invalid scenario responses therefore do not allocate a session. Frontend generation, scenario, session, request, and lifecycle checks ignore stale responses. They do not cancel work that has already reached the backend: if a session-creation request arrives before becoming obsolete, the backend may still allocate that session in process memory even though the frontend ignores its response. The current API has no delete-session endpoint, and the frontend cannot delete that session. Reset clears a session's history/state according to reset semantics; it is not deletion. An unused session remains in process memory until the backend releases it, such as by FIFO eviction at the existing session cap or when the process exits.

## Isolated policy comparison API — `backend/policy_api.py`

FastAPI service binding to `127.0.0.1:8082` when launched directly. `GET /health` returns fixed metadata. `POST /policy-comparisons` accepts strict JSON validated by `policy_compare.validate_policy_pair`, with a 512,000-byte limit. It creates only a `FakePolicyCandidateAdapter` response and returns proposal-only, human-review-required, `INCONCLUSIVE` output. Malformed input receives fixed errors; request contents and raw exceptions are not returned. Results are not persisted. The standalone `frontend/public/policy-comparison-demo.html` is a local-only demo containing an optional request to this API on `127.0.0.1:8082`, intended for local development. Phase 34.8's Vite build configuration excludes the page from production output. The page is not integrated into the main Story Connect application or connected to a deployed backend; this optional request is not in the main application's Vite proxy.

## Legacy handover API — `backend/app/main.py`

FastAPI application titled “Story Connect Handover Investigation Prototype.” It requires its SQLite database to be initialized before database-backed operations.

| Method and route | Purpose |
|---|---|
| `GET /api/health` | Health/readiness. |
| `GET /api/records` | List accessible records. |
| `POST /api/investigations` | Create an investigation. |
| `GET /api/investigations/{investigation_id}` | Read one investigation. |
| `POST /api/investigations/{investigation_id}/claims/{claim_id}/challenge` | Challenge a claim using record ID, exact quote and reason. |
| `GET /api/investigations/{investigation_id}/history` | Read investigation history. |

`app.store` performs SQLite work, including transactions and revision checks. README says tests use uniquely named temporary SQLite files; this documentation task did not open any database or verify runtime contents. There is no authentication; access context is not authentication.

Provider selection is constructed once when the backend starts. `MockProvider` is the default. Meta Muse Spark is optional and requires `ENABLE_META`, `MODEL_API_KEY`, `META_MAX_REQUESTS`, `META_MAX_ESTIMATED_COST_USD`, and `META_CONSERVATIVE_COST_PER_REQUEST_USD` in the backend process environment; simultaneous Meta and Baseten activation fails closed to mock. Claim attribution is captured from the invoked provider instance, with bounded response request ID and token usage when available. Legacy claims without attribution resolve to `unknown`. The 2026-11-03 one-request assessment remains inconclusive as to provider. See [`backend/META_PROVIDER.md`](../../backend/META_PROVIDER.md).

The React Policy Demo at `#/demo` is a separate synthetic workflow served by `policy_demo_api.py` on port 8083. It uses in-memory sessions and does not call the handover API's provider. The standalone policy-comparison API on port 8082 uses a fake adapter and is separate from both workflows.

## Internal-only policy modules

`policy_dependency_graph.py` validates typed nodes, edges, identifiers, evidence and applicability provenance. `policy_challenge_propagation.py` computes a bounded impact plan from a validated graph; it does not change graph state, create events, recompute policy, persist, or expose an API. `policy_orchestration.py` coordinates comparison output. `policy_demo_session.py` manages in-memory session events. `policy_candidate_adapter.py` defines a protocol and fake adapter.

## Error and data boundaries

The policy endpoints use strict input contracts and bounded request bodies, and avoid echoing raw exception/request data per their docs. These controls do not provide authentication or a same-process sandbox. Only synthetic input is appropriate. No HTTP behavior was exercised in this review.
