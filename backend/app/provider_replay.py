"""Offline replay of one recorded provider exchange.

Rows B5/B6 ask whether the *live* provider path behaves as the contract says.
That question cannot be answered from the repo, because the live path has never
executed against a vendor. This module is the piece that turns a single captured
exchange into evidence: it reads a cassette from a path the caller supplies and
pushes the recorded response body through **the same functions the live path
calls**, in the same order, with no bypass and no relaxed checks:

    serialize_provider_request  ->  BasetenMuseSparkOpenAdapter._wire_request
                                ->  BasetenMuseSparkOpenAdapter._parse_response

`_parse_response` is the exact validator that runs on a live response: pinned
model, envelope allowlist, refusal/empty handling, strict JSON, the proposal
budget, and the grounding checks (every `source_record_id` must be in the
request, every `quote` an exact substring of that record's text).

What this module never does:

* it performs no network I/O and constructs no transport or adapter instance;
* it never invents, repairs or normalises a response -- the recorded bytes are
  parsed exactly as recorded, and a body that fails a check raises
  `ProviderSafetyError` with the same code the live path raises;
* it never chooses its own input: the cassette path is required, and a cassette
  whose `request_sha256` does not match the request being replayed is refused,
  so a capture cannot be silently reused for a different question or corpus.

The cassette itself records the request digest but **not** a response digest.
That is deliberate: the load-bearing claim is that a modified quote is caught by
the grounding check, and hashing the response would make tampering fail earlier
on file integrity while proving less about the validator.

Cassette format (JSON, UTF-8, `provider-replay-cassette-v1`):

    {
      "format": "provider-replay-cassette-v1",
      "label": "synthetic" | "recorded",
      "endpoint": "https://inference.baseten.co/v1/chat/completions",
      "model": "meta-models/muse-spark-open-1026",
      "timestamp": "2026-11-02T12:00:00Z",
      "request_sha256": "<64 lowercase hex chars>",
      "request_envelope": "<exact bytes of the SerializedProviderRequest>",
      "response_body": "<exact bytes of the raw provider response body>"
    }

`label` is `synthetic` for a hand-written fixture and `recorded` for a real
capture. A synthetic cassette is never vendor output and must not be reported as
such; the label travels with the replay result so a downstream artifact cannot
quietly drop the distinction.

No vendor behaviour is asserted anywhere in this module. Whether a real model
returns a body that passes these checks is `Unknown` until a recording exists.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .httpx_transport import BASETEN_CHAT_COMPLETIONS_ENDPOINT
from .models import Record
from .provider_safety import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    BasetenMuseSparkOpenAdapter,
    ProviderSafetyError,
    serialize_provider_request,
)

CASSETTE_FORMAT = "provider-replay-cassette-v1"
SYNTHETIC_LABEL = "synthetic"
RECORDED_LABEL = "recorded"
CASSETTE_LABELS = frozenset({SYNTHETIC_LABEL, RECORDED_LABEL})
CASSETTE_FIELDS = frozenset({
    "format",
    "label",
    "endpoint",
    "model",
    "timestamp",
    "request_sha256",
    "request_envelope",
    "response_body",
})
# The envelope and the response are both JSON text embedded as JSON strings, so
# the worst case is that every byte needing an escape doubles. Anything larger
# than that bound cannot be a cassette this module produced or would accept.
MAX_CASSETTE_BYTES = 2 * (MAX_REQUEST_BYTES + MAX_RESPONSE_BYTES) + 1024
_HEX_DIGITS = frozenset("0123456789abcdef")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Same strictness as the live response parser: duplicate keys are refused."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _reject_nonstandard_constant(_value: str) -> None:
    raise ValueError("nonstandard JSON constant")


@dataclass(frozen=True)
class RecordedExchange:
    """One recorded exchange, exactly as stored. Nothing here is derived."""

    label: str
    endpoint: str
    model: str
    timestamp: str
    captured_at: datetime
    request_sha256: str
    request_envelope: str
    response_body: str


@dataclass(frozen=True)
class ReplayResult:
    """What the recorded body produced when the live validator read it."""

    proposals: tuple[dict[str, str], ...]
    label: str
    model: str
    endpoint: str
    timestamp: str
    request_sha256: str
    wire_sha256: str
    response_sha256: str


def _cassette_path(path: str | os.PathLike[str]) -> Path:
    if isinstance(path, bool) or not isinstance(path, (str, os.PathLike)):
        raise ProviderSafetyError("malformed_cassette")
    text = os.fspath(path)
    if not isinstance(text, str) or not text.strip():
        raise ProviderSafetyError("malformed_cassette")
    return Path(text)


def _read_cassette_text(path: str | os.PathLike[str]) -> str:
    cassette = _cassette_path(path)
    try:
        info = cassette.stat()
    except OSError:
        raise ProviderSafetyError("malformed_cassette") from None
    if not stat.S_ISREG(info.st_mode):
        raise ProviderSafetyError("malformed_cassette")
    if info.st_size > MAX_CASSETTE_BYTES:
        raise ProviderSafetyError("cassette_too_large")
    try:
        raw = cassette.read_bytes()
    except OSError:
        raise ProviderSafetyError("malformed_cassette") from None
    if len(raw) > MAX_CASSETTE_BYTES:
        raise ProviderSafetyError("cassette_too_large")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ProviderSafetyError("malformed_cassette") from None


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ProviderSafetyError("cassette_metadata_mismatch") from None
    if parsed.tzinfo is None:
        # A capture without an offset cannot be placed on a timeline, so it is
        # refused rather than assumed to be UTC.
        raise ProviderSafetyError("cassette_metadata_mismatch")
    return parsed.astimezone(timezone.utc)


def _exchange_from_payload(payload: Any) -> RecordedExchange:
    if type(payload) is not dict or set(payload) != CASSETTE_FIELDS:
        raise ProviderSafetyError("malformed_cassette")
    if any(type(value) is not str for value in payload.values()):
        raise ProviderSafetyError("malformed_cassette")
    if payload["format"] != CASSETTE_FORMAT:
        raise ProviderSafetyError("malformed_cassette")
    if payload["label"] not in CASSETTE_LABELS:
        raise ProviderSafetyError("malformed_cassette")
    digest = payload["request_sha256"]
    if len(digest) != 64 or set(digest) - _HEX_DIGITS:
        raise ProviderSafetyError("malformed_cassette")
    if payload["endpoint"] != BASETEN_CHAT_COMPLETIONS_ENDPOINT:
        raise ProviderSafetyError("cassette_metadata_mismatch")
    if payload["model"] != BasetenMuseSparkOpenAdapter.MODEL_SLUG:
        raise ProviderSafetyError("cassette_metadata_mismatch")
    captured_at = _timestamp(payload["timestamp"])

    envelope = payload["request_envelope"].encode("utf-8")
    if len(envelope) > MAX_REQUEST_BYTES:
        raise ProviderSafetyError("request_too_large")
    # The stored envelope must be the object the stored digest describes, so a
    # cassette edited after capture is refused before anything is parsed.
    if _sha256_hex(envelope) != digest:
        raise ProviderSafetyError("cassette_request_mismatch")

    body = payload["response_body"].encode("utf-8")
    if len(body) > MAX_RESPONSE_BYTES:
        raise ProviderSafetyError("response_too_large")

    return RecordedExchange(
        label=payload["label"],
        endpoint=payload["endpoint"],
        model=payload["model"],
        timestamp=payload["timestamp"],
        captured_at=captured_at,
        request_sha256=digest,
        request_envelope=payload["request_envelope"],
        response_body=payload["response_body"],
    )


def load_cassette(path: str | os.PathLike[str]) -> RecordedExchange:
    """Read and structurally check one cassette. Performs no replay.

    `path` is required and is the only source of input. The file must be a
    regular UTF-8 JSON file with exactly the documented fields, an approved
    endpoint, the pinned model, a timezone-bearing ISO-8601 timestamp, and a
    request digest that matches the envelope stored beside it.
    """
    text = _read_cassette_text(path)
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except (ValueError, TypeError, RecursionError):
        raise ProviderSafetyError("malformed_cassette") from None
    return _exchange_from_payload(payload)


def replay_recorded_exchange(
    path: str | os.PathLike[str],
    *,
    records: Sequence[Record],
    hypothesis_id: str,
) -> ReplayResult:
    """Replay one recorded response against the corpus it is claimed to answer.

    The request is rebuilt with `serialize_provider_request` from `records` and
    `hypothesis_id` -- the same serializer and eligibility filter the
    `MandatoryProviderBoundary` applies -- and its digest must equal the one in
    the cassette. That is what stops a capture from being reused for a different
    question, a different corpus, or a corpus whose text changed by one byte.

    The recorded body then passes through `_wire_request` (so a request the live
    path could not have sent is refused) and `_parse_response` (the live
    validator). Any violation raises `ProviderSafetyError` with the live code.
    """
    exchange = load_cassette(path)
    request = serialize_provider_request(records, hypothesis_id)
    request_sha256 = _sha256_hex(bytes(request))
    if request_sha256 != exchange.request_sha256:
        raise ProviderSafetyError("cassette_request_mismatch")
    wire = BasetenMuseSparkOpenAdapter._wire_request(request)
    body = exchange.response_body.encode("utf-8")
    proposals = BasetenMuseSparkOpenAdapter._parse_response(body, request)
    return ReplayResult(
        proposals=tuple(proposals),
        label=exchange.label,
        model=exchange.model,
        endpoint=exchange.endpoint,
        timestamp=exchange.timestamp,
        request_sha256=request_sha256,
        wire_sha256=_sha256_hex(wire),
        response_sha256=_sha256_hex(body),
    )
