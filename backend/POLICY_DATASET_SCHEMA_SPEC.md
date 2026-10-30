# Policy Evaluation Dataset Schema Specification

## Status and scope

**Design specification only — not implemented, tested, or validated by an evaluator.** No dataset version, hash, approval date, owner, or repository revision has been assigned; those values remain TBD.

This specification describes a future offline, synthetic-only policy-comparison evaluation dataset. It does not authorize schema implementation, data creation, evaluator implementation, evaluation, provider selection, key configuration, or external requests. Each requires a separate go/no-go decision.

Approved design decisions reflected here:

1. Keep each policy family and its related versions, pairs, passages, and rules in one partition. Uncertain lineage is not eligible for held-out placement until reviewed.
2. Use two independent reviewers and a third adjudicator where possible; preserve independent and unresolved decisions.
3. Report multiple acceptable labels separately and exclude them from primary single-label metrics.
4. Use synthetic policy text only, held in restricted local storage separate from annotation/report metadata, with retention and deletion approved before data creation. Hashes provide integrity, not anonymization.
5. Impact output and impact-quality evaluation remain NOT_EVALUATED and outside the current proposal contract.
6. Restrict held-out access. Any held-out contamination retires that partition from confirmatory evaluation; replacement data must be independently assembled and lineage-separated.

The current source contract defines the five labels CONTRADICTION, COMPATIBLE_CHANGE, NEW_RULE, SCOPE_OR_TIME_DIFFERENCE, and INCONCLUSIVE. The first four are affirmative relation labels. INCONCLUSIVE is represented by a pair-level decision item. Current proposal output remains proposal-only, semantic support remains unverified, and human review remains required. No impact-output fields are added here.

## 1. Logical record model and relationships

The future dataset is logically hierarchical; physical storage format (for example, normalized tables or versioned records) is TBD and must preserve these keys and references.

Every record has a stable opaque record ID unique within its owning dataset release (and, for run outputs, within the run where stated). References below are typed foreign keys, not free-form labels. Physical serialization and canonical JSON rules remain TBD; implementations must reject dangling, cross-dataset, cross-run, or wrong-type references.

| Entity | Cardinality and key relationships |
|---|---|
| Dataset manifest | One per dataset release; references many partition assignments, families, source documents, examples, annotation guide, and schema version. |
| Policy family / lineage group | Each policy family is assigned to exactly one partition; all its related lineages, versions, pairs, passages, and rules stay there. Every source version and pair also references exactly one lineage. Uncertain lineage blocks held-out assignment. |
| Source document | One document has one or more immutable versions. Document/version IDs are unique within dataset scope. |
| Source version | Belongs to one document and lineage; references immutable source text and locally derived passages. |
| Duplicate relationship | Stable check/relationship IDs link compared source versions and record procedure version, evidence, and human status. |
| Passage | Belongs to exactly one source version; offsets and hashes derive from exact source text. |
| Policy-pair example | References exactly one older and one newer source version from the same document/lineage; may have zero or many affirmative findings and zero or more decision items. |
| Gold finding | Belongs to one pair; references its evidence anchors and one resolved affirmative label or a separately stored multiple-acceptable-label set. |
| Decision item | Belongs to one pair; represents a comparison-level INCONCLUSIVE/abstention assessment, never an affirmative finding. |
| Annotation decision | Stable `annotation_id`; one immutable decision per reviewer and typed target. |
| Adjudication record | Stable `adjudication_id`; links the exact annotation decisions considered and records a final disposition or unresolved outcome. |
| Proposal run | Future-run entity only after separate authorization; one run may attempt many examples and has non-secret configuration identifiers only. |
| Proposal | Belongs to one run and example; candidate ID is distinct from all gold IDs. |
| Match edge/result | Stable edge ID; typed target is exactly one gold finding or pair-level decision item; adjudicated eligible edges and unresolved edges remain separately recorded. |
| Gold claim-citation target | Stable target for one independently adjudicated gold claim/evidence anchor and its required source side; separate from generated citations. |
| Claim-citation assessment | One proposal claim paired with one emitted citation; a claim with multiple citations has multiple assessment records. Provenance and semantic support are separate assessments. |
| Metric/report record | References manifest/run, eligibility rules, denominators, outcomes, and non-secret reproducibility identifiers. Does not duplicate source text. |

## 2. Field-level specification

Unless stated otherwise, exact field type and allowed enumerations are enforced by the future schema validator; unknown fields are rejected. “Denominator” indicates whether a field can determine eligibility or counting, not that it is a score itself. Source text and adjudication rationales are restricted data, not ordinary report content.

### 2.1 Manifest, lineage, and identity

| Field | Type / constraints | Requiredness | Origin and purpose | Metric use | Sensitivity / retention |
|---|---|---|---|---|---|
| schema_version | Exact integer; initially proposed 1 | Required | Administrative; selects record rules | No | Low; retain with dataset. |
| dataset_id, dataset_version | Stable opaque strings; unique within registry | Required | Administrative; identify immutable release | Defines evaluation population | Low; do not embed business details. |
| dataset_hash | SHA-256 of canonical manifest/payload per separately specified canonicalization | Conditional until release frozen | Derived; integrity/version verification | Reproducibility only | Hash does not anonymize source content. |
| partition_manifest_id, partition_manifest_version, partition_manifest_hash | Opaque ID, version string, SHA-256 | Required before partition freeze | Administrative/derived; records assignments and rules | Establishes partition eligibility | Low; manifest access controlled. |
| example_id | Stable opaque ID; unique within dataset | Required | Administrative; identifies one pair | Pair-level outcomes and abstention denominator | Low; no policy content in ID. |
| policy_family_id, lineage_id | Stable opaque IDs; required foreign keys | Required | Administrative/adjudicated grouping | Cluster and partition unit | Low; access restricted. |
| partition | DEVELOPMENT, VALIDATION, HELD_OUT | Required after assignment | Administrative; exactly one partition per lineage | Partition-specific reporting | Held-out assignment and labels restricted. |

### 2.2 Source documents, versions, passages, and pairs

| Field | Type / constraints | Requiredness | Origin and purpose | Metric use | Sensitivity / retention |
|---|---|---|---|---|---|
| document_id, version_id | Stable opaque strings; unique and referentially valid | Required | Synthetic source metadata; distinguishes versions | Citation and pair validation | No employee identifiers. |
| source_ref | Opaque local-storage reference; no arbitrary URL/path | Required | Administrative pointer to immutable source text | Links evidence to source | Restricted; path mapping protected. |
| original_text | Exact immutable UTF-8 content; synthetic only | Required in restricted source store, not duplicated in annotation metadata | Source content | Source for passage/citation derivation | Restricted local access; approved retention/deletion. |
| source_sha256 | Lowercase 64-hex SHA-256 recomputed from exact UTF-8 source | Required | Source-derived integrity value | Provenance verification | Hash is not anonymization. |
| effective_from, effective_to_exclusive | ISO YYYY-MM-DD or null; if both set, start < end | Required | Source metadata/validated pair input | Context only; does not decide precedence | Synthetic metadata. |
| scope.departments, scope.procedures | State KNOWN, UNKNOWN, or ALL; IDs required only for KNOWN; empty IDs otherwise | Required | Source metadata; ALL is explicit wildcard | Scope context; conclusions require adjudication/domain rule | Synthetic identifiers only. |
| scope.property_id | Valid opaque scope ID or null | Required | Source metadata | Scope context only | Synthetic metadata. |
| scope_evidence_refs | Array of source-anchor references | Conditional when scope is asserted known | Source-derived/adjudicated evidence | Scope adjudication only | References, not copied quotes. |
| text_coverage | FULL_DOCUMENT or EXCERPT | Required | Source-provided coverage metadata, independently checked where possible | Eligibility/uncertainty; caller flag alone is not proof | Synthetic metadata. |
| coverage_status | VERIFIED, UNVERIFIED, UNKNOWN, NOT_APPLICABLE plus evidence refs/rationale | Required | Reviewer-adjudicated | May stratify results; unknown never passes as complete | Rationale restricted. |
| passage_id, ordinal, start_cp, end_cp, passage_sha256 | Locally derived stable ID, exact integers excluding booleans, Unicode code-point half-open offsets, SHA-256 | Required per passage | Source-derived; recompute offsets/hash | Citation-provenance denominator | Hash/ID low; source span restricted. |
| passage_derivation_version | Versioned algorithm ID; initially proposed `policy-compare-paragraphs-v1` | Required per source version | Identifies segmentation, trimming, offsets, hashes, and IDs | Reproducibility and citation verification | Low. |
| older_version_ref, newer_version_ref | References to distinct versions of same document and lineage | Required per pair | Source-derived/validated | Defines comparison population | Low. |
| duplicate_group_id | Opaque group ID or null | Conditional when exact/near duplicate relation identified | Reviewer/admin metadata | Partition leakage checks | Low. |
| duplicate_check_id, duplicate_procedure_version, compared_version_refs, duplicate_status, evidence_refs | Stable check ID; versioned method; exact source-version refs; CONFIRMED_DUPLICATE, NOT_DUPLICATE, UNRESOLVED; hashes and method-specific evidence | Required for each screened relationship | Deterministic screen plus independent adjudication | Partition leakage checks | Low IDs/hashes; source-linked evidence restricted. |
| lineage_status | CONFIRMED, UNCERTAIN, EXCLUDED | Required before held-out assignment | Human-adjudicated/admin | Partition eligibility | Uncertain is ineligible for held-out. |

### 2.3 Gold findings, decision items, and annotations

| Field | Type / constraints | Requiredness | Origin and purpose | Metric use | Sensitivity / retention |
|---|---|---|---|---|---|
| finding_id | Stable opaque ID unique within dataset | Required per affirmative finding | Administrative; never a proposal ID | Matching and finding denominator | Low. |
| gold_relation | Exactly one of four affirmative labels | Required only for resolved single-label finding | Independently adjudicated | Primary per-class metrics | Restricted annotation. |
| acceptable_relations | Non-empty unique subset of four affirmative labels | Conditional for genuine ambiguity; stored separately from gold_relation | Adjudicated before model outputs | Separate acceptable-set accuracy; excluded from primary single-label metrics | Restricted annotation. |
| finding_status | RESOLVED, MULTIPLE_ACCEPTABLE, UNRESOLVED, MISSING_LABEL | Required | Adjudicated | Eligibility; unresolved/missing never count correct | Restricted. |
| evidence_refs | One or more version/passage IDs and code-point spans; must resolve to exact source | Required for affirmative finding | Source-derived and adjudicated | Evidence and claim matching | Do not copy quotes into reports. |
| uncertainty_reasons | Unique values from versioned approved annotation vocabulary | Required when applicable; empty only if guide permits | Reviewer-adjudicated | Stratification/abstention analysis | Rationale restricted. |
| decision_id | Stable opaque ID | Required per pair-level inconclusive decision | Administrative | Decision-item denominators | Low. |
| abstention_status | REQUIRED, ALLOWED, INCORRECT, UNRESOLVED | Required per decision item | Independently adjudicated | Abstention precision/recall | Restricted rationale. |
| annotation_id, review_cycle_id, decision_revision, decision_type, target_type, target_id | Opaque stable IDs; exact non-boolean integer revision; target type and ID resolve to one allowed record kind | Required per annotation decision | Reviewer-authored/administrative | Agreement, adjudication coverage | Reviewer identity mapping restricted. |
| supersedes_annotation_id | Prior annotation ID or null | Required | Correction history; prior decisions remain immutable | Reproducibility | Restricted. |
| annotation_value | Decision-type-specific enum/set; `UNRESOLVED` where applicable | Required per submitted decision | Independent reviewer | Label eligibility and disagreement | Restricted. |
| review_coverage_id, expected reviewer/target/decision refs, coverage_status | Stable ID and typed refs; COMPLETE, MISSING, EXCUSED | Required for every assigned reviewer-target-decision slot | Review coordinator | Reviewer coverage and missingness | Reviewer identity mapping restricted. |
| reviewer_id | Pseudonymous reviewer code, not a name | Required per decision | Administrative | Agreement and coverage reporting | Restricted identity mapping. |
| evidence_refs, rationale | Source references and bounded text; required when the guide requires justification | Conditional per decision type/status | Reviewer-authored | Eligibility/adjudication | Rationale may reveal policy content; restrict and redact. |
| adjudication_id, annotation_ids, adjudicator_id, adjudication_status, final_disposition | Stable ID, exact linked annotation IDs, opaque adjudicator ID, ADJUDICATED/UNRESOLVED/MISSING, typed disposition | Required when an adjudication record exists | Adjudicator/workflow | Final labels and disagreement reporting | Restricted. |
| adjudication_rationale | Bounded text with evidence refs | Conditional for adjudicated/unresolved outcome | Adjudicator-authored | Audit trail only | Restricted; not in ordinary reports. |
| eligible_by_metric | Map of metric ID to ELIGIBLE, EXCLUDED, UNRESOLVED, NOT_APPLICABLE plus reason | Required before scoring | Pre-registered/admin | Defines denominators | Reason may be sensitive. |

#### Annotation decision and adjudication record rules

`annotation_id`, `adjudication_id`, and `review_coverage_id` are opaque IDs unique within the dataset release. An annotation decision has exactly one `target_type` and matching target foreign key: `GOLD_FINDING`/`finding_id`, `DECISION_ITEM`/`decision_id`, `MATCH_EDGE`/`match_edge_id`, `GOLD_CLAIM_CITATION_TARGET`/`gold_target_id`, or `CLAIM_CITATION_ASSESSMENT`/`citation_assessment_id`. Exactly one target key is populated; all others are prohibited. The target must exist in the same dataset and, for proposal-derived targets, the same run/example. A reviewer ID is an opaque pseudonym with a separately protected identity mapping; it is not a name or employee identifier.

The reviewer-level uniqueness key is `(review_cycle_id, reviewer_id, target_type, target_id, decision_type, decision_revision)`, with one active latest revision per slot. A correction has a higher revision and references the prior `annotation_id` through `supersedes_annotation_id`; history is immutable. The exact `decision_type` set is `GOLD_LABEL`, `ABSTENTION`, `MATCH_EDGE`, `CITATION_PROVENANCE`, `SEMANTIC_SUPPORT`, `SCOPE_TIME`, and `PRECEDENCE`. Values are typed by decision type: `GOLD_LABEL` uses one affirmative label, a pre-adjudicated acceptable-label set, or `UNRESOLVED`; `ABSTENTION` uses `REQUIRED`, `ALLOWED`, `INCORRECT`, or `UNRESOLVED`; `MATCH_EDGE` uses `MATCH`, `NO_MATCH`, or `UNRESOLVED`; `CITATION_PROVENANCE` uses `VALID`, `INVALID`, or `UNRESOLVED`; `SEMANTIC_SUPPORT` uses `SUPPORTED`, `UNSUPPORTED`, `IRRELEVANT`, or `UNRESOLVED`. `SCOPE_TIME` and `PRECEDENCE` use only a separately versioned annotation-guide vocabulary and do not establish runtime behavior. Missing reviewer decisions are not reviewer annotations: a `review_coverage` record marks the assigned slot `MISSING` or `EXCUSED`, and no judgment is inferred.

An adjudication record includes `adjudication_id`, review-cycle and typed target references, `adjudicator_id` (opaque pseudonym), a non-empty set of distinct `annotation_ids` it considered, `adjudication_status` (`ADJUDICATED`, `UNRESOLVED`, `MISSING`), and a final disposition using the applicable decision-type vocabulary. Every linked annotation must target the same object and decision type. `ADJUDICATED` requires a final disposition and rationale/evidence references; `UNRESOLVED` or `MISSING` cannot carry a resolved final label. A third reviewer is used only when available and authorized; disagreement without adjudication, or an inconclusive adjudication, remains unresolved and is not scored as correct. Missing reviewer decisions are recorded as missing coverage, never synthesized from another reviewer or silently treated as agreement.

### 2.4 Future proposal run and output (not populated in this phase)

| Field | Type / constraints | Requiredness | Origin and purpose | Metric use | Sensitivity / retention |
|---|---|---|---|---|---|
| run_id | Opaque unique ID | Required only for separately authorized future run | Run-generated | Groups attempts | Low. |
| outcome_precedence_version | Versioned ID for the protocol decision order | Required per run | Protocol/admin | Reproducible primary outcome assignment | Low. |
| code_revision, schema_version, prompt_id/version, model_id/version, settings_id, config_id | Non-secret identifiers only; unknown values TBD, never guessed | Required for authorized run where applicable | Run/admin metadata | Reproducibility | No credentials or source text in settings fields. |
| run_outcome | Exactly one primary outcome: EMPTY_CANDIDATE_SET, RESPONSE_ACCEPTED_WITH_CANDIDATES, MALFORMED_RESPONSE, VALIDATION_REJECTION, TIMEOUT, RATE_LIMIT, PROVIDER_OR_RUNTIME_FAILURE | Required per attempted pair | Run-generated | Operational metrics, not relation metrics | Sanitized; no raw exception/provider text. |
| secondary_event_flags | Approved enum list | Optional | Run-generated | Failure breakdown | No raw diagnostics. |
| proposal_id | Stable unique candidate ID within run/example; never reused as finding_id | Required per candidate | Run-generated then locally validated | Matching/proposal counts | Low. |
| proposed_relation | One of five existing labels | Required per accepted proposal | Untrusted output, validated locally | Relation metrics | Always proposal-only. |
| reasoning_ref | Reference to restricted proposal text or bounded content in restricted storage | Required per accepted proposal | Generator output | Blinded match adjudication | Restricted; avoid reports/logs. |
| citation_refs | Declared side and source hint; normalized fields only after local validation | Required under current candidate rules; may be empty for valid abstention | Generator hints plus locally derived canonical fields | Provenance and semantic-support metrics | Restricted source-linked data. |
| uncertainty_reasons | Approved contract enum list | Required under current candidate contract | Generator output, validated | Uncertainty analysis | Low. |
| abstain | Exact boolean; true only with INCONCLUSIVE per current contract | Required | Generator output, validated | Abstention analysis | Low. |
| proposal_status | Literal PROPOSAL_ONLY | Required on normalized output | Locally trusted | Never means approval | Low. |
| semantic_support | Literal NOT_VERIFIED in current normalized output | Required | Locally trusted | Not model-derived evidence | Low. |
| human_review_required | Literal true | Required | Locally trusted | Human-review gate | Low. |
| impact_output | Not defined and prohibited by this specification | Not allowed under current contract | Requires separately reviewed contract | Impact remains NOT_EVALUATED | Future addition requires separate approval. |

For the current candidate validator, the uncertainty enum is `semantic_support_unverified`, `precedence_unverified`, `coverage_unverified`, `scope_or_time_unverified`, `missing_evidence`, and `unsupported_claim`; candidate IDs are unique within a response. Accepted outputs are locally normalized. This source-aligned list does not require future annotation vocabularies to be identical.

### 2.5 Matching edges and citation assessments

| Field | Type / constraints | Requiredness | Origin and purpose | Metric use | Sensitivity / retention |
|---|---|---|---|---|---|
| matching_guide_version/hash | Version and content SHA-256 | Required before match adjudication | Administrative | Reproducibility | Low. |
| matching_procedure_version | Versioned procedure ID | Required before matching | Administrative | Reproduces one-to-one mapping | Low. |
| match_edge_id | Opaque unique ID within run/example | Required per proposal-target edge | Run/admin | Matching graph | Low. |
| proposal_id, target_type, finding_id, decision_id | Valid same-run proposal FK and exactly one target type/FK pair: `AFFIRMATIVE_FINDING` requires `finding_id` only; `ABSTENTION_DECISION` requires `decision_id` only | Required per edge | Run/admin | Matching | Low. |
| match_status | MATCH, NO_MATCH, UNRESOLVED, MISSING | Required per edge adjudication | Independent reviewers/adjudicator | Eligible edge set | Rationale restricted. |
| match_evidence_refs, match_rationale | Source anchors and bounded text | Required for MATCH; rationale for disagreement/unresolved | Reviewer-adjudicated | Audits identity matching | Restricted. |
| matching_result | Matched edges, unmatched eligible findings and decision items, extra proposals, duplicate proposals, unresolved edges | Required after matching | Derived from adjudicated graph | TP/FP/FN and finding/decision recall | IDs only; no source text. |
| gold_target_id | Opaque stable ID unique within dataset | Required per gold claim-citation target | Gold annotation/admin | Citation/semantic-support recall denominators | Restricted references only. |
| target_type, finding_id, decision_id | `AFFIRMATIVE_FINDING` with `finding_id` only, or `PAIR_DECISION` with `decision_id` only | Required per gold target | Gold annotation/admin | Links target to its comparison claim | Restricted. |
| claim_ref, required_side, source_anchor | Stable claim reference, OLDER/NEWER, exact same-dataset version/passage/code-point span | Required when a source claim/evidence target exists | Independently adjudicated | Required-citation comparison | Source-linked; no report quote. |
| citation_required | Exact boolean | Required | Independently adjudicated | Citation recall eligibility | Low. |
| citation_metric_eligibility, semantic_metric_eligibility | ELIGIBLE, EXCLUDED, UNRESOLVED, NOT_APPLICABLE with reason per metric | Required before scoring | Pre-registered/adjudicated | Explicit recall denominators | Restricted reasons. |
| gold_support_status | SUPPORTED, UNSUPPORTED, IRRELEVANT, UNRESOLVED, MISSING, NOT_APPLICABLE | Required per target | Independent adjudication | Gold semantic-support recall denominator | Restricted rationale. |
| citation_assessment_id | Stable opaque ID | Required per claim-citation pair | Administrative | Pair-level assessment key | Low. |
| claim_ref, proposal_id, citation_ref | Valid references | Required | Run-generated/admin | Ensures every emitted pair is counted | Low. |
| gold_target_match_status, gold_target_id | MATCH, NO_MATCH, UNRESOLVED, MISSING; gold_target_id required only for MATCH and must resolve in the same example | Required per emitted pair | Independent blinded adjudication | Connects emitted pair to gold recall unit | Restricted references. |
| declared_side | OLDER or NEWER | Required | Generator hint, checked locally | Gold-evidence alignment | Low. |
| provenance_status | VALID, INVALID, UNRESOLVED | Required | Mechanical local validation | Provenance metrics | Low. |
| provenance_reason | Approved status/error enum; no raw exception | Required when not VALID | Validator-generated | Error categories | Low. |
| semantic_support_status | SUPPORTED, UNSUPPORTED, IRRELEVANT, UNRESOLVED; PENDING only before adjudication freeze | Required per emitted pair | Independent adjudication | Semantic metrics and coverage | Rationale restricted. |
| semantic_support_rationale, support_evidence_refs | Bounded text and source refs | Required for completed judgment | Reviewer-adjudicated | Auditability, not automated truth | Restricted. |
| adjudication_coverage | Derived numerator, denominator, unresolved count | Required in reports | Derived | Prevents incomplete support data appearing complete | No source content. |

Gold claim-citation targets are not generated citations. Each target links to exactly one affirmative finding or pair-level decision item, an adjudicated claim reference, and—when evidence is applicable—a required side and exact source anchor. If no citation is required, `citation_required` is false and the target is ineligible for citation recall. A required target is eligible only if its label and anchor are resolved and mechanically resolvable; unresolved, missing, excluded, and ineligible targets remain separately counted and reported. Semantic-support recall uses eligible gold targets independently adjudicated `SUPPORTED` as its denominator. Emitted claim-citation assessments link to a gold target only when adjudicators establish that relationship; absence of a link is not evidence that a target did not exist. Missing emitted citations are misses against eligible gold targets, never omitted rows in coverage reports.

#### Match target and one-to-one rules

`target_type` is exactly `AFFIRMATIVE_FINDING` or `ABSTENTION_DECISION`. An `AFFIRMATIVE_FINDING` edge requires an affirmative proposal relation and exactly one eligible `finding_id`; `decision_id` is prohibited. An `ABSTENTION_DECISION` edge requires an `INCONCLUSIVE` proposal and exactly one eligible pair-level `decision_id`; `finding_id` is prohibited. The proposal and target must belong to the same example and dataset, and the proposal to the same run. Edges with incompatible relation/target types are invalid. Only adjudicated `MATCH` edges enter matching; `NO_MATCH`, `UNRESOLVED`, and `MISSING` edges receive no credit, with unresolved/missing counts reported. Apply maximum-cardinality one-to-one matching separately within each example and target type, then lexicographically smallest sorted edge list among ties as specified in the protocol. Each proposal and each eligible gold finding or decision item can receive credit at most once. Unmatched eligible findings/decision items are misses; unmatched proposals, including duplicates, are extras. A missing proposal set is represented by the run outcome, not by fabricated edge records.

#### Citation assessment coverage

There is one citation-assessment record for each emitted claim-citation pair, keyed by `(run_id, proposal_id, claim_ref, citation_ref)`. `citation_ref` identifies exactly one citation emitted by that proposal. Provenance is mechanically derived from the local validator; semantic support is independently adjudicated. Gold targets remain separate. Blinded target matching records `MATCH`, `NO_MATCH`, `UNRESOLVED`, or `MISSING`; match adjudicators do not see provenance or semantic-support outcomes when deciding whether the claim refers to a gold target. Only adjudicated `MATCH` links a single emitted pair to one gold target for recall credit, and a gold target can receive credit at most once. Unresolved or missing mappings receive no credit and remain reported. Report counts for emitted pairs, completed adjudications, unresolved/missing adjudications, gold targets eligible for citation recall, gold targets eligible for semantic recall, missing emitted citations, and excluded/ineligible targets. No unresolved or missing status is dropped from a coverage denominator without an explicit, pre-registered metric rule.

For the present candidate contract, each accepted candidate represents one proposal claim using its `proposed_relation` and `reasoning`; `claim_ref` is an evaluation-only opaque ID assigned locally to that claim and is not a new adapter response field. Multiple claims per candidate would require a separately reviewed schema change.

#### Duplicate and near-duplicate lineage procedure

Exact duplicate content is detected by equality of the SHA-256 hashes of exact original UTF-8 bytes. No normalization is applied for this check. If a future normalization-based check is approved, it must define a deterministic normalization algorithm and version before use; until then normalized equality is `NOT_EVALUATED` and cannot override exact-byte provenance.

Near-duplicate screening is versioned and deterministic, but the screening tool/algorithm, parameters, threshold, and candidate-review sampling are **TBD** and require human approval before dataset creation or partition freeze. Do not invent a similarity threshold. Record `duplicate_check_id`, procedure/version, compared source-version IDs and exact hashes, normalized hashes only if the approved method defines them, score and method-specific evidence (for example, matched spans), reviewer decisions, and rationale. A relationship status is exactly `CONFIRMED_DUPLICATE`, `NOT_DUPLICATE`, or `UNRESOLVED`. Borderline cases require human adjudication; absent or inconclusive review remains `UNRESOLVED`.

Every confirmed duplicate relationship joins the involved source versions and their policy families into one duplicate/lineage group for partitioning. A confirmed group cannot span partitions. An unresolved relationship across proposed partitions blocks held-out assignment of all involved families until reviewed. If held-out labels or outcomes are exposed or otherwise inform a change, retire the affected held-out partition from confirmatory use; replacements must be independently assembled and lineage-separated, consistent with the evaluation protocol.

#### Passage derivation algorithm

The proposed algorithm identifier is `policy-compare-paragraphs-v1`, corresponding to the current `policy_compare._passages` implementation. It is not a claim that the runtime source currently stores this version field. The algorithm is:

1. Preserve the source string exactly; do not normalize Unicode or rewrite newline characters.
2. Find separators matching one or more blank-line boundaries: a line break (`CRLF`, `CR`, or `LF`), optional horizontal spaces/tabs, then one or more further line breaks each followed by optional horizontal spaces/tabs. Split at those separators while retaining source-relative offsets.
3. For each resulting span, trim leading and trailing characters for which Python `str.isspace()` is true. Do not alter internal characters. Omit spans that become empty. Assign one-based ordinal values in emitted passage order.
4. Offsets are Python Unicode code-point indices into the unchanged source string; use half-open `[start_cp, end_cp)` boundaries. CRLF remains two code points in source offsets.
5. Compute `passage_sha256` as lowercase SHA-256 over the strict UTF-8 encoding of the trimmed passage text.
6. Construct `passage_id` as `p` + the six-digit zero-padded ordinal + `-` + the first 16 lowercase hexadecimal characters of the passage hash.
7. Enforce the source implementation's maximum of 1,000 emitted passages; exceeding it is invalid input.

Any change to segmentation, whitespace trimming, encoding/hash input, offset units, ordinal assignment, passage ID format, or limits requires a new algorithm version. Store that version per source version and in reproducibility manifests; validators must recompute under the recorded version. The current behavior is evidenced by `policy_compare.py::_passages`; the proposed identifier and schema field are documentation design decisions pending implementation review.

## 3. Validation and metric semantics

- Enforce exact primitive types and enums; booleans are not integers. Reject unknown fields, duplicate IDs, dangling references, duplicate final matches, invalid offsets, and source/hash mismatches.
- Recompute source hashes, passages, IDs, and code-point offsets from immutable source text using the recorded passage_derivation_version. Stored derived values are checks, not authority.
- Assign one partition per lineage. Uncertain lineage or duplicate relationships are excluded from held-out pending review; linked content cannot cross partitions.
- Keep one resolved affirmative gold_relation per primary single-label finding. Store multiple acceptable labels separately and exclude them from primary single-label metrics. UNRESOLVED and MISSING_LABEL are reported and never counted correct.
- Keep pair-level decision_items separate from affirmative findings. An INCONCLUSIVE proposal matches only a decision item. A valid abstention is correct only when adjudication says REQUIRED.
- Use the versioned matching guide and deterministic maximum-cardinality, lexicographically tie-broken matching in the protocol. Unresolved edges receive no credit and are reported separately.
- Candidate count and model-supplied completeness flags do not prove coverage. Finding recall is matched eligible gold findings divided by eligible gold findings. Unknown coverage remains unknown.
- Validate citation provenance mechanically against exact source side/version/hash/passage/offset/quote. Adjudicate semantic support separately. Every emitted claim-citation pair remains in coverage; unresolved pairs are not silently removed or described as complete.
- Count accepted wrong labels, unmatched proposals, duplicates, unmatched findings, and operational failures under the protocol rules. Operational outcomes are never relation labels. For zero denominators report N/A; under the open finding universe, TN/FPR are NOT_DEFINED rather than fabricated.
- Assign each attempted pair exactly one primary run outcome using the frozen outcome_precedence_version; retain co-occurring events as secondary flags.
- Preserve the protocol's thresholds as provisional recommendations only. This specification computes no metric.

## 4. Privacy, retention, and held-out governance

- Synthetic source text only. No employee records or real confidential policy text.
- Store source text separately from labels, match records, and reports in restricted local storage. Storage location, access roles, encryption details, retention period, and deletion process are TBD and require human approval before dataset creation.
- Logs and ordinary reports contain no source text, quotes, reviewer names, credentials, secrets, raw provider errors, or sensitive rationale. Use opaque IDs and non-secret version/configuration identifiers.
- Hashes support integrity and reproducibility; they do not anonymize source text or prove content is non-sensitive.
- Restrict held-out labels and outcomes to approved evaluation roles. They must never guide prompt, example, schema, matching-rule, threshold, code, or model-setting changes. Record held-out-informed change count; target zero. Any contamination retires the partition from confirmatory evaluation. Replacement data is independently assembled and lineage-separated.
- Keep the dataset workflow separate from the employee handover application and its persistence.

## 5. Reproducibility fields

Before any future evaluation, record (with TBD until assigned): dataset/schema version; dataset and manifest hashes; partition-manifest version/hash; source version/hash; passage-derivation version; duplicate-screening procedure/version and parameters; family/lineage ID scheme; annotation-guide version/hash; matching-guide version/hash; matching-procedure version; outcome-precedence version; code revision; validator version; run ID; non-secret prompt/model/settings/config identifiers; metric definitions and eligibility-rule version; and held-out-informed change count.

Do not invent revisions, hashes, owners, approval dates, dataset IDs, or model identifiers. Do not include secrets, source text, or sensitive quotations in ordinary reports.

## 6. Separate future go/no-go gates

Each step requires its own explicit authorization; this specification authorizes none of them.

1. Implement the schema validator and manifest model.
2. Create synthetic policy text and annotation records after privacy, storage, retention, and lineage approval.
3. Freeze partitions, annotation decisions, and gold labels after adjudication and leakage review.
4. Implement the offline evaluator against the frozen protocol and this schema.
5. Run the offline synthetic evaluation after separate review of dataset integrity, denominator behavior, and reporting.
6. Consider any provider/model evaluation only after distinct provider, data-handling, budget, credential, and external-request approvals. Preserve the fake-only generation default until separately authorized implementation.

## Source-contract alignment

policy_compare.Classification supplies exactly the five relation labels listed above. policy_candidate_adapter.validate_candidate_response accepts proposal candidates with relation, reasoning, citations, uncertainty reasons, and abstention; normalized output is PROPOSAL_ONLY, NOT_VERIFIED, and human-review-required. Citation provenance validation does not establish semantic support. This document is metadata/evaluation design only: it does not extend runtime fields, introduce impact output, or create an evaluator.
