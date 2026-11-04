# Story Connect AI — Policy Evidence Engine and isolated handover prototype

This repository contains a synthetic policy comparison demo, a separate synthetic policy demo UI/API, and a handover investigation prototype. The policy graph persistence contract remains documentation/specification only; database execution remains BLOCKED and the prototype gate remains CLOSED.

The project documentation package is indexed at [`docs/project/PROJECT_DOCUMENTATION_INDEX.md`](docs/project/PROJECT_DOCUMENTATION_INDEX.md). It distinguishes implemented source paths from isolated modules and proposed persistence work.

The policy comparison API uses synthetic inputs and a fake adapter. The Policy Demo uses fictional scenarios and an in-memory session API. The separate handover backend defaults to `MockProvider`; it can optionally use Meta Muse Spark when explicitly enabled in the backend process. These workflows are not HR policy Q&A or document retrieval. The handover application has no authentication and is not production software. Exact citation provenance does not establish semantic support or applicability; human review is required.

Local databases, environment files, credentials, build artifacts, and caches are excluded by `.gitignore`.

---

## Handover investigation prototype

Local prototype for reviewing recurring missing information in hotel shift handovers. All included records are synthetic. Findings are decision support: a human must review the source evidence, uncertainty, and conflicts. Correlation is not proof of causation. This prototype has no authentication, is not production-ready, must not be used for employee ranking, blame, disciplinary decisions, or employment decisions, and must not connect to the existing PFA database or production services.

## Requirements and launch

- Python 3.10+ and `pip` for the backend.
- Node.js 22.6+ and npm for the frontend. The test suite uses Node's `--experimental-strip-types` flag, introduced in Node 22.6; the frontend dependencies are declared locally in `frontend/package.json`.
- From the repository root, create a Python environment and install backend requirements with `python -m venv .venv`, activate it, then run `python -m pip install -r backend/requirements.txt`. Install declared frontend dependencies with `npm ci` from `frontend/`.
- The synthetic Policy Demo at `http://127.0.0.1:5174/#/demo` uses the existing offline launcher: run `python scripts/launch_policy_demo.py` from the repository root. It starts only the API on `127.0.0.1:8083` and Vite on `127.0.0.1:5174`; it does not start the handover backend or policy-comparison API. Press Ctrl+C to stop the foreground launcher, or use `python scripts/launch_policy_demo.py --stop` for its tracked background processes.
- The separate handover UI/backend uses Vite port 5174 and FastAPI port 8081. From the repository root in PowerShell, set `$env:PYTHONPATH = (Resolve-Path backend).Path`; initialize the local synthetic database with `python -m app.store init`, then start `python -m uvicorn app.main:app --host 127.0.0.1 --port 8081`. Start the frontend with `npm run dev` from `frontend/`. The default database is `data/prototype.sqlite3`; `HACKATHON_DB_PATH` may select another permitted local prototype path. API docs are at `http://127.0.0.1:8081/docs`.
- The frontend proxies `/api` to the handover backend on port 8081 and `/demo-api` to the Policy Demo API on port 8083. The standalone policy-comparison API on port 8082 is a separate workflow and is not part of that proxy.
- Launcher shutdown checks recorded executable and command-line identity, but PID reuse and a check-to-stop race remain possible; Windows tree termination can affect descendants.
- Backend tests use temporary SQLite files. From the repository root with the backend environment active, run `python -m pytest -q backend/tests`. From `frontend/`, use `npm test`, `npm run typecheck`, or `npm run build`.

Initialization is explicit; importing modules and collecting tests does not create a database. The API refuses database-backed operations until initialization has been run. No endpoint exposes the restricted canary record. The access-control filter has an isolated unit test; its in-process context is not authentication.

The root `.gitignore` excludes local SQLite databases, environment files, and generated build/cache artifacts. Keep local runtime data and credentials out of commits.

## Local API

The handover backend defaults to `MockProvider`. Optional Meta Muse Spark activation requires the backend process variables `ENABLE_META`, `MODEL_API_KEY`, `META_MAX_REQUESTS`, `META_MAX_ESTIMATED_COST_USD`, and `META_CONSERVATIVE_COST_PER_REQUEST_USD`; `ENABLE_BASETEN` must not be enabled at the same time. The credential stays in the backend environment and is never a Vite variable. See [Meta provider notes](backend/META_PROVIDER.md). Activation does not connect the Policy Demo or policy-comparison API to Meta.

- `GET /api/health`
- `GET /api/records`
- `POST /api/investigations` with `{ "question": "..." }`
- `GET /api/investigations/{id}`
- `POST /api/investigations/{id}/claims/{claim_id}/challenge` with `{ "reason": "...", "source_record_id": "...", "quote": "exact source substring" }`
- `GET /api/investigations/{id}/history`

Assessments are `SUPPORTED`, `PARTIAL`, `CONTRADICTED`, or `INSUFFICIENT`; source stances are `SUPPORTS`, `CONTRADICTS`, and `NEUTRAL`. Quotes are independently validated as exact source substrings. Quote presence is not semantic support. A neutral source is not evidence against a hypothesis. Revisions are append-only; challenge recomputation follows stored source dependencies outside the write transaction, then checks the captured revision and atomically writes affected claim versions and before/after history. Stale computations return 409 for reload and retry.

## Local evidence evaluation

Run the deterministic synthetic gold-set harness from the repository root with the backend environment:

```powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
.\.venv\Scripts\python.exe -m app.evaluate
```

Gold labels and case rationales are in `backend/evaluation/gold_cases.json`; the original 14 labels are retained and the added adversarial cases are fixture judgments independent of engine output. The evaluator reports unguarded baseline and guarded results over the same cases, including false-support and false-neutral rates over explicit gold-label denominators. It creates then removes uniquely named SQLite files under `data/` for recomputation/history checks. Its 21-case synthetic set is a regression harness, not a general performance estimate.

The guard is a deliberately narrow phrase cue list for the five current prototype hypotheses. It checks the quoted text after exact-substring provenance validation, retains the proposed stance for audit, and downgrades a mismatch or unknown relation to `NEUTRAL`; it never flips a proposal to the opposite stance. It replaces provider rationale with fixed non-causal wording. This catches some included irrelevant and neutral-as-contradiction examples, but evaluation also demonstrates substantial false-neutral behavior on paraphrases and alternative wording. It cannot reliably understand arbitrary language, paraphrases, negation, context, partial semantic entailment, or causation. Unmatched evidence may be downgraded even when a human would find it relevant. Treat this as a local regression guard, not general semantic validation or a substitute for human review.

