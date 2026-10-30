# External Prerequisite and Joint Decision Checklist

## Purpose and status rules

This checklist records evidence needed to resolve E-1, E-2, and the joint ND-06/ND-07 package. It is a review aid only. It does not appoint an authority, approve a control, choose a canonicalization rule, authorize implementation, or authorize data creation or evaluation.

Use these statuses for each checklist item:

- `UNRESOLVED` — required evidence or a decision is missing.
- `PROPOSED` — a candidate approach has been submitted but not approved.
- `DOCUMENTED` — stated in a reviewed design document; this alone is not approval or operational verification.
- `APPROVED` — an explicit approval record from an authority whose scope is established by E-1 is available and applicable.
- `NOT VERIFIABLE` — available evidence does not establish the item’s status or effectiveness.

Do not infer `APPROVED` from silence, a draft, this checklist, or the presence of another design document. Record an evidence reference and reviewer/status for each item without copying secrets or sensitive source text into this checklist.

### Current contract boundary

Preserve the five relation labels: `CONTRADICTION`, `COMPATIBLE_CHANGE`, `NEW_RULE`, `SCOPE_OR_TIME_DIFFERENCE`, and `INCONCLUSIVE`. Accepted proposals remain `PROPOSAL_ONLY`, semantic support remains `NOT_VERIFIED`, `human_review_required` remains `true`, and impact remains `NOT_EVALUATED`. This checklist does not change the runtime contract or authorize a provider path.

## E-1 — Program Authority Appointment/Delegation Record

**Current status: `UNRESOLVED` / `NOT VERIFIABLE`.** The decision-resolution plan names E-1 as an external record from an existing authorized organizational process. No person, organization, appointment, delegation, or approval is supplied or inferred here.

### Evidence review checklist

| Check | Required evidence or review question | Status | Evidence reference / notes |
|---|---|---|---|
| Appointed authority | Record identifies the program authority role and the appointment/delegation instrument establishing it. | `UNRESOLVED` | |
| Delegated roles | Record identifies each delegated decision-making role needed by the plan, without assuming an unappointed role is authorized. | `UNRESOLVED` | |
| Authority scope | For each role, state which decisions and gates it may approve, any limits, and whether independent review is required. | `UNRESOLVED` | |
| Evidence reference | Reference identifies the authoritative record and permits its status and scope to be checked; avoid placing sensitive identity details here. | `UNRESOLVED` | |
| Effective date and version | Record provides effective date/version and enough information to determine whether it applies to the proposed decision date and scope. | `UNRESOLVED` | |
| Review and approval status | Record shows review/approval status and the authority responsible for that status. Verify rather than infer. | `UNRESOLVED` | |
| Expiry, supersession, or revocation | Determine whether the record remains current and whether a later instrument supersedes, limits, or revokes it. | `UNRESOLVED` | |
| Ambiguity or insufficiency | Check whether roles, scope, dates, or evidence are ambiguous, incomplete, expired, or internally inconsistent. Record the issue; do not resolve it by assumption. | `UNRESOLVED` | |

### Blocking rule

If E-1 is absent, expired, out of scope, ambiguous, or insufficient, mark the relevant authority and approval status `NOT VERIFIABLE` or `UNRESOLVED`; do not treat the affected approval-bearing decisions as approved. The plan identifies authority assignment (ND-18) and later approval-bearing decisions as blocked until valid E-1 evidence and role assignments are established. This includes the separate approval gates for validator work, canonicalization/hashes, dataset creation, held-out freeze, evaluation, and provider integration. A missing E-1 does not itself determine any substantive policy or canonicalization choice.

## E-2 — ND-08 Storage and Access Model Proposal

**Current status: `UNRESOLVED`; proposal status is `PROPOSED` until separately approved.** E-2 is an externally submitted proposal, not an approved model or proof that controls are implemented. A design statement is not operational verification.

For each proposed control, record separately: (a) proposal and scope, (b) approving authority/evidence under E-1, and (c) operational verification evidence. If only (a) exists, the control remains `PROPOSED`; if effectiveness cannot be demonstrated, mark it `NOT VERIFIABLE`.

| Review area | Proposal must specify | Approval / operational evidence to obtain | Status |
|---|---|---|---|
| Logical data separation | How restricted synthetic source text is separated from annotations, logs, reports, and exports; which fields may cross each boundary. Treat this as a design boundary, not an enforced security boundary. | Approved data-flow and report/log allowlist (ND-10), plus evidence that the selected implementation enforces it. | `UNRESOLVED` |
| Storage location | Candidate location(s), data classes stored there, and whether source text, identifiers, hashes, annotations, or outputs are held there. No location is selected by this checklist. | Explicit ND-08 location decision and evidence of the actual configured location. | `UNRESOLVED` |
| Permitted access roles | Roles needing access to source text, annotation records, hashes/identifiers, reports, and exports; least-privilege boundaries and review process. | Explicit ND-08 role approval linked to E-1 authority; access-control verification for the selected location. | `UNRESOLVED` |
| Encryption and key custody | Proposed encryption requirements for stored and transferred data, key custody/rotation responsibilities, and applicable data flows. Do not include keys or secrets in the proposal or this checklist. | Explicit ND-09 approval and evidence that the approved controls operate as specified. | `UNRESOLVED` |
| Retention | Retention period and scope for source text, identifiers, hashes, annotations, logs, reports, exports, replicas, and backups. No period is chosen here. | Separate explicit retention approval and evidence of configured retention behavior. | `UNRESOLVED` |
| Deletion | Deletion triggers, scope (including replicas, backups, logs, and exports), accountable process, and verification method. No procedure is approved here. | Separate deletion approval and evidence that deletion and verification work across the approved scope. | `UNRESOLVED` |
| Reports and exports | Allowed fields, redaction rules, recipients/access roles, and treatment of source excerpts, identifiers, hashes, annotations, and derived evaluation results. A hash is not anonymization. | Approved output allowlist and reviewable evidence that generated reports/exports follow it. | `UNRESOLVED` |
| Operational status | For every control, distinguish planned, implemented, tested, and independently verified states. | Control-specific verification record; documentation alone is insufficient. | `UNRESOLVED` |

Dataset creation remains blocked until the ND-08 location/access decisions, ND-09 encryption/key-custody requirements, separation design, retention/deletion approvals, and operational evidence required by the decision-resolution plan are complete. This checklist does not establish that any control currently exists.

## ND-06/ND-07 — Joint canonicalization and hash decision checklist

**Current status: `UNRESOLVED`.** ND-06 and ND-07 must be resolved together, not as sequential independent defaults. For every row, record the selected rule, alternatives considered, rationale, affected schema/algorithm versions, failure behavior, conformance evidence, approval record, and any exclusions. Do not implement canonicalization or calculate manifest/partition hashes until all applicable rows are decided and the joint approval record exists.

Decision authority must be established through E-1 and ND-18. The plan proposes a reproducibility-owner role, but that is not an appointment. Required approval evidence is an explicit, versioned joint ND-06/ND-07 decision record from the authorized roles plus the independent reproducibility review described in the plan. Each row remains `UNRESOLVED` until then.

| Decision | Choices / trade-offs to evaluate (not selected) | Required authority and approval evidence | Downstream work blocked |
|---|---|---|---|
| Unicode and string normalization | Preserve exact code points versus define a specified normalization for designated fields; normalization changes identity/equality behavior and must be versioned. Exact-source duplicate checks currently distinguish exact UTF-8 bytes; that does not settle manifest serialization. | Authorized joint ND-06/ND-07 decision naming fields, rule/version, exclusions, and conformance cases. | Canonical serialization and any hash depending on normalized strings. |
| Line endings | Preserve line endings versus define a conversion rule; source passage offsets currently refer to unchanged text, and CRLF is two code points. | Joint decision specifying whether each serialized field preserves or transforms line endings and how versioning/conformance is handled. | Reproducible serialization, passage-derived metadata, and dependent hashes. |
| Absent field versus explicit `null` | Treat as distinct states or define a canonical equivalence; this affects schema meaning and serialized bytes. | Joint decision tied to approved schema optionality/nullability and canonical representation. | Canonical records, manifests, and dependent hashes. |
| Object/map key ordering | Define deterministic ordering and comparison/encoding rules, or prohibit maps where ordering cannot be made unambiguous. | Joint decision with testable ordering rules and failure behavior. | Deterministic serialization and hashes. |
| Numeric serialization and precision | Define accepted numeric types, precision, representation, and rejection behavior; avoid assuming that numerically equal values serialize identically. | Joint decision consistent with the frozen schema and exact serialization examples/conformance evidence. | Canonical bytes and every dependent hash. |
| Collection ordering | Identify ordered versus semantically unordered collections; define stable ordering or preserve meaningful input order as applicable. | Joint decision mapping each collection to its semantics and ordering rule. | Reproducible manifests and dataset/partition hashes. |
| Character encoding | Select and specify encoding and invalid/unrepresentable input behavior; the schema’s exact UTF-8 source text does not by itself define every manifest encoding detail. | Joint decision naming encoding, error behavior, and conformance evidence. | Canonical byte generation and hashes. |
| Exact hash input fields and bytes | Specify included/excluded fields, field framing, exact bytes, and whether any values are derived or omitted. Source hashes, passage hashes, and manifest/partition hashes must not be conflated. | Joint canonicalization decision plus ND-17 hash-input specification linked to approved schema/version. | All manifest, dataset, partition, and release hash implementation/claims. |
| Hash algorithm/version and migration | Select algorithm identifier/version and define compatibility, migration, and how old/new hashes are distinguished. No algorithm migration policy is selected here. | Joint approval specifying algorithm/version identifiers and migration/conformance procedure. | Hash implementation, verification, and cross-version reproducibility claims. |
| Logical content versus persisted bytes | Decide whether hashes represent canonical logical content or exact persisted bytes; if persisted bytes are the target, resolve the applicable representation/decoder decision (ND-05). | Joint decision linked to ND-05 only if persisted bytes are the hash target, plus explicit hash-input specification. | Persistence-dependent hashing or logical-content hashing, whichever is selected. |
| Passage derivation and offsets (ND-07) | Record the passage algorithm/version, offset units, stable ordering/ID derivation, and source/passage hash inputs. The schema document describes a proposed code-point/half-open-span behavior, not an approval of the full global serialization package. | Joint ND-06/ND-07 record and passage-rule version/conformance evidence. | Reproducible passage IDs, citation verification, and hashes relying on passage metadata. |

The joint decision record must enumerate all applicable choices, exclusions, exact hash inputs, versions, and conformance evidence. Any unresolved applicable row blocks implementation of the affected canonicalization/hash behavior. Do not treat exact UTF-8 source hashing as a substitute for manifest canonicalization, and do not describe hashes as anonymization or disclosure-safety controls.

## Separate activity gates

Statuses below reflect the reviewed design documents, not approval records. `NOT AUTHORIZED` means no separate authorization was evidenced in those documents; it does not assert that an external process has never occurred.

| Activity | Minimum separate gate/evidence | Current checklist status |
|---|---|---|
| Validator implementation | Approved schema/version, annotation and matching rules, diagnostics, verification plan, authority evidence, and separate implementation authorization. | `UNRESOLVED` / not authorized by the reviewed plan. |
| Canonicalization/hash implementation | All applicable joint ND-06/ND-07 choices approved, applicable ND-05 representation decision, ND-17 hash inputs, conformance evidence, and independent reproducibility review. | `UNRESOLVED` / not ready. |
| Development-only synthetic calibration | Separate scoped development authorization, approved synthetic inputs/guides, screening/adjudication procedure, and approved operational controls. | `UNRESOLVED` / not authorized by the reviewed plan. |
| Dataset creation | Approved ownership, storage/access, encryption, separation, retention/deletion, annotation, lineage, and partition controls plus separate dataset go/no-go. | `UNRESOLVED` / not authorized. |
| Held-out partition freeze | Completed screening/adjudication, leakage review, unresolved-link disposition, controlled access, frozen labels/artifacts, and separate freeze approval. | `UNRESOLVED` / not authorized. |
| Confirmatory evaluation | Frozen reviewed dataset/partitions/labels and protocol/thresholds, provenance specification, established authority, and separate evaluation authorization. | `UNRESOLVED` / not authorized. |
| Provider integration | Separate provider/data-handling/security/budget/activation/credential/endpoint/request approvals and future authorized preflight. | `UNRESOLVED` / not authorized. |

Passing one gate does not authorize a later gate. This checklist does not load or configure credentials, select a provider, authorize external requests, or establish real-world model quality.
