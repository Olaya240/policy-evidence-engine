# Policy Comparison Evaluation Protocol (Proposal)

**Status:** Design document only. No model, provider, dataset, or evaluation run is approved by this document.

This protocol describes how a future candidate generator could be evaluated. It does not establish model quality or authorize a provider call. Current synthetic fixtures are regression examples, not independent held-out evidence.

## 1. Evaluation objectives

Evaluate these dimensions separately; a strong score in one cannot substitute for another.

1. **Relation classification quality:** Whether a proposed relation is appropriate for the adjudicated policy passages and metadata. The relation vocabulary currently defined in `policy_compare.py` is `CONTRADICTION`, `COMPATIBLE_CHANGE`, `NEW_RULE`, `SCOPE_OR_TIME_DIFFERENCE`, and `INCONCLUSIVE`.
2. **Citation provenance:** Whether every cited document, version, source hash, passage, offset, and quote refers exactly to the supplied immutable source.
3. **Semantic support:** Whether the cited passage actually supports the stated relationship. This requires independent human adjudication. Exact quote/offset matching proves source provenance only; it does not prove entailment, contradiction, or relevance.
4. **Abstention and uncertainty:** Whether the generator abstains or marks uncertainty for insufficient evidence, ambiguous precedence, unknown scope or dates, excerpts, and incomplete coverage.
5. **Invalid-output rejection:** Whether malformed, oversized, duplicate-key, unsupported-type, untrusted-field, or fabricated-citation output is rejected safely and consistently.
6. **Operational failure handling:** Whether timeouts, provider errors, malformed responses, throttling, and uncertain completion are surfaced safely and counted, without silently retrying or dropping cases.

Keep provenance and semantic support as distinct reported outcomes. A citation can be valid but irrelevant, and a semantically plausible claim can still have invalid provenance.

## 2. Dataset design

### Example coverage

Build synthetic policy pairs and adversarial response examples covering:

- A true contradiction with overlapping effective time and applicable scope, plus passages that directly support both obligations.
- Compatible wording changes that preserve the operative requirement.
- A genuinely new rule with adequate comparison coverage and no older counterpart.
- Scope differences and effective-time differences, including overlapping, disjoint, and unknown metadata.
- Insufficient evidence, ambiguous language, missing counterpart passages, and correct `INCONCLUSIVE` outcomes.
- Ambiguous precedence where the domain has not supplied a governing rule; expected outcome is unresolved/inconclusive.
- Incomplete-document and excerpt-only pairs, including a tempting but unsupported `NEW_RULE` claim.
- Unsupported impact proposals where no dependency evidence supports the named department or procedure.
- Valid citations and fabricated passage IDs, ambiguous quotes, cross-version substitutions, wrong hashes, wrong offsets, passage-boundary shifts, and quote text found elsewhere but not at the declared location.
- Malformed outputs: invalid JSON, duplicate keys, unexpected fields/types, booleans in integer fields, non-finite values, excessive nesting/size/counts, and invalid relation or uncertainty values.
- Operational failures: timeout before response, timeout after uncertain server completion, rate limit, provider error, invalid encoding, and malformed response.

All examples must be synthetic or otherwise explicitly approved for the applicable evaluation environment. Do not create or use real confidential hotel policy text under this protocol.

### Dataset record

Use a **gold finding** as the primary unit for affirmative relation-level scoring. A gold finding is one independently adjudicated relationship between a specific older/newer passage set (or a documented one-sided newer passage for a new rule), within one policy pair. For `INCONCLUSIVE`, record a separate gold comparison-level decision item stating whether abstention is required, allowed, or incorrect; it is not an affirmative finding. A policy pair may contain zero, one, or many findings; do not treat a pair's candidate count as its finding count. Give each pair a stable opaque `example_id`, each gold finding a stable opaque `finding_id`, and each abstention decision item a stable opaque `decision_id`.

Each labeled pair/finding record should have:

- Pair metadata: synthetic document ID, older/newer version IDs, effective dates, scope, `FULL_DOCUMENT`/`EXCERPT` coverage labels, and locally computed source hashes.
- Immutable source text and locally derived passage IDs, offsets, and passage hashes.
- Gold relation label, or an explicitly adjudicated set of acceptable labels where ambiguity is inherent.
- Required evidence passages for each side, with exact source spans and a separate semantic-support judgment for each claim/citation pair.
- Expected uncertainty reasons and whether abstention is required, allowed, or incorrect.
- Precedence status and rationale, if and only if an approved domain rule supplies it.
- Impact targets and their dependency evidence, or an explicit unsupported-impact label.
- For attack cases: malformed-response category, expected rejection category, and whether any partial output must be discarded.
- Adjudicator IDs represented by non-identifying codes, individual labels, final disposition, rationale, and disagreement status.
- A predeclared eligibility state for every metric, such as `ADJUDICATED`, `AMBIGUOUS_ACCEPTABLE_LABELS`, `UNRESOLVED`, or `MISSING_LABEL`, with reasons and counts.

Adjudicators should label independently before discussion. Preserve original labels; record the resolution, rationale, and unresolved disagreement rather than overwriting dissent. Do not force a single gold label when reasonable interpretations remain; mark the finding ambiguous and evaluate appropriate abstention.

### Partitioning by lineage

Assign partitions at the policy-family/document-lineage level, not the individual example or passage level. Keep every version, comparison pair, and related passage from a lineage in one partition. Identify shared passages and exact or near-duplicate rules across lineages; place linked material in one partition or exclude and document it before unsealing held-out labels. Use a documented deduplication method and adjudicate borderline matches. Development fixtures and synthetic regression tests remain separate from independent model-evaluation partitions.

Held-out outcomes must never be used to change prompts, examples, schemas, matching guides or rules, thresholds, code, or model settings. If an outcome informs any such change, retire that partition from independent evaluation. A replacement held-out partition must be independently assembled and lineage-separated. Record the number of changes informed by held-out observations; it must be zero for a valid independent held-out result.

## 3. Dataset separation

Maintain three distinct partitions, grouped by policy family/document lineage as described above:

- **Development:** May be inspected and used to develop prompts, parsing, and candidate ranking. It is not performance evidence.
- **Validation/threshold setting:** May be used to compare candidate configurations and choose thresholds. Freeze it before final evaluation.
- **Held-out evaluation:** Restricted access; labels and expected outputs must not appear in prompts, adapter code, examples, test fixtures, or development reports before the final run.

Use distinct IDs and access controls; record partition assignment and dataset hashes in a controlled evaluation manifest. Prevent passage-level or near-duplicate leakage across partitions. Keep synthetic unit fixtures separate from all three reported model-evaluation partitions. Held-out data cannot be used for prompt or threshold development; any held-out outcome that informs a change retires that partition from independent evaluation, as specified above.

The current repository's synthetic fixtures are not independently adjudicated held-out data. Dataset creation, curation, and adjudication require separate authorization and governance.

## 4. Metrics and counting rules

### Finding matching and relation metrics

Before evaluation, freeze a versioned matching annotation guide. For each proposal/finding pair, give both blinded adjudicators the proposal claim/reasoning, stable proposal ID, cited side/quote hints as locating clues, and the gold finding's source anchors, version metadata, and adjudicated description. They decide whether both describe the same underlying requirement relationship. They must not use the proposed relation label or citation-validity outcome to decide identity; citation correctness and relation correctness are scored separately. Source text may identify the claimed relationship, but adjudicators must not invent policy rules or decide policy correctness without evidence. Each records `MATCH`, `NO_MATCH`, or `UNRESOLVED`, with evidence references and a short rationale. A third blinded adjudicator resolves disagreements where possible. Preserve original decisions, resolutions/rationales, and unresolved states. Record the guide version/hash and reviewer agreement.

Only adjudicated `MATCH` edges are eligible. `NO_MATCH` edges are excluded; unresolved edges never become matches by default. Within each policy pair, sort stable non-sensitive proposal IDs and gold `finding_id`s lexicographically, find a maximum-cardinality one-to-one matching, and among maximum matchings choose the lexicographically smallest sorted edge list. Record the procedure/version and resulting edge list. A proposal and a gold finding can each receive at most one match. Unmatched proposals, including duplicates, are extras; unmatched eligible gold findings are misses. Report unresolved edges separately and do not award them credit.

- A matched proposal with an accepted relation is a true positive. A matched proposal with a wrong relation is a false positive for the proposed class and a false negative for the gold class. An unmatched proposal is an extra/false-positive finding; duplicate proposals remain extras after one-to-one matching.
- An unmatched gold finding is a missed finding and false negative for its gold relation(s).
- Zero proposals on a pair means every eligible gold finding in that pair is missed. A valid explicit abstention is reported separately and does not turn a missing finding into a correct classification.
- A finding with multiple pre-adjudicated acceptable labels may be correctly classified by any of them. Report these findings separately and score them with acceptable-set accuracy (`matched ambiguous findings whose proposed relation is in the frozen acceptable set / matched ambiguous findings`). Exclude them from single-label per-class TP/FP/FN unless adjudicators resolve the label before predictions are reviewed. Do not choose the acceptable label after seeing predictions. Match `INCONCLUSIVE` proposals separately and one-to-one to pair-level decision items; do not treat them as affirmative findings.
- Exclude `UNRESOLVED` and `MISSING_LABEL` findings from primary relation-quality denominators only under a pre-registered eligibility rule. Report their counts, reasons, and outcomes separately; never count them as correct. Include them in abstention analysis only if adjudicators explicitly determine whether abstention is appropriate.

For each affirmative class `c`, report TP, FP, and FN over eligible gold findings and matched/unmatched proposals. A wrong-label matched proposal contributes FP for its proposed class and FN for its gold class; an unmatched eligible finding contributes FN, and an extra proposal contributes FP for its proposed class. Report `INCONCLUSIVE` TP/FP/FN separately over eligible pair-level decision items and their matched/unmatched `INCONCLUSIVE` proposals. Report `finding recall = matched eligible gold findings / eligible gold findings` across affirmative findings; report `INCONCLUSIVE` decision-item recall separately. Never combine these populations without a pre-registered weighting rule.

Do **not** manufacture true negatives from hypothetical absent findings. The universe of possible unreported policy relationships is open-ended, so finding-level TN and FPR are not defined here. Report per-class precision, recall, and FNR where denominators are defined; report FPR/TN as `NOT DEFINED` rather than inventing an exhaustive universe. A conventional multiclass confusion matrix is not required where its cells cannot be justified. Use matched/wrong-label/missed/extra tables plus a separate operational-outcome table instead.

- `Precision_c = TP_c / (TP_c + FP_c)`.
- `Recall_c = TP_c / (TP_c + FN_c)`.
- `FNR_c = FN_c / (FN_c + TP_c)`.

If a denominator is zero, report `N/A` with the count; do not substitute zero. Define macro values as the unweighted arithmetic mean of per-class values for the predeclared class set; show the included class count and any `N/A` class. Do not combine affirmative-finding and pair-level decision-item classes into a macro score unless a weighting rule is pre-registered. Do not report micro averages unless their treatment of unmatched proposals and failures is separately defined. Since TN/FPR and a complete multiclass confusion matrix lack a defensible open-world finding universe, report them as `NOT DEFINED`; do not infer that the five labels are exhaustive over every possible absent relationship. Report extra, duplicate, missed, and zero-proposal counts. Gold-finding-level matching prevents multiple findings within one policy pair from inflating true positives.

Counting policy:

- Distinguish valid `INCONCLUSIVE`, valid explicit abstention, no proposal, malformed response, local validation rejection, timeout, provider/runtime failure, and rate limit. Report operational outcomes separately; none is a sixth relation label.
- Malformed response, validation rejection, timeout, or provider/runtime failure yields `NO_PREDICTION/FAILURE`, not `INCONCLUSIVE`. Each eligible unmatched gold finding is a false negative. Do not assign TNs to failed pairs; TN/FPR are undefined under this open-world protocol.
- A valid `INCONCLUSIVE` relation is scored as a relation prediction, not automatically as a correct abstention. Count abstention as correct only where independent adjudication says abstention is required. Report disputed/unresolved cases separately.
- Do not drop cases because of provider errors, malformed output, timeouts, or invalid citations.

Use a separate operational-outcome table with mutually exclusive primary outcomes per attempted pair: `EMPTY_CANDIDATE_SET` (an accepted response with zero candidates), `RESPONSE_ACCEPTED_WITH_CANDIDATES`, `MALFORMED_RESPONSE`, `VALIDATION_REJECTION`, `TIMEOUT`, `PROVIDER_OR_RUNTIME_FAILURE`, or `RATE_LIMIT`. Report valid explicit abstention and valid non-abstaining `INCONCLUSIVE` within accepted responses. These outcomes are not relation labels and do not create TN counts.

#### Frozen primary-outcome precedence (`outcome-precedence-v1`)

Assign exactly one primary outcome using the first applicable rule in this order; record every other observed condition as a secondary event flag. The order classifies observable evaluation-stage outcomes and does not assume provider-specific behavior:

1. `TIMEOUT`: the attempt deadline expires before a complete response is available. A later response or status is secondary and does not replace the timeout.
2. `RATE_LIMIT`: an explicit, recognized rate-limit outcome is observed before the deadline and before a complete candidate response is accepted. A response body accompanying a recognized rate-limit outcome is not parsed as candidate JSON.
3. `PROVIDER_OR_RUNTIME_FAILURE`: a non-timeout, non-rate-limit terminal provider or local runtime failure prevents completion of response validation.
4. `MALFORMED_RESPONSE`: a complete nominal candidate response is received but cannot be decoded or parsed under the frozen parser contract, including invalid encoding or JSON syntax.
5. `VALIDATION_REJECTION`: a response parses as JSON but is rejected by the frozen local schema, bounds, or citation validator.
6. `EMPTY_CANDIDATE_SET`: a response passes parsing and local validation and contains zero normalized candidates.
7. `RESPONSE_ACCEPTED_WITH_CANDIDATES`: a response passes parsing and local validation and contains one or more normalized candidates.

In a tie recorded at one observation point, use the order above. `MALFORMED_RESPONSE` is reserved for decode/parse failure; a parsed response rejected by local rules is `VALIDATION_REJECTION`. Timeout and explicit rate-limit outcomes take precedence over any later body/validation result; provider/runtime failure is used only when neither applies. Store `outcome-precedence-v1` in run/report provenance. Any change requires a new version and must be frozen before evaluation.

Additional metrics:

- **Abstention rate:** `decision items matched to a valid explicit abstention proposal / eligible pair-level decision items`. Match abstaining `INCONCLUSIVE` proposals one-to-one to decision items using the stable matching rules; duplicate abstentions do not receive multiple credit. Report valid non-abstaining `INCONCLUSIVE` proposals separately.
- **Abstention quality:** precision is `matched abstention proposals on decision items adjudicated as requiring abstention / all valid abstention proposals`; recall is `decision items requiring abstention with a matched valid abstention proposal / all decision items adjudicated as requiring abstention`. Also report unnecessary abstentions on determinate items and disputed/unresolved items. A malformed response, validation rejection, timeout, or missing prediction is never intentional abstention.
- Pair every emitted claim with each citation it asserts supports that claim; each claim-citation pair retains the proposal ID, relation, source side, and mapping for adjudication.
- **Citation provenance precision:** `citations that resolve exactly to declared source/version/hash/passage/offset/quote / all emitted citations`. Separately report gold-evidence alignment: wrong-side, irrelevant-to-gold, extra, ambiguous, missing, or cross-version citations do not satisfy a required gold citation even if valid elsewhere in the corpus.
- **Citation provenance recall:** `eligible gold citation targets with an emitted citation on the required side that is locally valid / all eligible gold citation targets`. A gold citation target is independently adjudicated before model output review and records the required claim, source side, source anchor, and whether a citation is required. Count missing required citations as failures; unresolved or missing gold-target adjudication remains visible and is excluded only under a pre-registered eligibility rule. Report per-finding exact-match rate and extra/ambiguous/wrong-side counts.
- Every emitted claim-citation pair requires adjudication status `SUPPORTED`, `UNSUPPORTED`, `IRRELEVANT`, or `UNRESOLVED`, with rationale. **Semantic-support precision:** `SUPPORTED emitted pairs / all emitted claim-citation pairs`. If any pair is unresolved or unadjudicated, report it and do not call the precision complete; any complete-case score must include adjudication coverage and be labeled incomplete.
- **Semantic-support recall:** `distinct eligible gold claim-citation targets matched to an emitted pair adjudicated SUPPORTED / all eligible gold claim-citation targets adjudicated SUPPORTED`. Gold targets are separately annotated from emitted citations before model output review. Blinded adjudicators map an emitted pair to at most one gold target for recall credit; each gold target receives credit at most once. Missing citations and unmatched gold targets are misses. `UNSUPPORTED`, `IRRELEVANT`, and `UNRESOLVED` emitted pairs are not supported; unresolved/missing target mappings remain visible and receive no credit. Adjudication coverage is `emitted pairs with completed semantic adjudication / all emitted pairs`.
- **Invalid-response rejection rate:** `invalid responses safely rejected / all invalid responses deliberately submitted`. Also report false acceptance count; target zero. Fixed sanitized errors and absence of partial accepted candidates are checked separately.
- **Timeout rate:** `timed-out attempts / all attempted cases`.
- **Operational failure rate:** `attempted pairs whose primary outcome is an operational failure / all attempted pairs`. Use the mutually exclusive primary outcome table above; report secondary event flags separately so a pair is counted once in the aggregate rate.
- **Latency:** report median and tail percentiles over all attempted cases, with failures/timeouts shown separately and the timeout threshold stated.

When independent adjudicated dependency evidence exists, report impact-target precision and recall separately: `adjudicated supported emitted targets / all emitted targets` and `adjudicated supported emitted targets / all gold-supported targets`. Match target kind, identifier, dependency citation, and source version to the adjudicated record. Without this evidence/adjudication, report impact quality as `NOT EVALUATED`. Scope, time, and precedence remain unresolved unless explicit domain rules or independent adjudication support them. Proposal status never means approval.

Report numerators, denominators, exclusions, unresolved counts, and rates. Use confidence intervals where supported; because findings cluster by policy family/document lineage, prefer a cluster-aware interval or resampling method at that level. State the method and number of clusters. Do not assume findings are independent without justification. Report adjudication coverage, unresolved cases, inter-adjudicator agreement, and raw disagreement counts. Agreement statistics do not replace adjudication or make ambiguous labels certain.

Candidate count does not prove exhaustive discovery. A model-supplied `coverage_complete` or equivalent flag also does not prove exhaustive discovery. Report finding-level recall against independently adjudicated eligible gold findings. Unknown coverage remains unknown; never convert it into a pass based on counts or flags.

## 5. Provisional thresholds for human review

The following are **provisional recommendations only**, not approved acceptance criteria:

- Zero false acceptance of deliberately malformed or invalid-provenance responses in the targeted security suite.
- At least 0.95 citation-provenance precision and 0.90 citation-provenance recall on the adjudicated set.
- At least 0.90 semantic-support precision; recall must be reported by relation and not optimized by suppressing all proposals.
- For each affirmative relation, provisional precision of at least 0.90, with a separately approved minimum recall and confidence-interval rule.
- At least 0.90 correct abstention recall on cases adjudicated as requiring abstention, while reporting unnecessary abstentions on determinate cases.
- No unresolved critical privacy, authentication, quota, or error-leakage issue before any external request.

Human owners must approve or replace thresholds before evaluation. Freeze thresholds before opening held-out labels/results. Do not tune or re-label after inspecting held-out outcomes; any changed system requires a new or formally retired evaluation set.

## 6. Test protocol

1. Freeze the response schema, prompt/template, model and version, decoding/settings, request limits, validator version, code revision, and intended data-handling configuration. Record non-secret identifiers only.
2. Run deterministic offline regression and malformed-input tests. Keep `FakePolicyCandidateAdapter` as the only executable proposal generator until a separately approved provider implementation exists.
3. Validate dataset records, labels, source hashes, adjudicator process, and partition isolation. Confirm no held-out labels entered prompts, fixtures, or development materials.
4. Obtain separate authorization for provider selection, data transmission, key configuration, costs, and the real-model test. This design phase authorizes none of them.
5. Run only the separately authorized evaluation, with bounded quotas and a predeclared timeout/failure policy. Do not retry automatically when request completion or billing is uncertain.
6. Account for every attempted case, including failures, malformed outputs, missing predictions, abstentions, and timeouts. Preserve sanitized raw outcome categories and locally validated outputs under the approved data-handling plan.
7. Report all partitions separately. Preserve the held-out set for one final evaluation, or explicitly record each reuse and stop describing reused cases as untouched held-out evidence.

## 7. Reporting template

No scores are supplied by this document.

Record non-secret reproducibility identifiers: dataset version/hash, partition-manifest version/hash, annotation-guide version/hash, matching-guide version/hash, matching-procedure version, outcome-precedence version, passage-derivation version, duplicate-screening procedure/version, stable identifier scheme, code revision, schema/validator version, and applicable prompt/model/settings identifiers. Record matching adjudication coverage, disagreements, unresolved edges, held-out-informed change count (target zero), eligible gold-finding denominator, matched finding numerator, and finding recall. Never include credentials, secrets, or sensitive source content in the report.

| Result group | Dataset/version + hash | Partition manifest + hash | Annotation/matching guide versions | Matching procedure / ID scheme | Code/schema/config IDs | Attempted pairs / eligible findings | Matched / eligible findings; recall | Failures / abstentions / extras / duplicates | Metrics, denominators, CI | Adjudication coverage / disagreements / unresolved | Held-out-informed changes | Notes |
|---|---|---|---|---|---|---:|---|---|---|---|---:|---|
| Synthetic unit/regression tests |  |  |  |  |  |  |  |  |  |  |  | Code-contract evidence only |
| Development examples |  |  |  |  |  |  |  |  |  |  |  | Not unbiased quality evidence |
| Validation/threshold setting |  |  |  |  |  |  |  |  |  |  |  | Used for selection/tuning |
| Held-out model evaluation |  |  |  |  |  |  |  |  |  |  |  | Must be zero for independent result |
| Human semantic adjudication |  |  |  |  |  |  |  |  |  |  |  | Include disagreement and coverage |

For each relation, report TP/FP/FN and denominators only where defined; report TN/FPR as `NOT DEFINED` under the open-world finding protocol. Include precision, recall, FNR, confidence intervals, and `NO_PREDICTION/FAILURE` counts. Also report extra, duplicate, missed findings, zero-proposal pairs, valid abstentions, malformed responses, validation rejections, timeouts, provider/runtime failures, and rate limits. Add separate tables for citation provenance, semantic support, adjudication coverage/unresolved pairs and edges, impact (or `NOT EVALUATED`), invalid-output rejection, latency, and other failures. Label each result synthetic, development, validation, held-out, or human-adjudicated; never combine them into one unqualified score.

## 8. Readiness gates

| Gate | Required decision/evidence | Current status |
|---|---|---|
| Dataset creation | Data classification, synthetic-data rules, ownership, annotation guide, adjudicator independence, access/retention plan | Not approved here |
| Held-out evaluation | Frozen partitions, leakage controls, pre-registered metrics/thresholds, label audit, evaluation owner | Not established |
| Provider selection | Current official technical documentation, verified model/output/context behavior, privacy terms, regions, retention/training terms, pricing, contract review | No provider selected or verified |
| Key configuration | Explicit activation decision, approved secret source/access policy, server-side handling, quota/cost owner, preflight, rollback and audit plan | Not authorized |
| External requests | Separate approval for exact data, endpoint, authentication, transport controls, request limits, timeout/retry/billing policy, and test budget | Not authorized |
| Production use | Successful independent evaluation at approved thresholds, domain-owner precedence rules, human workflow, privacy/security review, monitoring, incident response, and change control | Not ready |

## Current implementation context

Source inspection for this protocol used `policy_compare.py` for the five classification labels, pair/citation validation, and explicit semantic-support limitations; `policy_candidate_adapter.py` for the proposal-only candidate contract and fake adapter; `policy_orchestration.py` for fake-only orchestration; `policy_proposal_contract.py` and `POLICY_PROPOSAL_CONTRACT.md` for the provider-neutral request/response shape; and the corresponding policy comparison, candidate adapter, orchestration, and proposal-contract tests for synthetic regression patterns.

The proposal contract is not itself a model integration. The current synthetic tests do not establish independent semantic correctness, held-out performance, provider behavior, or production readiness. Python same-process checks are application safeguards, not a security sandbox.
