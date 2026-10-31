# AGENTS.md — Architecture specification and binding rules

**Status:** binding. Read this before changing code in this repository.
**Owner:** the human engineering lead. This file is the contract, not a plan.
**Applies to:** `backend/**`, `frontend/src/**`, `scripts/**`, `docs/diagrams/**`, and every AI agent working in the tree.

---

## 0. How to read this file

Two jobs share this file, in this order:

1. **Rules — §§1–3 and §§6–14.** What an agent MUST, MUST NOT and SHOULD do. Consult these while working.
2. **Model — §§4–5 and §§15–17.** What the architecture actually is, and what each guarantee does and does not cover. Read these before arguing that a rule is wrong.

**Precedence.** Rules (§§1–3, 6–14) > model (§§4–5, 15–17) > `docs/project/*` > code comments. `docs/project` owns status, inventory and narrative; this file owns rules, sequencing and gates. If a rule here and a document there disagree, stop and fix the disagreement in the same change; do not follow the more convenient one.

**If this file disagrees with the code, the code is wrong** — unless the disagreement is listed in §15 (Known deviations) with an accepted decision. Fix the code and add the test that would have caught it; amend §15 only when the decision is genuinely accepted by the owner, and say why.

| Term | Meaning |
|---|---|
| **MUST / MUST NOT** | Enforced by code or by a gate in §13, or marked `PARTIAL`/`NOT MET` in §2 with the fix outstanding. A change that violates it is rejected, not renegotiated. |
| **SHOULD** | Default. Deviating is allowed only if the change description says which rule was traded and why. |
| **IMPLEMENTED** | Lives in the tree and is exercised by at least one test. |
| **SCRIPTED** | Deterministic fixed output, not derived. Must be labelled scripted everywhere it is shown. |
| **ABSENT** | Not in the tree. Never described as working. |
| **BLOCKED** | Governance forbids implementation (§16). An agent may not implement it, even partially. |

**Out of scope for this file:** product narrative, historical review findings, per-field reference tables. Those live in `docs/project/` — point at them, do not fork them.

### 0.1 Non-negotiables

These eight are violated by shipping, not by disagreement. A change that needs one is
an owner decision (§16), never a local design choice.

1. No authentication, identity or tenant model is added.
2. No listener beyond `127.0.0.1`. Loopback is not authorization.
3. No real provider call, credential input or egress path outside `provider_safety`.
4. No persistence for the policy graph; the prototype gate stays CLOSED.
5. No positive classification. `INCONCLUSIVE` is the only signed result.
6. No "audit", "append-only" or "tamper-evident" for the session log or snapshot identity.
7. No test weakened, skipped or rewritten to make a gate green.
8. No hand-edited `.excalidraw` or SVG. Figures are generated and validated.

**The working loop for any change.**

1. Find the invariant(s) and rule(s) the change touches (§2, §3, §6). If none seems to apply, say why in the change description.
2. Decide whether a guarantee (§5), the refuse list (§14) or a deviation (§15) is affected; update the document in the same change.
3. Use the change matrix (§12) to find every file and test that must move together.
4. Run the gates (§13) the change requires. Never record a gate as passing when it was skipped, and never weaken a test to make a gate green.

---

## 1. Identity and scope

This repository is an **offline prototype** with five distinct pieces of software and one core:

| Program | Port | Entry point | Owns | State |
|---|---|---|---|---|
| Policy demo API | 8083 | `backend/policy_demo_api.py` | scenario, session, challenge routes | in-process session dict |
| Policy comparison API | 8082 | `backend/policy_api.py` | one stateless comparison route | nothing |
| Handover API | 8081 | `backend/app/main.py` | investigations, claims, challenges | SQLite in `data/` |
| Demo UI | 5174 | `frontend/src/App.tsx`, `PolicyDemoPage.tsx` | hash-routed React pages | browser only |
| Launcher / health | — | `scripts/launch_policy_demo.py`, `check_policy_demo_health.py` | start, probe, stop | runtime JSON file |
| Offline core | — | `policy_compare`, `policy_dependency_graph`, `policy_challenge_propagation`, `policy_demo_graph` | validation, projection, planning | none |

The core's claim is narrow and it earns it: **validated provenance, deterministic graph validation, and bounded reachability** over synthetic data. It is not a policy engine, not legal analysis, and not production software.

MUST NOT be introduced without an owner decision: authentication, network exposure beyond `127.0.0.1`, a real provider call, persistence for the policy graph, a second source of truth for scenario data.

---

## 2. Binding invariants

Every row is a rule, the mechanism that enforces it today, and the test that would go red. `Status` is `MET`, `PARTIAL` or `NOT MET` (§15 carries the deviation).

| ID | Rule | Enforced by | Falsification test | Status |
|---|---|---|---|---|
| I1 | Inputs MUST be exact built-in types. No coercion, no subclasses, no `bool` accepted as `int`. | `policy_compare._object/_string/_identifier`; `policy_dependency_graph._prevalidate_construction_inputs` | Pass `True` for an int field, or a `dict` subclass → coded error, not acceptance | MET |
| I2 | Identity MUST be derived, never accepted: digests, passage ids and node ids are recomputed and compared. | `source_passage_id`, `_expected_node_id`, `_validate_node_shape` | Edit one text byte and keep the old digest → `invalid_node` | MET |
| I3 | A citation MUST resolve by document + version + digest to a real passage, and its span MUST slice back to the exact quote. | `validate_citation`; `_validate_citations` | Shift `start_cp` by 1, or swap in the other side's quote → `invalid_citation` | MET |
| I4 | A caller assertion MUST NOT become a finding. `classification` stays `INCONCLUSIVE`; caller claims are carried as `*_assertion` marked `UNTRUSTED_CALLER_ASSERTION`. | `compare_candidate`, `validate_result` | Set `classification` to a positive value, or `human_review_required=False` → `invalid_result` | MET |
| I5 | An edge MUST be legal in both type pair and epistemic status, and provenance edges MUST match a declared citation or evidence id. | `_valid_edge_types`, `_validate_edge`, `_validate_applicability_provenance` | Emit `DERIVED_FROM` from a `PolicyVersion`, or `SUPPORTS` as `SOURCE_VALIDATED` → rejected | MET |
| I6 | Every claim citation and every condition evidence id MUST have exactly one matching `DERIVED_FROM` edge. | `_validate_graph_contents` | Delete one provenance edge → `invalid_citation` | MET |
| I7 | Ordering MUST be total and independent of input order; the snapshot identity MUST be recomputed from sorted nodes. | `EvidenceDependencyGraph.__post_init__`, `create_graph` | Shuffle nodes and edges → identical graph, ids and identity (`test_graph_order_is_deterministic_for_shuffled_input`) | MET |
| I8 | Budgets MUST be applied before sorting and before content hashing. | `_prevalidate_construction_inputs` | Exceed each budget at the exact limit and at limit + 1 | MET |
| I9 | The graph MUST be immutable and planning MUST NOT mutate graph or request. | frozen dataclasses; plan built from a validated snapshot | Hash graph and request before/after planning (`test_planning_does_not_mutate_graph_or_request`) | MET |
| I10 | The planner MUST NOT follow `AFFECTS`, `CONTAINS` or `APPLIES_TO`, and MUST NOT fan out from a prerequisite. | adjacency build skips all three; `_make_transitions` returns `()` in `prerequisite` mode; `_validate_plan` rejects such steps | Inspect every plan path step's edge type | MET |
| I11 | `UNCHANGED` MUST appear only in a complete search. An incomplete plan MUST name its unexplored nodes and its limit. Over-declaring incompleteness is permitted; under-declaring is not. | `TraversalCompleteness`, `scope_note` | Force a limit → no `UNCHANGED`, non-empty `unexplored_node_ids` (`test_incomplete_plan_scope_note_does_not_claim_unexplored_nodes_unchanged`) | MET |
| I12 | A plan MUST contain exactly one `DIRECTLY_CHALLENGED` target, with `paths == ((),)`. | `_validate_plan` | Duplicate or omit the direct target | MET |
| I13 | The graph and planner MUST NOT import the scenario layer. `policy_demo_graph.py` is the only module allowed to know both. Adding a scenario MUST touch zero graph code. | module imports (§3); no automated guard yet | Import the graph in a process that never imported `policy_evidence_demo` | PARTIAL |
| I14 | `assert` MUST NOT be used as runtime validation. | — | Run the module under `python -O` and repeat the invalid-input cases | NOT MET |
| I15 | Errors MUST be coded, bounded and sanitized. No request content, provider text or exception string may reach the caller. | `PolicyCompareError`, `DependencyGraphError`, `ChallengePropagationError`, HTTP handlers | Submit oversized, malformed and adversarial input; inspect bodies | PARTIAL |
| I16 | Every write MUST happen after the computation succeeds. A refusal MUST leave state unchanged. | demo challenge: graph + plan before `record_challenge_event_snapshot` | Force a planning failure → `503 graph_unavailable`, history count 0 (`test_graph_failure_is_a_sanitized_503_and_records_no_event`) | MET |
| I17 | State MUST be bounded and its bounds MUST be observable to the caller: capacity, truncation, eviction and generation. | `MAX_SESSIONS`, `MAX_EVENTS_PER_SESSION`, `max_events` in the history response; `generation` internal | Append 21 events; reset; read history | PARTIAL |
| I18 | No credentials, tokens or egress path may exist outside the sealed provider boundary. | `provider_safety`, `httpx_transport`; no credential input | Search the tree for secrets; attempt a non-allowlisted origin | MET |

---

## 3. Layering and dependency direction

Arrows are imports that define a layer, not the full import graph. The nine figures in `docs/diagrams/` are the full graph; `arch-09-system-atlas` is the entry sheet. The rules below are what an agent must preserve.

| Module | May import | MUST NOT import | Protects |
|---|---|---|---|
| `policy_compare` | stdlib only | any other project module | the core vocabulary |
| `policy_dependency_graph` | `policy_compare` | `policy_evidence_demo`, any `SCENARIO_*` constant, any entry point | scenario-blind validation |
| `policy_challenge_propagation` | `policy_dependency_graph` | `policy_evidence_demo`, entry points | a planner that works on any graph |
| `policy_demo_graph` | demo + graph + compare | entry points | **the only dual-layer module** |
| `policy_demo_session` | `policy_evidence_demo` (allowlist only) | planner, graph | session bookkeeping stays scenario-level |
| `policy_demo_api` | demo, graph, planner, session | `app/*` | one entry point per product |
| `policy_api` | compare, adapter, orchestration | `app/*`, demo modules | stateless comparison |
| `app/*` | `app/*` only | any `policy_*` module | a separate product path |

**The seam rule.** `policy_demo_graph.py` is the only module permitted to know both the hotel corpus and the typed graph. Anything the graph needs that is scenario-shaped must be passed in, not imported. `project_policy_graph(pair, initial, challenge, *, scenario_id)` is that boundary; the scenario id is a parameter because the graph layer must not know which scenarios exist.

**Operational test of I13.** Add a fourth scenario and count the files that change outside `policy_evidence_demo.py`, `policy_demo_api.py` and the UI map. Any change under `policy_dependency_graph.py` or `policy_challenge_propagation.py` means the seam has been breached.

---

## 4. Domain contract

### 4.1 Graph shape

Eight node types: `SourceDocument`, `PolicyVersion`, `SourcePassage`, `Claim`, `ApplicabilityCondition`, `ComparisonRelation`, `Conclusion`, `ChallengeEvent`. Seven edge types, with allowed endpoint pairs:

| Edge | Allowed endpoints |
|---|---|
| `CONTAINS` | document → version, version → passage |
| `DERIVED_FROM` | claim → passage, condition → passage |
| `SUPPORTS` / `CONTRADICTS` | passage → claim or relation |
| `APPLIES_TO` | version → condition |
| `DEPENDS_ON` | claim → claim or condition, relation → claim or condition, conclusion → claim or relation |
| `AFFECTS` | challenge → passage, condition, claim, relation or conclusion |

A graph is a **closed snapshot over one comparison**: exactly one `comparison_id` across claim/condition/relation/conclusion/challenge nodes, and every provenance reference resolves inside the graph.

### 4.2 What each epistemic status proves

| Status | Held by | Proves | Does not prove |
|---|---|---|---|
| `SOURCE_VALIDATED` | document, version, passage; a condition only with a known scope | text hashes to the recorded digest; span and passage id are derived from that text | authenticity, currency, completeness, relevance |
| `PROPOSED` | claim, relation | a candidate assertion with citations | that the citations entail it |
| `LOCALLY_DERIVED` | conclusion, and only when `classification == "INCONCLUSIVE"`, `human_review_required` and `official_policy_mutated is False` | the result envelope passed local validation | any positive finding, or that the judgement is right |
| `CHALLENGED` | challenge event; the challenged version's condition | a reviewer questioned this node | that the node is wrong |
| `UNVERIFIED` | the unchallenged condition | applicability was not established | that the target does not apply |

### 4.3 Identity

- Node, edge, passage and citation identities are **derived by type-specific helpers** and verified on construction. A caller cannot name a node.
- Allowlisted patterns govern every identifier (`syn-policy-…`, `v…`, `cmp-syn-…`, `cand-…`, `p{ordinal}-{sha[:16]}`, scope ids, scenario ids). Free text is never an identifier.
- `snapshot_identity` is `provisional-graph-v1|` + comparison id + `(document, version, source_sha256)` triples + challenge ids. **It commits to none of the edges, claims or node text.** It MUST NOT be described as a digest of the graph, used as a tamper check, or used as a cache key for graph content.

### 4.4 Candidate ownership

A claim, relation and conclusion carry a `candidate_id`; a condition does not. Candidate equality is enforced for `Relation→Claim`, `Conclusion→Claim` and `Conclusion→Relation`. It is **not** enforced for `Claim→Claim` (only the comparison id is checked), and it cannot be enforced for conditions. Until that is fixed (§15 DEV-3), a projection MUST NOT place claims from two candidates in one graph.

---

## 5. Guarantee ledger

Each guarantee is stated in the shape an agent must reuse when documenting anything: **what it provides, what it does not, and what proves it.**

| Guarantee | Provided by | Not provided | Proven by |
|---|---|---|---|
| Citation provenance equality | `validate_citation`: document/version/digest match, passage existence, monotone span, `original_text[start:end] == quote` | semantic support, applicability, precedence, coverage | `tests/test_policy_compare.py` |
| Deterministic graph validation | exact-type checks, derived ids, sorted construction, cycle rejection over `DEPENDS_ON`, budgets before hashing | detection of tampering (identity excludes edges), or legal priority | `tests/test_policy_dependency_graph.py` |
| Bounded impact planning | typed traversal with explicit limits, `TraversalCompleteness`, blockers, `scope_note` | global independence, semantic non-impact, reassessment | `tests/test_policy_challenge_propagation.py` |
| Fail-closed challenge orchestration | parse → compute → project → plan → record; sanitized refusals; session generation check | durability across restart, or an audit trail | `tests/test_policy_demo_api.py` |
| Scenario isolation within a process | session bound to one scenario; mismatch rejected before and under the lock | cross-process isolation; a second worker sees `session_not_found` | `tests/test_session_concurrency.py` |
| Refusals that leak nothing | fixed error codes; no request content in bodies; loopback-only listeners | authorization, sandboxing, denial of local users | refusal cases in `tests/test_policy_demo_api.py`, `tests/test_provider_safety.py`, `tests/test_httpx_transport.py` |

**Reading the ledger.** A guarantee may be cited verbatim. Its `Not provided` column may not be dropped when the guarantee is quoted in UI copy, docs or commit messages.

---

## 6. Challenge pipeline contract

The demo challenge route is the one place where session state, the domain core and the planner meet. Its order is part of the contract:

1. Read a bounded body (32 KiB cap, JSON only).
2. Validate scenario against the allowlist and department against the scenario's allowed set.
3. If a session is named: it exists, and its scenario matches the request.
4. Resolve the pair (`get_scenario_pair`) and run the initial investigation.
5. Build the reviewer challenge **server-side** (`build_scenario_reviewer_challenge`). No HTTP caller supplies a quote, side or passage id today.
6. Recompute the scenario assessment — **SCRIPTED**: the post-challenge proposal is a literal `INCONCLUSIVE` abstention with fixed reasons; only `applicability_audit` varies with the department (DEV-6).
7. Project the same pair, investigation and challenge into a graph (`project_policy_graph`).
8. Plan impact with the challenged **applicability condition** as the target (`plan_challenge_impact`).
9. Record the session event with the expected generation.
10. Return the recomputation, the graph summary and the plan.

Rules:

- Steps 4–8 MUST complete before step 9. A failure in 7 or 8 returns `503 graph_unavailable` and records nothing (I16).
- A department challenge MUST NOT be presented as graph-derived. In this projection the challenge reaches the condition by `AFFECTS`, which the planner never traverses, so the plan reports the condition as the only impacted node and everything else `UNCHANGED` within a complete search. That is a **modelling fact about the projection**, not evidence of independence.
- The HTTP challenge names a department; the planner is aimed at the condition. Do not conflate the two when reading or extending the plan.
- `evidence_refs` are descriptive. They add no edges and repair no missing provenance.

---

## 7. Storage regimes and audit language

| Regime | Where | Survives restart | What it can honestly be called |
|---|---|---|---|
| SQLite | `backend/app/store.py`, handover only | yes | durable store with revision CAS; **not** tamper-evident, **not** complete |
| In-process session dict | `policy_demo_session.py`, demo only | no | session activity log (bounded, clearable) |
| Graph | none | — | per-request projection; no snapshot has been stored |
| Evaluation DB | temporary file, env-selected | no | single-process scratch space |

**Rules.**

- The demo log MUST NOT be called append-only, an audit trail, or durable. It holds at most 100 sessions × 20 events, drops the oldest event silently, and `reset` clears history and restarts sequence numbers. An operator-clearable log is not an audit trail.
- Any use of the word **audit** requires three mechanisms: durability, tamper-evidence, and completeness against an independent expectation surface. None exist today. Do not assemble a sentence that implies otherwise.
- Sequence numbers are per session generation, not durable ordinals.
- **Deferred journal design** (BLOCKED until a contract exists). If it is ever built, these constraints carry forward and are not negotiable: tamper-evidence and completeness are orthogonal; "we log everything" is not a completeness argument — name the expectation surface (intent record, causal reference, snapshot, external witness) and the positive test; every budget-exhaustion path returns an explicit partial state with a named boundary; no quarantine record without a reason code and a link to the claim or policy it supports.

---

## 8. Provider, evidence and untrusted input

The evidence ladder is one-directional. No layer may promote a lower rung into a higher one:

1. **Exact text** → provenance equality only.
2. **Stance / relation** → a proposal, always `PROPOSED`, never a finding.
3. **Confidence** → a deterministic heuristic in `app/engine.py`, not a probability and not calibrated.

**Rules.**

- Provider egress MUST stay inside `app/provider_safety.py` + `app/httpx_transport.py`: one pinned origin, one path, no proxies/cookies/redirects/retries, 16 KiB request (predicted, then verified byte-for-byte), 4 KiB response, 20 s timeout, 17 requests, $5.00 estimated ceiling, single-flight.
- No credential input exists. Do not add one without an owner decision; do not read environment secrets for provider use.
- If a provider is ever authorized (D-4), an AI-derived assertion MUST enter evidence state only as a versioned, human-gated proposal carrying model id, model version, prompt version and confirming actor. It MUST NOT be journaled as a validated finding.
- Source text is untrusted data. A provider proposal is untrusted data. `semantic_guard` is a substring cue filter — it MUST NOT be described as entailment, and negation defeats it (DEV-12).
- Evidence excluded by restriction or PII rules MUST be counted or identifiable in the response. Silent truncation is not permitted (DEV-12).
- Every boundary re-derives provenance. A challenge that carries a quote, a side or a passage id MUST be validated against the pair before recomputation (DEV-9).

---

## 9. HTTP boundary contract

| App | Routes | Body cap | Error envelope | Docs |
|---|---|---|---|---|
| `policy_demo_api` :8083 | `/demo-api/health`, `/scenarios`, `/scenario`, `/session/new`, `/session/{id}/history`, `/session/{id}/reset`, `/challenge` | 32 KiB | `{"detail": {"error", "detail"}}` | `/openapi.json` still served |
| `policy_api` :8082 | `/health`, `POST /policy-comparisons` | 512,000 B | `{"error", "detail"}` | docs, redoc and openapi disabled |
| `app/main.py` :8081 | `/api/health`, `/api/records`, `POST /api/investigations`, `GET /api/investigations/{id}`, `POST …/claims/{claim_id}/challenge`, `GET …/history` | no explicit cap | `{"detail": str}` | `/docs` live |

**Rules.**

- One canonical envelope (`{"error", "detail"}`) SHOULD govern all three apps (DEV-11). Until then, a client MUST handle the envelope of the service it calls; a shared helper that assumes one shape is a defect.
- Every route MUST have a body cap applied before parsing, and MUST reject duplicate keys and non-finite numbers (today only `policy_api` does).
- Error bodies MUST NOT echo caller input. `Scenario ID '{id}' is not recognized` and the session error are reflected-input patterns (DEV-11).
- A service with a writable store MUST NOT publish `/docs`, `/redoc` or `/openapi.json`. 8081 does (DEV-11).
- CORS stays explicit and credential-free. The demo and comparison APIs allow only `http://127.0.0.1:5174`; opening the UI at `localhost:5174` is browser-blocked. Do not widen this to `*`.
- Loopback binding is a blast-radius bound, never an authorization boundary.

---

## 10. Failure semantics

| Condition (demo API unless noted) | Response | State effect |
|---|---|---|
| Body over cap | `413 body_too_large` | none |
| Wrong content type | `415 unsupported_media_type` | none |
| Malformed or invalid fields | `422 invalid_request` | none |
| Unknown scenario (demo GET) | `400 unknown_scenario` | none |
| Department not allowed for scenario | `422 invalid_challenge_department` | none |
| Session missing | `404 session_not_found` | none |
| Session bound to another scenario | `422 scenario_mismatch` | none |
| Reset during computation | `409 session_reset` | no event written |
| Graph or plan invalid | `503 graph_unavailable` | no event written |
| Unexpected internal failure | `503 demo_unavailable` | no event written |
| Comparison pair invalid | coded 4xx, no echo | nothing persisted |

**Rules.**

- No silent timeout and no "no impact / unaffected" fallback. Budget exhaustion produces an explicit incomplete plan with a named limit.
- No partial success. A response is either the full computed result or a refusal.
- A 5xx MUST NOT contain exception text, provider text or request content.
- Session capacity, reset and eviction MUST be visible in the response for any claim about history (DEV-7).

---

## 11. Budgets and limits

| Budget | Value | Source | Boundary test |
|---|---|---|---|
| Graph nodes / edges | 5,000 / 10,000 | `policy_dependency_graph.py` | exact and +1 |
| Aggregate text | 4 MiB UTF-8 | same | exact and +1 |
| Aggregate references / nested entries | 256 / 25,000 | same | exact and +1 |
| Snapshot identity | 10,000 bytes | same | exact and +1 |
| Provenance / description / citation text | 500 / 500 / 4,000 chars | same | over-length rejection |
| Planner visited nodes / edges | 1,000 / 3,000 | `policy_challenge_propagation.py` | forced limit → no `UNCHANGED` |
| Planner path length / paths per node / total entries | 32 / 4 / 6,000 | same | forced limit → no `UNCHANGED` |
| Demo request body | 32,768 B | `policy_demo_api.py` | over cap → 413 |
| Comparison request body | 512,000 B | `policy_api.py` | over cap → 413 |
| Provider request / response / timeout | 16 KiB / 4 KiB / 20 s | `app/provider_safety.py` | serialized size equality |
| Provider attempts / budget | 17 / $5.00 | same | reservation without refund |
| Sessions / events per session | 100 / 20 | `policy_demo_session.py` | eviction and ring-buffer drop |

Changing a number means changing the constant, the boundary test, and any figure that prints it — in one change.

---

## 12. Change protocol

| Change | Files that must move together |
|---|---|
| Add a scenario | builder in `policy_evidence_demo.py`; `SCENARIO_METADATA`; `ALLOWED_CHALLENGE_DEPARTMENTS` in `policy_demo_api.py`; UI scenario map; API tests for scenario, challenge and plan; **zero graph edits** |
| Add a node type | dataclass, `NodeType`, id helper, `_validate_node_shape`, `_expected_node_id`, `_valid_edge_types`, aggregation budget accounting, planner `_TARGET_TYPES`/`_make_transitions`/`_reason`, `POLICY_KNOWLEDGE_GRAPH.md`, an arch figure, boundary tests |
| Add an edge type | `EdgeType`, `_valid_edge_types`, `_validate_edge`, planner adjacency and transition rules (or an explicit exclusion), docs, tests that assert it is not traversed if excluded |
| Add a route | request model + cap, canonical error envelope, health check coverage, `BACKEND_AND_API_DOCUMENTATION.md`, API tests including a refusal case |
| Change a budget or constant | constant, boundary test, §11, any figure that prints it |
| Change the projection | `policy_demo_graph.py` only; prove with the add-a-scenario test that no graph module changed |
| Add a diagram | builder in `scripts/render_diagrams.py`, row in `docs/diagrams/README.md`, unconnected-card guard, rendered SVG, `validate` clean on schema/bindings/text_overflow/layout/overlap, no arrow between non-importing modules |
| Change an authored claim | update the doc it lives in **and** the guarantee ledger if it is a guarantee; see §14 for forbidden phrasing |

### 12.1 Figure laws

- A scene is generated from `scripts/render_diagrams.py`. Never hand-edit a `.excalidraw` file or an SVG. Source and image are committed together; a diagram without its builder is not a diagram, it is a screenshot.
- `Figure.save` fails the build on a card with no connector unless the card is declared with `unconnected_ok`. `arch-02` declares exactly three; the generator printing three lines is expected, not a warning to silence.
- No arrow between modules that do not import each other. Arrows are the imports that define a layer, not the full import graph. The one exception is `arch-09-system-atlas`: a horizontal arrow there orders the reading within a band, only its vertical spine is flow, and its footer states that rule.
- No arrow may cross a card other than its endpoints. When the needed arrow would cross several bands, state the import in that band's note instead of drawing it.
- A figure may not print a number the repository cannot reproduce, and its footer states what it does not claim.

---

## 13. Verification gates

| Gate | Command | Green means | Cannot prove |
|---|---|---|---|
| Backend suite | `PYTHONPATH=backend python -m pytest -q backend/tests` | every test passes except the two known `test_launcher.py` identity failures (800 passed / 2 failed at the time of writing) | UI behaviour, runtime database state, semantic correctness |
| Focused domain tests | `PYTHONPATH=backend python -m pytest -q backend/tests/test_policy_dependency_graph.py backend/tests/test_policy_challenge_propagation.py` | validation, budgets, planner invariants | that the projection is semantically fair |
| Frontend typecheck | `cd frontend && npm run typecheck` | types compile | that the page renders or the flow works |
| Diagram build | `python3 scripts/render_diagrams.py` | every card is bound to an arrow or declared, and every card fits its cell | that an arrow is semantically right |
| Diagram validation | `excalidraw.validate(rules=["schema","bindings","text_overflow","layout","overlap"])` on each scene | scenes are structurally sound | overlap warnings that are text inside its own card |
| Health probe | `python3 scripts/check_policy_demo_health.py` | the launcher's three services and the UI answer correctly | correctness of any analysis |

**The two launcher failures are a known platform limit, not a licence.** They fail on non-Windows because process identity is read through `ntpath`/PowerShell. Fixing them means making identity portable; weakening or skipping them is a violation of this file.

The suite is 481 test functions in 20 modules; parametrisation widens that to 802
cases. The counts describe size, not strength — a green run does not prove coverage.
A green suite is not evidence for the UI (there is no frontend test runner) and does
not prove the demo's recompute is derived.

**Definition of done for any change.** The touched gates ran with their real command;
the §12 row is complete; every changed invariant has a falsification test; no figure
or doc prints a number the tree cannot reproduce; copy and commit message obey §14. A
successful build alone is not done.

---

## 14. Refuse list

Each forbidden sentence is paired with the defensible one. Reusing the left-hand phrasing in code, docs, UI copy, commit messages or reviews is a defect.

| Do not write | Write instead |
|---|---|
| "append-only audit trail" | "bounded in-process session activity log; reset clears it" |
| "the system can prove its audit trail is complete" | no audit trail exists; completeness needs an expectation surface, and there is none |
| "snapshot identity is an integrity/tamper-evident hash" | it commits to comparison, version and challenge identity; it cannot detect edge tampering |
| "the demo recomputes from the dependency graph" | the recompute is a scripted abstention; the graph and plan are returned beside it |
| "UNCHANGED means unaffected" | no supported path was found within the bounded scope of this snapshot |
| "exact quote proves the claim" | exact quote proves provenance; support is a proposal |
| "the provider was assessed" / "the model concluded" | a deterministic mock/fake produced the proposal; no model ran |
| "the planner assesses all affected conclusions" | it reports reachability and review needs; it does not reassess or mutate |
| "quarantined" (with no store) | name the blocker and the limit; there is no quarantine store |
| "budget exhaustion returns partial results" | name the limit, the unexplored set, and the visible signal |
| "we will decide ownership later" | name the decision in §16 with what hinges on it |

---

## 15. Known deviations

Accepted, or required to be fixed before the trigger. An agent MUST NOT silently "fix" one by editing this file.

| ID | Deviation | Where | Decision |
|---|---|---|---|
| DEV-1 | `ALL` vs `UNKNOWN` scope returns `OVERLAP`, overstating certainty; `UNKNOWN` should dominate | `policy_compare._dimension_relation` | Fix before any multi-department claim |
| DEV-2 | Chronology is not validated, and version roles are re-derived by sorting `(effective_from, version_id)` | `validate_policy_pair`, `_pair_from_version_nodes` | Fix before any non-synthetic pair |
| DEV-3 | Cross-candidate `Claim→Claim` is permitted; conditions carry no candidate id, so two candidates can share one condition | `_validate_edge`, `ApplicabilityCondition` | Fix before projecting two candidates |
| DEV-4 | A `MISSING_PROVENANCE` blocker can coexist with a `REASSESSMENT_REQUIRED` state for the same node | planner merge priority | Fix: blocker and state MUST agree |
| DEV-5 | One saturated node marks the whole plan incomplete | planner `break` on path limits | Accepted: conservative direction is safe under I11 |
| DEV-6 | Demo recompute is a literal; UI copy implies derivation | `recompute_investigation_after_challenge`, demo UI | Fix copy; never cite the recompute as graph-derived |
| DEV-7 | Session log is called append-only; capacity is exposed but truncation, eviction and reset are not recorded | `policy_demo_session.py`, route docstrings, UI | Rename and expose generation and a truncation marker |
| DEV-8 | `assert` is used as narrowing | demo routes, provider gate, graph/planner internals | Replace with coded errors |
| DEV-9 | The recompute path never validates the challenge's quote, side or passage | `recompute_investigation_after_challenge` | Fix at the boundary (review H1) |
| DEV-10 | Planner accepts any `SourcePassage` as an evidence ref, not one in the target's version | `plan_challenge_impact` | Fix: scope to target document/version |
| DEV-11 | Three error envelopes and body contracts; 8081 serves `/docs`; demo echoes input | `app/main.py`, `policy_api.py`, `policy_demo_api.py` | Unify; disable docs on the writable service |
| DEV-12 | Restriction/PII exclusions are dropped without a count; `semantic_guard` is substring-only and negation-blind | `provider_safety.eligible_provider_records`, `semantic_guard.py` | Count exclusions; never call the guard entailment |
| DEV-13 | Launcher termination is Windows-only and returns 0 when a child dies unexpectedly | `scripts/launch_policy_demo.py` | State the platform; fix the exit code |

---

## 16. Decisions and blocked work

**Decided (binding):** the layering in §3; provenance-only reading of citations; `INCONCLUSIVE` as the only classification; bounded, read-only planning; per-request graph projection with no stored snapshot; loopback-only, unauthenticated services.

**Deferred to the owner (an agent may not decide these):**

| ID | Decision | Options | What hinges on it |
|---|---|---|---|
| D-1 | Claim identity | `(investigation, claim, version)` blob vs content-addressed node id | whether typed edges can ever key a stored claim; the one change a later migration cannot undo |
| D-2 | Journal contract | build a durable, tamper-evident, complete journal vs keep the session log | any use of the word "audit"; multi-worker support |
| D-3 | Authentication and deployment | loopback prototype vs exposed service with identity | CORS, docs exposure, session sharing |
| D-4 | Real provider | remain mock/fake vs authorize a provider | credential handling, retention, evaluation validity |
| D-5 | Demo storage | view state only vs domain data in the demo | whether 8083 needs a store or stays ephemeral |
| D-6 | Graph persistence | continue design-only vs authorize execution | snapshot identity, quarantine, projections |

**Blocked (do not implement, do not partially implement):** policy-graph database execution and RT-01–RT-03; the prototype gate is CLOSED. Real provider selection, credentials, retention of real sources, and authorization changes all require separate owner approval.

---

## 17. Provenance of this specification

Written 2026-10-31 against the tree at that date. Sources read directly: `backend/policy_compare.py`, `policy_dependency_graph.py`, `policy_challenge_propagation.py`, `policy_demo_graph.py`, `policy_demo_api.py`, `policy_demo_session.py`, `policy_evidence_demo.py`, `app/provider_safety.py`, `app/main.py`, `app/store.py`, `scripts/render_diagrams.py`, the test inventory, and `docs/project/*` plus `docs/reviews/ARCHITECTURE_AND_CODE_REVIEW.md`.

Marker discipline, so a later reader can tell what was verified from what was inferred:

- **Given** (read in source or executed): ports, routes, envelopes, budgets, node/edge legality, planner exclusions, write ordering, test counts, the two launcher failures.
- **Inferred** (derived, not separately exercised): the layering import map was parsed from the modules; the UI's audit copy and the demo's scripted recompute were read, not clicked through.
- **Assumed** (state explicitly if wrong): the handover SQLite contents were not opened; no frontend test runner exists, so UI behaviour is unverified; the governance statuses (BLOCKED, CLOSED, RT-01–03) are carried from `docs/project/ROADMAP_AND_NEXT_PHASES.md` and are not re-derived here.

If any of these assumptions changes, the affected sections are §3, §7, §13 and §16 — update them in the same change that invalidates them.
