# Policy Decision Resolution Plan

## 1. Current state and scope

This plan organizes decisions needed before validator, canonicalization/hash, dataset, or evaluation work. It is documentation only; it does not approve a decision or authorize implementation, data creation, evaluation, credential loading, or provider activity.

### Status meanings

- **DOCUMENTED** — present as a rule or design statement in the reviewed documents. This does not prove formal approval.
- **PROPOSED** — a suggested direction that still requires review and approval where applicable.
- **APPROVED** — supported by an explicit approval record. No approval record was available for this plan.
- **UNRESOLVED** — a decision or evidence remains outstanding.
- **NOT VERIFIABLE** — available documents do not establish the status.

Where a row says `DOCUMENTED; approval NOT VERIFIABLE`, it records that distinction explicitly. Earlier `DECIDED` labels mean only “documented” unless an approval record is produced. The formal Phase 12F register was not available in the reviewed repository documents; its full contents, owners, and approval history have not been independently verified. The ND summaries below rely on the three design documents and the Phase 12I report.

The runtime boundary remains unchanged: `CONTRADICTION`, `COMPATIBLE_CHANGE`, `NEW_RULE`, `SCOPE_OR_TIME_DIFFERENCE`, and `INCONCLUSIVE`; accepted output remains `PROPOSAL_ONLY`, semantic support `NOT_VERIFIED`, and `human_review_required: true`. Impact remains `NOT_EVALUATED` and outside the current output contract. `FakePolicyCandidateAdapter` remains the only executable proposal generator.

## 2. Dependency-ordered decision backlog

Owner roles are **proposals**, not assignments. Approval evidence is still required. Dependencies below refer to named outputs or external submissions in Section 5. ND-06 and ND-07 are a joint-resolution package, not sequential prerequisites.

| ID | Evidence status in reviewed documents | Decision or evidence required | Dependencies | Proposed owner role | Approval evidence needed | Blocked until resolved |
|---|---|---|---|---|---|---|
| ND-01 | DOCUMENTED exact-byte SHA-256 rule; formal approval NOT VERIFIABLE | Confirm exact original UTF-8 bytes as the scope of exact-duplicate identification and define its evidence record | None beyond the externally supplied authority record for approval | Dataset methodology owner (proposed) | Versioned decision record; do not call it approved without that record | Use as an approved dataset partition control |
| ND-02 | UNRESOLVED for any normalization-based comparison | Decide whether normalized comparison is out of scope or define a separate deterministic normalization method and version | ND-01 scope confirmation | Data methodology owner (proposed) | Explicit scope decision or approved method/version | Normalization-based comparison |
| ND-03 | UNRESOLVED — method, parameters, threshold, and sampling TBD | Select and version a near-duplicate candidate-screening procedure; calibrate parameters and threshold using approved evidence; do not presume a method or value | ND-02; ND-04 framework; ND-18 authority/roles | Evaluation methodology owner (proposed) | Approved procedure, calibration evidence, and version | Near-duplicate screening and partition freeze |
| ND-04 | PROPOSED — adjudication and unresolved blocking described; qualifications/roles open | Approve the general duplicate-adjudication procedure before screening; after ND-03 produces candidates, reviewers separately record confirmed, not-duplicate, or unresolved relationships | ND-18 for approval authority; ND-03 output for case-level decisions | Data governance owner (proposed) | Versioned adjudication guide and authorized reviewer-role record; case records remain separate | Human disposition of candidate relationships and held-out assignment |
| ND-05 | UNRESOLVED — persisted representation and decoder scope undecided | Decide whether validation is logical/in-memory only or needs persisted input; if persisted, specify format and decoder | ND-16 core logical schema | Data engineering owner (proposed) | Approved I/O and format specification; storage approval if operational data is persisted | Persistence adapter and storage-backed validation; logical design can proceed |
| ND-06 | UNRESOLVED — canonical manifest serialization undecided | Define canonical logical serialization, included/excluded fields, exact hash input, and failure behavior, jointly with ND-07 | Joint package with ND-07; ND-16 core schema; ND-05 only if persisted bytes are the hash target | Reproducibility owner (proposed) | Jointly approved, versioned canonicalization specification and independent reproducibility review | Manifest/dataset/release hash implementation and hash claims |
| ND-07 | PROPOSED passage behavior; global ordering/encoding unresolved | Define stable collection ordering and encoding jointly with ND-06; specify passage derivation version, offset units, and source/passage hash inputs | Joint package with ND-06; ND-16; ND-05 only if persisted bytes are the hash target | Reproducibility owner (proposed) | Same joint approval plus passage-rule version record | Reproducible manifest hashes; passage validation beyond an approved recorded rule |
| ND-08 | UNRESOLVED — storage location and access roles undecided | Review and approve the submitted `ND-08 Storage and Access Model Proposal`; values remain proposed until approval | ND-10 data-flow/separation design; ND-18 authority; external proposal E-2 | Data custodian (proposed; subject to authority assignment) | Explicit location/access approval record and role assignment | Dataset storage and access |
| ND-09 | UNRESOLVED — encryption requirements undecided | Define encryption, key custody, and verification evidence for the selected storage/data flow | Approved ND-08 model; ND-18 | Security/privacy owner (proposed) | Approved control specification and operational verification evidence | Dataset storage under required encryption controls |
| ND-10 | PROPOSED — source/report separation required; implementation controls open | Define logical source-text, annotation, log, and report boundaries before selecting physical storage | ND-18 for approval authority | Privacy owner (proposed) | Approved data-flow and report/log allowlist specification | Storage/access selection and any dataset/report workflow |
| ND-11 | DOCUMENTED five-label and affirmative/pair-level decision split; formal approval NOT VERIFIABLE | Preserve the five labels; do not add operational failures or impacts as relation labels | None beyond authority record for any formal approval | Policy evaluation owner (proposed) | Existing contract reference; any change requires a separate versioned approval | No blocker while documented contract is preserved |
| ND-12 | UNRESOLVED — scope vocabulary and interpretation undecided | Define scope dimensions, values, evidence requirements, and unknown/unresolved representation | ND-15 general annotation framework; ND-18 | Domain annotation lead (proposed) | Versioned scope guide approved by relevant domain owner | Scope annotation, validation, and gold labeling |
| ND-13 | PROPOSED date syntax/end-date convention; temporal interpretation unresolved | Confirm date syntax and interval convention; define overlap/disjointness/unknown evidence rules without deriving precedence from dates alone | ND-15 general framework; ND-18; ND-12 where scope changes interpretation | Domain annotation lead (proposed) | Versioned temporal guide approved by relevant domain owner | Temporal annotation and validation |
| ND-14 | DOCUMENTED absence of a universal precedence rule; formal approval NOT VERIFIABLE | Preserve “no universal rule.” Any policy-specific precedence reasoning requires a separately supplied owner rule and evidence | ND-18 for policy-specific authority; external evidence E-3 if a policy-specific rule is proposed | Policy owner for relevant policy family (proposed) | Policy-specific rule reference and approval, if supplied | Affirmative policy-specific precedence conclusion; ambiguity remains unresolved |
| ND-15 | PROPOSED general review structure; detailed evidence/disagreement rules unresolved | Approve general annotation records, independent decisions, revisions, missingness, disagreement/adjudication, insufficient evidence, and unresolved handling without defining domain meanings | ND-18 | Annotation program lead (proposed) | Versioned general annotation/adjudication guide reviewed independently | Frozen annotation workflow; enables ND-12/13 guides |
| ND-16 | PROPOSED schema version 1; compatibility policy unresolved | Stage approval: freeze core logical records, exact types, IDs, references, and compatibility first; add guide-dependent annotation fields after ND-12–15 | Core: ND-18 and documented contract; extensions: ND-12–15; ND-05 follows core approval if persistence is wanted | Schema owner (proposed) | Versioned core schema and separately versioned extensions/compatibility records | Frozen structural validator for approved scope and dataset release schema |
| ND-17 | PROPOSED exact UTF-8 source hash; manifest/partition hash inputs unresolved | Freeze dataset/partition hash inputs only after joint ND-06/07 approval; distinguish integrity from anonymization | ND-06/ND-07 joint package; applicable ND-16 version | Reproducibility owner (proposed) | Hash specification linked to approved serialization and version | Dataset/partition hash generation and release reproducibility claims |
| ND-18 | UNRESOLVED — ownership and approval authority unassigned | Assign accountable data, policy, privacy/security, annotation, and evaluation roles and independent review authority | External authority appointment E-1 | Program sponsor (proposed; appointment must be evidenced) | Role/authority record linked to E-1; identities handled under approved governance | Approval-bearing decisions and later gates |
| ND-19 | PROPOSED run-provenance fields; no run/provider authorized | First approve a run-provenance specification. Populate a run-specific record only after separate evaluation authorization and actual execution | Specification: ND-15; applicable ND-16; frozen protocol; ND-06/07 only if run manifests are hashed. Run record: evaluation authorization and completed run evidence | Evaluation owner (proposed) | Versioned specification approval; later authorization record and actual run artifacts are separate evidence | Run-specific provenance until an authorized run actually occurs; this does not authorize evaluation or provider use |

### External or submitted prerequisite artifacts

These inputs are not created or approved by this plan:

| ID | Artifact | Producer/source | Required contents | Status requirement |
|---|---|---|---|---|
| E-1 | Program Authority Appointment/Delegation Record | Existing authorized organization process; no person or role is invented here | Designated program authority role; scope of authority; appointment/delegation evidence reference; effective date and version; review/approval status | Must be available and valid before approval-bearing decisions; otherwise those decisions remain blocked |
| E-2 | `ND-08 Storage and Access Model Proposal` | Proposed producer: designated data custodian, subject to E-1 and ND-18 role assignment | Proposed storage location; access roles; encryption requirements; source/report separation controls; retention and deletion; operational verification evidence plan | Every value remains `PROPOSED` until separately approved; proposal is not an approved model |
| E-3 | Policy-specific precedence evidence, if any | Authorized owner of the relevant policy family | Rule, scope, effective period, source evidence, owner authority, and approval reference | Optional; absence means precedence remains unresolved. It never establishes a universal rule |
| E-4 | Synthetic dataset/source inputs, only after dataset authorization | Future separately authorized data-preparation step | Synthetic-only source text and version metadata required by the frozen schema | Does not exist in this planning phase; no real policy or employee data is implied |

## 3. Minimum decision groups and staged outputs

### Schema and versioning

Review the core logical schema independently of physical storage. Its output is a versioned logical record and compatibility decision. Then decide whether a persisted representation is needed; if so, approve its format and decoder. Annotation-specific schema extensions follow the general framework and domain vocabularies. This avoids making a storage-format choice a prerequisite for logical schema review.

### Annotation vocabulary and adjudication

Resolve ND-15 first as a general framework: record structure, independent decisions, revisions, missing coverage, disagreement, adjudication, and unresolved/insufficient-evidence handling. It intentionally does not define policy scope, time, or precedence. ND-12 and ND-13 then define scope and temporal meanings. ND-14 preserves the absence of a universal precedence rule; any policy-specific rule needs E-3 and separate approval. Ambiguous cases remain unresolved.

### Exact duplicates and near-duplicate screening

Keep five distinct steps:

1. **Exact identification (ND-01):** the documented rule compares exact original UTF-8 bytes. Confirm the exact-check scope; do not normalize or trim this input.
2. **Normalization scope (ND-02):** decide whether normalized comparison is out of scope. If not, define and version the normalization separately; do not treat a method as selected.
3. **Adjudication framework (ND-04):** approve reviewer qualifications, candidate disposition labels, evidence, disagreement, and unresolved blocking before screening. This is independent of choosing a similarity algorithm.
4. **Screening procedure design (ND-03):** after ND-02 and the ND-04 framework, propose method, parameters, sampling, and threshold-calibration procedure. This plan selects no algorithm or value. Final method/threshold approval requires evidence from an authorized synthetic development set.
5. **Screening, case adjudication, and partition impact:** only after synthetic-data authorization and privacy controls, apply the approved procedure to authorized synthetic inputs. Reviewers record confirmed, not-duplicate, or unresolved outcomes. Unresolved cross-partition relationships block held-out placement. Confirmed groups stay in one partition. If held-out information informs a change, retire the affected partition from confirmatory use; retirement is a governance action, not semantic classification.

The screening record and case adjudications enable partition decisions. The validator checks those records; it does not discover every duplicate.

### Canonical serialization, ordering, and hashes

ND-06 and ND-07 form a **joint-resolution package**, not sequential dependencies. Before approval, the package must decide all applicable items below without presupposing their values:

- Unicode and other string normalization policy.
- Line-ending treatment.
- Absent field versus explicit `null`.
- Map/object key ordering.
- Numeric serialization, supported precision, and representation.
- Collection ordering and whether any collection is semantically unordered.
- Character encoding.
- Exact fields and bytes included in each manifest/partition hash input.
- Hash algorithm, identifier/version, and migration/compatibility behavior.
- Relationship of logical canonical bytes to any optional persisted format.

The approval record must identify the canonical form and its version, testable conformance evidence, and all exclusions. ND-17 then fixes dataset/partition hash inputs under that approved rule. **No canonicalization or hash implementation is authorized until every applicable item is decided and the joint ND-06/ND-07 approval record exists.** Source hashes over exact UTF-8 text do not settle manifest canonicalization and do not anonymize content.

### Storage, access, encryption, retention, and deletion

Use staged decisions:

1. ND-10 defines logical boundaries among source text, annotations, logs, and reports. This is a design artifact, not an operationally enforced security boundary.
2. The externally submitted E-2 proposal describes candidate storage/access controls and remaining privacy requirements. It is not approval.
3. ND-08 selects/approves location and roles; ND-09 approves encryption and key-custody requirements for that model.
4. Retention and deletion require explicit approval, including applicable replicas, backups, logs, and exports. The reviewed ND list has no separate retention/deletion ID; do not invent one.
5. Before dataset creation, obtain operational evidence that access, encryption, retention, and deletion controls work as approved. A validator can check references and metadata only.

No actual location, role, encryption setting, retention period, or deletion procedure is approved without its explicit approval record.

### Partition lineage and contamination governance

After screening and case adjudications exist, assign each family/lineage, versions, pairs, passages, and confirmed duplicate group to one partition. Unresolved cross-partition links block held-out eligibility. Restrict held-out access. If exposure or outcomes inform a change, retire the affected partition from confirmatory use and require an independently assembled, lineage-separated replacement. The validator checks assignments, not discovery completeness.

### Run provenance and evaluation authorization

ND-19 is divided into separate artifacts and decisions:

1. **Run-provenance specification:** define required nonsecret fields, schema/protocol versions, dataset and partition references, configuration identifiers, and reproducibility metadata. Approval of this specification does not authorize or execute an evaluation.
2. **Evaluation go/no-go:** review the frozen dataset and protocol, approved owners, completed governance gates, and approved run-provenance specification. Its output is a separate evaluation authorization record.
3. **Authorized execution and execution-result artifact:** only after Stage 10 authorization, the authorized run consumes that authorization and the frozen, approved artifacts within its scope. The run produces an execution-result artifact containing the actual outcome and the nonsecret evidence needed to describe what ran, using only fields and linkage rules defined by the approved run-provenance specification. This plan does not choose a storage format, hash rule, owner, approval, or run-identifier convention.
4. **Run-specific provenance record:** after execution, this record consumes the execution-result artifact and references to the frozen artifacts under the approved run-provenance specification. It records the run-specific provenance; it does not authorize, trigger, or retroactively legitimize execution.

No stage uses its own output as an input. The provenance specification precedes evaluation authorization; Stage 10 authorization precedes execution; the execution-result artifact is produced by that authorized run; and the run-specific provenance record consumes the execution-result artifact. Provenance recording is descriptive and does not authorize or initiate a run.

## 4. Mechanical checks versus human approval

A future validator may check exact types, fields, enums, bounds, IDs, typed references, cardinality, recorded adjudication links, matching, partition assignments, and source/passage hashes under approved rules. It may check whether governance references are present and linked, or block when a prerequisite is unresolved.

It cannot prove policy truth or completeness, semantic support, exhaustive duplicate discovery, reviewer independence, or approval authenticity/adequacy. It cannot prove actual access-control enforcement, encryption at rest, retention/deletion execution, or that held-out content was never exposed. Hashes support integrity and reproducibility; they are not anonymization or disclosure-safety evidence.

## 5. Revised dependency graph and separate gates

Stages list the exact artifact inputs and outputs. Inputs are either emitted by an earlier stage or explicitly marked as external/submitted. Proposed artifacts remain proposed until the named approval record exists.

| Stage | Inputs and source artifacts | Outputs and artifact types | Required approval records | Decisions unlocked | Work still blocked |
|---|---|---|---|---|---|
| 0. Authority and status baseline | Reviewed design documents; **external E-1 Program Authority Appointment/Delegation Record** | ND-18 role/authority matrix; documented-versus-approved status/provenance note | Verification/acceptance of E-1 by authorized authority; role assignment record | Approval-bearing decisions in later stages | Any approval if E-1 is absent or its scope/status is unclear |
| 1. Independent foundations | Stage 0 ND-18 matrix; current documented contract | ND-10 logical data-flow/separation design; ND-15 general annotation framework; ND-16 core logical schema; ND-01 exact-check scope record; ND-14 no-universal-precedence status record | Separate approvals for each foundational decision; documentation alone is insufficient | ND-02 scope choice; ND-05 optional persistence choice; domain guides | Screening, storage operation, hashes, dataset creation |
| 2. Domain and process decisions | Stage 1 ND-15 framework and ND-01 record; Stage 0 role matrix; E-3 only if policy-specific precedence is proposed | ND-12 scope guide; ND-13 temporal guide; ND-04 adjudication procedure; ND-02 normalization-scope decision; optional policy-specific ND-14 evidence record | Domain-owner guide approvals; reviewer procedure approval; explicit approval of any E-3 rule | ND-03 procedure design; annotation schema extensions; case-review procedure | Screening until authorized development calibration; unresolved precedence conclusions; partition freeze |
| 3. Conditional representation and screening procedure | Stage 1 ND-16 core schema; Stage 2 ND-02 decision and ND-04 framework; ND-18 | Optional ND-05 format/decoder spec; ND-03 screening-procedure proposal and calibration plan (not screening results) | Format approval if persistence is needed; screening procedure remains provisional pending authorized calibration | Optional persistence adapter; synthetic-data preparation gate | Screening source text, case dispositions, and held-out assignment before dataset authorization |
| 4. Joint canonicalization package | Stage 1 ND-16 core schema; Stage 3 ND-05 only if persisted bytes are hash target | Joint ND-06/ND-07 canonicalization spec; ND-17 hash-input specification; conformance evidence definition | One explicit joint ND-06/ND-07 approval record plus independent reproducibility review | Canonicalization/hash implementation may be separately considered | Any implementation/hash claim before every applicable edge case is resolved and approved |
| 5. Privacy and operational evidence | Stage 1 ND-10 design; Stage 0 ND-18 matrix; **externally submitted E-2 ND-08 Storage and Access Model Proposal** | ND-08 location/access decision; ND-09 encryption decision; separate retention/deletion approval record; operational verification evidence | Explicit ND-08/09 and retention/deletion approvals; verified evidence before data creation | Dataset storage/access after approval | Dataset creation while any control or evidence is missing |
| 6. Synthetic-data creation go/no-go | Stages 1–5 applicable approved artifacts; schema/guides; ND-03 provisional procedure/calibration plan; Stage 5 operational controls | Dataset-creation authorization or rejection, explicitly scoped to synthetic development preparation/calibration; no data is created by this decision stage | Separate authorized dataset go/no-go with stated use/scope | Stage 7 only if authorized | Data preparation if authorization is absent or conditions fail; held-out or confirmatory use remains blocked |
| 7. Synthetic development-data preparation and calibration | Stage 6 development-scope authorization; approved schema/guides; E-4 synthetic source inputs created only under authorization; Stage 3 ND-03 provisional procedure; Stage 5 controls | Development-only synthetic records; ND-03 calibration evidence and final screening-procedure decision; candidate screening/adjudication records; provisional lineage/partition proposal | Dataset owner approval; reviewer decisions under ND-04; ND-03 method/threshold approval after calibration | Partition-freeze review; held-out assignment only if leakage/duplicate conditions pass | Held-out eligibility for unresolved cross-partition relationships; no confirmatory claims from development data |
| 8. Dataset/partition freeze gate | Stage 7 records; approved lineage rules; privacy evidence; frozen labels; leakage review; Stage 4 hash rules if hashes are claimed | Frozen synthetic dataset/partition manifest; approved hashes only if canonicalization is approved; freeze/retirement record | Independent label/partition review; separate dataset/partition freeze approval | Evaluation go/no-go review | Held-out evaluation if unresolved lineage, contamination, missing governance evidence, or unfrozen protocol remains |
| 9. Run-provenance specification | Frozen schema and protocol; required dataset/partition reference definitions; Stage 4 hash rules if run manifests are hashed | Versioned run-provenance specification, nonsecret configuration-field catalog, and validation criteria | Separate approval of specification only; no evaluation authorization | Stage 10 may consume this specification | Evaluation execution; no run-specific record exists |
| 10. Evaluation go/no-go | Stage 8 frozen dataset/partition and review records; frozen protocol/thresholds; Stage 0 owner matrix; Stage 5 governance evidence; Stage 9 approved provenance specification | Separate evaluation authorization/rejection record with authorized scope and nonsecret configuration identifiers | Explicit evaluation authorization by assigned authority | Stage 11 only if authorized | Any evaluation run without authorization |
| 11a. Authorized execution | Stage 10 evaluation authorization including its scope/configuration identifiers; frozen, approved artifacts within that scope | Execution-result artifact produced by the authorized run: actual outcome and nonsecret evidence needed to describe what ran, as defined by the approved provenance specification | Stage 10 authorization must precede execution | Stage 11b provenance recording and reporting for that authorized run | Any run without applicable Stage 10 authorization or beyond its scope |
| 11b. Run-specific provenance recording | Stage 11a execution-result artifact; references to the frozen artifacts; Stage 9 approved run-provenance specification | Run-specific provenance record linking the actual execution result to the frozen artifacts using only approved nonsecret fields/linkage rules | No execution authorization is created here; the record is populated only after the authorized run | Reporting for that authorized run | Any future run beyond its authorization scope; provenance recording cannot authorize, trigger, or retroactively legitimize execution |

### Separate go/no-go gates

| Gate | Minimum evidence | Status |
|---|---|---|
| Prototype design discussion | Logical scope and unresolved-state behavior | May be discussed; no implementation authorization |
| Logical validator prototype | Explicit separate authorization and approved prototype boundary | Not authorized by this plan |
| Frozen structural validator | Approved schema/version, annotation rules, matching/eligibility, diagnostics, and verification plan | Not ready |
| Canonicalization/hash implementation | Complete approved ND-06/ND-07 package, applicable representation decision, and ND-17 hash inputs | Not ready |
| Dataset creation | Approved ownership, storage/access, encryption, separation, retention/deletion, annotation, lineage, and partition controls | Not authorized |
| Held-out partition freeze | Screening/adjudication outputs, leakage review, unresolved-link disposition, controlled access, and separate freeze decision | Not authorized |
| Confirmatory evaluation | Frozen, reviewed dataset/partitions/labels; pre-registered metrics/thresholds; owner and separate authorization | Not authorized |
| External provider integration | Separate provider, data-handling, security, budget, activation, credential, endpoint, and request approvals | Not authorized |

Approval at one gate does not authorize a later gate.

## 6. Approval record template

Maintain a separate, access-controlled record for each approval. Do not include credentials, source text, sensitive quotations, or secret-bearing references.

| Field | Required content |
|---|---|
| Decision ID and version | Stable identifier and revision; identify any superseded record |
| Exact decision text | Adopted rule, scope, and exclusions |
| Alternatives considered | Options and rationale for selection/rejection |
| Rationale and risks | Evidence, trade-offs, residual risks, and limits |
| Owner and independent reviewer | Authorized roles; identities handled in the approved controlled system |
| Approval date | Leave unset until explicit approval occurs |
| Affected versions | Schema, guides, duplicate procedure, protocol, canonicalization, or other versions |
| Rollback or supersession | How future use changes without silently rewriting prior records |
| Evidence reference | Nonsecret reference to approval and review artifacts |

## 7. Readiness and open questions

The next discussion can settle the logical validator boundary, identify the external authority appointment record, assign proposed approval roles, decide whether duplicate normalization is out of scope, and decide whether persistence is needed. These remain discussions until approval evidence exists.

No near-duplicate algorithm or threshold is selected. No storage location, access role, encryption setting, retention period, or deletion procedure is approved. No manifest hash is ready until every applicable canonicalization edge case has an approved resolution. There is no universal precedence rule. Impact remains `NOT_EVALUATED`; the five relation labels and proposal-only fields remain unchanged.

This plan authorizes no validator implementation, dataset creation, evaluation, credential loading, provider integration, or external request. Each requires its own explicit decision and evidence.
