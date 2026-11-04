"""Safe reproducibility metadata; deliberately has no prompt/response/text fields."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

# Explicit stand-in for an identity this module cannot establish. A run record
# states that it does not know, rather than omitting the field and looking like
# it recorded something.
UNKNOWN = "unknown"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,119}$")
_HOST_LIKE = re.compile(r"(?i)(?:^|[._-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\.?$|[/:?#])")
_IPV4_SHAPED = re.compile(r"^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$")
_ALT_IPV4_PART = re.compile(r"^(?:0[xX][0-9a-fA-F]+|[0-9]+)$")
_SINGLE_LABEL_HOST = re.compile(r"(?i)^(?:(?:localhost|server|host|api|gateway|router|proxy|backend|frontend|intranet|database|db|mysql|postgres|redis|nginx|production)(?:[-_.][a-z0-9-]+)*|server\d*|host\d*|db\d*)$")
_SECRET_MARKER = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|credential|bearer|access[_-]?token|"
    r"\b(?:sk|pk|rk)[-_](?:live|test|proj)?[-_][A-Za-z0-9_-]{8,}\b|"
    r"\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{30,}\b)"
)
_ERROR_CATEGORIES = {
    "timeout", "provider_failure", "malformed_response", "malformed_output",
    "invalid_source", "invalid_quote", "invalid_stance", "invalid_rationale",
    "unexpected_exception", "request_limit", "single_flight_limit",
    "estimated_budget_exceeded", "serialization_failure",
}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _looks_like_ipv4_literal(value: str) -> bool:
    candidate = value.rstrip(".")
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        pass
    # Browsers and URL parsers accept shortened, octal, hexadecimal, and
    # integer IPv4 forms. Metadata identifiers must not carry those forms.
    parts = candidate.split(".")
    if not (1 <= len(parts) <= 4 and all(_ALT_IPV4_PART.fullmatch(part) for part in parts)):
        return False
    try:
        numbers = []
        for part in parts:
            if part.lower().startswith("0x"):
                numbers.append(int(part[2:], 16))
            elif len(part) > 1 and part.startswith("0"):
                numbers.append(int(part, 8))
            else:
                numbers.append(int(part, 10))
    except ValueError:
        # An invalid octal-looking or mixed-base form is still an ambiguous
        # numeric host token and must not be accepted as metadata.
        return True
    # All 1-4 component numeric host forms are reserved as ambiguous. Reject
    # them even when a component is outside an address range.
    return True


def _safe_metadata_id(value: str, *, allow_version: bool = False) -> bool:
    # Metadata fields are identifiers, never URLs or free-form text. Exact type
    # checks avoid subclasses with surprising serialization behavior.
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        return False
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        return False
    if _SECRET_MARKER.search(value) or _SINGLE_LABEL_HOST.fullmatch(value.rstrip(".")):
        return False
    if _HOST_LIKE.search(value):
        return False
    version3 = allow_version and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value) is not None
    # Four dotted components are IPv4-shaped even in version fields. Three
    # numeric components remain allowed as conventional semantic versions.
    if _IPV4_SHAPED.fullmatch(value):
        return False
    if _looks_like_ipv4_literal(value) and not version3:
        return False
    return True


@dataclass(frozen=True)
class AttemptMetadata:
    """Usage metadata for one case.

    `request_count` is the number of controlled requests spent on this case. It
    is deliberately not the run-wide counter: a cumulative number cannot be
    checked against the attempt it is attached to, and every attempt after the
    first would misreport its own cost. Zero is legal and means the run
    controller refused the case before reserving anything (for example
    `request_limit`), so no request was spent on it.
    """

    case_id: str
    request_count: int
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_category: str | None = None

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not _safe_metadata_id(self.case_id):
            raise ValueError("Invalid case identifier")
        if type(self.request_count) is not int or self.request_count < 0:
            raise ValueError("Invalid request count")
        for value in (self.latency_ms, self.input_tokens, self.output_tokens):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Invalid numeric usage metadata")
        if self.error_category is not None and (type(self.error_category) is not str or self.error_category not in _ERROR_CATEGORIES):
            raise ValueError("Invalid controlled error category")

    def to_dict(self) -> dict[str, Any]:
        self._validate()
        return {
            "case_id": self.case_id,
            "request_count": self.request_count,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error_category": self.error_category,
        }


@dataclass
class ExperimentRunManifest:
    """Metadata for one evaluation run, bound to the attempts actually made.

    Two mechanisms keep the record attached to the run it describes:

    * Attempts enter only through `add_attempt`, which fingerprints the list.
      `to_dict` recomputes the fingerprint and refuses a list that was appended
      to, replaced, or emptied behind the class's back, so an attempt cannot be
      added after the fact merely because `attempts` is a list.
    * `seal` is the point at which the manifest claims to describe a run. A
      sealed manifest must carry at least one attempt (a run that recorded
      nothing is not a run record) and must name the code and the model behind
      it, with `UNKNOWN` as the accepted way to say "not established". After
      sealing the attempt list is frozen.
    """

    run_id: str
    dataset_sha256: str
    evaluator_version: str
    prompt_version: str
    prompt_sha256: str
    serializer_version: str
    serializer_sha256: str
    code_revision: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    temperature: float | None = None
    seed: int | None = None
    attempts: list[AttemptMetadata] = field(default_factory=list)
    _attempts_sha256: str | None = field(default=None, init=False, repr=False, compare=False)
    _sealed: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._validate()
        self._attempts_sha256 = self._fingerprint_attempts()

    def _validate(self) -> None:
        if not _safe_metadata_id(self.run_id):
            raise ValueError("Invalid run identifier")
        for digest in (self.dataset_sha256, self.prompt_sha256, self.serializer_sha256):
            if type(digest) is not str or not _DIGEST.fullmatch(digest):
                raise ValueError("Invalid metadata digest")
        for value in (self.evaluator_version, self.prompt_version, self.serializer_version):
            if not _safe_metadata_id(value, allow_version=True):
                raise ValueError("Invalid metadata version")
        for value in (self.code_revision, self.model_name, self.model_version):
            if value is not None and not _safe_metadata_id(value):
                raise ValueError("Invalid model or revision identifier")
        if self.temperature is not None and (type(self.temperature) not in (int, float)
                                             or not math.isfinite(self.temperature) or self.temperature < 0):
            raise ValueError("Invalid temperature metadata")
        if self.seed is not None and type(self.seed) is not int:
            raise ValueError("Invalid seed metadata")

    def _fingerprint_attempts(self) -> str | None:
        """Digest of the attempt list exactly as it stands now."""
        if type(self.attempts) is not list or any(type(item) is not AttemptMetadata for item in self.attempts):
            return None
        payload = [attempt.to_dict() for attempt in self.attempts]
        return sha256_hex(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def add_attempt(self, attempt: AttemptMetadata) -> None:
        if self._sealed:
            raise ValueError("Manifest is sealed; attempts cannot be added")
        if type(attempt) is not AttemptMetadata:
            raise ValueError("Invalid attempt metadata")
        attempt._validate()
        self.attempts.append(attempt)
        self._attempts_sha256 = self._fingerprint_attempts()

    def seal(self) -> None:
        """Freeze the record once every attempt has been recorded."""
        if self._sealed:
            raise ValueError("Manifest is already sealed")
        self._validate()
        if type(self.attempts) is not list or not self.attempts:
            raise ValueError("A sealed manifest must record at least one attempt")
        if self.code_revision is None or self.model_name is None:
            raise ValueError("A sealed manifest must record code_revision and model_name")
        if self._attempts_sha256 is None or self._fingerprint_attempts() != self._attempts_sha256:
            raise ValueError("Manifest attempts were modified outside add_attempt")
        self._sealed = True

    def to_dict(self) -> dict[str, Any]:
        # Explicit fields prevent accidental inclusion of prompts, proposals, or record text.
        self._validate()
        if type(self.attempts) is not list or any(type(item) is not AttemptMetadata for item in self.attempts):
            raise ValueError("Invalid attempt metadata")
        for attempt in self.attempts:
            attempt._validate()
        if self._attempts_sha256 is None or self._fingerprint_attempts() != self._attempts_sha256:
            raise ValueError("Manifest attempts were modified outside add_attempt")
        return {
            "schema_version": "1",
            "run_id": self.run_id,
            "dataset_sha256": self.dataset_sha256,
            "code_revision": self.code_revision,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "serializer_version": self.serializer_version,
            "serializer_sha256": self.serializer_sha256,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "decoding": {"temperature": self.temperature, "seed": self.seed},
            "evaluator_version": self.evaluator_version,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }
