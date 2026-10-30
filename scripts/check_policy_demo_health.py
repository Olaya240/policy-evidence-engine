"""Deterministic loopback-only health checks for the Story Connect Policy Demo.

Performs offline HTTP health checks against the local demo API (port 8083)
and local frontend (port 5174).

Safety constraints:
- Strictly loopback only (127.0.0.1).
- Bounded timeouts (default 3.0s per check).
- Sanitized output; never prints environment variables or credentials.
- Pure Python standard library (urllib.request).
"""
from __future__ import annotations

import json
import ipaddress
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from typing import Any

DEFAULT_API_BASE = "http://127.0.0.1:8083"
DEFAULT_FRONTEND_BASE = "http://127.0.0.1:5174"
REQUEST_TIMEOUT = 3.0
# Health JSON and the Vite entry page are small; cap each response at 16 KiB.
MAX_RESPONSE_BYTES = 16 * 1024
RESPONSE_READ_CHUNK_BYTES = 4096
ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
API_PORT = 8083
FRONTEND_PORT = 5174
SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}\Z")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so a loopback probe cannot be redirected elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HealthCheckResponseError(ValueError):
    """Controlled error for invalid or oversized local health responses."""


def _read_bounded_response(resp: Any, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read at most limit bytes, incrementally, and reject any additional byte."""
    chunks: list[bytes] = []
    size = 0
    while True:
        # Read one byte beyond the remaining allowance to distinguish exact-limit
        # responses from oversized ones without accumulating the extra byte.
        request_size = min(RESPONSE_READ_CHUNK_BYTES, limit - size + 1)
        chunk = resp.read(request_size)
        if not chunk:
            return b"".join(chunks)
        if size + len(chunk) > limit:
            raise HealthCheckResponseError("Health-check response exceeds its size limit.")
        chunks.append(chunk)
        size += len(chunk)


def _read_json_response(resp: Any) -> tuple[int, Any]:
    """Read and decode a bounded JSON health response with controlled errors."""
    status = resp.status
    body = _read_bounded_response(resp)
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HealthCheckResponseError("Health-check response is empty or invalid JSON.") from None
    return status, data


def _validated_base(base: str, expected_port: int) -> str:
    """Return a canonical loopback origin or reject it before opening a URL."""
    if not isinstance(base, str):
        raise ValueError("Health-check base must be a loopback HTTP URL.")
    try:
        parsed = urlsplit(base)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("Health-check base must be a valid loopback HTTP URL.") from None
    if parsed.scheme.lower() != "http" or not host or parsed.username is not None or parsed.password is not None:
        raise ValueError("Health-check base must be a loopback HTTP URL without user information.")
    normalized_host = host.lower()
    if normalized_host not in ALLOWED_LOOPBACK_HOSTS:
        try:
            address = ipaddress.ip_address(normalized_host)
            if not address.is_loopback or normalized_host not in ALLOWED_LOOPBACK_HOSTS:
                raise ValueError
        except ValueError:
            raise ValueError("Health-check base host is not an explicitly permitted loopback host.") from None
    if port != expected_port or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Health-check base has an unexpected port or URL component.")
    authority_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    return urlunsplit(("http", f"{authority_host}:{expected_port}", "", "", ""))


def _endpoint(base: str, expected_port: int, path: str) -> str:
    """Build an endpoint only from a validated origin and a fixed local path."""
    origin = _validated_base(base, expected_port)
    return urlunsplit((*urlsplit(origin)[:2], path, "", ""))


def _open_local(req: urllib.request.Request, timeout: float):
    # Ignore ambient HTTP proxy configuration and never follow a redirect.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )
    return opener.open(req, timeout=timeout)


class HealthCheckResult:
    def __init__(self, name: str, passed: bool, message: str, details: Any = None) -> None:
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "details": self.details,
        }


def _http_get_json(url: str, timeout: float = REQUEST_TIMEOUT) -> tuple[int, Any]:
    """Perform a GET request expecting JSON."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with _open_local(req, timeout=timeout) as resp:
        return _read_json_response(resp)


def _http_post_json(url: str, payload: dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> tuple[int, Any]:
    """Perform a POST request with a JSON payload expecting JSON."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with _open_local(req, timeout=timeout) as resp:
        return _read_json_response(resp)


def check_api_health(api_base: str = DEFAULT_API_BASE) -> HealthCheckResult:
    """Verify GET /demo-api/health returns status ready and mode offline_demo."""
    url = _endpoint(api_base, API_PORT, "/demo-api/health")
    try:
        status, data = _http_get_json(url)
        if status == 200 and data.get("status") == "ready" and data.get("mode") == "offline_demo":
            return HealthCheckResult(
                name="api_health",
                passed=True,
                message="Demo API is healthy in offline_demo mode.",
                details={"status_code": status, "mode": data.get("mode")},
            )
        return HealthCheckResult(
            name="api_health",
            passed=False,
            message=f"Unexpected health response: status {status}, data: {data}",
        )
    except Exception as exc:
        return HealthCheckResult(
            name="api_health",
            passed=False,
            message=f"Could not connect to demo API at {url}: {exc}",
        )


def check_scenarios_listing(api_base: str = DEFAULT_API_BASE) -> HealthCheckResult:
    """Verify GET /demo-api/scenarios returns all 3 synthetic scenarios."""
    url = _endpoint(api_base, API_PORT, "/demo-api/scenarios")
    try:
        status, data = _http_get_json(url)
        if status != 200 or not isinstance(data, list):
            return HealthCheckResult(
                name="scenarios_listing",
                passed=False,
                message=f"Invalid response from scenarios endpoint: status {status}",
            )
        ids = [item.get("id") for item in data if isinstance(item, dict)]
        expected = ["scheduling", "uniform_grooming", "lounge_access"]
        if ids == expected:
            return HealthCheckResult(
                name="scenarios_listing",
                passed=True,
                message=f"Successfully listed 3 synthetic scenarios: {ids}",
                details={"scenario_ids": ids},
            )
        return HealthCheckResult(
            name="scenarios_listing",
            passed=False,
            message=f"Scenario IDs mismatch: expected {expected}, got {ids}",
        )
    except Exception as exc:
        return HealthCheckResult(
            name="scenarios_listing",
            passed=False,
            message=f"Failed to fetch scenarios from {url}: {exc}",
        )


def check_scenario_loading(api_base: str = DEFAULT_API_BASE) -> HealthCheckResult:
    """Verify loading each of the three synthetic scenarios."""
    scenarios = [
        ("scheduling", "COMPATIBLE_CHANGE"),
        ("uniform_grooming", "CONTRADICTION"),
        ("lounge_access", "SCOPE_OR_TIME_DIFFERENCE"),
    ]
    loaded = {}
    for sid, expected_rel in scenarios:
        url = _endpoint(api_base, API_PORT, f"/demo-api/scenario?id={sid}")
        try:
            status, data = _http_get_json(url)
            if status != 200:
                return HealthCheckResult(
                    name="scenario_loading",
                    passed=False,
                    message=f"Scenario '{sid}' returned status {status}",
                )
            proposed = data.get("proposed_relation")
            if proposed != expected_rel:
                return HealthCheckResult(
                    name="scenario_loading",
                    passed=False,
                    message=f"Scenario '{sid}' relation mismatch: expected {expected_rel}, got {proposed}",
                )
            loaded[sid] = proposed
        except Exception as exc:
            return HealthCheckResult(
                name="scenario_loading",
                passed=False,
                message=f"Error loading scenario '{sid}' from {url}: {exc}",
            )

    return HealthCheckResult(
        name="scenario_loading",
        passed=True,
        message="All 3 synthetic scenarios loaded with expected relations.",
        details=loaded,
    )


def check_session_lifecycle(api_base: str = DEFAULT_API_BASE) -> HealthCheckResult:
    """Verify session creation, challenge audit recording, and session reset."""
    try:
        # 1. Create session
        create_url = _endpoint(api_base, API_PORT, "/demo-api/session/new")
        status, sess_data = _http_post_json(create_url, {"scenario_id": "scheduling"})
        if status != 200 or "session_id" not in sess_data:
            return HealthCheckResult(
                name="session_lifecycle",
                passed=False,
                message=f"Failed to create session: status {status}, data: {sess_data}",
            )
        session_id = sess_data["session_id"]
        if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
            return HealthCheckResult(
                name="session_lifecycle",
                passed=False,
                message="Invalid session_id format; expected 32 lowercase hexadecimal characters.",
            )

        # 2. Submit challenge
        challenge_url = _endpoint(api_base, API_PORT, "/demo-api/challenge")
        c_status, c_data = _http_post_json(
            challenge_url,
            {
                "scenario_id": "scheduling",
                "department_id": "HOUSEKEEPING",
                "session_id": session_id,
            },
        )
        if c_status != 200:
            return HealthCheckResult(
                name="session_lifecycle",
                passed=False,
                message=f"Challenge failed with status {c_status}",
            )
        if c_data.get("sequence_number") != 1:
            return HealthCheckResult(
                name="session_lifecycle",
                passed=False,
                message=f"Expected sequence_number 1, got {c_data.get('sequence_number')}",
            )

        # 3. Check history
        history_url = _endpoint(api_base, API_PORT, f"/demo-api/session/{session_id}/history")
        h_status, h_data = _http_get_json(history_url)
        if h_status != 200 or h_data.get("event_count") != 1:
            return HealthCheckResult(
                name="session_lifecycle",
                passed=False,
                message=f"History verification failed: count is {h_data.get('event_count')}",
            )

        # 4. Reset session
        reset_url = _endpoint(api_base, API_PORT, f"/demo-api/session/{session_id}/reset")
        r_status, r_data = _http_post_json(reset_url, {"scenario_id": "scheduling"})
        if r_status != 200 or r_data.get("event_count") != 0:
            return HealthCheckResult(
                name="session_lifecycle",
                passed=False,
                message=f"Reset verification failed: status {r_status}",
            )

        return HealthCheckResult(
            name="session_lifecycle",
            passed=True,
            message="Session lifecycle verified: created, challenged (seq #1), verified history, and reset cleanly.",
            details={"session_id_prefix": session_id[:8] + "...", "event_count_after_reset": 0},
        )
    except Exception as exc:
        return HealthCheckResult(
            name="session_lifecycle",
            passed=False,
            message=f"Session lifecycle test failed: {exc}",
        )


def check_frontend_availability(frontend_base: str = DEFAULT_FRONTEND_BASE) -> HealthCheckResult:
    """Verify frontend HTML availability on loopback port 5174."""
    url = _endpoint(frontend_base, FRONTEND_PORT, "/")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "StoryConnectHealthCheck/1.0"})
        with _open_local(req, timeout=REQUEST_TIMEOUT) as resp:
            status = resp.status
            html = _read_bounded_response(resp).decode("utf-8", errors="replace")
            if status == 200 and ("<div id=\"root\">" in html or "<div id='root'>" in html or "Story Connect" in html or "html" in html.lower()):
                return HealthCheckResult(
                    name="frontend_availability",
                    passed=True,
                    message="Frontend server is accessible on loopback.",
                    details={"status_code": status, "url": f"{frontend_base}/#/demo"},
                )
            return HealthCheckResult(
                name="frontend_availability",
                passed=False,
                message=f"Frontend responded with status {status} but unexpected HTML structure.",
            )
    except Exception as exc:
        return HealthCheckResult(
            name="frontend_availability",
            passed=False,
            message=f"Frontend connection failed at {url}: {exc}",
        )


def run_passive_checks(
    api_base: str = DEFAULT_API_BASE,
    frontend_base: str = DEFAULT_FRONTEND_BASE,
) -> tuple[bool, list[HealthCheckResult]]:
    """Run strictly non-mutating loopback checks (GET requests only, zero session capacity consumed)."""
    checks = [
        check_api_health(api_base),
        check_scenarios_listing(api_base),
        check_scenario_loading(api_base),
        check_frontend_availability(frontend_base),
    ]
    all_passed = all(c.passed for c in checks)
    return all_passed, checks


def run_all_checks(
    api_base: str = DEFAULT_API_BASE,
    frontend_base: str = DEFAULT_FRONTEND_BASE,
    active: bool = False,
) -> tuple[bool, list[HealthCheckResult]]:
    """Run local health checks deterministically.

    Parameters:
    - active (bool): If False (default), executes only passive non-mutating checks.
      If True, also executes active session lifecycle verification (creates and resets a session).
    """
    all_passed, checks = run_passive_checks(api_base=api_base, frontend_base=frontend_base)
    if active:
        lifecycle = check_session_lifecycle(api_base)
        checks.append(lifecycle)
        all_passed = all_passed and lifecycle.passed
    return all_passed, checks


def main(active: bool = False) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Story Connect Policy Demo — Local Offline Health Checks",
    )
    parser.add_argument(
        "--active",
        action="store_true",
        help="Run active session lifecycle verification (POST/challenge/reset) in addition to passive checks.",
    )
    parser.add_argument(
        "--passive",
        action="store_true",
        help="Run strictly passive non-mutating GET checks without creating sessions (default).",
    )

    # Use parse_known_args to allow calling from other scripts or CLI
    parsed, _ = parser.parse_known_args()
    is_active = active or parsed.active

    mode_str = "ACTIVE (Passive Checks + Session Lifecycle Probe)" if is_active else "PASSIVE (Strictly Non-Mutating GET Checks)"

    print("==================================================================")
    print("  Story Connect Policy Demo — Local Offline Health Checks")
    print("==================================================================")
    print(f"Mode:                 {mode_str}")
    print(f"Target API Base:      {DEFAULT_API_BASE}")
    print(f"Target Frontend Base: {DEFAULT_FRONTEND_BASE}")
    print("------------------------------------------------------------------")

    all_passed, results = run_all_checks(active=is_active)

    for r in results:
        status_marker = "[ PASS ]" if r.passed else "[ FAIL ]"
        print(f"{status_marker} {r.name:24} : {r.message}")
        if r.details:
            print(f"         Details: {r.details}")

    print("------------------------------------------------------------------")
    check_count = len(results)
    if all_passed:
        print(f"RESULT: ALL {check_count} HEALTH CHECKS PASSED (100% Loopback Healthy)")
        print(f"Demo Interface URL:   {DEFAULT_FRONTEND_BASE}/#/demo")
        print(f"Demo API Health URL:  {DEFAULT_API_BASE}/demo-api/health")
        print("==================================================================")
        return 0
    else:
        print("RESULT: HEALTH CHECKS FAILED — Review failed items above.")
        print("==================================================================")
        return 1


if __name__ == "__main__":
    sys.exit(main())
