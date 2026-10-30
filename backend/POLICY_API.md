# Offline policy comparison API

This isolated API serves the synthetic policy comparison workflow. It does not
import the handover app, use a provider, or read or write a database. It is not
connected to the static demo page.

## Local launch

From the repository root in PowerShell, use the already installed hackathon
environment:

```powershell
$env:PYTHONPATH = (Resolve-Path hackathon\backend).Path
.\hackathon\.venv\Scripts\python.exe -m policy_api
```

The supported entry point binds only to `127.0.0.1:8082`. The port is fixed; if
it is occupied, startup fails rather than choosing another port. The Vite page
is served at `http://127.0.0.1:5174`. CORS permits only that exact origin, only
`POST`, and only the `Content-Type` request header; credentials are disabled.
No wildcard browser origin is enabled. Serve the page through Vite rather than
opening it as a `file://` URL.

## Endpoints

- `GET /health` returns fixed readiness metadata without accessing a provider,
  filesystem data, or database.
- `POST /policy-comparisons` accepts an `application/json` object matching
  `policy_compare.validate_policy_pair` and is limited to 512,000 request bytes.
  Extra fields are rejected by that strict contract. It returns the existing
  orchestration result with proposal-only status, human review required, and
  `INCONCLUSIVE` classification.

The endpoint constructs only a deterministic `FakePolicyCandidateAdapter`
response. It cites bounded excerpts from the supplied versions but abstains
from semantic assessment; exact citation provenance does not establish
semantic support, precedence, complete coverage, or operational impact.
Malformed bodies and policy inputs receive fixed errors; raw exception text
and request contents are not returned. Requests and results are not persisted.

Use synthetic policy text only. The API validates the synthetic identifier
format but cannot determine whether supplied text contains real or confidential
policy material. The localhost listener is an application boundary, not a
security sandbox against malicious same-process code.
