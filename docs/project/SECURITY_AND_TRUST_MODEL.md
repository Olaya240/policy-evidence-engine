# Security and trust model

## Current trust boundaries

This is local prototype software, not a production service. The legacy handover README states there is no authentication. No production identity, role system, or deployment access-control scheme is established. Its in-process access context/filter is not authentication.

Policy API docs describe loopback binding, strict input validation, request bounds, fixed errors and no persistence. Those are application-level boundaries; they do not turn Python into a sandbox. The demo is intended for fictional synthetic material only. A localhost listener is not an authorization boundary against other local processes.

## Provider and evidence trust

The handover backend defaults to `MockProvider`. Meta Muse Spark is an optional provider selected only when `ENABLE_META`, `MODEL_API_KEY`, and all three Meta budget variables are valid; it reads the credential only in the backend process. `ENABLE_BASETEN` and `ENABLE_META` together fail closed to mock. The standalone policy-comparison API uses `FakePolicyCandidateAdapter`; the React Policy Demo is a separate synthetic workflow. Provider attribution comes from the invoked instance, may include a bounded response request ID and token counts, and resolves to `unknown` for legacy or unidentifiable records. The previous one-request assessment remains inconclusive as to provider.

Quotes and citations establish provenance only. Semantic support, applicability, precedence, complete coverage, and operational impact need separate evidence and human review. Source text is untrusted data; provider proposals are not authoritative conclusions.

## Data isolation and auditability

The policy demo keeps session history in process memory; it is ephemeral. The older handover application stores data through SQLite code, but this review did not inspect database state. Policy graph persistence remains design-only and blocked. No assurance about deployed isolation, retention, backups, or access logs can be made.

## Risks and unresolved matters

There is no production authentication; mock/fake content can be mistaken for validated analysis; exact quote provenance can be overread; in-process Python can be deliberately modified; local SQLite behavior is not a security boundary; retention and access governance for any future real sources are unsettled; raw source sidecars have no approval for capture or retention. No security test or runtime exercise was performed for this document package.
