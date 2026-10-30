# Glossary

| Term | Meaning |
|---|---|
| Policy version | A particular identified revision of a source policy document. |
| Source passage | A bounded portion of a versioned source, identified by offsets and provenance data. |
| Claim | A candidate statement about a policy or its effects, linked to evidence and dependencies. |
| Applicability | Whether a policy requirement governs a scope such as a department or property. |
| Evidence | A source or observation offered in support of review; it may be incomplete or disputed. |
| Provenance | Where content came from and how it is linked to the source. Exact quote matching establishes provenance, not semantic support. |
| Dependency graph | Typed nodes and edges describing source, claim, applicability, relation, conclusion and challenge connections. |
| Challenge event | A recorded reviewer objection or request to inspect evidence/interpretation. |
| Impact propagation | Bounded traversal estimating which dependent nodes may require review. |
| Reassessment | Recomputing a conclusion after relevant evidence, assumptions, or versions change. |
| Conclusion | A candidate result with an epistemic status and uncertainty; not necessarily authoritative. |
| Epistemic status | A label describing what is known, supported, unknown, or unresolved. |
| Canonical serialization | A deterministic byte representation of structured data, so equivalent valid inputs can be compared consistently. |
| Decoded-source identity | Digest identity of decoded source text under a specified encoding/domain/version rule. |
| Raw-source identity | Digest identity of original source bytes; separate from decoded text and requires sidecar input. |
| Human review | A person checks evidence, uncertainty, scope and consequences before relying on a result. |
| Fake adapter | Deterministic local fixture implementation used instead of an external model/provider. |
| Option B | Phase 20A sequencing choice for offline documentation/specification preparation, with database work deferred. |
