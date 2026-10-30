# Data and persistence design

## Existing application data paths

The legacy handover app defines SQLite storage through `backend/app/store.py` and requires explicit initialization. This is separate from the policy demo, whose session manager is in memory and loses state when the process stops. This review did not open or inspect any SQLite file and makes no claims about database contents or runtime verification.

The policy graph persistence design is governed by `POLICY_GRAPH_PERSISTENCE_CONTRACT.md`. It defines a future snapshot/normalized-row contract, including graph serialization, canonicalization, digests, keys, relational constraints and transaction invariants. Its existence does not mean policy graph persistence is implemented.

## Canonicalization and digest concepts

The operative contract defines exact graph shape and canonicalization requirements; D30-01 records owner approval to sort contract-declared set-like arrays using specified comparators, reject duplicates, preserve semantically ordered arrays, and retain JCS object-key ordering. This owner decision does not amend the operative contract or authorize implementation. Golden vectors are specification evidence, not a running serializer.

Decoded-source identity is computed over decoded text under the contract’s stated domain/version tuple. Raw-source identity refers to original source bytes and requires separately supplied sidecar information; it cannot be derived from the graph’s decoded text. Relational references and passage/evidence child rows have separate identities.

## Snapshot, transaction and integrity concepts

The future design requires stable snapshot scope keys, exact node/edge identity, normalized row comparisons, foreign-key integrity, atomic snapshot writes and rejection of inconsistent state. Exact mapping of all 18 `snapshot_node` columns across eight node variants is still subject to individual decisions. D30-02/D30-10 approval is methodology-only; no individual mapping or NULL is thereby approved.

## Unresolved design and gates

RT-01, RT-02 and RT-03 remain INCOMPLETE. Needed decisions include per-node candidate/document/version identity, digest tuple population, raw sidecar binding, claim citation cardinality, challenge target identity, evidence-passage resolution, canonical node-byte extraction, and complete fixture keys/oracles. Phase 20A sequencing is Option B. Database execution is BLOCKED and the prototype gate is CLOSED. No schema or contract behavior is changed by this document.
