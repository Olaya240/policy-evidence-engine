"""FastAPI local API. Does not initialize the database or make network calls."""
from copy import deepcopy

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .access import visible_records
from .engine import AssessmentEngine, AssessmentError, ProviderError
from .models import (ChallengeCreate, HistoryEntry, Investigation,
                     InvestigationCreate, InvestigationPreset,
                     INVESTIGATION_PRESET_HYPOTHESES,
                     INVESTIGATION_PRESET_QUESTIONS, Record)
from . import store

app = FastAPI(title="Story Connect Handover Investigation Prototype", version="0.1.0",
              description="Synthetic local decision support. Findings require human review; this is not production software.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
                   allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
engine = AssessmentEngine()


@app.exception_handler(store.DatabaseUnavailable)
async def database_unavailable_handler(_request, _exc: store.DatabaseUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Local prototype database is unavailable."})


@app.exception_handler(ProviderError)
async def provider_error_handler(_request, _exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Assessment provider is unavailable or returned invalid output."})


def require_database() -> None:
    try:
        path = store.database_path()
        if not path.is_file():
            raise HTTPException(status_code=503, detail="Local prototype database is not initialized. See hackathon/README.md.")
    except (OSError, ValueError, store.DatabaseUnavailable):
        raise HTTPException(status_code=503, detail="Local prototype database is not initialized. See hackathon/README.md.")


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
    try:
        path = store.database_path()
        initialized = path.is_file()
    except (OSError, ValueError):
        initialized = False
    available = False
    if initialized:
        try:
            with store.connect() as db:
                db.execute("SELECT 1").fetchone()
            available = True
        except store.DatabaseUnavailable:
            pass
    return {"status": "ok" if not initialized or available else "degraded", "prototype": True, "synthetic_data_only": True, "database_initialized": initialized, "database_available": available,
            "authentication": False, "human_review_required": True}


@app.get("/api/records", response_model=list[Record])
def records() -> list[Record]:
    require_database()
    return visible_records(store.list_records())


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
    records = store.list_records()
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

