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
# The unmutated suite takes ~47s. A mutation that removes a termination guard shows up as a
# run that never ends rather than as a failing assertion, so the run is bounded well above the
# control and the outcome is recorded as HUNG instead of being left to hang the audit.
SUITE_TIMEOUT_SECONDS = 240
# The working tree can be edited while this runs (other agents share it). One tree is
# snapshotted and every control and mutation run is made from that snapshot, so a red control
# means the snapshot itself is red, not that two runs saw different trees. A snapshot taken
# mid-edit can still be red, so the control is retried a bounded number of times against a
# fresh snapshot and the attempt that was measured is printed.
CONTROL_ATTEMPTS = 3
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.sqlite3")

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
    # --- surface added this week -------------------------------------------------
    (
        "app/store.py",
        '"SELECT * FROM records WHERE restricted=0 AND department=? AND text=? "\n'
        "            \"AND COALESCE(source_group,'')=? ORDER BY timestamp, id LIMIT 1\"",
        '"SELECT * FROM records WHERE restricted=0 AND department=? AND text=? AND 0 "\n'
        "            \"AND COALESCE(source_group,'')=? ORDER BY timestamp, id LIMIT 1\"",
        "ingestion duplicate identity (dedupe lookup never matches)",
    ),
    (
        "app/store.py",
        '"SELECT * FROM records WHERE restricted=0 AND department=? AND text=? "',
        '"SELECT * FROM records WHERE department=? AND text=? "',
        "restricted rows are not a dedupe target on ingestion",
    ),
    (
        "app/models.py",
        '        if category == "Cc":',
        '        if False:  # mutation: C0/C1 control-character check disabled',
        "control-character refusal at the schema boundary",
    ),
    (
        "app/store.py",
        "        try:\n"
        "            records.append(_record_from_row(row))\n"
        "        except CorruptStoredRow as error:\n"
        "            skipped.append(error.row)",
        "        records.append(_record_from_row(row))",
        "corrupt-row localisation (decoder raises instead of skipping/reporting)",
    ),
    (
        "app/dependency_graph.py",
        "    return tuple(sorted(cid for cid, claim in claims.items() if record_id in _cited_record_ids(claim)))",
        "    return list(cid for cid, claim in claims.items() if record_id in _cited_record_ids(claim))",
        "dependency-graph ordering determinism (unsorted direct set)",
    ),
    (
        "app/dependency_graph.py",
        "            if dependent in seen or dependent not in claims:",
        "            if dependent not in claims:",
        "dependency-graph cycle guard (visited set)",
    ),
    (
        "app/semantic_guard.py",
        "    return _EVIDENCE_ABOUTNESS_FRAME.search(segment) is not None",
        "    return False",
        "evidence-aboutness frame ('no evidence the X was Y')",
    ),
    (
        "app/semantic_guard.py",
        "    return _HEDGE_FRAME.search(segment) is not None",
        "    return False",
        "hedge frame ('perhaps the X was Y')",
    ),
]


def run_suite(cwd: Path) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            [PYTHON, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"],
            cwd=cwd,
            env={"PYTHONPATH": ".:../scripts", "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=SUITE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        # No test failed, so this is not a kill under the definition used here; it is a
        # separate outcome that says the removed control was a termination guard.
        return False, f"timeout after {SUITE_TIMEOUT_SECONDS}s: pytest never terminated", "timeout"
    summary = result.stdout.strip().splitlines()
    tail = [line for line in summary if line.strip()][-1:] or [""]
    # A kill only counts if a test failed. A collection error kills every mutation for the
    # same reason, so it is reported separately and excluded from the kill rate.
    kind = "failed" if " failed" in tail[0] else ("error" if "error" in tail[0] else "other")
    return result.returncode == 0, tail[0], kind


def build_copy(source_root: Path, destination: Path) -> Path:
    """Copy the parts the suite needs from ``source_root`` and return the backend dir."""
    for name in NEEDED:
        source = source_root / name
        if source.is_dir():
            shutil.copytree(source, destination / name, ignore=IGNORE)
        else:
            shutil.copy2(source, destination / name)
    return destination / "backend"


def main() -> int:
    records = []

    with tempfile.TemporaryDirectory(prefix="mutation-audit-") as directory:
        work = Path(directory)
        green = False
        detail = ""
        # Control: an unmutated copy must be green, or nothing below means anything.
        for attempt in range(1, CONTROL_ATTEMPTS + 1):
            snapshot_root = work / f"snapshot{attempt}"
            snapshot_root.mkdir()
            snapshot = build_copy(REPO, snapshot_root)
            green, detail, kind = run_suite(snapshot)
            print(
                f"[control attempt {attempt}/{CONTROL_ATTEMPTS}]"
                f" {'GREEN' if green else 'RED':5} {detail}",
                flush=True,
            )
            if green:
                break
        if not green:
            print("CONTROL FAILED: the harness cannot measure anything until an unmutated copy passes.")
            return 1
        # Every mutation below is applied to a copy of the green snapshot, never to the
        # working tree, so all runs in one report describe the same tree.
        for index, (relative, old, new, description) in enumerate(MUTATIONS, start=1):
            with tempfile.TemporaryDirectory(prefix=f"mut{index}-") as directory:
                copy = build_copy(snapshot_root, Path(directory))
                target = copy / relative
                text = target.read_text()
                if text.count(old) != 1:
                    records.append({"mutation": description, "status": "NOT_APPLIED", "detail": f"{text.count(old)} matches"})
                    print(f"[{index}] NOT_APPLIED  {description}", flush=True)
                    continue
                target.write_text(text.replace(old, new))

                survived, detail, kind = run_suite(copy)
                if survived:
                    status = "SURVIVED"
                elif kind == "failed":
                    status = "KILLED"
                elif kind == "timeout":
                    status = "HUNG"
                else:
                    status = "KILLED_BY_ERROR"
                records.append({"mutation": description, "status": status, "detail": detail})
                print(f"[{index}] {status:15} {description} | {detail}", flush=True)

    applied = [record for record in records if record["status"] != "NOT_APPLIED"]
    killed = [record for record in applied if record["status"] == "KILLED"]
    errors = [record for record in applied if record["status"] == "KILLED_BY_ERROR"]
    hung = [record for record in applied if record["status"] == "HUNG"]
    survivors = [record for record in applied if record["status"] == "SURVIVED"]
    print(
        "\napplied", len(applied), "killed-by-failure", len(killed),
        "killed-by-error", len(errors), "hung", len(hung), "survived", len(survivors),
    )
    if applied:
        print("test-failure kill rate %.1f%%" % (100.0 * len(killed) / len(applied)))
    for record in errors:
        print("ERROR-KILL (not counted):", record["mutation"], "|", record["detail"])
    for record in hung:
        print("HUNG (not counted, no test failed):", record["mutation"], "|", record["detail"])
    for record in survivors:
        print("SURVIVOR:", record["mutation"], "|", record["detail"])
    Path("/home/alex/policy-evidence-fix/ct3/audit/mutation-results.json").write_text(
        json.dumps(records, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
