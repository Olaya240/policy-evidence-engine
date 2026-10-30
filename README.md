# Story Connect AI — Policy Evidence Engine and isolated handover prototype

This directory contains the offline **Policy Evidence Engine** project: a synthetic policy-change demo, an isolated policy comparison API, an in-memory policy graph and challenge planner, and a separate handover investigation prototype. The policy persistence contract is documentation/specification only; database execution remains BLOCKED and the prototype gate remains CLOSED.

The project documentation package is indexed at [`docs/project/PROJECT_DOCUMENTATION_INDEX.md`](docs/project/PROJECT_DOCUMENTATION_INDEX.md). It distinguishes implemented source paths from isolated modules and proposed persistence/provider work.

The policy comparison and policy demo use synthetic fixtures and fake adapters. The handover application remains a local prototype without authentication. No real external model provider is connected. Exact citation provenance does not establish semantic support or applicability; human review is required.

The publication excludes the governance, provider, and policy-persistence documents shown in the requested screenshots. Local databases, environment files, credentials, build artifacts, and caches are also excluded by `.gitignore`.

---

## Handover investigation prototype

Local prototype for reviewing recurring missing information in hotel shift handovers. All included records are synthetic. Findings are decision support: a human must review the source evidence, uncertainty, and conflicts. Correlation is not proof of causation. This prototype has no authentication, is not production-ready, must not be used for employee ranking, blame, disciplinary decisions, or employment decisions, and must not connect to the existing PFA database or production services.

## Requirements and launch

- Python 3.10+ and `pip` for the backend.
- Node.js 20+ and npm for the frontend. The frontend dependencies are declared locally in `frontend/package.json`.
- Install dependencies only into a dedicated prototype environment when ready: `python -m venv hackathon/.venv`, activate it, then `pip install -r hackathon/backend/requirements.txt`. From `hackathon/frontend`, run `npm install`.
- From the repository root, initialize the local synthetic database: `PYTHONPATH=hackathon/backend python -m app.store init` (PowerShell: `$env:PYTHONPATH='hackathon/backend'; python -m app.store init`). The default path is `hackathon/data/prototype.sqlite3`; override with `HACKATHON_DB_PATH` only to another local prototype path.
- From the repository root, start the backend: `PYTHONPATH=hackathon/backend uvicorn app.main:app --reload --port 8081` (PowerShell: `$env:PYTHONPATH='hackathon/backend'; uvicorn app.main:app --reload --port 8081`). API docs are at `http://127.0.0.1:8081/docs`.
- In another terminal, from `hackathon/frontend`, run `npm run dev`. Vite serves the UI at `http://127.0.0.1:5174`, proxies `/api` to the handover application at `127.0.0.1:8081`, and proxies `/demo-api` to the isolated policy demo API at `127.0.0.1:8083`. The active Policy API is not part of this demo proxy.
- Launcher shutdown checks the recorded executable and command line to reduce accidental termination. PID reuse and the check-to-kill race remain possible, and Windows `taskkill /T` can affect descendant processes.
- Backend tests use uniquely named temporary SQLite databases inside `hackathon/data/` and remove them during fixture teardown; they do not use the default development database. From the repository root with the backend environment active, run `PYTHONPATH=hackathon/backend pytest -q hackathon/backend/tests` (PowerShell: `$env:PYTHONPATH=(Resolve-Path hackathon/backend).Path; .\hackathon\.venv\Scripts\python.exe -m pytest -q hackathon\backend\tests`). Frontend typecheck: from `hackathon/frontend`, run `npm run typecheck`.

Initialization is explicit; importing modules and collecting tests does not create a database. The API refuses database-backed operations until initialization has been run. No endpoint exposes the restricted canary record. The access-control filter has an isolated unit test; its in-process context is not authentication.

The repository's existing `.gitignore` does not cover `hackathon/data/`; the synthetic SQLite file will appear as an untracked local artifact after initialization. Do not stage or commit that runtime file. No repository-wide ignore rules were changed for this isolated phase.

## Local API

See [AI_PROVIDER_BOUNDARY.md](AI_PROVIDER_BOUNDARY.md) for the current offline provider contract, deterministic validation rules, failure handling, and prerequisites for any future provider adapter.

See [SEMANTIC_PROVIDER_EXPERIMENT.md](SEMANTIC_PROVIDER_EXPERIMENT.md) for the controlled, synthetic-only plan to compare a future model-assisted assessor with the measured baseline and phrase-cue guard. It does not enable a provider or authorize API calls.

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
$env:PYTHONPATH = (Resolve-Path hackathon\backend).Path
.\hackathon\.venv\Scripts\python.exe -m app.evaluate
```

Gold labels and case rationales are in `backend/evaluation/gold_cases.json`; the original 14 labels are retained and the added adversarial cases are fixture judgments independent of engine output. The evaluator reports unguarded baseline and guarded results over the same cases, including false-support and false-neutral rates over explicit gold-label denominators. It creates then removes uniquely named SQLite files under `hackathon/data/` for recomputation/history checks. Its 21-case synthetic set is a regression harness, not a general performance estimate.

The guard is a deliberately narrow phrase cue list for the five current prototype hypotheses. It checks the quoted text after exact-substring provenance validation, retains the proposed stance for audit, and downgrades a mismatch or unknown relation to `NEUTRAL`; it never flips a proposal to the opposite stance. It replaces provider rationale with fixed non-causal wording. This catches some included irrelevant and neutral-as-contradiction examples, but evaluation also demonstrates substantial false-neutral behavior on paraphrases and alternative wording. It cannot reliably understand arbitrary language, paraphrases, negation, context, partial semantic entailment, or causation. Unmatched evidence may be downgraded even when a human would find it relevant. Treat this as a local regression guard, not general semantic validation or a substitute for human review.

