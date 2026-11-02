"""Measure how sensitive the suite is to the safety properties it claims.

Line coverage answers "was this line executed". It does not answer the question an audit
needs: if the control on that line were removed, would anything fail? This script answers
the second question by deleting each control in a throwaway copy of the backend and running
the suite against the copy.

Mutation = (file, exact substring, replacement, the property it removes).
The script never touches the working tree: every run happens in its own copy under /tmp.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path("/home/alex/policy-evidence-fix/backend")
REPO = Path("/home/alex/policy-evidence-fix")
# The suite imports a helper from ../scripts and reads ../data, so a copy of backend alone
# cannot even collect. Copy the parts the suite needs, nothing more.
NEEDED = ("backend", "scripts", "data", "pytest.ini", "README.md")
PYTHON = "/home/alex/policy-evidence-latest/.venv/bin/python"

MUTATIONS = [
    (
        "app/decision_table.py",
        "    group = group_key(item)",
        "    group = item.source_group or item.source_record_id",
        "source-group normalisation (zero-width / NFC)",
    ),
    (
        "app/decision_table.py",
        'policy_id="SIGNED_MARGIN_3_TO_1",\n    min_support_groups=2,',
        'policy_id="SIGNED_MARGIN_3_TO_1",\n    min_support_groups=1,',
        "two independent groups required for SUPPORTED",
    ),
    (
        "app/provider_safety.py",
        "MAX_PROPOSALS = 43",
        "MAX_PROPOSALS = 4343",
        "proposal capacity budget",
    ),
    (
        "app/provider_safety.py",
        "MAX_REQUEST_BYTES = 16 * 1024",
        "MAX_REQUEST_BYTES = 16 * 1024 * 1024",
        "provider request byte budget",
    ),
    (
        "app/main.py",
        "    if request.url.path in _RATE_LIMIT_EXEMPT_PATHS:\n        return await call_next(request)",
        "    if request.url.path in _RATE_LIMIT_EXEMPT_PATHS:\n        return await call_next(request)\n    return await call_next(request)",
        "rate limiting at all",
    ),
    (
        "app/store.py",
        'SELECT * FROM records WHERE id=? AND restricted=0',
        'SELECT * FROM records WHERE id=?',
        "restricted records excluded from reads",
    ),
    (
        "app/semantic_guard.py",
        "            or _NEGATED_FRAME.search(final_clause) is not None\n",
        "",
        "negated propositional frame ('not true that')",
    ),
    (
        "app/semantic_guard.py",
        "    return re.search(r\"\\bthat\\b\", tail, re.IGNORECASE) is None",
        "    return True",
        "quantifier scoping in subject position",
    ),
    (
        "app/mock_provider.py",
        "            return validate_fixture_output(fixture_output, records)",
        "            return fixture_output",
        "fixture citation validation",
    ),
    (
        "app/engine.py",
        'if quote not in record.text or len(quote.strip()) < 3:',
        'if len(quote) < 0:',
        "quote grounding against the named record",
    ),
    (
        "app/engine.py",
        "record = next((r for r in records if r.id == record_id and not r.restricted), None)",
        "record = next((r for r in records if r.id == record_id), None)",
        "restricted records excluded from challenge",
    ),
]


def run_suite(cwd: Path) -> tuple[bool, str, str]:
    result = subprocess.run(
        [PYTHON, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"],
        cwd=cwd,
        env={"PYTHONPATH": ".:../scripts", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=900,
    )
    summary = result.stdout.strip().splitlines()
    tail = [line for line in summary if line.strip()][-1:] or [""]
    # A kill only counts if a test failed. A collection error kills every mutation for the
    # same reason, so it is reported separately and excluded from the kill rate.
    kind = "failed" if " failed" in tail[0] else ("error" if "error" in tail[0] else "other")
    return result.returncode == 0, tail[0], kind


def main() -> int:
    records = []

    # Control: an unmutated copy must be green, or nothing below means anything.
    with tempfile.TemporaryDirectory(prefix="control-") as directory:
        root = Path(directory)
        for name in NEEDED:
            source = REPO / name
            if source.is_dir():
                shutil.copytree(source, root / name, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.sqlite3"))
            else:
                shutil.copy2(source, root / name)
        green, detail, kind = run_suite(root / "backend")
    print(f"[control] {'GREEN' if green else 'RED':5} {detail}", flush=True)
    if not green:
        print("CONTROL FAILED: the harness cannot measure anything until an unmutated copy passes.")
        return 1
    for index, (relative, old, new, description) in enumerate(MUTATIONS, start=1):
        with tempfile.TemporaryDirectory(prefix=f"mut{index}-") as directory:
            root = Path(directory)
            for name in NEEDED:
                source = REPO / name
                if source.is_dir():
                    shutil.copytree(source, root / name, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.sqlite3"))
                else:
                    shutil.copy2(source, root / name)
            copy = root / "backend"
            target = copy / relative
            text = target.read_text()
            if text.count(old) != 1:
                records.append({"mutation": description, "status": "NOT_APPLIED", "detail": f"{text.count(old)} matches"})
                print(f"[{index}] NOT_APPLIED  {description}", flush=True)
                continue
            target.write_text(text.replace(old, new))

            survived, detail, kind = run_suite(copy)
            status = "SURVIVED" if survived else ("KILLED" if kind == "failed" else "KILLED_BY_ERROR")
            records.append({"mutation": description, "status": status, "detail": detail})
            print(f"[{index}] {status:15} {description} | {detail}", flush=True)

    applied = [record for record in records if record["status"] != "NOT_APPLIED"]
    killed = [record for record in applied if record["status"] == "KILLED"]
    errors = [record for record in applied if record["status"] == "KILLED_BY_ERROR"]
    survivors = [record for record in applied if record["status"] == "SURVIVED"]
    print(
        "\napplied", len(applied), "killed-by-failure", len(killed),
        "killed-by-error", len(errors), "survived", len(survivors),
    )
    if applied:
        print("test-failure kill rate %.1f%%" % (100.0 * len(killed) / len(applied)))
    for record in errors:
        print("ERROR-KILL (not counted):", record["mutation"], "|", record["detail"])
    for record in survivors:
        print("SURVIVOR:", record["mutation"], "|", record["detail"])
    Path("/home/alex/policy-evidence-fix/ct3/audit/mutation-results.json").write_text(
        json.dumps(records, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
