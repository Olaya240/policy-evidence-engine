# Policy Demo Baseten provider

The Policy Demo now has a policy-specific proposal provider interface in
`policy_baseten_provider.py`. It does not reuse the Handover Assessment
adapter. The existing deterministic synthetic provider remains the default.

## Runtime status

The transport is implemented and uses the configured Model APIs Chat
Completions endpoint at
`https://inference.baseten.co/v1/chat/completions`, bearer-key authentication,
and the fixed model slug `meta-models/muse-spark-open-1026`. It sends no model
override from frontend input. Provider responses remain proposals and pass
through the local strict citation contract before deterministic comparison.

Baseten is opt-in; synthetic remains the default. Selecting
`POLICY_DEMO_PROVIDER=baseten` can make an outbound remote inference request.
Live Baseten execution has not been verified successfully. When Baseten is
selected, missing configuration or provider failure returns a sanitized error;
the API does not silently fall back to a synthetic proposal.

## Configuration names reserved for activation

These backend process environment variable names define the configuration
boundary:

- `POLICY_DEMO_PROVIDER` (`synthetic` by default; set to `baseten` to opt in)
- `BASETEN_API_KEY` (backend only)
- `POLICY_DEMO_BASETEN_MAX_REQUESTS`
- `POLICY_DEMO_BASETEN_MAX_ESTIMATED_COST_USD`
- `POLICY_DEMO_BASETEN_CONSERVATIVE_COST_PER_REQUEST_USD`

The model slug is pinned in code. Set `POLICY_DEMO_PROVIDER=baseten` only for
an explicitly authorized live test; keep request and cost budgets small.
Provider selection and its request/cost gate are initialized once per backend
process, so route calls cannot reset the budget. Restart the backend to apply
configuration changes.

## Scenario, session, and challenge request costs

Each successful `GET /demo-api/scenario` computes a new proposal and can make
one Baseten request when Baseten is selected. The response includes a random
`proposal_id`; session creation must present that ID and binds a bounded,
immutable snapshot of the exact displayed proposal. A pending snapshot can be
consumed once and expires when the bounded pending-snapshot capacity evicts it.
Challenges require the session and proposal IDs and recompute from that bound
snapshot. Session creation and challenges make no provider request, so they do
not consume additional provider request or estimated-cost budget. Reloading or
requesting another scenario computes a new proposal and can consume another
request. Provider selection and the configured request/cost gate still apply
to each such scenario request.

## Deterministic trust boundary

The provider returns only proposal fields. `normalize_proposal_response`
validates the request ID, relation, abstention, source passage IDs, and exact
quotes, and derives citation offsets and hashes locally. The existing policy
comparison engine computes the final classification and retains proposal-only,
unverified semantic support, and human-review requirements. Challenges
recompute locally from the original proposal snapshot and retain its provider
attribution; they do not ask the provider to override applicability or policy
evidence.
