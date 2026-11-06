"""FastAPI local API. Does not initialize the database or make network calls."""
import json
import logging
import os
from collections.abc import Mapping
from copy import deepcopy

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .access import visible_records
from .engine import AssessmentEngine, AssessmentError, ProviderError
from .local_env import load_backend_env_file
from .models import (ChallengeCreate, HistoryEntry, IngestCreate, Investigation,
                     InvestigationCreate, InvestigationPreset,
                     INVESTIGATION_PRESET_HYPOTHESES,
                     INVESTIGATION_PRESET_QUESTIONS, Record)
from .provider_activation import (BASETEN_API_KEY_ENV_VAR,
                                 ProviderActivationError,
                                 create_assessment_engine,
                                 create_meta_assessment_engine)
from .provider_safety import ProviderBudgetConfig
from .rate_limit import TokenBucketRateLimiter
from . import ingest, store

logger = logging.getLogger(__name__)

# Activation is opt-in through the environment and default-off. The flag is
# necessary but never sufficient: the key and every budget input must also be
# supplied, so no credential or misconfiguration can switch the network
# provider on by itself.
ACTIVATE_BASETEN_ENV_VAR = "ENABLE_BASETEN"
BASETEN_MAX_REQUESTS_ENV_VAR = "BASETEN_MAX_REQUESTS"
BASETEN_MAX_ESTIMATED_COST_ENV_VAR = "BASETEN_MAX_ESTIMATED_COST_USD"
BASETEN_CONSERVATIVE_COST_ENV_VAR = "BASETEN_CONSERVATIVE_COST_PER_REQUEST_USD"
_ACTIVATION_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})
_ACTIVATION_DISABLED_VALUES = frozenset({"", "0", "false", "no", "off"})
META_API_KEY_ENV_VAR = "MODEL_API_KEY"
ACTIVATE_META_ENV_VAR = "ENABLE_META"
META_MAX_REQUESTS_ENV_VAR = "META_MAX_REQUESTS"
META_MAX_ESTIMATED_COST_ENV_VAR = "META_MAX_ESTIMATED_COST_USD"
META_CONSERVATIVE_COST_ENV_VAR = "META_CONSERVATIVE_COST_PER_REQUEST_USD"


def _activation_requested(environ: Mapping[str, str]) -> bool:
    """Read the flag as an explicit literal; an unrecognised value is off."""
    raw = environ.get(ACTIVATE_BASETEN_ENV_VAR)
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in _ACTIVATION_ENABLED_VALUES:
        return True
    if value in _ACTIVATION_DISABLED_VALUES:
        return False
    logger.warning(
        "%s is not a recognised activation value; serving the mock provider. "
        "Set it to one of %s to request Baseten activation.",
        ACTIVATE_BASETEN_ENV_VAR, sorted(_ACTIVATION_ENABLED_VALUES))
    return False


def _meta_activation_requested(environ: Mapping[str, str]) -> bool:
    raw = environ.get(ACTIVATE_META_ENV_VAR)
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in _ACTIVATION_ENABLED_VALUES:
        return True
    if value in _ACTIVATION_DISABLED_VALUES:
        return False
    logger.warning("%s is not a recognised activation value; serving the mock provider.", ACTIVATE_META_ENV_VAR)
    return False


def _budget_from_environment(environ: Mapping[str, str]) -> ProviderBudgetConfig | None:
    """Return the explicit budget, or None when any of its inputs is absent or malformed."""
    max_requests = environ.get(BASETEN_MAX_REQUESTS_ENV_VAR)
    ceiling = environ.get(BASETEN_MAX_ESTIMATED_COST_ENV_VAR)
    per_request = environ.get(BASETEN_CONSERVATIVE_COST_ENV_VAR)
    if not max_requests or not ceiling or not per_request:
        return None
    try:
        parsed_requests = int(max_requests)
    except (TypeError, ValueError):
        return None
    return ProviderBudgetConfig(
        enabled=True,
        max_requests=parsed_requests,
        max_estimated_cost_usd=ceiling,
        conservative_cost_per_request_usd=per_request,
    )


def _meta_budget_from_environment(environ: Mapping[str, str]) -> ProviderBudgetConfig | None:
    values = (environ.get(META_MAX_REQUESTS_ENV_VAR), environ.get(META_MAX_ESTIMATED_COST_ENV_VAR),
              environ.get(META_CONSERVATIVE_COST_ENV_VAR))
    if not all(values):
        return None
    try:
        count = int(values[0])
    except (TypeError, ValueError):
        return None
    return ProviderBudgetConfig(enabled=True, max_requests=count,
        max_estimated_cost_usd=values[1], conservative_cost_per_request_usd=values[2])


def _environment_key_source(environ: Mapping[str, str]):
    """Hand the factory a callable instead of the secret, read only after validation."""
    def key_source():
        return environ[BASETEN_API_KEY_ENV_VAR]

    return key_source


def build_engine_from_environment(environ: Mapping[str, str]) -> AssessmentEngine:
    """Compose the process engine: MockProvider by default; Meta or Baseten only on explicit request.

    Each optional provider requires its affirmative activation flag, a key in
    the corresponding backend environment variable, and its three budget
    inputs. If both providers are requested, or activation is incomplete or
    invalid, this function returns MockProvider and logs only a sanitized
    reason. Provider request failures after activation do not fall back to mock.
    """
    meta_requested = _meta_activation_requested(environ)
    baseten_requested = _activation_requested(environ)
    if meta_requested and baseten_requested:
        logger.warning("Both ENABLE_META and ENABLE_BASETEN are enabled; serving the mock provider.")
        return create_assessment_engine()
    if meta_requested:
        if not environ.get(META_API_KEY_ENV_VAR):
            logger.warning("Meta activation was refused (key_source_required); serving the mock provider.")
            return create_assessment_engine()
        try:
            return create_meta_assessment_engine(
                key_source=lambda: environ[META_API_KEY_ENV_VAR],
                budget_config=_meta_budget_from_environment(environ),
            )
        except ProviderActivationError as error:
            logger.warning("Meta provider activation was refused (%s); serving the mock provider.", error.code)
        except Exception:
            logger.warning("Meta provider activation failed unexpectedly; serving the mock provider.")
        return create_assessment_engine()
    if not baseten_requested:
        if environ.get(BASETEN_API_KEY_ENV_VAR):
            logger.warning(
                "%s is set but %s is not enabled; serving the mock provider and "
                "ignoring the key. Set %s=1 to request Baseten activation.",
                BASETEN_API_KEY_ENV_VAR, ACTIVATE_BASETEN_ENV_VAR,
                ACTIVATE_BASETEN_ENV_VAR)
        return create_assessment_engine()

    key_source = None
    if environ.get(BASETEN_API_KEY_ENV_VAR):
        key_source = _environment_key_source(environ)
    try:
        return create_assessment_engine(
            activate_baseten=True,
            key_source=key_source,
            budget_config=_budget_from_environment(environ),
        )
    except ProviderActivationError as error:
        logger.warning(
            "Baseten provider activation was refused (%s); serving the mock provider.",
            error.code)
    except Exception:  # the composition root must never fail to start
        logger.warning(
            "Baseten provider activation failed unexpectedly; serving the mock provider.")
    return create_assessment_engine()


app = FastAPI(title="Story Connect Handover Investigation Prototype", version="0.1.0",
              description="Synthetic local decision support. Findings require human review; this is not production software.")


def _json_safe(value):
    """Make a validation-error value renderable as UTF-8 JSON.

    A lone surrogate is legal in a JSON escape and illegal in UTF-8. Starlette's
    default validation handler echoes the offending input back through
    `json.dumps(..., ensure_ascii=False).encode("utf-8")`, so a body containing
    `\\ud800` raised `UnicodeEncodeError` inside the error handler itself — a 500
    from a 422 path, reachable by any client.
    """
    try:
        json.dumps(value, allow_nan=False)
        return value
    except (TypeError, ValueError):
        return "<unrenderable>"


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        item = {
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        if "input" in error:
            item["input"] = _json_safe(error["input"])
        errors.append(item)
    # `json.dumps` here keeps `ensure_ascii=True`, so a surrogate is escaped rather
    # than encoded, and a non-finite number cannot masquerade as JSON.
    return Response(
        content=json.dumps({"detail": errors}, allow_nan=False),
        media_type="application/json",
        status_code=422,
    )


app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
                   allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
# Fill unset documented variables from backend-only backend/.env. The real
# process environment wins; see app/local_env.py. Skipped under pytest.
load_backend_env_file()
engine = build_engine_from_environment(os.environ)

# Threat row H8: nothing bounded request volume before this. The prototype is
# single-user and local, so the limit is deliberately generous — it exists to stop
# a runaway loop or a hostile local process, not to police a shared service. The
# limiter is a module attribute so a test (or a deployment) can replace it without
# touching the routes.
rate_limiter = TokenBucketRateLimiter(limit=600, window_seconds=60.0)


# Health is exempt. Metring it made the probe go 429 under exactly the load an
# operator needs it for, so the flood suppressed the signal it was supposed to
# describe; the route is a constant-size read with no database writes, so leaving
# it unmetered costs nothing an attacker can use.
_RATE_LIMIT_EXEMPT_PATHS = frozenset({"/api/health"})


@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    if request.url.path in _RATE_LIMIT_EXEMPT_PATHS:
        return await call_next(request)
    decision = rate_limiter.check(request.client.host if request.client else "unknown")
    if not decision.allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests; retry later."},
            headers={"Retry-After": decision.retry_after_header},
        )
    return await call_next(request)


@app.exception_handler(store.DatabaseUnavailable)
async def database_unavailable_handler(_request, _exc: store.DatabaseUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Local prototype database is unavailable."})


@app.exception_handler(ProviderError)
async def provider_error_handler(_request: Request, exc: ProviderError) -> JSONResponse:
    # `request_too_large` is raised before any provider call, when the eligible
    # corpus cannot be serialised inside the bounded request. Reporting it as an
    # outage told the client to retry something that can never succeed.
    if exc.code == "request_too_large":
        return JSONResponse(
            status_code=413,
            content={"detail": "The evidence corpus exceeds the bounded provider request budget."},
        )
    if exc.code == "proposal_capacity_exceeded":
        return JSONResponse(
            status_code=413,
            content={"detail": "The evidence corpus exceeds the proposal budget for one assessment."},
        )
    return JSONResponse(status_code=503, content={"detail": "Assessment provider is unavailable or returned invalid output."})


def require_database() -> None:
    try:
        path = store.database_path()
        if not path.is_file():
            raise HTTPException(status_code=503, detail="Local prototype database is not initialized. Run `PYTHONPATH=backend python -m app.store init` from the repository root (see README.md).")
    except (OSError, ValueError, store.DatabaseUnavailable):
        raise HTTPException(status_code=503, detail="Local prototype database is not initialized. Run `PYTHONPATH=backend python -m app.store init` from the repository root (see README.md).")


def _prepare_investigation_response(investigation: dict) -> dict:
    """Add response-only compatibility fields without trusting stored values."""
    response = deepcopy(investigation)
    response["preset_id"] = _derive_preset_id(response)
    for claim in response["claims"]:
        for evidence in claim["evidence"]:
            if "review_state" not in evidence:
                evidence["review_state"] = "UNVERIFIED"
    return response


def _mark_unavailable_traces_in_snapshots(value: dict) -> dict:
    """Mark legacy snapshot traces unavailable in response copies only."""
    response = deepcopy(value)
    for snapshot_name in ("before", "after"):
        snapshots = response.get(snapshot_name)
        if type(snapshots) is not dict:
            continue
        for claim in snapshots.values():
            if type(claim) is dict and "explanation_trace" not in claim:
                claim["explanation_trace"] = None
    return response


def _derive_preset_id(investigation: dict) -> InvestigationPreset | None:
    """Infer a preset only from its canonical question and matching single claim."""
    question = investigation.get("question")
    claims = investigation.get("claims")
    if type(claims) is not list or len(claims) != 1 or type(claims[0]) is not dict:
        return None
    claim = claims[0]
    for preset_id, canonical_question in INVESTIGATION_PRESET_QUESTIONS.items():
        hypothesis_id = INVESTIGATION_PRESET_HYPOTHESES[preset_id]
        if (question == canonical_question
                and claim.get("id") == hypothesis_id
                and claim.get("hypothesis_id") == hypothesis_id):
            return preset_id
    return None


@app.get("/api/health")
def health() -> dict:
    # A rejected path and an uninitialised one are different states: the first is a
    # configuration error that makes every data route 503, the second is a normal
    # first run. Reporting both as "ok" made the health signal disagree with the
    # availability it is supposed to describe.
    misconfigured = False
    try:
        path = store.database_path()
        initialized = path.is_file()
    except ValueError:
        misconfigured = True
        initialized = False
    except OSError:
        initialized = False
    available = False
    if initialized:
        try:
            with store.connect() as db:
                # `SELECT 1` is a constant expression: SQLite answers it without
                # reading the file header, so a corrupt database reported healthy.
                # `PRAGMA schema_version` reads page 1 and fails loudly instead.
                db.execute("PRAGMA schema_version").fetchone()
            available = True
        except store.DatabaseUnavailable:
            pass
    if misconfigured:
        status = "misconfigured"
    else:
        status = "ok" if not initialized or available else "degraded"
    return {"status": status, "prototype": True, "synthetic_data_only": True, "database_initialized": initialized, "database_available": available,
            "authentication": False, "human_review_required": True}


@app.get("/api/records", response_model=list[Record])
def records(response: Response) -> list[Record]:
    """The readable corpus, with the skipped rows named in headers.

    A list read needs many rows and no row in particular, so one corrupt record
    must not make the corpus unreadable. It must also not be silent: the caller
    learns the count and the ids from `X-Unreadable-Rows` /
    `X-Unreadable-Row-Ids`, because "skipped and reported" is false if only the
    server log knows.
    """
    require_database()
    rows, skipped = store.list_records_with_report()
    if skipped:
        response.headers["X-Unreadable-Rows"] = str(len(skipped))
        response.headers["X-Unreadable-Row-Ids"] = ",".join(row.row_id for row in skipped)[:1024]
    return visible_records(rows)


@app.post("/api/records/ingest", status_code=201)
def ingest_record(payload: IngestCreate, response: Response) -> dict:
    """Ingest one plain-text document as a record.

    Scope, the duplicate rule and the 200-vs-409 choice are stated in
    ``app/ingest.py``. 201 with the new record, or 200 with the record already
    stored for the same normalised text, department and source group.
    """
    require_database()
    outcome = ingest.ingest_text(payload)
    if not outcome.created:
        response.status_code = 200
    return {"id": outcome.record.id, "record": outcome.record, "created": outcome.created}


@app.post("/api/investigations", response_model=Investigation, status_code=201)
def create_investigation(payload: InvestigationCreate) -> dict:
    require_database()
    question = payload.question
    hypothesis_id = None
    if payload.preset_id is not None:
        preset_id = InvestigationPreset(payload.preset_id)
        expected_question = INVESTIGATION_PRESET_QUESTIONS[preset_id]
        if payload.question != expected_question:
            raise HTTPException(status_code=422, detail="Question does not match the selected investigation preset.")
        question = expected_question
        hypothesis_id = INVESTIGATION_PRESET_HYPOTHESES[preset_id]
    # A verdict is a claim about the whole corpus. If part of it cannot be read, the
    # verdict would be computed over a corpus that is quietly shorter than the one the
    # caller believes is there, so this fails closed and names the row instead. The
    # list route degrades because inspecting a corpus is not a claim about it.
    records, skipped = store.list_records_with_report()
    if skipped:
        first = skipped[0]
        raise store.CorruptStoredRow(
            table=first.table, row_id=first.row_id, field=first.field, reason=first.reason
        )
    claims = ([engine.assess_hypothesis(records, hypothesis_id)]
              if hypothesis_id is not None else engine.investigate(records))
    result = store.create_investigation(question, claims)
    return _prepare_investigation_response(result)


@app.get("/api/investigations/{investigation_id}", response_model=Investigation)
def investigation(investigation_id: str) -> dict:
    require_database()
    result = store.get_investigation(investigation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return _prepare_investigation_response(result)


@app.post("/api/investigations/{investigation_id}/claims/{claim_id}/challenge")
def challenge(investigation_id: str, claim_id: str, payload: ChallengeCreate) -> dict:
    require_database()
    record = store.get_record(payload.source_record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Source record not found")
    if payload.quote not in record.text:
        raise HTTPException(status_code=422, detail="Challenge quote must be an exact source substring")
    snapshot = store.get_challenge_snapshot(investigation_id, claim_id, record.id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Investigation or claim not found")
    try:
        # Provider work and recomputation happen against a read snapshot before
        # apply_challenge opens its short write transaction.
        records = store.list_records()
        revised_claims = {
            cid: engine.challenge(claim, records, record.id, payload.quote)
            for cid, claim in snapshot["claims"].items()
        }
        result = store.apply_challenge(
            investigation_id, claim_id, payload.reason, record.id, payload.quote,
            expected_revision=snapshot["revision"], expected_claims=snapshot["claims"],
            revised_claims=revised_claims,
        )
    except AssessmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except store.StaleRevision:
        raise HTTPException(status_code=409, detail="Investigation changed during challenge computation; reload and retry.")
    if result is None:
        raise HTTPException(status_code=404, detail="Investigation or claim not found")
    result = _mark_unavailable_traces_in_snapshots(result)
    result["reason"] = payload.reason
    return result


@app.get("/api/investigations/{investigation_id}/history", response_model=list[HistoryEntry])
def history(investigation_id: str) -> list[dict]:
    require_database()
    result = store.get_history(investigation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return [_mark_unavailable_traces_in_snapshots(item) for item in result]

