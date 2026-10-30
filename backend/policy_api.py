"""Database-free localhost API for the offline synthetic policy demo.

Supported launch: ``python -m policy_api`` with this directory on
``PYTHONPATH``. The listener is fixed to 127.0.0.1:8082; there is no port
fallback. This module does not import the handover application or its store.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from policy_candidate_adapter import FakePolicyCandidateAdapter
from policy_compare import PolicyCompareError, PolicyPair, validate_policy_pair
from policy_orchestration import (
    PolicyOrchestrationError,
    orchestrate_policy_comparison,
)


LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 8082
MAX_REQUEST_BYTES = 512_000

app = FastAPI(
    title="Story Connect Offline Policy Comparison",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5174"],
    allow_credentials=False,
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)


class _RequestError(ValueError):
    def __init__(self, code: str, status_code: int, detail: str) -> None:
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_non_json_constant(_value: str) -> None:
    raise ValueError("invalid JSON constant")


async def _read_json_body(request: Request) -> Any:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise _RequestError("unsupported_media_type", 415, "Send a JSON request body.")

    content_length = request.headers.get("content-length")
    if content_length is not None:
        if not content_length.isascii() or not content_length.isdecimal():
            raise _RequestError("invalid_content_length", 400, "Request body is invalid.")
        if len(content_length) > 12 or int(content_length) > MAX_REQUEST_BYTES:
            raise _RequestError("body_too_large", 413, "Request body exceeds its size limit.")

    chunks: list[bytes] = []
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_REQUEST_BYTES:
                raise _RequestError("body_too_large", 413, "Request body exceeds its size limit.")
            chunks.append(chunk)
    except _RequestError:
        raise
    except Exception:
        raise _RequestError("invalid_body", 400, "Request body is invalid.") from None

    try:
        text = b"".join(chunks).decode("utf-8", "strict")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise _RequestError("malformed_json", 400, "Request body is not valid JSON.") from None


def _fixture_citation(version: Any, side: str) -> dict[str, Any]:
    passage = version.passages[0]
    quote = passage.text[:1_000]
    return {
        "side": side,
        "document_id": version.document_id,
        "version_id": version.version_id,
        "source_sha256": version.source_sha256,
        "passage_id": passage.passage_id,
        "start_cp": passage.start_cp,
        "end_cp": passage.start_cp + len(quote),
        "quote": quote,
    }


def _fixture_adapter(pair: PolicyPair) -> FakePolicyCandidateAdapter:
    """Build a deterministic abstaining response with exact source citations."""
    response = {
        "schema_version": 1,
        "candidates": [{
            "candidate_id": "cand-syn-api-fixture",
            "proposed_relation": "INCONCLUSIVE",
            "reasoning": "Offline fixture citations are shown for review; semantic support is not assessed.",
            "citations": [
                _fixture_citation(pair.older, "OLDER"),
                _fixture_citation(pair.newer, "NEWER"),
            ],
            "uncertainty_reasons": ["missing_evidence", "semantic_support_unverified"],
            "abstain": False,
        }],
    }
    return FakePolicyCandidateAdapter(json.dumps(response, ensure_ascii=True, separators=(",", ":")))


def _error_response(code: str, detail: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": code, "detail": detail})


@app.get("/health")
async def health() -> dict[str, str]:
    """Readiness response with no provider, filesystem, or database access."""
    return {"status": "ready", "mode": "offline_fixture"}


@app.post("/policy-comparisons")
async def create_policy_comparison(request: Request) -> Any:
    try:
        payload = await _read_json_body(request)
    except _RequestError as error:
        return _error_response(error.code, error.detail, error.status_code)

    try:
        pair = validate_policy_pair(payload)
    except PolicyCompareError as error:
        return _error_response(error.code, str(error), 422)

    try:
        normalized = orchestrate_policy_comparison(payload, _fixture_adapter(pair))
    except PolicyOrchestrationError as error:
        return _error_response(error.code, str(error), 422)
    except Exception:
        return _error_response(
            "internal_error", "Policy comparison could not be completed.", 500
        )
    return normalized


def main() -> None:
    """Run the dedicated service on its fixed loopback address and port."""
    import uvicorn

    uvicorn.run(app, host=LOCAL_HOST, port=LOCAL_PORT, reload=False)


if __name__ == "__main__":
    main()
