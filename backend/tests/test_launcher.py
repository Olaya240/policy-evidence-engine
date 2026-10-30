"""Offline tests for the Story Connect Policy Demo Launcher and Health Checks.

Verifies:
- Port detection invariants (loopback-only).
- Health check functions against local demo services.
- Safe runtime PID file serialization and removal.
- Safety invariants: no external network targets, no credential access.
"""
from __future__ import annotations

import ast
import io
import json
from email.message import Message
from pathlib import Path
import sys
from typing import Any

import pytest

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_policy_demo_health as health
import launch_policy_demo as launcher


def test_loopback_binding_invariants() -> None:
    """Launcher and health-checker must bind only to 127.0.0.1."""
    assert launcher.HOST == "127.0.0.1"
    assert launcher.API_PORT == 8083
    assert launcher.FRONTEND_PORT == 5174
    assert launcher.FRONTEND_URL.startswith("http://127.0.0.1:5174")
    assert launcher.API_HEALTH_URL.startswith("http://127.0.0.1:8083")

    assert health.DEFAULT_API_BASE.startswith("http://127.0.0.1:8083")
    assert health.DEFAULT_FRONTEND_BASE.startswith("http://127.0.0.1:5174")


def test_is_port_in_use_uses_only_requested_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    class FakeSocket:
        def __init__(self, *_args): pass
        def settimeout(self, _timeout): pass
        def connect_ex(self, address):
            seen.append(address)
            return 0 if address[1] == 8083 else 1
        def __enter__(self): return self
        def __exit__(self, *_args): pass

    monkeypatch.setattr(launcher.socket, "socket", FakeSocket)
    assert launcher.is_port_in_use(8083) is True
    assert launcher.is_port_in_use(59998) is False
    assert seen == [("127.0.0.1", 8083), ("127.0.0.1", 59998)]


def test_runtime_pid_file_serialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime file correctly writes and parses JSON PIDs, and removes cleanly."""
    fake_runtime_file = tmp_path / ".policy_demo_runtime_test.json"
    monkeypatch.setattr(launcher, "RUNTIME_FILE", fake_runtime_file)

    assert launcher.read_runtime_pids() is None
    launcher.write_runtime_pids(api_pid=12345, frontend_pid=12346)
    assert fake_runtime_file.exists()

    data = launcher.read_runtime_pids()
    assert data is not None
    assert data["api_pid"] == 12345
    assert data["frontend_pid"] == 12346
    assert "created_at" in data

    launcher.remove_runtime_file()
    assert not fake_runtime_file.exists()
    assert launcher.read_runtime_pids() is None


def test_runtime_record_update_is_atomic_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(launcher, "RUNTIME_FILE", runtime)
    launcher.write_runtime_pids(101, None, _make_expected(), None)
    old = runtime.read_text()
    def fail_replace(_self, _target):
        raise OSError("synthetic replace failure")
    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        launcher.write_runtime_pids(101, 102, _make_expected(), _make_expected("Frontend"))
    assert runtime.read_text() == old
    assert not runtime.with_name(runtime.name + ".tmp").exists()


def test_api_health_check_passes_with_mocked_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200
        body = b'{"status":"ready","mode":"offline_demo"}'
        offset = 0
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def read(self, size=-1):
            chunk = self.body[self.offset:self.offset + size]
            self.offset += len(chunk)
            return chunk
    seen = []
    monkeypatch.setattr(health, "_open_local", lambda req, timeout: (seen.append((req.full_url, req.get_method())) or Response()))
    res = health.check_api_health()
    assert res.passed is True
    assert seen == [("http://127.0.0.1:8083/demo-api/health", "GET")]


def test_scenarios_listing_passes_with_mocked_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "_http_get_json", lambda *_args: (200, [{"id": sid} for sid in ["scheduling", "uniform_grooming", "lounge_access"]]))
    res = health.check_scenarios_listing()
    assert res.passed is True
    assert res.details["scenario_ids"] == ["scheduling", "uniform_grooming", "lounge_access"]


def test_scenario_loading_passes_with_mocked_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {"scheduling": "COMPATIBLE_CHANGE", "uniform_grooming": "CONTRADICTION", "lounge_access": "SCOPE_OR_TIME_DIFFERENCE"}
    monkeypatch.setattr(health, "_http_get_json", lambda url: (200, {"proposed_relation": values[url.rsplit("=", 1)[1]]}))
    res = health.check_scenario_loading()
    assert res.passed is True
    assert res.details["scheduling"] == "COMPATIBLE_CHANGE"
    assert res.details["uniform_grooming"] == "CONTRADICTION"
    assert res.details["lounge_access"] == "SCOPE_OR_TIME_DIFFERENCE"


def test_session_lifecycle_check_passes_only_when_explicitly_called(monkeypatch: pytest.MonkeyPatch) -> None:
    gets = []
    posts = []
    def fake_get(url):
        gets.append(url)
        if url.endswith("/history"):
            return 200, {"event_count": 1}
        return 200, {"status": "ready"}
    def fake_post(url, payload):
        posts.append(url)
        if url.endswith("/session/new"):
            return 200, {"session_id": "a" * 32}
        if url.endswith("/challenge"):
            return 200, {"sequence_number": 1}
        return 200, {"event_count": 0}
    monkeypatch.setattr(health, "_http_get_json", fake_get)
    monkeypatch.setattr(health, "_http_post_json", fake_post)
    res = health.check_session_lifecycle()
    assert res.passed is True
    assert res.details["event_count_after_reset"] == 0


def test_session_lifecycle_accepts_lowercase_hex_id_and_completes_all_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = "abcdef0123456789abcdef0123456789"
    posts = []
    gets = []

    def fake_post(url, _payload):
        posts.append(url)
        if url.endswith("/session/new"):
            return 200, {"session_id": session_id}
        if url.endswith("/challenge"):
            return 200, {"sequence_number": 1}
        return 200, {"event_count": 0}

    def fake_get(url):
        gets.append(url)
        return 200, {"event_count": 1}

    monkeypatch.setattr(health, "_http_post_json", fake_post)
    monkeypatch.setattr(health, "_http_get_json", fake_get)

    result = health.check_session_lifecycle()

    assert result.passed
    assert any(url.endswith(f"/session/{session_id}/history") for url in gets)
    assert any(url.endswith(f"/session/{session_id}/reset") for url in posts)


@pytest.mark.parametrize("session_id", [
    "a" * 31,
    "a" * 33,
    "A" * 32,
    "a" * 15 + "/" + "a" * 16,
    "a" * 15 + "?" + "a" * 16,
    "a" * 15 + " " + "a" * 16,
    "",
    None,
    123,
])
def test_session_lifecycle_rejects_invalid_id_before_history_or_reset(
    session_id: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = []
    gets = []

    def fake_post(url, _payload):
        posts.append(url)
        return 200, {"session_id": session_id}

    monkeypatch.setattr(health, "_http_post_json", fake_post)
    monkeypatch.setattr(health, "_http_get_json", lambda url: (gets.append(url) or (200, {"event_count": 1})))

    result = health.check_session_lifecycle()

    assert not result.passed
    assert "Invalid session_id format" in result.message
    assert posts == ["http://127.0.0.1:8083/demo-api/session/new"]
    assert gets == []


def test_frontend_availability_check_passes_with_mocked_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200
        body = b'<html><div id="root"></div></html>'
        offset = 0
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def read(self, size=-1):
            chunk = self.body[self.offset:self.offset + size]
            self.offset += len(chunk)
            return chunk
    seen = []
    monkeypatch.setattr(health, "_open_local", lambda req, timeout: (seen.append(req.get_method()) or Response()))
    res = health.check_frontend_availability()
    assert res.passed is True
    assert seen == ["GET"]


@pytest.mark.parametrize("base", [
    "https://127.0.0.1:8083", "http://example.invalid:8083", "http://127.0.0.2:8083",
    "http://user@127.0.0.1:8083", "http://127.0.0.1:80", "http://127.0.0.1:8083/path", "http://localhost:8083",
    "http://127.0.0.1:8083?next=http://example.invalid", "http://[::1]:8083/bad",
])
def test_invalid_health_base_rejected_before_opener(base: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health.urllib.request, "build_opener", lambda *_args: pytest.fail("opener called for invalid URL"))
    with pytest.raises(ValueError):
        health.check_api_health(base)


def test_redirect_is_rejected_without_requesting_location(monkeypatch: pytest.MonkeyPatch) -> None:
    opened = []
    def mocked_transport(_handler, req):
        opened.append(req.full_url)
        headers = Message()
        headers["Location"] = "https://example.invalid/collect"
        response = health.urllib.response.addinfourl(io.BytesIO(b""), headers, req.full_url, 302)
        response.msg = "Found"
        return response
    monkeypatch.setattr(health.urllib.request.HTTPHandler, "http_open", mocked_transport)
    with pytest.raises(health.urllib.error.HTTPError):
        health._http_get_json("http://127.0.0.1:8083/demo-api/health")
    assert opened == ["http://127.0.0.1:8083/demo-api/health"]


def test_local_opener_uses_empty_proxy_configuration_and_no_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class FakeOpener:
        def open(self, req, timeout):
            captured["request"] = req.full_url
            captured["timeout"] = timeout
            return "mocked-response"

    real_proxy_handler = health.urllib.request.ProxyHandler
    def capture_opener(*handlers):
        captured["handlers"] = handlers
        return FakeOpener()

    monkeypatch.setattr(health.urllib.request, "ProxyHandler", real_proxy_handler)
    monkeypatch.setattr(health.urllib.request, "getproxies", lambda: pytest.fail("ambient proxies were consulted"))
    monkeypatch.setattr(health.urllib.request, "build_opener", capture_opener)
    response = health._open_local(health.urllib.request.Request("http://127.0.0.1:8083/probe"), timeout=1.25)

    assert response == "mocked-response"
    proxy_handlers = [item for item in captured["handlers"] if isinstance(item, real_proxy_handler)]
    redirect_handlers = [item for item in captured["handlers"] if isinstance(item, health._NoRedirectHandler)]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    assert len(redirect_handlers) == 1
    assert captured["request"] == "http://127.0.0.1:8083/probe"
    assert captured["timeout"] == 1.25


class _ChunkedMockResponse:
    status = 200

    def __init__(self, body: bytes, piece_size: int = 4096) -> None:
        self.body = body
        self.offset = 0
        self.piece_size = piece_size
        self.read_sizes: list[int] = []

    def __enter__(self): return self
    def __exit__(self, *_args): pass

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.offset >= len(self.body):
            return b""
        take = min(size, self.piece_size, len(self.body) - self.offset)
        result = self.body[self.offset:self.offset + take]
        self.offset += take
        return result


class _TrackedResponse(_ChunkedMockResponse):
    def __init__(self, body: bytes, *, read_error: bool = False, piece_size: int = 4096) -> None:
        super().__init__(body, piece_size=piece_size)
        self.read_error = read_error
        self.entered = False
        self.closed = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_args):
        self.closed = True

    def read(self, size: int = -1) -> bytes:
        if self.read_error:
            raise OSError("synthetic response read failure")
        return super().read(size)


def test_health_json_response_within_limit_is_read_incrementally(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'{"status":"ready","mode":"offline_demo"}'
    response = _ChunkedMockResponse(body, piece_size=7)
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: response)

    status, data = health._http_get_json("http://127.0.0.1:8083/demo-api/health")

    assert status == 200 and data["status"] == "ready"
    assert len(response.read_sizes) > 1
    assert all(0 < size <= health.RESPONSE_READ_CHUNK_BYTES for size in response.read_sizes)


def test_health_json_response_exactly_at_limit_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = b'{"ok":true}'
    body = prefix + b" " * (health.MAX_RESPONSE_BYTES - len(prefix))
    response = _ChunkedMockResponse(body, piece_size=1300)
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: response)

    status, data = health._http_get_json("http://127.0.0.1:8083/demo-api/health")

    assert status == 200 and data == {"ok": True}
    assert response.offset == health.MAX_RESPONSE_BYTES


def test_health_json_response_one_byte_over_limit_is_rejected_before_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _ChunkedMockResponse(b" " * (health.MAX_RESPONSE_BYTES + 1), piece_size=1024)
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(health.json, "loads", lambda *_args, **_kwargs: pytest.fail("oversized body reached JSON parsing"))

    with pytest.raises(health.HealthCheckResponseError, match="exceeds its size limit"):
        health._http_get_json("http://127.0.0.1:8083/demo-api/health")

    assert response.offset == health.MAX_RESPONSE_BYTES + 1


def test_active_json_post_response_uses_same_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _ChunkedMockResponse(b" " * (health.MAX_RESPONSE_BYTES + 1), piece_size=1024)
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: response)

    with pytest.raises(health.HealthCheckResponseError, match="exceeds its size limit"):
        health._http_post_json("http://127.0.0.1:8083/demo-api/session/new", {"scenario_id": "scheduling"})

    assert response.offset == health.MAX_RESPONSE_BYTES + 1


@pytest.mark.parametrize("body", [b"", b"not-json"])
def test_health_json_empty_or_malformed_response_is_controlled(body: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    response = _ChunkedMockResponse(body)
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: response)

    with pytest.raises(health.HealthCheckResponseError, match="empty or invalid JSON"):
        health._http_get_json("http://127.0.0.1:8083/demo-api/health")


def test_frontend_response_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _ChunkedMockResponse(b"<html>" + b"x" * health.MAX_RESPONSE_BYTES, piece_size=2048)
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: response)

    result = health.check_frontend_availability()

    assert not result.passed
    assert "exceeds its size limit" in result.message
    assert response.offset == health.MAX_RESPONSE_BYTES + 1


@pytest.mark.parametrize("method", ["get", "post"])
def test_json_response_context_closes_after_success(method: str, monkeypatch: pytest.MonkeyPatch) -> None:
    response = _TrackedResponse(b'{"ok":true}')
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: response)

    if method == "get":
        status, data = health._http_get_json("http://127.0.0.1:8083/probe")
    else:
        status, data = health._http_post_json("http://127.0.0.1:8083/probe", {"probe": True})

    assert status == 200 and data == {"ok": True}
    assert response.entered and response.closed


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("failure", ["malformed", "oversized", "read"])
def test_json_response_context_closes_after_failure(
    method: str, failure: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if failure == "malformed":
        response = _TrackedResponse(b"not-json")
        error_type = health.HealthCheckResponseError
    elif failure == "oversized":
        response = _TrackedResponse(b" " * (health.MAX_RESPONSE_BYTES + 1), piece_size=1024)
        error_type = health.HealthCheckResponseError
    else:
        response = _TrackedResponse(b"", read_error=True)
        error_type = OSError
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: response)

    with pytest.raises(error_type):
        if method == "get":
            health._http_get_json("http://127.0.0.1:8083/probe")
        else:
            health._http_post_json("http://127.0.0.1:8083/probe", {"probe": True})

    assert response.entered and response.closed


def test_frontend_response_context_closes_after_success_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    successful = _TrackedResponse(b'<html><div id="root"></div></html>')
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: successful)
    assert health.check_frontend_availability().passed
    assert successful.entered and successful.closed

    oversized = _TrackedResponse(b"<html>" + b"x" * health.MAX_RESPONSE_BYTES, piece_size=1024)
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: oversized)
    assert not health.check_frontend_availability().passed
    assert oversized.entered and oversized.closed

    read_failure = _TrackedResponse(b"", read_error=True)
    monkeypatch.setattr(health, "_open_local", lambda *_args, **_kwargs: read_failure)
    assert not health.check_frontend_availability().passed
    assert read_failure.entered and read_failure.closed


def test_invalid_frontend_base_rejected_before_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health.urllib.request, "build_opener", lambda *_args: pytest.fail("opener called for invalid URL"))
    with pytest.raises(ValueError):
        health.check_frontend_availability("http://example.invalid:5174")


def test_passive_checks_do_not_call_post_and_active_mode_does(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("check_api_health", "check_scenarios_listing", "check_scenario_loading", "check_frontend_availability"):
        monkeypatch.setattr(health, name, lambda _name=name, **_kwargs: health.HealthCheckResult(_name, True, "ok"))
    methods = []
    def fake_get(url):
        methods.append("GET")
        return (200, {"event_count": 1}) if url.endswith("/history") else (200, {"status": "ready"})
    def fake_post(url, payload):
        methods.append("POST")
        if url.endswith("/session/new"):
            return 200, {"session_id": "b" * 32}
        if url.endswith("/challenge"):
            return 200, {"sequence_number": 1}
        return 200, {"event_count": 0}
    monkeypatch.setattr(health, "_http_get_json", fake_get)
    monkeypatch.setattr(health, "_http_post_json", fake_post)
    health.run_all_checks(active=False)
    assert "POST" not in methods
    health.run_all_checks(active=True)
    assert methods.count("POST") == 3


def test_active_flag_requires_health_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["launcher", "--active"])
    with pytest.raises(SystemExit) as exc:
        launcher.main()
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# SEC-01: PID ownership verification
# ---------------------------------------------------------------------------

def _make_expected(service: str = "Demo API") -> dict:
    command = launcher.api_launch_command() if service == "Demo API" else launcher.frontend_launch_command()
    return launcher.expected_identity(command)


def _make_identity(pid: int, expected: dict, *, command: list[str] | None = None, executable: str | None = None) -> dict:
    argv = command if command is not None else expected["argv"]
    exe = executable if executable is not None else expected["executable"]
    return {"ProcessId": pid, "Name": Path(exe).name, "ExecutablePath": exe, "CommandLine": launcher.subprocess.list2cmdline(argv)}


def test_process_identity_accepts_exact_expected_launch() -> None:
    expected = _make_expected()
    info = _make_identity(12345, expected)
    ok, _ = launcher.verify_process_ownership(12345, "Demo API", lambda _pid: info, expected)
    assert ok


@pytest.mark.parametrize("lookalike", [
    ["python.exe", "other.py", "policy_demo_api.py"],
    ["python.exe", "policy_demo_api.py", "--extra"],
    ["python.exe", "policy_demo_api.py.bak"],
])
def test_process_identity_rejects_api_lookalikes(lookalike: list[str]) -> None:
    expected = _make_expected()
    info = _make_identity(12345, expected, command=lookalike)
    ok, _ = launcher.verify_process_ownership(12345, "Demo API", lambda _pid: info, expected)
    assert not ok


def test_process_identity_rejects_wrong_executable_and_missing_metadata() -> None:
    expected = _make_expected()
    wrong = _make_identity(12345, expected, executable="C:/other/python.exe")
    assert not launcher.verify_process_ownership(12345, "Demo API", lambda _pid: wrong, expected)[0]
    missing = {"ProcessId": 12345, "ExecutablePath": expected["executable"]}
    assert not launcher.verify_process_ownership(12345, "Demo API", lambda _pid: missing, expected)[0]
    assert not launcher.verify_process_ownership(12345, "Demo API", lambda _pid: None, expected)[0]


def test_frontend_identity_rejects_adversarial_substrings_and_accepts_exact() -> None:
    expected = _make_expected("Frontend")
    exact = _make_identity(12346, expected)
    assert launcher.verify_process_ownership(12346, "Frontend", lambda _pid: exact, expected)[0]
    for argv in (["node.exe", "other.js", "dev", "5174"], ["node.exe", "vite", "frontend"], ["node.exe", "vite.js", "--port", "5174"]):
        fake = _make_identity(12346, expected, command=list(argv))
        assert not launcher.verify_process_ownership(12346, "Frontend", lambda _pid: fake, expected)[0]
    wrong_exe = _make_identity(12346, expected, executable="C:/other/node.exe")
    assert not launcher.verify_process_ownership(12346, "Frontend", lambda _pid: wrong_exe, expected)[0]


def test_termination_rechecks_identity_before_fake_killer() -> None:
    expected = _make_expected()
    exact = _make_identity(55555, expected)
    changed = dict(exact, CommandLine="python.exe unrelated.py")
    identities = iter([exact, changed])
    killed = []
    result = launcher.terminate_launcher_process(
        55555, "Demo API", identity_getter=lambda _pid: next(identities),
        expected=expected, running_getter=lambda _pid: True, killer=killed.append,
    )
    assert result is False
    assert killed == []


def test_termination_rejects_adversarial_lookalike_without_fake_killer() -> None:
    expected = _make_expected()
    fake = _make_identity(55666, expected, command=[*expected["argv"], "--label", "policy_demo_api.py"])
    killed = []
    result = launcher.terminate_launcher_process(
        55666, "Demo API", identity_getter=lambda _pid: fake, expected=expected,
        running_getter=lambda _pid: True, killer=killed.append,
    )
    assert result is False
    assert killed == []


def test_process_metadata_getter_exception_fails_closed() -> None:
    expected = _make_expected()
    def unavailable(_pid): raise OSError("synthetic metadata failure")
    assert not launcher.verify_process_ownership(12345, "Demo API", unavailable, expected)[0]


def test_termination_uses_fake_killer_only_for_exact_identity() -> None:
    expected = _make_expected()
    exact = _make_identity(55555, expected)
    identities = iter([exact, dict(exact)])
    killed = []
    result = launcher.terminate_launcher_process(
        55555, "Demo API", identity_getter=lambda _pid: next(identities), expected=expected,
        running_getter=lambda _pid: True, killer=killed.append, exit_waiter=lambda _pid: True,
    )
    assert result is True
    assert killed == [55555]


def test_cleanup_retains_runtime_record_for_refused_or_failed_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(launcher, "RUNTIME_FILE", runtime)
    launcher.write_runtime_pids(101, None, _make_expected(), None)
    unresolved = launcher.cleanup_tracked_processes(
        [{"pid": 101, "service": "Demo API", "identity": _make_expected()}],
        terminator=lambda *_args, **_kwargs: False,
    )
    assert unresolved == ["Demo API (PID 101)"]
    assert runtime.exists()


def test_successful_cleanup_removes_runtime_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(launcher, "RUNTIME_FILE", runtime)
    launcher.write_runtime_pids(101, None, _make_expected(), None)
    assert launcher.cleanup_tracked_processes(
        [{"pid": 101, "service": "Demo API", "identity": _make_expected()}],
        terminator=lambda *_args, **_kwargs: True,
    ) == []
    assert not runtime.exists()


def test_stale_process_is_removed_only_after_fake_running_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(launcher, "RUNTIME_FILE", runtime)
    launcher.write_runtime_pids(111, None, _make_expected(), None)
    queried = []
    result = launcher.terminate_launcher_process(
        111, "Demo API", expected=_make_expected(),
        identity_getter=lambda pid: pytest.fail("stale PID must not need identity lookup"),
        running_getter=lambda pid: (queried.append(pid) or False),
    )
    assert result is True
    assert queried == [111]
    assert launcher.cleanup_tracked_processes(
        [{"pid": 111, "service": "Demo API", "identity": _make_expected()}],
        terminator=lambda *_args, **_kwargs: True,
    ) == []
    assert not runtime.exists()


def _configure_fake_launch(monkeypatch: pytest.MonkeyPatch, runtime: Path, popen_factory, waiter, terminator):
    monkeypatch.setattr(launcher, "RUNTIME_FILE", runtime)
    monkeypatch.setattr(launcher, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(launcher, "api_launch_command", lambda: [sys.executable, str(launcher.BACKEND_DIR / "policy_demo_api.py")])
    monkeypatch.setattr(launcher, "frontend_launch_command", lambda: [sys.executable, "fake-vite.js", "--host", "127.0.0.1", "--port", "5174"])
    return dict(popen_factory=popen_factory, startup_waiter=waiter, terminator=terminator)


def test_startup_timeout_preserves_unresolved_runtime_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    processes = iter([type("Proc", (), {"pid": 101})(), type("Proc", (), {"pid": 102})()])
    runtime = tmp_path / "runtime.json"
    kwargs = _configure_fake_launch(monkeypatch, runtime, lambda *_args, **_kwargs: next(processes), lambda **_kwargs: False, lambda *_args, **_kwargs: False)
    assert launcher.launch_demo(background=True, **kwargs) == 1
    data = json.loads(runtime.read_text())
    assert data["api_pid"] == 101 and data["frontend_pid"] == 102


def test_frontend_start_exception_rolls_back_api_and_retains_record_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    def popen(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("synthetic frontend start failure")
        return type("Proc", (), {"pid": 201})()
    runtime = tmp_path / "runtime.json"
    kwargs = _configure_fake_launch(monkeypatch, runtime, popen, lambda **_kwargs: True, lambda *_args, **_kwargs: False)
    assert launcher.launch_demo(background=True, **kwargs) == 1
    assert json.loads(runtime.read_text())["api_pid"] == 201


def test_runtime_write_failure_rolls_back_and_retries_record_if_process_unresolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = tmp_path / "runtime.json"
    real_writer = launcher.write_runtime_pids
    calls = []
    def writer(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("synthetic record write failure")
        return real_writer(*args, **kwargs)
    monkeypatch.setattr(launcher, "write_runtime_pids", writer)
    kwargs = _configure_fake_launch(monkeypatch, runtime, lambda *_args, **_kwargs: type("Proc", (), {"pid": 301})(), lambda **_kwargs: True, lambda *_args, **_kwargs: False)
    assert launcher.launch_demo(background=True, **kwargs) == 1
    assert json.loads(runtime.read_text())["api_pid"] == 301


def test_foreground_keyboard_interrupt_retains_unresolved_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = tmp_path / "runtime.json"
    fake_proc = type("Proc", (), {"pid": 401, "poll": lambda self: None})()
    kwargs = _configure_fake_launch(monkeypatch, runtime, lambda *_args, **_kwargs: fake_proc, lambda **_kwargs: True, lambda *_args, **_kwargs: False)
    def interrupt(_seconds): raise KeyboardInterrupt
    monkeypatch.setattr(launcher.time, "sleep", interrupt)
    assert launcher.launch_demo(background=False, **kwargs) == 1
    assert json.loads(runtime.read_text())["api_pid"] == 401


def test_foreground_monitor_exception_retains_both_process_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = tmp_path / "runtime.json"
    class FakeProc:
        def __init__(self, pid): self.pid = pid
        def poll(self): raise RuntimeError("synthetic poll failure")
    processes = iter([FakeProc(411), FakeProc(412)])
    kwargs = _configure_fake_launch(monkeypatch, runtime, lambda *_args, **_kwargs: next(processes), lambda **_kwargs: True, lambda *_args, **_kwargs: False)
    assert launcher.launch_demo(background=False, **kwargs) == 1
    data = json.loads(runtime.read_text())
    assert (data["api_pid"], data["frontend_pid"]) == (411, 412)


def test_powershell_wrapper_forwards_active_only_with_health() -> None:
    source = (SCRIPTS_DIR / "launch_policy_demo.ps1").read_text(encoding="utf-8")
    assert "if ($Active -and -not $Health)" in source
    assert 'if ($Health) { $pythonArgs += "--health" }' in source
    assert 'if ($Active) { $pythonArgs += "--active" }' in source


def test_normal_stop_reports_refusal_and_keeps_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(launcher, "RUNTIME_FILE", runtime)
    launcher.write_runtime_pids(501, None, _make_expected(), None)
    monkeypatch.setattr(launcher, "terminate_launcher_process", lambda *_args, **_kwargs: False)
    assert launcher.stop_demo() == 1
    assert runtime.exists()
    assert "Demo API (PID 501)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# SEC-02: Passive vs active health check mode
# ---------------------------------------------------------------------------

def _install_fake_health(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    called: list[str] = []
    result_names = {
        "check_api_health": "api_health",
        "check_scenarios_listing": "scenarios_listing",
        "check_scenario_loading": "scenario_loading",
        "check_frontend_availability": "frontend_availability",
    }
    for name in result_names:
        def fake(*_args, _name=name, **_kwargs):
            called.append(_name)
            return health.HealthCheckResult(result_names[_name], True, "ok")
        monkeypatch.setattr(health, name, fake)
    monkeypatch.setattr(health, "check_session_lifecycle", lambda *_args: (called.append("session_lifecycle") or health.HealthCheckResult("session_lifecycle", True, "ok")))
    return called


def test_sec02_run_passive_checks_returns_4_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """Passive mode excludes the mutating session lifecycle probe."""
    called = _install_fake_health(monkeypatch)
    all_passed, results = health.run_passive_checks()
    assert all_passed
    assert len(results) == 4
    names = {r.name for r in results}
    assert "api_health" in names
    assert "scenarios_listing" in names
    assert "scenario_loading" in names
    assert "frontend_availability" in names
    assert "session_lifecycle" not in names, "Passive mode must NOT include session_lifecycle"
    assert "session_lifecycle" not in called


def test_sec02_run_all_checks_passive_returns_4_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_all_checks(active=False) returns exactly 4 results."""
    called = _install_fake_health(monkeypatch)
    all_passed, results = health.run_all_checks(active=False)
    assert all_passed
    assert len(results) == 4
    assert "session_lifecycle" not in {r.name for r in results}
    assert "session_lifecycle" not in called


def test_sec02_run_all_checks_active_returns_5_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_all_checks(active=True) returns exactly 5 results including session_lifecycle."""
    called = _install_fake_health(monkeypatch)
    all_passed, results = health.run_all_checks(active=True)
    assert all_passed
    assert len(results) == 5
    assert "session_lifecycle" in {r.name for r in results}
    assert called.count("session_lifecycle") == 1


def test_sec02_passive_mode_all_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_health(monkeypatch)
    all_passed, results = health.run_passive_checks()
    failed = [r for r in results if not r.passed]
    assert all_passed is True, f"Passive checks failed: {[r.message for r in failed]}"


def test_sec02_active_mode_all_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_health(monkeypatch)
    all_passed, results = health.run_all_checks(active=True)
    failed = [r for r in results if not r.passed]
    assert all_passed is True, f"Active checks failed: {[r.message for r in failed]}"


def test_scripts_contain_no_credentials_or_external_hosts() -> None:
    """AST inspection: launcher and health scripts must not import or load credentials or external hosts."""
    for script_file in [SCRIPTS_DIR / "launch_policy_demo.py", SCRIPTS_DIR / "check_policy_demo_health.py"]:
        source = script_file.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Check imports
        forbidden_imports = {"dotenv", "google", "openai", "anthropic"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden_imports, f"Forbidden import: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for forbidden in forbidden_imports:
                        assert not node.module.startswith(forbidden), f"Forbidden import: {node.module}"

        # Check for external URLs
        for line in source.splitlines():
            if "http://" in line or "https://" in line:
                assert "127.0.0.1" in line or "localhost" in line or "{HOST}" in line or "example.com" in line, (
                    f"External URL found in {script_file.name}: {line}"
                )
