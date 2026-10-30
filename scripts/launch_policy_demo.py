"""Unified offline launcher for Story Connect AI Policy Change & Conflict Investigator.

Starts the isolated demo API (127.0.0.1:8083) and Vite frontend (127.0.0.1:5174).

Safety & Operating Constraints:
- Loopback only: binds exclusively to 127.0.0.1.
- Isolated: does NOT start the active policy API (policy_api.py) or handover backend.
- Non-destructive: checks port occupancy and requires exact recorded process identity before termination.
- Residual limitation: PID reuse can still race the final identity check; Windows tree termination may affect descendants.
- Safe shutdown: tracks launcher-created child PIDs in .policy_demo_runtime.json.
- No credential access: never reads or prints .env, secrets, or environment variables.
- Platform: Windows with Python 3.12 (.venv) and Node.js/npm.
"""
from __future__ import annotations

import argparse
import json
import ntpath
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any

API_PORT = 8083
FRONTEND_PORT = 5174
HOST = "127.0.0.1"

REPO_HACKATHON_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_HACKATHON_DIR / "backend"
FRONTEND_DIR = REPO_HACKATHON_DIR / "frontend"
VITE_CLI = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
RUNTIME_FILE = REPO_HACKATHON_DIR / ".policy_demo_runtime.json"

PYTHON_EXE = REPO_HACKATHON_DIR / ".venv" / "Scripts" / "python.exe"
if not PYTHON_EXE.exists():
    PYTHON_EXE = Path(sys.executable)

FRONTEND_URL = f"http://{HOST}:{FRONTEND_PORT}/#/demo"
API_HEALTH_URL = f"http://{HOST}:{API_PORT}/demo-api/health"


def api_launch_command() -> list[str]:
    return [str(PYTHON_EXE), str(BACKEND_DIR / "policy_demo_api.py")]


def frontend_launch_command(node_exe: str | None = None) -> list[str]:
    resolved_node = node_exe or shutil.which("node")
    if not resolved_node:
        raise FileNotFoundError("Node.js executable was not found on PATH.")
    return [resolved_node, str(VITE_CLI), "--configLoader", "runner", "--host", HOST, "--port", str(FRONTEND_PORT)]


def expected_identity(command: list[str]) -> dict[str, Any]:
    return {"executable": str(Path(command[0]).resolve()), "argv": command}


def is_port_in_use(port: int, host: str = HOST) -> bool:
    """Check if a TCP port is currently occupied on loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def get_pid_using_port_windows(port: int) -> int | None:
    """Get the owning PID of a listening port on Windows via netstat without third-party deps."""
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for line in output.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5 and parts[0].upper() == "TCP":
                local_addr = parts[1]
                state = parts[3].upper()
                if local_addr.endswith(f":{port}") and state == "LISTENING":
                    return int(parts[4])
    except Exception:
        pass
    return None


def write_runtime_pids(
    api_pid: int | None,
    frontend_pid: int | None,
    api_identity: dict[str, Any] | None = None,
    frontend_identity: dict[str, Any] | None = None,
) -> None:
    """Record launcher-created child process IDs to a local runtime file."""
    data = {
        "api_pid": api_pid,
        "frontend_pid": frontend_pid,
        "api_identity": api_identity,
        "frontend_identity": frontend_identity,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api_url": API_HEALTH_URL,
        "frontend_url": FRONTEND_URL,
    }
    temporary = RUNTIME_FILE.with_name(RUNTIME_FILE.name + ".tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(RUNTIME_FILE)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_runtime_pids() -> dict[str, Any] | None:
    """Read launcher-created process IDs if runtime file exists."""
    if not RUNTIME_FILE.exists():
        return None
    try:
        data = json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def remove_runtime_file() -> bool:
    """Safely remove the runtime PID file."""
    try:
        if RUNTIME_FILE.exists():
            RUNTIME_FILE.unlink()
        return not RUNTIME_FILE.exists()
    except OSError:
        return False


def is_process_running(pid: int) -> bool | None:
    """Check if a specific process ID is currently alive."""
    if sys.platform == "win32":
        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for row in __import__("csv").reader(output.splitlines()):
                if len(row) >= 2 and row[1].strip() == str(pid):
                    return True
            return False
        except Exception:
            return None
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return None


def get_process_identity_windows(pid: int) -> dict[str, Any] | None:
    """Retrieve process identity metadata (Name, CommandLine, ExecutablePath) on Windows.

    Residual Limitation Notice:
    If a process runs with elevated privileges while this inspection runs non-elevated,
    or if WMI service is unavailable, CommandLine may be unreadable. In all ambiguous
    cases, verify_process_ownership fails closed and refuses to terminate.
    """
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}' | "
            "Select-Object ProcessId, Name, CommandLine, ExecutablePath | ConvertTo-Json -Compress",
        ]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=3.0).strip()
        if output:
            data = json.loads(output)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return None


def verify_process_ownership(
    pid: int,
    service_name: str,
    identity_getter: Any = None,
    expected: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Match the complete executable path and exact argument vector recorded at launch."""
    getter = identity_getter or get_process_identity_windows
    try:
        info = getter(pid)
    except Exception:
        info = None
    if not isinstance(info, dict):
        return False, f"Process PID {pid} is not running or process metadata could not be queried."

    if service_name not in {"Demo API", "Frontend"} or not isinstance(expected, dict):
        return False, f"Expected launch identity is missing for {service_name}."
    executable, argv = expected.get("executable"), expected.get("argv")
    if not isinstance(executable, str) or not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
        return False, f"Expected launch identity is malformed for {service_name}."
    if service_name == "Demo API":
        canonical = api_launch_command()
        if [ntpath.normcase(arg) for arg in argv] != [ntpath.normcase(arg) for arg in canonical]:
            return False, "Recorded Demo API arguments do not match the exact launcher command."
        if ntpath.normcase(ntpath.normpath(executable)) != ntpath.normcase(ntpath.normpath(str(Path(canonical[0]).resolve()))):
            return False, "Recorded Demo API executable does not match the configured Python executable."
    else:
        try:
            canonical = frontend_launch_command()
        except Exception:
            return False, "Configured Node executable is unavailable; refusing to terminate."
        if argv != canonical:
            return False, "Recorded Frontend arguments do not match the exact Node/Vite launcher command."
    if str(info.get("ProcessId")) != str(pid):
        return False, f"Process metadata PID does not match {pid}."
    actual_executable, command_line = info.get("ExecutablePath"), info.get("CommandLine")
    if not isinstance(actual_executable, str) or not isinstance(command_line, str):
        return False, f"Process metadata is incomplete for PID {pid}."
    if ntpath.normcase(ntpath.normpath(argv[0])) != ntpath.normcase(ntpath.normpath(executable)):
        return False, f"Recorded {service_name} executable and command line disagree."
    if ntpath.normcase(ntpath.normpath(actual_executable)) != ntpath.normcase(ntpath.normpath(executable)):
        return False, f"Process executable does not match the recorded {service_name} executable."
    if ntpath.normcase(command_line) != ntpath.normcase(subprocess.list2cmdline(argv)):
        return False, f"Process command line does not exactly match the recorded {service_name} launch."
    return True, f"Exact launch identity verified as {service_name}."


def _identity_signature(info: dict[str, Any] | None) -> tuple[Any, Any, Any, Any] | None:
    if not isinstance(info, dict):
        return None
    return (info.get("ProcessId"), info.get("Name"), info.get("ExecutablePath"), info.get("CommandLine"))


def wait_for_process_exit(pid: int, timeout: float = 2.0) -> bool:
    """Confirm process exit; metadata or process-query failures are not treated as exit."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = is_process_running(pid)
        if state is False:
            return True
        if state is None:
            return False
        time.sleep(0.05)
    return is_process_running(pid) is False


def terminate_launcher_process(
    pid: int,
    service_name: str,
    identity_getter: Any = None,
    killer: Any = None,
    expected: dict[str, Any] | None = None,
    running_getter: Any = None,
    exit_waiter: Any = None,
) -> bool:
    """Terminate only after repeat identity reads; PID replacement can still race the last check."""
    running_getter = running_getter or is_process_running
    exit_waiter = exit_waiter or wait_for_process_exit
    try:
        state = running_getter(pid)
    except Exception:
        state = None
    if state is False:
        return True
    if state is None:
        print(f"  [{service_name}] Cannot determine whether PID {pid} is running; refusing termination.")
        return False
    getter = identity_getter or get_process_identity_windows
    try:
        first_info = getter(pid)
    except Exception:
        first_info = None
    verified, reason = verify_process_ownership(
        pid, service_name, identity_getter=lambda _pid: first_info, expected=expected
    )
    if not verified:
        print(f"  [{service_name}] Refusing to terminate PID {pid}: {reason}")
        return False
    try:
        second_info = getter(pid)
    except Exception:
        second_info = None
    if _identity_signature(second_info) != _identity_signature(first_info):
        print(f"  [{service_name}] Refusing to terminate PID {pid}: identity changed during verification.")
        return False
    try:
        state = running_getter(pid)
    except Exception:
        state = None
    if state is not True:
        print(f"  [{service_name}] Refusing to terminate PID {pid}: running state became uncertain.")
        return False

    print(f"  [{service_name}] Verified ownership ({reason}). Stopping PID {pid}...")
    try:
        if killer:
            killer(pid)
        elif sys.platform == "win32":
            # Windows tree termination can affect descendants and is not atomic with identity checks.
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if completed.returncode != 0:
                return False
        else:
            os.kill(pid, signal.SIGTERM)
        return bool(exit_waiter(pid))
    except Exception as exc:
        print(f"  [{service_name}] Failed to terminate PID {pid}: {exc}")
        return False


def cleanup_tracked_processes(entries: list[dict[str, Any]], terminator: Any = None) -> list[str]:
    """Attempt each tracked PID and retain the runtime record for unresolved entries."""
    unresolved: list[str] = []
    for entry in entries:
        pid, service = entry.get("pid"), entry.get("service")
        if type(pid) is not int or pid <= 0 or not isinstance(service, str):
            unresolved.append(str(service or "unknown service"))
            continue
        if not (terminator or terminate_launcher_process)(pid, service, expected=entry.get("identity")):
            unresolved.append(f"{service} (PID {pid})")
    if unresolved:
        print("Unresolved tracked processes: " + ", ".join(unresolved))
        print("Runtime recovery record retained.")
    else:
        if remove_runtime_file():
            print("All tracked processes are confirmed stopped; runtime recovery record cleared.")
        else:
            unresolved.append("runtime recovery record could not be removed")
            print("All processes stopped, but the runtime recovery record could not be removed.")
    return unresolved


def _runtime_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for pid_key, service, identity_key in (
        ("api_pid", "Demo API", "api_identity"),
        ("frontend_pid", "Frontend", "frontend_identity"),
    ):
        pid = data.get(pid_key)
        if pid is not None:
            entries.append({"pid": pid, "service": service, "identity": data.get(identity_key)})
    return entries


def _write_entries(entries: list[dict[str, Any]]) -> None:
    api = next((item for item in entries if item.get("service") == "Demo API"), None)
    frontend = next((item for item in entries if item.get("service") == "Frontend"), None)
    write_runtime_pids(
        api.get("pid") if api else None,
        frontend.get("pid") if frontend else None,
        api.get("identity") if api else None,
        frontend.get("identity") if frontend else None,
    )


def _rollback(entries: list[dict[str, Any]], persist_on_failure: bool = True, terminator: Any = None) -> bool:
    unresolved = cleanup_tracked_processes(entries, terminator=terminator)
    if unresolved and persist_on_failure and any("PID " in item for item in unresolved):
        try:
            _write_entries(entries)
            print("Recovery record written for unresolved processes.")
        except Exception as exc:
            print(f"Could not persist recovery record for {', '.join(unresolved)}: {exc}")
    return not unresolved


def stop_demo() -> int:
    """Stop only launcher-owned processes recorded in the runtime file."""
    print("==================================================================")
    print("  Story Connect Policy Demo — Safe Shutdown")
    print("==================================================================")
    data = read_runtime_pids()
    if not data:
        if RUNTIME_FILE.exists():
            print("Runtime recovery record exists but could not be parsed; it was retained for inspection.")
            print("==================================================================")
            return 1
        print("No launcher runtime file found (.policy_demo_runtime.json).")
        print("No launcher-owned processes to stop.")
        print("Note: If processes were started independently or via IDE tasks,")
        print("manage them through their respective task IDs or processes.")
        print("==================================================================")
        return 0

    if "api_pid" not in data or "frontend_pid" not in data:
        print("Runtime recovery record is incomplete; it was retained and no process was terminated.")
        print("==================================================================")
        return 1
    if type(data.get("api_pid")) is not int or data["api_pid"] <= 0:
        print("Runtime recovery record has an invalid API PID; it was retained and no process was terminated.")
        print("==================================================================")
        return 1
    frontend_pid = data.get("frontend_pid")
    if frontend_pid is not None and (type(frontend_pid) is not int or frontend_pid <= 0):
        print("Runtime recovery record has an invalid frontend PID; it was retained and no process was terminated.")
        print("==================================================================")
        return 1

    unresolved = cleanup_tracked_processes(_runtime_entries(data))
    print("==================================================================")
    return 1 if unresolved else 0


def check_status() -> int:
    """Report status of demo ports and launcher runtime file."""
    print("==================================================================")
    print("  Story Connect Policy Demo — Status Check")
    print("==================================================================")

    api_in_use = is_port_in_use(API_PORT)
    frontend_in_use = is_port_in_use(FRONTEND_PORT)

    api_pid = get_pid_using_port_windows(API_PORT) if api_in_use else None
    frontend_pid = get_pid_using_port_windows(FRONTEND_PORT) if frontend_in_use else None

    runtime = read_runtime_pids()

    print(f"Demo API Port ({API_PORT}):       {'IN USE (PID ' + str(api_pid) + ')' if api_in_use else 'FREE'}")
    print(f"Frontend Port ({FRONTEND_PORT}):       {'IN USE (PID ' + str(frontend_pid) + ')' if frontend_in_use else 'FREE'}")
    print(f"Launcher Runtime File: {'FOUND' if runtime else 'NOT FOUND'}")
    if runtime:
        print(f"  Recorded API PID:      {runtime.get('api_pid')}")
        print(f"  Recorded Frontend PID: {runtime.get('frontend_pid')}")
        print(f"  Started At:            {runtime.get('created_at')}")

    print("------------------------------------------------------------------")
    if api_in_use and frontend_in_use:
        print("STATUS: Demo services are running.")
        print(f"  Demo Web Interface: {FRONTEND_URL}")
        print(f"  API Health URL:     {API_HEALTH_URL}")
    elif not api_in_use and not frontend_in_use:
        print("STATUS: Demo services are stopped.")
    else:
        print("STATUS: Partially running. Inspect ports above.")
    print("==================================================================")
    return 0


def run_health_checks_cmd(active: bool = False) -> int:
    """Execute the local health check suite (passive by default, active if requested)."""
    from check_policy_demo_health import main as health_main
    return health_main(active=active)


def wait_for_demo_ports(timeout: float = 8.0, port_checker: Any = None) -> bool:
    port_checker = port_checker or is_port_in_use
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_checker(API_PORT) and port_checker(FRONTEND_PORT):
            return True
        time.sleep(0.5)
    return False


def launch_demo(
    background: bool = False,
    popen_factory: Any = None,
    port_checker: Any = None,
    startup_waiter: Any = None,
    terminator: Any = None,
) -> int:
    """Launch the demo API and frontend with pre-flight port checks and PID tracking."""
    print("==================================================================")
    print("  Story Connect Policy Demo — Unified Offline Launcher")
    print("==================================================================")
    print(f"Host:              {HOST} (loopback only)")
    print(f"Demo API Port:     {API_PORT}")
    print(f"Frontend Port:     {FRONTEND_PORT}")
    print(f"Python Executable: {PYTHON_EXE}")
    print("------------------------------------------------------------------")

    # 1. Preflight port checks
    port_checker = port_checker or is_port_in_use
    api_busy = port_checker(API_PORT)
    fe_busy = port_checker(FRONTEND_PORT)

    if api_busy and fe_busy:
        print("[NOTICE] Both ports 8083 and 5174 are already occupied.")
        print("Checking if existing services respond to health checks...")
        from check_policy_demo_health import run_all_checks
        passed, _ = run_all_checks()
        if passed:
            print("[SUCCESS] Existing demo services are healthy and active.")
            print(f"  Demo Interface: {FRONTEND_URL}")
            print(f"  API Health:     {API_HEALTH_URL}")
            print("Launcher will not start duplicate processes.")
            print("==================================================================")
            return 0
        else:
            print("[ERROR] Ports are occupied but health check failed.")
            print("Existing processes must be inspected or stopped before relaunching.")
            print("The launcher refuses to kill existing processes automatically.")
            print("==================================================================")
            return 1

    if api_busy:
        pid = get_pid_using_port_windows(API_PORT)
        print(f"[ERROR] Port {API_PORT} is already occupied (PID {pid}).")
        print("Cannot start Demo API. The launcher will not replace existing processes.")
        return 1

    if fe_busy:
        pid = get_pid_using_port_windows(FRONTEND_PORT)
        print(f"[ERROR] Port {FRONTEND_PORT} is already occupied (PID {pid}).")
        print("Cannot start Frontend. The launcher will not replace existing processes.")
        return 1

    # 2. Launch Demo API
    api_script = BACKEND_DIR / "policy_demo_api.py"
    if not api_script.exists():
        print(f"[ERROR] policy_demo_api.py not found at {api_script}")
        return 1
    try:
        api_command = api_launch_command()
        frontend_command = frontend_launch_command()
    except Exception as exc:
        print(f"[ERROR] Could not prepare launcher commands: {exc}")
        return 1
    api_identity = expected_identity(api_command)
    frontend_identity = expected_identity(frontend_command)
    entries: list[dict[str, Any]] = []
    popen = popen_factory or subprocess.Popen
    try:
        print(f"Starting Demo API on http://{HOST}:{API_PORT}...")
        api_proc = popen(api_command, cwd=str(REPO_HACKATHON_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        entries.append({"pid": api_proc.pid, "service": "Demo API", "identity": api_identity})
        print(f"  Demo API started (PID {api_proc.pid}).")
        _write_entries(entries)

        print(f"Starting Frontend on http://{HOST}:{FRONTEND_PORT}...")
        fe_proc = popen(frontend_command, cwd=str(FRONTEND_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        entries.append({"pid": fe_proc.pid, "service": "Frontend", "identity": frontend_identity})
        print(f"  Frontend started (PID {fe_proc.pid}).")
        _write_entries(entries)

        print("Waiting for demo services to initialize (up to 8 seconds)...")
        ready = (startup_waiter or wait_for_demo_ports)(port_checker=port_checker)
        if not ready:
            print("[ERROR] Demo services did not open ports within timeout.")
            _rollback(entries, terminator=terminator)
            return 1
    except KeyboardInterrupt:
        print("[WARNING] Startup interrupted; rolling back launcher-created processes.")
        _rollback(entries, terminator=terminator)
        return 1
    except Exception as exc:
        print(f"[ERROR] Startup failed: {exc}")
        _rollback(entries, terminator=terminator)
        return 1

    print("------------------------------------------------------------------")
    print("[SUCCESS] Story Connect Policy Demo is running offline on loopback:")
    print(f"  * Web Interface:  {FRONTEND_URL}")
    print(f"  * Demo API:       {API_HEALTH_URL}")
    print("  * Scenarios:      http://127.0.0.1:8083/demo-api/scenarios")
    print("------------------------------------------------------------------")
    print("To verify health:   python hackathon/scripts/launch_policy_demo.py --health")
    print("To check status:    python hackathon/scripts/launch_policy_demo.py --status")
    print("To safe shutdown:   python hackathon/scripts/launch_policy_demo.py --stop")
    print("==================================================================")

    if background:
        return 0

    # Foreground mode: monitor child processes and handle graceful shutdown
    print("Running in foreground mode. Press Ctrl+C to stop demo services.")
    try:
        while True:
            time.sleep(1.0)
            if api_proc.poll() is not None:
                print("\n[WARNING] Demo API process terminated unexpectedly.")
                break
            if fe_proc.poll() is not None:
                print("\n[WARNING] Frontend process terminated unexpectedly.")
                break
    except KeyboardInterrupt:
        print("\nShutdown requested by user (Ctrl+C).")
    except Exception as exc:
        print(f"\n[ERROR] Foreground monitor failed: {exc}")
        stopped = _rollback(entries, terminator=terminator)
        return 0 if stopped else 1
    stopped = _rollback(entries, terminator=terminator)
    if not stopped:
        print("Foreground shutdown incomplete; unresolved services are listed above.")
        return 1
    print("All launcher processes are confirmed stopped.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified offline launcher for Story Connect Policy Investigator Demo",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check port occupancy and launcher status.",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Run local loopback health checks against running demo services (passive by default).",
    )
    parser.add_argument(
        "--active",
        action="store_true",
        help="Run active mutating lifecycle checks in addition to passive health checks.",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Safely terminate launcher-created child processes.",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="Launch services in the background and return immediately.",
    )

    args = parser.parse_args()

    if args.active and not args.health:
        parser.error("--active is valid only together with --health")

    if args.status:
        return check_status()
    if args.health:
        return run_health_checks_cmd(active=args.active)
    if args.stop:
        return stop_demo()

    return launch_demo(background=args.background)


if __name__ == "__main__":
    sys.exit(main())
