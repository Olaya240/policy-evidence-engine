# Decision register

Every load-bearing choice in the backend, the alternative it beat, the reason, and the
test that fails if the decision is reversed. "Best" is not a property a test can assert;
what can be asserted is that a choice is explicit, reversible, and that reversing it
breaks something visible. That is the standard this register holds the code to.

Status column: **pinned** = a test fails if the decision is reversed. **open** = the
decision is real, but nothing would notice if it flipped.

| # | Decision | Alternative rejected | Why | Falsifier | Test | Status |
|---|---|---|---|---|---|---|
| 1 | The verdict table is a signed margin: `s >= 2 and s >= 3c+1` → SUPPORTED, `c >= 3s+1` → CONTRADICTED | Counting evidence items, or a fixed ratio without a minimum | Group counts, not records, are the unit of independence; the rule is machine-checked in `ct3/DecisionTable.v:120-122` | A configuration whose label the proof calls SUPPORTED but the code calls PARTIAL (or vice versa) | `tests/test_decision_table_slice9_labels.py` | pinned |
| 2 | Refutation is asymmetric: one contradiction decides, one support does not | Symmetric minimum on both directions | The Coq model has the same shape; a refutation does not need corroboration to withhold a claim | A change to the bound that makes `decide(0,1)` anything but CONTRADICTED | `test_a_single_contradiction_is_decisive_while_a_single_support_is_not` | pinned |
| 3 | A challenged group is counted once in the as-if evaluation | Adding disputed counts to undisputed counts | One source is one unit of independence; adding it twice reports a score the evidence cannot reach | `decide_evidence([G1, G1-disputed])` reporting the disputed rule | `test_a_group_with_a_challenged_and_a_clean_record_is_one_source` | pinned |
| 4 | A challenge re-evaluates freshness at its own clock | Keeping the stored `stale` flags | A persisted claim must not contradict a reassessment of the same records at the same instant | A challenged claim whose status differs from `assess_hypothesis` at that clock | `test_challenge_re_evaluates_staleness_at_its_own_clock` | pinned |
| 5 | A future-dated record is non-current, not invalid | Raising `invalid_timestamp`; clamping the age | Historical-clock evaluation (backtesting) legitimately sees the corpus in the future | An assessment against a historical clock failing instead of excluding the record | `test_a_future_dated_record_is_not_current_evidence` | pinned |
| 6 | The provider sees a projection, never the caller's records | Passing `permitted` records from the engine, or trusting the caller | The boundary is the only choke point every provider shares; enforcement must not depend on which caller is in use | Any restricted id or text appearing in a serialized provider request | `tests/test_architecture_invariants.py::test_no_restricted_record_reaches_the_provider_request` | pinned |
| 7 | Provider output is a closed allowlist: unknown keys fail closed | Ignoring unknown keys | A vendor extra could be the vector; failing closed is the safe direction for a boundary | A response with `logprobs` accepted | `test_baseten_response_parser_fails_closed_on_unsupported_or_empty_shapes` (code only, not the code value) | open — over-strictness untested against a live echo |
| 8 | Proposals must quote their own source record | Trusting `source_record_id` alone | A citation that is not in its own record is not evidence | A proposal accepted with a quote absent from its record | `tests/test_provider_safety.py` grounding cases | pinned |
| 9 | Coverage is advisory and direction-blind; it never moves a verdict | Folding coverage into confidence | A missing corroboration is a review prompt, not evidence | Any coverage flag changing `status` or `confidence` | `tests/test_evidence_coverage_slice11.py` | pinned |
| 10 | Challenge persistence is optimistic: read snapshot, recompute, `BEGIN IMMEDIATE`, verify revision and claims | Locking the investigation for the whole provider call | Provider work must not hold a write lock; the revision check makes the race detectable | A challenge committed over a changed revision | `tests/test_store_slices13_14.py::test_a_stale_revision_writes_nothing` | pinned |
| 11 | Restricted records are filtered at the query *and* refused by the engine | Either layer alone | Two independent controls; one bug does not expose the canary | `get_record` returning a restricted row, or the engine accepting one | `test_restricted_records_are_hidden_from_reads` | pinned |
| 12 | A response may carry at most 43 proposals — the measured ceiling of the 4 KiB body | 128 (unreachable, decided nothing) and 32 (rejected legitimate 33-43-record corpora) | Measured twice: 43 minimum-size proposals fill the byte cap, 44 cannot be encoded; and a 43-record corpus is the largest the engine can assess in one call, 44 refuses | A 44th proposal accepted, or a 43-record corpus refused | `test_the_proposal_cap_binds_before_the_byte_cap_can`, `test_capacity_boundary_is_43_records_and_refused_fast_above_it` | pinned (re-measured 2026-11-02) |
| 13 | Requests are limited to 600 per minute per client host | No limit (threat row H8) | A single-user local prototype still needs a runaway-loop guard; 600/min does not constrain a human reviewer and stops a spinning client | A legitimate client pattern exceeding 600 requests in a minute | `tests/test_rate_limit_wiring.py` | pinned |
| 14 | Provider activation goes through `build_engine_from_environment`: flag + key source + enabled budget, mock on any failure | Building `AssessmentEngine()` directly in `main.py` | Activation must be explicit and reversible; a failure must leave a working process, not a half-configured one | Any path reaching the network without all three inputs | `tests/test_activation_wiring.py` | pinned |
| 15 | Document ingestion is a text endpoint (`POST /api/records/ingest`): no file upload, no PDF/DOCX, no new dependency, no flag | A file-upload MVP with a parsing library | The corpus is text; a parser adds dependencies and attack surface for no evidence gain, and a flag would be a second behaviour nobody proved | A deployment that must ingest binary documents | `tests/test_ingest.py` | pinned |
| 16 | Duplicate ingestion returns 200 with the existing id, not 409 | A bare 409 | The caller needs the id to continue; a 409 forces a raceable follow-up lookup. Identity is normalised text + department + `source_group`; tags and a supplied timestamp are not part of it | A caller that must distinguish "new" from "already there" by status alone — it reads `created` instead | `tests/test_ingest.py` | pinned |
| 17 | The affected-claim set is the transitive closure from `dependency_graph`, plus the challenged claim | A per-route comprehension over `dependencies` | One definition, so the evaluator's `only_dependency_affected_claims_recomputed` check and the store cannot drift apart | A claim-to-claim edge appearing in the data without `claim_edges` being populated | `tests/test_dependency_graph.py` | pinned |
| 18 | Confidence is a magnitude of group imbalance, not a probability; at a status switch the reported score is **not** monotone in settled support (0.50 → 0.25), deliberately | A monotone score | A withheld verdict must not advertise the strength of the evidence under challenge; both cannot hold at the switch, so status integrity wins | A consumer that reads `score` as a confidence trend across disputed verdicts | `tests/test_confidence_reliability.py`, `ct3/audit/CONFIDENCE-CALIBRATION.md` | pinned (policy, with named cost) |

## What the register says about "each decision is the best"

Eleven of twelve decisions are pinned and have a stated alternative. One is not:
**decision 7**, the provider allowlist's strictness. It cannot be closed from inside this
repository — it needs one recorded response from the real vendor to say whether
`system_fingerprint`, `logprobs` or a dated model echo appear in normal traffic. Until
then the code fails closed and the register says so; claiming it is "best" would be a
claim with no artifact.

**Decision 12 was closed by measurement, not by argument.** The previous cap was 128 and
the 4 KiB body holds at most 43 minimum-size proposals, so the cap could never fire — a
decision that decided nothing, green on both sides. It is now 32, below the measured
ceiling, so the 33rd proposal is refused by count before the byte cap can bind. That is
the pattern worth repeating: when two bounds exist, assert that the tighter one is the
one that fires.
