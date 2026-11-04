"""FastAPI demo API for the Story Connect Policy Investigator Evidence Demo.

Runs on port 8083, completely isolated from policy_api.py (port 8082).
Provides endpoints for the frontend Policy Demo Page. Synthetic is the default
provider. Explicitly selecting the opt-in Meta or Baseten provider can make an
outbound remote inference request. Credentials are read only from the backend
process environment and are never returned to clients. Provider failures are
visible; there is no silent fallback to synthetic output.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import sys
import threading
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from pydantic import ValidationError

from app.local_env import load_backend_env_file
from policy_demo_session import (
    MAX_EVENTS_PER_SESSION,
    PolicySessionError,
    default_session_manager,
)
from policy_evidence_demo import (
    ALLOWED_SCENARIO_IDS,
    SCENARIO_LOUNGE,
    SCENARIO_METADATA,
    SCENARIO_SCHEDULING,
    SCENARIO_UNIFORM,
    ReviewerChallenge,
    build_hotel_scheduling_policy_pair,
    build_scenario_reviewer_challenge,
    get_scenario_pair,
    recompute_investigation_after_challenge,
    run_initial_evidence_investigation,
)
from policy_baseten_provider import (
    POLICY_META_MODEL_ID,
    POLICY_BASETEN_MODEL_ID,
    POLICY_PROVIDER_ENV,
    PolicyProviderError,
    build_policy_provider_from_environment,
)

app = FastAPI(title="Story Connect Policy Demo API", version="0.1.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5174"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

ALLOWED_CHALLENGE_DEPARTMENTS: dict[str, set[str]] = {
    SCENARIO_SCHEDULING: {"HOUSEKEEPING", "FRONT_DESK", "MAINTENANCE"},
    SCENARIO_UNIFORM: {"CONCIERGE", "BELL_SERVICE", "VALET"},
    SCENARIO_LOUNGE: {"VALET", "SECURITY", "BANQUETS"},
}

# Requests contain only small scenario/session identifiers; cap before JSON parsing.
# This bounds application-level accumulation; an ASGI server may allocate an
# individual receive chunk before handing it to this parser.
MAX_REQUEST_BYTES = 32_768
# Fill unset documented variables from backend-only backend/.env. The real
# process environment wins; see app/local_env.py. Skipped under pytest.
load_backend_env_file()
_policy_provider_lock = threading.Lock()
_policy_provider_initialized = False
_policy_provider = None
_policy_provider_failure_code: str | None = None


def _get_policy_provider():
    """Initialize provider and gate once per process so budgets persist across routes."""
    global _policy_provider_initialized, _policy_provider, _policy_provider_failure_code
    if not _policy_provider_initialized:
        with _policy_provider_lock:
            if not _policy_provider_initialized:
                try:
                    _policy_provider = build_policy_provider_from_environment(os.environ)
                except PolicyProviderError as exc:
                    _policy_provider_failure_code = exc.code
                except Exception:
                    _policy_provider_failure_code = "provider_unavailable"
                _policy_provider_initialized = True
    if _policy_provider_failure_code is not None:
        raise PolicyProviderError(_policy_provider_failure_code)
    return _policy_provider


async def _parse_request_model(request: Request, model: type[BaseModel], allow_empty: bool = False) -> BaseModel | None:
    """Read a bounded request stream, then validate JSON without exposing parse details."""
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    content_length = request.headers.get("content-length")
    if content_length is not None:
        if not content_length.isascii() or not content_length.isdecimal():
            raise HTTPException(status_code=400, detail={"error": "invalid_content_length", "detail": "Request body is invalid."})
        if len(content_length) > 12 or int(content_length) > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail={"error": "body_too_large", "detail": "Request body exceeds its size limit."})
    empty_optional_body = allow_empty and content_length in (None, "0")
    if content_type != "application/json" and not empty_optional_body:
        raise HTTPException(status_code=415, detail={"error": "unsupported_media_type", "detail": "Send a JSON request body."})

    chunks: list[bytes] = []
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_REQUEST_BYTES:
                raise HTTPException(status_code=413, detail={"error": "body_too_large", "detail": "Request body exceeds its size limit."})
            chunks.append(chunk)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "invalid_body", "detail": "Request body is invalid."}) from None

    if content_type != "application/json":
        if allow_empty and size == 0:
            return None
        raise HTTPException(status_code=415, detail={"error": "unsupported_media_type", "detail": "Send a JSON request body."})
    if not chunks and allow_empty:
        return None
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8", "strict"))
        if allow_empty and payload is None:
            return None
        return model.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError, ValidationError):
        raise HTTPException(status_code=422, detail={"error": "invalid_request", "detail": "Request fields are invalid."}) from None


class CreateSessionRequest(BaseModel):
    scenario_id: str = SCENARIO_SCHEDULING
    proposal_id: str

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario(cls, v: str) -> str:
        if v not in ALLOWED_SCENARIO_IDS:
            raise ValueError(f"Scenario ID '{v}' is not recognized.")
        return v


class ResetSessionRequest(BaseModel):
    scenario_id: str | None = None

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_SCENARIO_IDS:
            raise ValueError(f"Scenario ID '{v}' is not recognized.")
        return v


class ChallengeRequest(BaseModel):
    department_id: str
    scenario_id: str = SCENARIO_SCHEDULING
    session_id: str
    proposal_id: str

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario(cls, v: str) -> str:
        if v not in ALLOWED_SCENARIO_IDS:
            raise ValueError(f"Scenario ID '{v}' is not recognized.")
        return v

    @field_validator("department_id")
    @classmethod
    def validate_department(cls, v: str) -> str:
        all_allowed = set().union(*ALLOWED_CHALLENGE_DEPARTMENTS.values())
        if v not in all_allowed:
            raise ValueError(f"Department '{v}' is not accepted in demo challenge scope.")
        return v


@app.get("/demo-api/health")
def health() -> dict[str, str]:
    """Health check endpoint — confirms demo API is ready in offline mode."""
    return {"status": "ready", "mode": "offline_demo"}


@app.get("/demo-api/provider-status")
def provider_status(request: Request) -> dict[str, Any]:
    """Read provider selection and budget reservations without initializing it."""
    peer = request.client.host if request.client is not None else None
    try:
        address = ipaddress.ip_address(peer) if isinstance(peer, str) else None
    except ValueError:
        address = None
    is_loopback = bool(
        address is not None
        and (address.is_loopback or (
            isinstance(address, ipaddress.IPv6Address)
            and address.ipv4_mapped is not None
            and address.ipv4_mapped.is_loopback
        ))
    )
    if not is_loopback:
        raise HTTPException(status_code=403, detail={"error": "loopback_only"})

    configured = os.environ.get(POLICY_PROVIDER_ENV, "synthetic").strip().lower()
    if configured not in {"synthetic", "meta", "baseten"}:
        configured = "unknown"
    pinned_models = {"meta": POLICY_META_MODEL_ID, "baseten": POLICY_BASETEN_MODEL_ID}

    # Snapshot the lazy provider state under the same lock used by initialization.
    # This endpoint deliberately never calls _get_policy_provider or its builder.
    with _policy_provider_lock:
        initialized = _policy_provider_initialized
        provider = _policy_provider if initialized else None
        failed = _policy_provider_failure_code is not None if initialized else False
        if not initialized:
            provider_id = None
            model_id = pinned_models.get(configured)
            state = "not_initialized"
            attempts = 0
        elif failed or provider is None:
            provider_id = None if failed else "synthetic"
            model_id = pinned_models.get(configured) if failed else None
            state = "unavailable" if failed else "ready"
            attempts = 0
        else:
            try:
                actual_id = getattr(provider, "provider_id", None)
                provider_id = actual_id if actual_id in {"meta", "baseten"} else "unknown"
                expected_model = pinned_models.get(provider_id)
                actual_model = getattr(provider, "model_id", None)
                model_valid = expected_model is not None and actual_model == expected_model
                model_id = actual_model if model_valid else None
                gate = getattr(provider, "_gate", None)
                count = getattr(gate, "request_count", None)
                attempts = count if type(count) is int and count >= 0 else None
            except Exception:
                provider_id = "unknown"
                model_id = None
                attempts = None
                model_valid = False
            state = "ready" if provider_id != "unknown" and model_valid and attempts is not None else "unknown"

    return {
        "configured_provider": configured,
        "provider_id": provider_id,
        "model_id": model_id,
        "provider_state": state,
        "authorized_request_attempts": attempts,
        "counter_semantics": "budget reservations before transport; not confirmed HTTP deliveries",
    }


@app.get("/demo-api/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    """Return allowlisted metadata for all available synthetic policy scenarios."""
    return list(SCENARIO_METADATA)


@app.get("/demo-api/scenario")
def scenario(id: str = SCENARIO_SCHEDULING) -> dict[str, Any]:
    """Run initial evidence investigation for the requested scenario ID."""
    if id not in ALLOWED_SCENARIO_IDS:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_scenario", "detail": f"Scenario ID '{id}' is not recognized."},
        )
    try:
        pair = get_scenario_pair(id)
        provider = _get_policy_provider()
        result = run_initial_evidence_investigation(pair, provider)
        result["scenario_id"] = id
        result["proposal_id"] = default_session_manager.register_proposal(id, result)
        return result
    except PolicyProviderError as exc:
        status_code = 503 if exc.code != "budget_exhausted" else 429
        raise HTTPException(status_code=status_code, detail={"error": exc.code, "detail": str(exc)}) from None
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "demo_unavailable", "detail": "Demo scenario could not be computed."},
        ) from exc


@app.post("/demo-api/session/new")
async def create_session(request: Request) -> dict[str, Any]:
    """Start a fresh in-memory investigation session for a scenario."""
    body = await _parse_request_model(request, CreateSessionRequest)
    try:
        assert isinstance(body, CreateSessionRequest)
        session = default_session_manager.create_session(body.scenario_id, body.proposal_id)
        return {
            "session_id": session.session_id,
            "scenario_id": session.scenario_id,
            "proposal_id": session.proposal_id,
            "created_at_iso": session.created_at_iso,
        }
    except PolicySessionError as exc:
        status = 404 if exc.code == "proposal_not_found" else 409 if exc.code == "proposal_scenario_mismatch" else 400
        raise HTTPException(status_code=status, detail={"error": exc.code, "detail": exc.detail}) from None


@app.get("/demo-api/session/{session_id}/history")
def get_session_history(session_id: str) -> dict[str, Any]:
    """Retrieve append-only audit history for the given in-memory session."""
    try:
        # Read metadata and history together because reset can change scenario binding.
        snapshot = default_session_manager.get_session_history_snapshot(session_id)
        return {
            "session_id": snapshot.metadata.session_id,
            "scenario_id": snapshot.metadata.scenario_id,
            "proposal_id": snapshot.metadata.proposal_id,
            "events": [event.to_dict() for event in snapshot.events],
            "count": len(snapshot.events),
            "event_count": len(snapshot.events),
            "max_events": MAX_EVENTS_PER_SESSION,
            "storage_mode": "ephemeral_in_memory",
        }
    except PolicySessionError as exc:
        status_code = 404 if exc.code == "session_not_found" else 400
        raise HTTPException(status_code=status_code, detail={"error": exc.code, "detail": exc.detail}) from exc


@app.post("/demo-api/session/{session_id}/reset")
async def reset_session(session_id: str, request: Request) -> dict[str, Any]:
    """Clear audit history for an active session and optionally bind to a new scenario."""
    body = await _parse_request_model(request, ResetSessionRequest, allow_empty=True)
    try:
        new_scenario = body.scenario_id if isinstance(body, ResetSessionRequest) else None
        session = default_session_manager.reset_session(session_id, new_scenario_id=new_scenario)
        return {
            "session_id": session.session_id,
            "scenario_id": session.scenario_id,
            "proposal_id": session.proposal_id,
            "events": [],
            "count": 0,
            "event_count": 0,
            "status": "reset",
        }
    except PolicySessionError as exc:
        status_code = 404 if exc.code == "session_not_found" else 400
        raise HTTPException(status_code=status_code, detail={"error": exc.code, "detail": exc.detail}) from exc


@app.post("/demo-api/challenge")
async def challenge(request: Request) -> dict[str, Any]:
    """Recompute investigation after a reviewer challenge on the given department and scenario."""
    body = await _parse_request_model(request, ChallengeRequest)
    assert isinstance(body, ChallengeRequest)
    allowed_depts = ALLOWED_CHALLENGE_DEPARTMENTS.get(body.scenario_id, set())
    if body.department_id not in allowed_depts:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_challenge_department",
                "detail": f"Department '{body.department_id}' does not match expected challenge target for scenario '{body.scenario_id}'.",
            },
        )

    try:
        session, initial = default_session_manager.get_bound_proposal(
            body.session_id, body.scenario_id, body.proposal_id,
        )
        pair = get_scenario_pair(body.scenario_id)
        reviewer_challenge, result = await asyncio.to_thread(
            _recompute_bound_challenge, pair, initial, body.department_id, body.scenario_id,
        )
        result["scenario_id"] = body.scenario_id
        result["proposal_id"] = body.proposal_id

        summary = (
            f"Reviewer challenged {body.department_id} on {body.scenario_id} proposal {body.proposal_id}. "
            f"Applicability: {result['applicability_audit']['applicability_status']}. "
            f"Core result: {result['recomputed_core_result']['classification']}."
        )
        recorded = default_session_manager.record_challenge_event_snapshot(
            session_id=body.session_id,
            scenario_id=body.scenario_id,
            target_department=body.department_id,
            target_side=reviewer_challenge.target_side,
            applicability_status=result["applicability_audit"]["applicability_status"],
            initial_relation=initial.get("proposed_relation", "UNKNOWN"),
            recomputed_relation=result["recomputed_proposal"]["proposed_relation"],
            core_classification=result["recomputed_core_result"]["classification"],
            uncertainty_reasons=result["recomputed_core_result"]["uncertainty_reasons"],
            contract_enforced=result["contract_enforcement"]["one_sided_change_rejected"],
            summary=summary,
            expected_generation=session.generation,
            proposal_id=body.proposal_id,
        )
        result["session_id"] = body.session_id
        result["sequence_number"] = recorded.event.sequence_number
        result["history_count"] = recorded.metadata.history_count

        return result
    except PolicySessionError as exc:
        status_code = {
            "session_not_found": 404, "invalid_session_id": 400,
            "scenario_mismatch": 422, "session_reset": 409,
            "invalid_proposal_id": 400, "proposal_mismatch": 409,
            "proposal_unavailable": 409,
        }.get(exc.code, 400)
        raise HTTPException(status_code=status_code, detail={"error": exc.code, "detail": exc.detail}) from None
    except PolicyProviderError as exc:
        status_code = 503 if exc.code != "budget_exhausted" else 429
        raise HTTPException(status_code=status_code, detail={"error": exc.code, "detail": str(exc)}) from None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "demo_unavailable", "detail": "Demo scenario could not be computed."},
        ) from exc


def _recompute_bound_challenge(pair, initial, department_id: str, scenario_id: str):
    """Run bounded local challenge work off the async route's event loop."""
    reviewer_challenge = build_scenario_reviewer_challenge(
        pair, initial, department_id, scenario_id=scenario_id,
    )
    result = recompute_investigation_after_challenge(pair, initial, reviewer_challenge)
    return reviewer_challenge, result



def main() -> None:
    """Run the demo API server on 127.0.0.1:8083."""
    uvicorn.run(app, host="127.0.0.1", port=8083, reload=False, proxy_headers=False)


if __name__ == "__main__":
    main()
