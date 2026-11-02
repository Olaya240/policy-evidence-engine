#!/usr/bin/env python3
"""The executable form of `ct3/audit/ENGINEERING-STANDARD.md`.

Seven checks. Each prints `PASS`, `FAIL` or `SKIPPED` and the number or string
that decides it. Run it with the project venv (the one that has FastAPI and
pytest):

    /home/alex/policy-evidence-latest/.venv/bin/python scripts/quality_gate.py
    /home/alex/policy-evidence-latest/.venv/bin/python scripts/quality_gate.py --fast

Exit status is the standard, in one integer:

    0   every check PASSED                      -- the tree supports the claim
    1   at least one check FAILED               -- it does not
    2   no failures, but at least one SKIPPED   -- nobody checked, so not certified

A skipped check is never printed as PASS and never folds into a 0. `--fast`
skips the full pytest run only (check 4, the slowest by an order of magnitude);
it cannot make a failing check disappear.

Standard library only, except for the app under test: check 6 imports
`backend/app` itself, which needs FastAPI and httpx from the project venv. It is
non-interactive: no prompts, no stdin, no network.

Check 2 naive-grep warning: `ct3/StanceAlgebra.v` contains the English word
"admits" in a *comment* ("...admits a replacement..."). A `grep -n admit *.v`
therefore reports a file that proves every lemma it states. Comment stripping is
not a refinement here, it is the difference between a true result and a false
one, so comments are removed before the pattern is applied, and `(* *)` in Coq
nests -- which is why stripping counts depth instead of regexing `\\(\\*.*?\\*\\)`.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CT3 = ROOT / "ct3"
PYTHON = sys.executable

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"

# Checks that cost real time. `--fast` may skip these, and only these.
SLOW_CHECKS = {4}
SUITE_TIMEOUT_S = 1800


@dataclass
class Result:
    status: str
    detail: str
    lines: list[str] = field(default_factory=list)


def ok(detail: str, *lines: str) -> Result:
    return Result(PASS, detail, list(lines))


def bad(detail: str, *lines: str) -> Result:
    return Result(FAIL, detail, list(lines))


def skipped(detail: str, *lines: str) -> Result:
    return Result(SKIPPED, detail, list(lines))


def _rel(path: Path) -> str:
    """Path relative to the repo when it is inside it (a temp copy is not)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- #
# Coq source handling (shared by checks 1 and 2)
# --------------------------------------------------------------------------- #


def strip_coq_comments(text: str) -> str:
    """Remove `(* ... *)` (nested) and `"..."` literals, keeping line numbers.

    Comments are replaced character-for-character by spaces except newlines, so
    a match's line number in the result is its line number in the file.
    """
    out: list[str] = []
    depth = 0
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        pair = text[i : i + 2]
        if depth:
            if pair == "(*":
                depth += 1
                out.append("  ")
                i += 2
                continue
            if pair == "*)":
                depth -= 1
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if in_string:
            if ch == '"':
                if text[i : i + 2] == '""':  # escaped quote inside a Coq string
                    out.append("  ")
                    i += 2
                    continue
                in_string = False
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if pair == "(*":
            depth = 1
            out.append("  ")
            i += 2
            continue
        if ch == '"':
            in_string = True
            out.append(" ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def proof_files() -> list[Path]:
    """`ct3/*.v` plus `ct3/refinement/*.v`, the two directories the proofs live in."""
    return sorted([*CT3.glob("*.v"), *CT3.glob("refinement/*.v")])


def _requires(path: Path) -> set[str]:
    """Logical names this file `Require`s, name-by-name (comments already gone)."""
    body = strip_coq_comments(path.read_text(encoding="utf-8", errors="replace"))
    names: set[str] = set()
    for match in re.finditer(
        r"(?m)^\s*(?:From\s+\S+\s+)?Require\s+(?:Import\s+|Export\s+)?([^.]*)\.", body
    ):
        for token in match.group(1).split():
            names.add(token.split(".")[-1])
    return names


def build_order(files: list[Path]) -> list[Path]:
    """Topological order over in-tree `Require`s; raises ValueError on a cycle."""
    by_name = {p.stem: p for p in files}
    deps = {
        p: {by_name[name] for name in _requires(p) if name in by_name and by_name[name] != p}
        for p in files
    }
    ordered: list[Path] = []
    remaining = dict(deps)
    while remaining:
        ready = [p for p, d in remaining.items() if not (d - set(ordered))]
        if not ready:  # pragma: no cover - no cycle exists in this tree
            raise ValueError(f"cyclic Require chain among {[p.name for p in remaining]}")
        ordered.extend(sorted(ready))
        for p in ready:
            del remaining[p]
    return ordered


# --------------------------------------------------------------------------- #
# 1. Proofs build
# --------------------------------------------------------------------------- #


def check_proofs_build(_fast: bool) -> Result:
    """`coqc` every proof in dependency order, in a temp copy of `ct3/`."""
    if shutil.which("coqc") is None:
        return bad("coqc not on PATH; no proof was compiled (this is not a pass)")

    files = proof_files()
    if not files:
        return bad("no .v files found under ct3/ -- the check itself is misconfigured")

    try:
        order = build_order(files)
    except ValueError as exc:
        return bad(str(exc))

    started = time.monotonic()
    compiled: list[str] = []
    with tempfile.TemporaryDirectory(prefix="quality-gate-proofs-") as tmp:
        work = Path(tmp) / "ct3"
        shutil.copytree(CT3, work)
        for stale in list(work.rglob("*.vo")) + list(work.rglob("*.vos")):
            stale.unlink()
        for stale in list(work.rglob("*.vok")) + list(work.rglob("*.glob")):
            stale.unlink()

        for source in order:
            relative = source.relative_to(CT3)
            compiled.append(source.name)
            proc = subprocess.run(
                ["coqc", "-Q", str(work), "", str(work / relative)],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if proc.returncode != 0:
                tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
                return bad(
                    f"{source.name} failed to compile (coqc exit {proc.returncode})",
                    f"    build order: {' -> '.join(compiled)} (of {len(order)})",
                    *(f"    {line}" for line in tail),
                )
    elapsed = time.monotonic() - started
    return ok(
        f"{len(order)} .v files compiled in {elapsed:.1f}s ({', '.join(p.name for p in order)})"
    )


# --------------------------------------------------------------------------- #
# 2. No unproved steps
# --------------------------------------------------------------------------- #

# `admit`/`Admitted` are tactics and can sit mid-line (`Proof. admit.`), so they
# are matched anywhere; the declaration commands only count at command position.
_UNPROVED_TACTIC = re.compile(r"(?m)\b(?:Admitted|admit)\b")
_UNPROVED_DECL = re.compile(r"(?m)^[ \t]*(?:Axiom|Axioms|Parameter|Parameters)\b")


def check_no_unproved_steps(_fast: bool) -> Result:
    """Fail on `Admitted`/`admit`/`Axiom`/`Parameter` outside comments and strings."""
    files = proof_files()
    hits: list[str] = []
    for path in files:
        body = strip_coq_comments(path.read_text(encoding="utf-8", errors="replace"))
        for pattern in (_UNPROVED_TACTIC, _UNPROVED_DECL):
            for match in pattern.finditer(body):
                line = body.count("\n", 0, match.start()) + 1
                hits.append(f"{_rel(path)}:{line}: {match.group(0).strip()}")
    if hits:
        return bad(f"{len(hits)} unproved step(s) in {len(files)} .v files", *hits)
    return ok(f"0 unproved steps in {len(files)} .v files")


# --------------------------------------------------------------------------- #
# 3. Refinement freshness
# --------------------------------------------------------------------------- #

_REFINEMENT_TEST = BACKEND / "tests" / "test_decision_table_refinement.py"
_REGENERATE = (
    'cd ct3/refinement && coqc -Q .. "" generate_table.v   # then re-record '
    "GENERATED_FROM_DIGESTS in backend/tests/test_decision_table_refinement.py"
)


def _recorded_digests() -> dict[str, str] | None:
    tree = ast.parse(_REFINEMENT_TEST.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        if any(isinstance(t, ast.Name) and t.id == "GENERATED_FROM_DIGESTS" for t in targets):
            value = node.value  # type: ignore[attr-defined]
            if isinstance(value, ast.Dict):
                return {k.value: v.value for k, v in zip(value.keys, value.values)}
    return None


def check_refinement_freshness(_fast: bool) -> Result:
    """Recompute the recorded digests *and* regenerate the table from Coq.

    The digest handshake alone is a weaker check than it looks: it compares two hashes
    that both live in the same commit, so editing `generate_table.v` and re-recording
    its digest certifies a table nobody regenerated. This check therefore rebuilds the
    table from source in a throwaway copy and compares bytes with the committed
    artifact. The digests stay as a fast, readable first line; the rebuild is the check.
    """
    recorded = _recorded_digests()
    if not recorded:
        return bad(
            "backend/tests/test_decision_table_refinement.py records no GENERATED_FROM_DIGESTS;"
            " freshness cannot be checked"
        )

    rows: list[str] = []
    stale: list[str] = []
    for name, expected in sorted(recorded.items()):
        path = CT3 / "refinement" / name if name == "generate_table.v" else CT3 / name
        if not path.is_file():
            stale.append(f"{name}: recorded but missing at {_rel(path)}")
            rows.append(f"    {name:<20} {expected:<18} MISSING")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        verdict = "ok" if actual == expected else "STALE"
        rows.append(f"    {name:<20} recorded {expected}  actual {actual}  {verdict}")
        if actual != expected:
            stale.append(f"{name}: recorded {expected}, actual {actual}")

    regenerated, detail = _regenerate_table()
    rows.append(f"    rebuild: {detail}")
    if not regenerated:
        stale.append(f"the table does not rebuild from source: {detail}")

    if stale:
        return bad(
            f"{len(stale)} problem(s) with the refinement boundary",
            *rows,
            f"    regenerate: {_REGENERATE}",
        )
    return ok("2 of 2 recorded digests match and the table rebuilds byte-identically", *rows)


def _regenerate_table() -> tuple[bool, str]:
    """Rebuild `decision-table.out` from `generate_table.v` in a copy and compare bytes.

    A copy, not the working tree: a check that repairs the artifact it is checking can
    never fail twice. `coqc` writes the artifact through a `Redirect`, so the command is
    the one the refinement test documents.
    """
    artifact = CT3 / "refinement" / "decision-table.out"
    source_dir = CT3 / "refinement"
    if not artifact.is_file() or not (source_dir / "generate_table.v").is_file():
        return False, "generate_table.v or decision-table.out is missing"

    with tempfile.TemporaryDirectory(prefix="refinement-") as directory:
        copy_root = Path(directory) / "ct3"
        shutil.copytree(CT3, copy_root, ignore=shutil.ignore_patterns("*.vo", "*.glob", "*.vok", "*.vos", "*.aux"))
        # `generate_table.v` imports DecisionTable, and build products are not copied,
        # so the dependency is compiled in the copy first. Compiling it here rather than
        # reusing the tree's `.vo` is deliberate: a stale object file would let a broken
        # source build, which is the failure this check exists to catch.
        dependency = subprocess.run(
            ["coqc", "DecisionTable.v"],
            cwd=copy_root,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if dependency.returncode != 0:
            tail = " | ".join((dependency.stdout + dependency.stderr).strip().splitlines()[-2:])
            return False, f"DecisionTable.v did not compile: {tail}"
        build = subprocess.run(
            ["coqc", "-Q", "..", "", "generate_table.v"],
            cwd=copy_root / "refinement",
            capture_output=True,
            text=True,
            timeout=300,
        )
        if build.returncode != 0:
            tail = " | ".join((build.stdout + build.stderr).strip().splitlines()[-2:])
            return False, f"coqc failed: {tail}"
        produced = copy_root / "refinement" / "decision-table.out"
        if not produced.is_file():
            return False, "coqc produced no decision-table.out"
        if produced.read_bytes() != artifact.read_bytes():
            return False, "regenerated table differs from the committed artifact"
    return True, "coqc regenerated decision-table.out byte-identically"


# --------------------------------------------------------------------------- #
# 4. Suite
# --------------------------------------------------------------------------- #

_SUMMARY = re.compile(r"^(?P<body>.*?)\bin (?P<seconds>[0-9.]+)s", re.MULTILINE)


def _count(text: str, word: str) -> int:
    match = re.search(rf"(\d+) {word}\b", text)
    return int(match.group(1)) if match else 0


_CONSTANT_TRUE = lambda node: isinstance(node, ast.Constant) and bool(node.value)


def _vacuous_tests(root: Path) -> list[str]:
    """Test functions whose body cannot fail: `pass`, or `assert <literal true>`.

    Narrow on purpose. A test may assert inside a helper, so "no `assert` in this
    function" is not evidence of a vacuous test and using it would flag honest tests.
    A body that is *only* `pass`, or *only* `assert True`, cannot check anything, and
    a count of passing tests cannot tell it apart from a real one — which is the attack
    this exists to catch.
    """
    findings: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            body = [statement for statement in node.body
                    if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))]
            if not body:
                findings.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.name}() has an empty body")
                continue
            if len(body) == 1:
                only = body[0]
                if isinstance(only, ast.Pass):
                    findings.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.name}() is `pass`")
                elif isinstance(only, ast.Assert) and _CONSTANT_TRUE(only.test):
                    findings.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.name}() is `assert <literal true>`")
    return findings


def check_suite(fast: bool) -> Result:
    """The whole pytest suite, from `backend/`, with the venv that is running this."""
    if fast:
        return skipped("--fast: the full suite is the slowest check; run without --fast")

    vacuous = _vacuous_tests(BACKEND / "tests")
    if vacuous:
        return bad(
            f"{len(vacuous)} test function(s) cannot fail, so their passes are not evidence",
            *vacuous[:20],
        )

    env = dict(os.environ, PYTHONPATH=".", PYTHONDONTWRITEBYTECODE="1")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            timeout=SUITE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return bad(f"pytest did not finish within {SUITE_TIMEOUT_S}s")

    elapsed = time.monotonic() - started
    output = proc.stdout + proc.stderr
    summary = next(
        (line.strip() for line in reversed(output.strip().splitlines()) if " in " in line and "=" not in line),
        output.strip().splitlines()[-1] if output.strip() else "<no output>",
    )
    passed, failed, xfailed = _count(summary, "passed"), _count(summary, "failed"), _count(summary, "xfailed")
    errors = _count(summary, "error") + _count(summary, "errors")
    count = f"{passed} passed, {failed} failed, {xfailed} xfailed, {errors} errors in {elapsed:.1f}s"

    if proc.returncode != 0 or failed or errors:
        failures = [line for line in output.splitlines() if line.startswith(("FAILED ", "ERROR "))]
        return bad(f"{count} (pytest exit {proc.returncode})", *failures[:40])
    return ok(count)


# --------------------------------------------------------------------------- #
# 5. Xfail discipline
# --------------------------------------------------------------------------- #

_DEFECT_MARKER = re.compile(r"defect|bug|gap|misread|known|pinned|xfail", re.IGNORECASE)
_MIN_REASON = 30


def _module_literal(tree: ast.Module, name: str):
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            try:
                return ast.literal_eval(node.value)  # type: ignore[attr-defined]
            except (ValueError, TypeError):
                return None
    return None


def _reason_strings(node: ast.AST | None, tree: ast.Module) -> tuple[list[str] | None, str]:
    """Resolve `reason=` to concrete strings, or say why it cannot be resolved."""
    if node is None:
        return None, "no reason="
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value], "literal"
    if isinstance(node, ast.JoinedStr):
        return ["".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))], "f-string"
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        table = _module_literal(tree, node.value.id)
        if isinstance(table, dict):
            values = [v for v in table.values() if isinstance(v, str)]
            return values, f"{node.value.id}[...] ({len(values)} row(s))"
        return None, f"{node.value.id} is not a module-level dict literal"
    if isinstance(node, ast.Name):
        literal = _module_literal(tree, node.id)
        if isinstance(literal, str):
            return [literal], node.id
        if isinstance(literal, dict):
            return [v for v in literal.values() if isinstance(v, str)], f"{node.id} ({len(literal)} row(s))"
        return None, f"{node.id} is not a string or dict literal"
    return None, f"reason is a {type(node).__name__} expression"


def check_xfail_discipline(_fast: bool) -> Result:
    """Every `strict=True` xfail needs a long `reason=` and a comment naming the defect."""
    sites = 0
    xfail_rows = 0
    non_strict = 0
    violations: list[str] = []
    notes: list[str] = []

    for path in sorted((BACKEND / "tests").rglob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        comments = [
            (tok.start[0], tok.string)
            for tok in tokenize.generate_tokens(io.StringIO(source).readline)
            if tok.type == tokenize.COMMENT
        ]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if name != "xfail":
                continue
            kwargs = {k.arg: k.value for k in node.keywords if k.arg}
            strict_node = kwargs.get("strict")
            is_strict = isinstance(strict_node, ast.Constant) and strict_node.value is True
            if not is_strict:
                # A non-strict xfail tolerates a *passing* test: the assertion can go
                # green and the suite still reports xfailed. That is a dead assertion
                # with a receipt, so it is a violation, not a statistic. This used to
                # be counted and passed.
                non_strict += 1
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: non-strict xfail "
                    "(a passing test here would be reported as xfailed, not as a pass)"
                )
                continue

            sites += 1
            where = f"{path.relative_to(ROOT)}:{node.lineno}"
            reasons, why = _reason_strings(kwargs.get("reason"), tree)
            xfail_rows += len(reasons or [])
            if reasons is None:
                violations.append(f"{where}: strict xfail with no statically verifiable reason ({why})")
            elif not reasons:
                notes.append(f"{where}: reason map {why} is empty -- 0 rows are xfailed, site is inert")
            else:
                short = [r for r in reasons if len(r) <= _MIN_REASON]
                if short:
                    violations.append(
                        f"{where}: reason too short ({min(len(r) for r in short)} <= {_MIN_REASON} chars, {why}): {short[0]!r}"
                    )

            window_top = max(1, node.lineno - 60)
            named = [text for line, text in comments if window_top <= line <= node.end_lineno]
            if not any(_DEFECT_MARKER.search(text) for text in named):
                violations.append(
                    f"{where}: no comment within 60 lines above names the defect"
                    " (expected one of: defect, bug, gap, misread, known, pinned)"
                )

    detail = (
        f"{sites} strict xfail site(s) covering {xfail_rows} row(s), "
        f"{non_strict} non-strict, {len(violations)} violation(s)"
    )
    if violations:
        return bad(detail, *violations, *notes)
    return ok(detail, *notes)


# --------------------------------------------------------------------------- #
# 6. No unexpected 5xx on hostile input
# --------------------------------------------------------------------------- #

# The only 5xx the standard tolerates, by exact documented detail string. Each
# one names a condition the client cannot fix by sending better input: the local
# store is corrupt/absent, or the assessment provider is at capacity.
ALLOWED_5XX = {
    "Local prototype database is unavailable.": "documented corrupt-storage outage (store.DatabaseUnavailable)",
    "Local prototype database is not initialized.": "documented uninitialized-storage outage (require_database)",
    "Assessment provider is unavailable or returned invalid output.": "documented provider-capacity outage (ProviderError)",
}

_BIG_BODY = json.dumps({"question": "a" * (2 * 1024 * 1024)}).encode()

# (label, method, path, body, extra headers). Fixed list: the same requests every
# run, so a status change is a behaviour change.
HOSTILE_REQUESTS: list[tuple[str, str, str, bytes | None, dict[str, str]]] = [
    ("truncated JSON body", "POST", "/api/investigations", b'{"question": "why', {}),
    ("2 MiB body", "POST", "/api/investigations", _BIG_BODY, {}),
    ("control characters", "POST", "/api/investigations",
     json.dumps({"question": "null\u0000bell\u0007del\u007fcharacters", "department": "ops"}).encode(), {}),
    ("JSON array body", "POST", "/api/investigations", b"[]", {}),
    ("traversal id", "GET", "/api/investigations/../../etc/passwd", None, {}),
    ("encoded traversal id", "GET", "/api/investigations/..%2F..%2Fetc%2Fpasswd", None, {}),
    ("unknown route", "GET", "/api/definitely-not-a-route", None, {}),
    ("bad claim ids", "POST", "/api/investigations/not-a-uuid/claims/not-a-claim/challenge",
     b'{"reason": "because", "source_record_id": "r", "quote": "qqq"}', {}),
    ("negative limit", "GET", "/api/records?limit=-1", None, {}),
    ("empty ingest", "POST", "/api/records/ingest", json.dumps({"text": "", "department": ""}).encode(), {}),
    ("wrong method", "DELETE", "/api/health", None, {}),
    ("health baseline", "GET", "/api/health", None, {}),
]


def _import_app(db_path: Path):
    """Import the ASGI app against a throwaway database, never the seeded one.

    `store.validate_database_path` refuses any path outside `data/`, so the
    throwaway file has to live there under a name of its own; the caller deletes
    it (and its WAL/SHM siblings) afterwards, leaving the tree as it found it.
    """
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    os.environ["HACKATHON_DB_PATH"] = str(db_path)
    from app import store  # imported late: needs HACKATHON_DB_PATH set first

    store.initialize_database()
    from app.main import app

    return app


def check_hostile_surface(_fast: bool) -> Result:
    """Drive the ASGI app with hostile input; fail on any undocumented 5xx."""
    import asyncio

    try:
        import httpx
    except ImportError:
        return skipped("httpx is not importable from this interpreter; no request was sent")

    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = data_dir / f".quality-gate-{os.getpid()}.sqlite3"
    for leftover in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        leftover.unlink(missing_ok=True)
    try:
        app = _import_app(db_path)

        async def drive():
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            rows = []
            async with httpx.AsyncClient(transport=transport, base_url="http://gate.local") as client:
                for label, method, path, body, headers in HOSTILE_REQUESTS:
                    response = await client.request(method, path, content=body, headers=headers)
                    detail = ""
                    try:
                        payload = response.json()
                        if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
                            detail = payload["detail"]
                    except ValueError:
                        detail = ""
                    rows.append((label, method, path, response.status_code, detail))
            return rows

        rows = asyncio.run(drive())
    finally:
        for leftover in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            leftover.unlink(missing_ok=True)

    table = [f"    {'request':<22} {'method':<6} {'route':<62} {'status':<6} verdict"]
    failures: list[str] = []
    allowed = 0
    for label, method, path, status, detail in rows:
        verdict = "ok"
        if status >= 500:
            reason = next((why for frag, why in ALLOWED_5XX.items() if frag in detail), None)
            if reason is None:
                verdict = "UNEXPECTED 5xx"
                failures.append(f"{label}: {method} {path} -> {status} {detail!r}")
            else:
                verdict = f"allowed: {reason}"
                allowed += 1
        elif label == "health baseline" and status != 200:
            verdict = "UNEXPECTED non-200"
            failures.append(f"health baseline {method} {path} -> {status}")
        table.append(f"    {label:<22} {method:<6} {path:<62} {status:<6} {verdict}")

    detail = (
        f"{len(HOSTILE_REQUESTS)} hostile requests, "
        f"{sum(1 for r in rows if r[3] < 500)} 4xx/2xx, {allowed} documented 5xx, "
        f"{len(failures)} unexpected 5xx"
    )
    if failures:
        return bad(detail, *table, *failures)
    return ok(detail, *table)


# --------------------------------------------------------------------------- #
# 7. Mutation floor
# --------------------------------------------------------------------------- #

_MUTATION_HARNESS = CT3 / "audit" / "measure_mutations.py"


def check_mutation_floor(fast: bool) -> Result:
    """Run the harness's fast sample and require every sampled mutant to be killed.

    A sample is not a score: the number of controls left outside it is printed with the
    result, and `SURVIVED`, `NOT_APPLIED` and `HUNG` are all failures. `NOT_APPLIED` in
    particular means the harness substring no longer exists — the measurement is stale
    and must not be reported as a pass.
    """
    if not _MUTATION_HARNESS.is_file():
        return skipped(f"{_MUTATION_HARNESS.relative_to(ROOT)} is absent; mutation score not measured")
    if fast:
        return skipped("--fast: mutation sample not run (requested)")

    started = time.monotonic()
    proc = subprocess.run(
        [PYTHON, str(_MUTATION_HARNESS), "--fast"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    elapsed = time.monotonic() - started
    output = proc.stdout + proc.stderr
    killed = re.search(r"kill-rate (\d+)/(\d+)", output)
    outside = re.search(r"not-covered (\d+) of (\d+)", output)
    if killed is None or outside is None:
        return bad(f"mutation harness produced no kill-rate after {elapsed:.1f}s",
                   *output.strip().splitlines()[-4:])

    killed_count, sampled = int(killed.group(1)), int(killed.group(2))
    outside_count, total = int(outside.group(1)), int(outside.group(2))
    survivors = [line for line in output.splitlines() if line.startswith(("SURVIVOR:", "STALE:", "HUNG:"))]
    detail = (f"{killed_count}/{sampled} sampled mutants killed in {elapsed:.1f}s;"
              f" {outside_count} of {total} controls are outside the sample")

    if proc.returncode != 0 or killed_count != sampled or sampled == 0:
        return bad(detail + " -- mutation floor NOT met", *survivors)
    return ok(detail)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

CHECKS = [
    ("proofs-build", check_proofs_build),
    ("no-unproved", check_no_unproved_steps),
    ("refinement", check_refinement_freshness),
    ("suite", check_suite),
    ("xfail", check_xfail_discipline),
    ("hostile-5xx", check_hostile_surface),
    ("mutation-floor", check_mutation_floor),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the engineering-standard gate.")
    parser.add_argument("--fast", action="store_true", help="skip the slow checks (never pass them)")
    args = parser.parse_args(argv)

    print(f"engineering standard gate -- {ROOT}")
    print(f"python {sys.version.split()[0]}  mode {'--fast' if args.fast else 'full'}")
    print()

    results: list[Result] = []
    for index, (slug, check) in enumerate(CHECKS, start=1):
        started = time.monotonic()
        try:
            result = check(args.fast)
        except Exception as exc:  # a broken check is a failure, never a pass
            result = bad(f"check raised {type(exc).__name__}: {exc}")
        elapsed = time.monotonic() - started
        results.append(result)
        print(f"[{index}/{len(CHECKS)}] {slug:<16} {result.status:<8} {result.detail}")
        for line in result.lines:
            print(line if line.startswith("    ") else f"    {line}")
        if result.status == SKIPPED and result.detail.startswith("--fast"):
            print(f"    (check ran {elapsed:.1f}s and decided nothing)")

    passed = sum(1 for r in results if r.status == PASS)
    failed = sum(1 for r in results if r.status == FAIL)
    skipped_count = sum(1 for r in results if r.status == SKIPPED)
    print()
    print(f"--- {passed} PASS, {failed} FAIL, {skipped_count} SKIPPED ---")
    if failed:
        print("result: FAILED -- the tree does not support the claim")
        return 1
    if skipped_count:
        print("result: NOT CERTIFIED -- nothing failed, but the skipped checks did not run")
        return 2
    print("result: PASSED -- every check ran and every check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
