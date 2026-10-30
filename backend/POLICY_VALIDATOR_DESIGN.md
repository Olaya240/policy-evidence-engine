# Policy Dataset Validator Design Blueprint

## Status and scope

**Design only.** This document proposes a format-independent validation architecture for a future policy-comparison evaluation dataset. It does not implement or authorize a validator, dataset creation, evaluation, provider selection, key configuration, or external requests. Each operational step requires separate approval.

The validator's role is to check the structure and recorded provenance of supplied logical records. It cannot establish policy truth, semantic support, precedence, exhaustive finding coverage, model quality, or organizational approval. It is not a security sandbox, and it cannot prove that external access controls, encryption, or deletion are effective.

The current runtime contract remains unchanged:

- The five relation labels are `CONTRADICTION`, `COMPATIBLE_CHANGE`, `NEW_RULE`, `SCOPE_OR_TIME_DIFFERENCE`, and `INCONCLUSIVE`. The first four are affirmative; `INCONCLUSIVE` is a pair-level decision item.
- Accepted proposal output remains `PROPOSAL_ONLY`, with semantic support `NOT_VERIFIED` and `human_review_required: true`.
- Impact remains `NOT_EVALUATED`, outside the current response contract.
- `FakePolicyCandidateAdapter` remains the only executable proposal-generation path; this design adds no runtime/provider path.
- The workflow remains separate from the employee handover application.

## 1. Conceptual interfaces

These are logical interfaces, not Python APIs or a selected storage format.

### Logical dataset manifest input

The validator receives a manifest containing a dataset identity/version, schema version, typed references to all record collections, partition assignments, source/lineage identity, applicable guide and algorithm versions, and any required approval references. Dataset and partition hashes are checked only when their canonicalization rules have been approved and supplied. The manifest must not contain credentials or source text duplicated from the restricted source store.

### Typed record collections

The logical input includes the record types and relationships in `POLICY_DATASET_SCHEMA_SPEC.md`: source documents and versions, passages, policy-pair examples, lineages and partitions, gold findings, pair-level decision items, duplicate checks, reviewer assignments/coverage, annotation decisions, adjudications, future proposal runs and proposals (only for an authorized evaluation), match edges/results, gold claim-citation targets, emitted claim-citation assessments, and metric/report records.

Every reference is typed and scoped to the owning dataset, example, and run as applicable. The validator rejects dangling or cross-scope references; it does not repair records or infer missing ones.

### Validation context

The context supplies the approved schema/compatibility version, annotation-guide version, matching-guide/procedure version, eligibility-rule version, passage-derivation version, duplicate-screening procedure version where applicable, and run outcome-precedence version. Each must resolve to an explicitly supplied approved definition. This design assigns no final versions or hashes.

Canonicalization is intentionally absent from the active context until approved. If a requested check depends on unresolved canonicalization, the validator reports a governance blocker and does not report the manifest hash as verified.

### Structured validation report

The report contains:

- Overall state: `STRUCTURALLY_VALID`, `STRUCTURALLY_INVALID`, or `BLOCKED_BY_UNRESOLVED_PREREQUISITE`.
- Stable diagnostic codes, severity, and references to affected record IDs; no source text, quotes, secrets, or raw exception messages.
- Separate counts of errors, warnings, unresolved human-review items, governance blockers, and records checked.
- Per-layer state and checks performed, skipped, or blocked with reason.
- Reproducibility identifiers actually supplied and verified; absent values are explicitly missing, never invented.

Warnings and unresolved items never silently count as successful validation. A report can be structurally valid while governance remains unapproved; those are distinct states.

## 2. Validation layers

Each layer has logical inputs, deterministic checks, output, and prerequisites. A layer can be designed before it is authorized for implementation.

| Layer | Inputs | Deterministic checks | Output | Prerequisites / implementation gate |
|---|---|---|---|
| 1. Record shape and exact types | Each record plus schema version | Required/optional/unknown fields; exact primitive types; enum membership; bounds; booleans not integers; approved nullability. | Record-level diagnostics and shape status. | Schema/version freeze (ND-16); annotation vocabularies for annotation-specific records (ND-12–15). |
| 2. IDs and typed references | IDs, target types, and reference fields | ID uniqueness in declared namespace; syntax where frozen; exactly one permitted target key; prohibited target keys absent; reference scope matches dataset/example/run. | ID/reference index and typed-reference diagnostics. | ID/version policy (ND-16); logical record schema approval. |
| 3. Referential integrity and cardinality | All record collections | Every FK resolves; source version belongs to one document/lineage; pair versions are distinct versions of the same document/lineage; findings/decision items belong to one pair; proposals belong to a run/example; annotation/adjudication links are consistent. | Relationship/cardinality status and dangling-reference diagnostics. | Logical schema approval and physical decoder if validating persisted files (ND-05, ND-16). |
| 4. Annotation and adjudication | Reviewer coverage, decisions, revisions, adjudications | Reviewer-target uniqueness; revision/supersession chain; typed values; adjudications link distinct decisions for the same target/type; final disposition consistent with adjudication status; missing reviewers and unresolved disagreement remain visible. | Per-target decision coverage, adjudicated disposition, and unresolved/missing counts. | Approved guide vocabularies and adjudication rules (ND-12–16, ND-18). |
| 5. Findings vs pair-level decisions | Gold findings, decision items, labels | Affirmative findings use only four affirmative labels; decision items are pair-level and use abstention states; `INCONCLUSIVE` proposals cannot be matched to affirmative findings; no decision item is counted as an affirmative finding. | Separate finding and decision-item eligibility populations. | Relation vocabulary is fixed (ND-11); decision criteria depend on guide approval (ND-15). |
| 6. Proposal-to-target matching | Proposal records and adjudicated match edges | Affirmative proposals target findings; `INCONCLUSIVE` proposals target decision items; target key exclusivity; one-to-one credit; deterministic maximum-cardinality/tie-breaking; unresolved or missing edges do not earn credit; unmatched targets/proposals remain reportable. | Matching result, credited edges, misses, extras, and unresolved edges. | Matching procedure is in the protocol; freeze matching guide/version (ND-16). No semantic validity is inferred. |
| 7. Gold citation targets vs emitted assessments | Gold target anchors, emitted citations, local provenance result, independent assessment | Gold targets are separate from emitted citations; required-side/source anchor references resolve; one emitted pair maps to at most one gold target for recall credit; provenance and semantic support remain distinct; all emitted pairs and unresolved/missing mappings appear in coverage. | Provenance/semantic-support coverage and recall-eligibility counts, kept separate. | Annotation and matching guide (ND-15–16); passage algorithm version. Semantic support remains human-adjudicated. |
| 8. Metric eligibility and denominators | Gold records, targets, assignments, matching, outcomes | Recompute counts from eligible records; enforce pre-registered exclusions; zero denominator is `N/A`; unresolved/missing and excluded counts are explicit; no fabricated TN/FPR; run failures are not relation labels. | Per-metric numerator, denominator, exclusions, `N/A`, and unresolved counts. | Frozen eligibility/annotation rules and protocol versions (ND-15–16); canonical output only if metrics/report hashes are required (ND-06–07). |
| 9. Partition, lineage, duplicate records | Family/lineage graph, duplicate-check results, partition manifest | One partition per lineage and confirmed duplicate group; source versions/pairs inherit correct lineage; unresolved cross-partition duplicate relation blocks held-out eligibility; contaminated held-out partition is marked retired. | Partition consistency status and held-out blockers/retirement markers. | Approved screening records and adjudication (ND-01–04); partition governance/access (ND-18). Validator checks the manifest; it does not discover all duplicates. |
| 10. Reproducibility and hashes | Source text, passages, manifests, algorithm/config IDs | Recompute source and passage hashes from exact bytes; verify offsets/IDs under recorded passage version; check required version IDs; manifest hash only under approved canonicalization; outcome category under frozen precedence. | Verified/missing version and hash attestations with per-record diagnostics. | Passage algorithm is documented as proposed; canonicalization/order unresolved (ND-05–07); instance hashes require frozen inputs (ND-17). |
| 11. Privacy and held-out governance metadata | Approval references, storage/retention policy IDs, partition access metadata, report fields | Check presence, shape, linkage, and allowed values of required governance metadata; report allowlist excludes source fields and secrets by schema. | Governance metadata presence report and blockers; no assurance of operational enforcement. | Policies/approvals (ND-08–10, ND-18); held-out access decision. Presence is not proof of authenticity or enforcement. |

The validator checks recorded facts against supplied inputs and approved rules. It cannot prove that gold findings are exhaustive, that semantic-support labels are correct, that a duplicate screening method found every near-duplicate, or that a human approval is genuine.

## 3. Stable error and warning taxonomy

Diagnostics use fixed codes and safe record IDs only. No values from source text, rationales, provider errors, or exceptions are copied into messages.

| Code | Severity / class | Meaning and disposition |
|---|---|---|
| `MISSING_FIELD`, `UNKNOWN_FIELD` | ERROR / structural failure | Record shape violates the frozen schema; record is invalid. |
| `WRONG_TYPE`, `INVALID_ENUM`, `INVALID_VALUE` | ERROR / structural failure | Exact type, enum, bound, or invariant fails. |
| `DUPLICATE_ID` | ERROR / structural failure | Two records collide in a required ID namespace. |
| `REFERENCE_MISSING`, `REFERENCE_SCOPE_MISMATCH` | ERROR / structural failure | A typed reference is dangling or crosses an invalid dataset/example/run boundary. |
| `TARGET_REFERENCE_CONFLICT` | ERROR / structural failure | Mutually exclusive typed target fields are missing, multiple, or incompatible with record type. |
| `CARDINALITY_VIOLATION`, `MATCH_CARDINALITY_VIOLATION` | ERROR / structural failure | Record ownership or one-to-one matching constraints fail. |
| `ANNOTATION_MISSING`, `ADJUDICATION_UNRESOLVED` | WARNING / human-review requirement | Reviewer coverage is missing or a disagreement remains unresolved; never counted as resolved/correct. |
| `ELIGIBILITY_INCONSISTENT`, `DENOMINATOR_INCONSISTENT` | ERROR / structural failure | Metric eligibility or derived denominator disagrees with source records/rules. |
| `DUPLICATE_RELATION_UNRESOLVED` | BLOCKER / governance and partition gate | Unresolved duplicate relationship affects proposed partition separation; held-out assignment cannot pass. |
| `VERSION_MISSING`, `VERSION_MISMATCH` | ERROR or BLOCKER by dependency | Required version absent/mismatched; structural error if frozen, blocker if governing definition remains unapproved. |
| `HASH_MISMATCH` | ERROR / structural failure | Recomputed hash differs under a specified hash rule. |
| `CANONICALIZATION_UNAVAILABLE` | BLOCKER / reproducibility gate | Manifest hash cannot be verified because canonicalization is unresolved or unavailable. |
| `APPROVAL_EVIDENCE_MISSING` | BLOCKER / governance gate | Required approval reference is absent; validator does not grant approval. |
| `PRIVACY_CONTROL_UNVERIFIED` | WARNING or BLOCKER per gate | Metadata is recorded, but actual access, encryption, retention, or deletion enforcement cannot be established by the validator. |
| `COVERAGE_UNVERIFIED`, `SEMANTIC_SUPPORT_UNVERIFIED` | WARNING / human-review requirement | Recorded metadata or source provenance does not establish completeness or semantic support. |

Severity precedence for the report is: any structural error makes the dataset `STRUCTURALLY_INVALID`; otherwise unresolved prerequisites yield `BLOCKED_BY_UNRESOLVED_PREREQUISITE`; otherwise all performed structural checks may yield `STRUCTURALLY_VALID`. Governance warnings/blockers remain separately visible and cannot be collapsed into structural success.

## 4. Determinism and reproducibility gates

Deterministic validation can be claimed only for checks whose governing inputs are frozen and identified. Required records include:

- Approved schema and compatibility version.
- Annotation-guide and matching-guide versions/hashes; matching procedure and eligibility-rule versions.
- Passage-derivation version. The current source implementation is documented as `policy-compare-paragraphs-v1`; the schema field is proposed, not implemented.
- Duplicate-screening procedure/version and parameters when that screening is used.
- Manifest canonicalization, stable collection ordering, encoding, exact hash input, and hash algorithm.
- Outcome-precedence version (`outcome-precedence-v1` in the protocol).
- Non-secret run configuration, code, validator, prompt/model/settings identifiers when a separately authorized run exists.

Do not generate or claim dataset, partition, source, or release hashes until the exact input bytes and applicable hash rules are frozen. The source hash is defined over exact UTF-8 text; this does not settle canonicalization of dataset manifests. An unavailable canonicalization yields `CANONICALIZATION_UNAVAILABLE`, not a guessed digest.

## 5. Duplicate-screening boundary

**PROPOSED, not approved:** Near-duplicate detection belongs in a separately versioned data-preparation workflow. The validator should check recorded method IDs/parameters, comparison evidence references, adjudication status, duplicate groups, and partition consistency against an approved manifest. It must not select a similarity method or threshold.

Exact duplicate screening is documented as SHA-256 equality over exact UTF-8 bytes with no normalization. Near-duplicate method, parameters, thresholds, and sampling remain `TBD` (ND-02/03). Borderline cases require human adjudication (ND-04). A confirmed duplicate group cannot cross partitions. An unresolved cross-partition relationship blocks held-out eligibility until reviewed; if held-out information affects a change, the affected partition is retired rather than silently reused.

## 6. Governance and privacy boundary

The validator may check that required approval references, policy IDs, storage/access metadata, retention/deletion policy IDs, and held-out assignment records are present, well-formed, and linked to the right release. It cannot establish:

- Authenticity, scope, or adequacy of approval references.
- Actual access-control enforcement or who has accessed source text.
- Encryption at rest/in transit or key management.
- Successful deletion from primary storage, replicas, backups, logs, or exports.
- That report allowlists prevent all runtime or logging leakage.
- Security isolation from malicious same-process code.

These require separately approved organizational controls and evidence (ND-08–10, ND-18). Source text remains synthetic only. Reports should use record IDs and safe diagnostics, not source quotations, reviewer identities, secrets, or raw exceptions.

## 7. Decision dependencies (ND-01–ND-19)

ND identifiers refer to the Phase 12F decision register in the conversation; no values, owners, thresholds, or approvals are assigned here. “Core” means a format-independent structural validator; “layer” means a gated component.

| ND | Current status and dependency | Can the validator be deterministic while open? | Blocks |
|---|---|---|---|
| ND-01 | Exact-byte duplicate rule is documented; duplicate/lineage records depend on its result. | Yes for exact hash equality, not broader similarity. | Dataset partitioning. |
| ND-02 | Normalization is absent for exact checks; any future normalized comparison is undecided. | Yes if normalization is explicitly out of scope; otherwise no for that screening layer. | Near-duplicate preparation and dataset partitioning. |
| ND-03 | Near-duplicate algorithm/parameters/threshold are undecided. Validator consumes its approved records. | Core yes; duplicate-screening outcome no. | Dataset creation and partition freeze. |
| ND-04 | Human duplicate adjudication and unresolved blocking rule are documented; role details remain open. | Yes to enforce recorded statuses; not to decide borderline cases. | Dataset/held-out assignment. |
| ND-05 | Physical storage format is undecided. | Core yes if it consumes logical records; persistence/decoder layer no. | Storage-backed validator and dataset creation. |
| ND-06 | Manifest canonicalization is undecided. | Core structural checks yes; manifest hash verification no. | Hash layer and dataset release. |
| ND-07 | Passage code-point behavior is documented; global ordering/encoding remains open. | Passage checks yes under recorded algorithm; manifest hashes no. | Hash/reproducibility layer; ND-06 first. |
| ND-08 | Storage location and access roles are undecided. | Structural validator yes; operational privacy cannot be proven. | Dataset creation. |
| ND-09 | Encryption requirements are undecided. | Structural validator yes; enforcement cannot be proven. | Dataset creation. |
| ND-10 | Text/report separation is required; implementation controls are undecided. | Schema checks yes; operational leakage prevention no. | Dataset creation. |
| ND-11 | Five relation labels and affirmative/pair-decision split are documented in source. | Yes for enum/record-shape checks. | Neither; immutable contract boundary. |
| ND-12 | Scope annotation vocabulary and interpretation are undecided. | Generic structure yes; annotation-value validation awaits guide. | Annotation-aware layer and dataset annotation. |
| ND-13 | Date syntax/end-date convention is documented; temporal classification rules are open. | Metadata shape yes; temporal annotation validation awaits guide. | Annotation-aware layer for temporal labels and dataset annotation. |
| ND-14 | No universal precedence rule is documented or implied. | Validator can preserve unresolved values; cannot validate a domain conclusion. | Precedence annotation and dataset creation. |
| ND-15 | Reviewer/adjudication structure is documented; evidence and disagreement vocabularies remain open. | Record shape partly; guide-dependent consistency awaits approval. | Annotation-aware layer and dataset creation. |
| ND-16 | Schema version 1 is proposed; identifier/version compatibility policy is not frozen. | Prototype shape checks possible; release validator cannot be frozen. | Validator freeze and dataset release. |
| ND-17 | Source hash input is defined; dataset/partition hashes depend on ND-06/07. | Source hash checks yes; release hash checks no. | Dataset release and manifest hash layer. |
| ND-18 | Ownership and approval values are unassigned. | Validator can check recorded references, not authority or adequacy. | Dataset creation and evaluation governance. |
| ND-19 | Future run provenance fields are described; no run/provider is authorized. | Run schema can be designed; actual run validation waits for frozen IDs. | Evaluation only; no blocker to fake-only structural design. |

## 8. Mechanical validation versus approval

**Mechanical once the applicable schema is frozen:** exact types/enums; required and unknown fields; IDs and uniqueness; foreign keys; typed-target exclusivity; cardinality; annotation/adjudication links; one-to-one matching constraints; metric denominator arithmetic; required version identifiers; source/passage hash and offset checks; partition consistency against an approved lineage manifest; and outcome categorization under the frozen precedence rule.

**Human/organizational approval:** annotation and matching guides; near-duplicate method and thresholds; domain rules for scope/time/precedence; storage location/access/encryption; retention/deletion; reviewer and adjudicator authorization; held-out access; dataset freeze; and evaluation go/no-go. A validator may report missing approval evidence but cannot authorize or verify that approval by itself.

## 9. Dependency-ordered minimum decisions

1. **Approve the logical schema boundary and version policy** (ND-16), including which record references and enumerations are stable. This enables final structural design without selecting a file format.
2. **Approve annotation vocabularies and guides** for scope, dates, precedence, insufficient evidence, and disagreement (ND-12–15). Keep source labels fixed (ND-11).
3. **Decide validator I/O scope and storage format separately** (ND-05). A logical core can remain format-independent; any persistence adapter needs an approved format.
4. **Specify canonical serialization and ordering** (ND-06/07) before implementing or verifying dataset/partition manifest hashes. Source hash checks can be designed separately.
5. **Decide duplicate-preparation scope and approve its method** (ND-01–04). The validator design should consume versioned results, not perform unapproved similarity scoring.
6. **Approve ownership, privacy, retention, deletion, and access controls** (ND-08–10, ND-18) before creating data. These are not substitutes for structural schema decisions.
7. **Freeze the design and approve implementation separately.** Evidence should include field/enum catalog, typed FK/cardinality matrix, annotation/matching rules, metric denominator rules, version compatibility, canonicalization if hash validation is included, and privacy/approval gates.
8. **Authorize dataset creation, partition freeze, and evaluation separately.** ND-19 run fields do not authorize provider use or data transmission. Any future provider/model activity needs separate approvals.

## 10. Future verification plan (not executed)

After implementation is separately authorized, test plans should include synthetic-only unit and property-based checks for:

- Missing/unknown fields, wrong exact types, boolean-as-integer values, invalid enums, and bounded values.
- Duplicate IDs, dangling/cross-dataset/cross-run references, and every typed-target exclusivity combination.
- Referential ownership, cardinality, annotation revisions/supersession, adjudication links, missing reviewers, and unresolved states.
- Finding vs decision-item separation; affirmative and `INCONCLUSIVE` matching target compatibility; maximum-cardinality one-to-one matching and tie reproducibility.
- Gold target versus emitted citation separation; missing, duplicate, unresolved, invalid-provenance, and semantic-support outcomes without conflation.
- Denominator arithmetic, eligibility/exclusion handling, zero-denominator `N/A`, and open-world TN/FPR behavior.
- Partition/lineage constraints for confirmed and unresolved duplicate relationships against a supplied manifest.
- Source/passage recomputation under the recorded algorithm and deterministic manifest serialization only after canonicalization is approved.
- Outcome precedence under competing terminal-event observations and secondary flags.
- Report allowlists and sanitized diagnostics, while acknowledging that such tests do not prove system-wide logging or access-control safety.

Do not create fixtures or run these checks in this phase. Synthetic regression outcomes are not independent held-out evidence.

## 11. Open decisions and readiness

Open implementation-affecting decisions include: physical format if persisted I/O is in scope (ND-05); canonical byte/ordering/hash rules (ND-06/07); approved annotation vocabularies and decision rules (ND-12–16); and final schema/version compatibility policy (ND-16). Open dataset gates include near-duplicate screening and adjudication (ND-02–04), storage/access/encryption/retention/deletion (ND-08–10), accountable ownership and approvals (ND-18), and frozen source/partition hashes (ND-17). Evaluation-run IDs and model/configuration values remain future provenance only (ND-19).

| Readiness question | Verdict | Reason |
|---|---|---|
| Ready for logical design review? | YES | Layers and unresolved dependencies can be reviewed without selecting formats or creating data. |
| Ready to implement structural validator? | NO | Schema/version compatibility and guide-dependent enumerations are not frozen; this blueprint is not implementation authorization. |
| Ready for canonicalization/hash implementation? | NO | Canonical serialization, stable collection ordering, and exact manifest hash inputs remain undecided (ND-06/07). |
| Ready to create a synthetic dataset? | NO | Privacy, ownership, annotation, duplicate/partition, and retention gates remain open. |
| Ready to run an evaluation? | NO | No dataset/run is authorized; evaluation requires a separate go/no-go. |

## Source alignment reviewed

`policy_compare.Classification` defines the five listed values. The module documentation says it validates input/provenance but does not establish semantic support, policy relations, precedence, scope semantics, or complete coverage. `policy_candidate_adapter.validate_candidate_response` normalizes accepted candidates to `PROPOSAL_ONLY`, `NOT_VERIFIED`, and `human_review_required: true`; the fake adapter remains fixture-backed. This blueprint adds no runtime fields or provider behavior, and impact remains `NOT_EVALUATED`.
