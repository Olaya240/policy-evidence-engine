# Meta Muse Spark provider (backend only)

The main backend can explicitly select Meta through `ENABLE_META=1`. It reads
`MODEL_API_KEY` from the backend process environment. The React/Vite application
must never receive this variable. Mock remains the default. If Meta activation
is incomplete or refused, startup logs a sanitized reason and keeps the mock;
once Meta is active, request failures are returned as provider failures and do
not fall back to mock results.

Activation also requires all three budget settings:

```text
META_MAX_REQUESTS
META_MAX_ESTIMATED_COST_USD
META_CONSERVATIVE_COST_PER_REQUEST_USD
```

For a one-request test, set the request limit to `1` and set both cost values
to an operator-approved positive estimate with the total at least equal to the
per-request estimate. The existing budget validator imposes the configured
maximum. `ENABLE_META` and `ENABLE_BASETEN` cannot be enabled together; that
configuration fails closed to MockProvider.

The adapter is pinned to `https://api.meta.ai/v1/chat/completions` and
`muse-spark-1.3`. It uses HTTPX already declared in `requirements.txt`; it does
not load `.env` files. Configure the environment for the backend process using
the local shell or a secret manager. Do not put secrets in source, frontend
variables, or committed files. A real call is a separate, explicit operation.

The adapter belongs to the main assessment engine used by the handover API. The
React Policy Demo is a separate synthetic workflow and is not connected to this
provider. This provider integration does not implement HR policy Q&A, document
retrieval, or source references for answers.

Each new claim records `provider_attribution` from the provider instance that
was invoked: `meta`, `baseten`, or `mock`. A validated response may also include
a bounded request ID and token usage when those fields are supplied. Legacy
claims without attribution resolve to `unknown`; existing results are not
retroactively classified. The one-request assessment performed on 2026-11-03
remains **INCONCLUSIVE** as to provider because its response and database did
not identify a provider.
