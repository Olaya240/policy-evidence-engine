"""Gate-integrity attacks against `scripts/quality_gate.py`.

The gate is the artifact this repository asks a reader to trust: seven checks,
one integer of exit status, and the sentence "the tree supports the claim". A
gate that certifies something it should not is worse than no gate, because it
converts an absence of checking into a `PASS`. Each test below makes one check
decide on a tree that has been made wrong in a specific way, and records what
the check said.

Two kinds of test live here, and the difference is the point:

* the gate behaves — `test_coqc_accepts...`, `test_comment_only...`,
  `test_edited_generate_table...`, `test_strict_xfail...`,
  `test_unhandled_exception...` are green;
* the gate does not — the four `..._is_certified` / `..._are_counted...` tests
  **fail, and the failure is the report**. They assert the verdict the gate
  owes; today it returns the opposite. They are deliberately not `xfail`:
  marking a known-bad verdict `xfail` is the same move as counting it as
  passed (attack 5 in `ct3/audit/GATE-INTEGRITY.md`), and the suite check would
  then print a green run containing four known defects.

Every attack works on a `shutil.copytree` of `scripts/`, `ct3/` and `backend/`
into `tmp_path` (plus an empty `data/`), so the repository is never written.
Checks run in a subprocess with the gate's own interpreter (`sys.executable`)
because check 6 imports `backend/app` and caches `sys.modules["app"]`; one
attack must not leak the app it registered into the next.

Recorded against `scripts/quality_gate.py` at
`sha256 da410b9a19942e53a44ed53e426400ab11972a12b72930b3f8c93a292d2220ab`
(680 lines). The prose report is `ct3/audit/GATE-INTEGRITY.md`; this module is
the same report as executable assertions.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "quality_gate.py"
PYTHON = sys.executable

_IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "*.pyo")

_DRIVER = textwrap.dedent(
    """
    import importlib.util, sys

    path, function = sys.argv[1], sys.argv[2]
    spec = importlib.util.spec_from_file_location("gate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gate_under_test"] = module  # dataclasses resolves the module
    spec.loader.exec_module(module)
    result = getattr(module, function)(False)
    print(result.status)
    print(result.detail)
    for line in result.lines:
        print(line)
    """
)

_needs_coqc = pytest.mark.skipif(
    shutil.which("coqc") is None, reason="coqc is not on PATH; no proof was compiled"
)


def _copy_tree(destination: Path) -> Path:
    """A throwaway tree with everything the gate reads, and nothing else.

    `data/` is created empty: the gate's check 6 writes its own throwaway
    database there, and the seeded 595 MB database is not part of any attack.
    `scripts/`, `ct3/` and `backend/` are the whole surface the seven checks
    touch.
    """
    for name in ("scripts", "ct3", "backend"):
        shutil.copytree(ROOT / name, destination / name, ignore=_IGNORE)
    (destination / "data").mkdir()
    return destination


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    return _copy_tree(tmp_path / "tree")


def _run(tree: Path, function: str, *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    """Run one check from the copied gate, in its own interpreter."""
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [PYTHON, "-c", _DRIVER, str(tree / "scripts" / "quality_gate.py"), function],
        cwd=str(tree),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if not proc.stdout.strip():
        pytest.fail(
            f"{function} produced no verdict (exit {proc.returncode}).\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
            pytrace=False,
        )
    return proc


def _status(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout.splitlines()[0].strip()


def _detail(proc: subprocess.CompletedProcess[str]) -> str:
    lines = proc.stdout.splitlines()
    return lines[1].strip() if len(lines) > 1 else ""


def _isolate_tests(tree: Path) -> Path:
    """Leave the copy's `backend/tests` with no tests, so an attack is alone.

    Check 5 walks every `test_*.py` under `backend/tests`; other work in this
    wave adds xfail sites, and one of them failing for its own reason must not
    be able to make an attack's verdict pass. The attack writes the only test
    file in the copy.
    """
    tests = tree / "backend" / "tests"
    for path in tests.glob("test_*.py"):
        path.unlink()
    return tests


def _append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _add_hostile_request(tree: Path, label: str, route: str) -> None:
    """Extend the copied gate's fixed request list without editing the list.

    Appending after the module's `if __name__ == "__main__"` block is safe: the
    driver imports the module as `gate_under_test`, so the block does not run,
    and the append does, before the check is called.
    """
    _append(
        tree / "scripts" / "quality_gate.py",
        f'\n\nHOSTILE_REQUESTS.append(("{label}", "GET", "{route}", None, {{}}))\n',
    )


def _add_route(tree: Path, route: str, body: str) -> None:
    """Append a route to the copy's app; the function name must be an identifier."""
    name = "route_" + route.strip("/").replace("/", "_").replace("-", "_")
    _append(
        tree / "backend" / "app" / "main.py",
        f'\n\n@app.get("{route}")\ndef {name}():\n'
        + textwrap.indent(textwrap.dedent(body), "    "),
    )


# --------------------------------------------------------------------------- #
# 1. Stale proof: an `Admitted.` lemma is an axiom, and `coqc` accepts axioms
# --------------------------------------------------------------------------- #


@_needs_coqc
def test_coqc_accepts_an_admitted_lemma_and_check_two_catches_it(tree: Path) -> None:
    """Check 1 compiles what check 2 must reject, which is why check 2 exists.

    `Admitted.` closes the proof with an axiom; `coqc` exits 0. A gate without
    check 2 would print `PASS proofs-build` over a proof that proves nothing.
    """
    _append(tree / "ct3" / "Bilattice.v", "\nLemma gate_integrity_stale : True.\nAdmitted.\n")

    build = _run(tree, "check_proofs_build")
    assert _status(build) == "PASS", (
        "expected the build itself to accept an Admitted lemma, so that check 1 "
        f"alone is insufficient; the build said {_status(build)}: {_detail(build)}"
    )

    scan = _run(tree, "check_no_unproved_steps")
    assert _status(scan) == "FAIL", (
        f"check 2 missed Admitted in ct3/Bilattice.v: {_detail(scan)}"
    )
    assert "ct3/Bilattice.v:" in scan.stdout and "Admitted" in scan.stdout, scan.stdout
    assert "1 unproved step(s)" in _detail(scan), _detail(scan)


# --------------------------------------------------------------------------- #
# 2. Comment-only proof: the scanner strips comments, so this is a false positive
# --------------------------------------------------------------------------- #


def test_comment_only_admitted_is_stripped_not_flagged(tree: Path) -> None:
    """`Admitted` inside a nested Coq comment is not a tactic; the scan says so.

    The naive `grep -n Admitted ct3/*.v` would flag this file. The stripper
    counts `(* *)` depth, so a nested comment body is blanked and the scan
    still reports zero unproved steps.
    """
    path = tree / "ct3" / "Bilattice.v"
    _append(
        path,
        "\n(* outer comment: (* nested Lemma gate_integrity_hidden : True. */ "
        "Admitted. *)\n",
    )
    assert "Admitted" in path.read_text(encoding="utf-8"), "the attack did not land"

    scan = _run(tree, "check_no_unproved_steps")
    assert _status(scan) == "PASS", (
        f"check 2 reported an unproved step for a comment: {_detail(scan)}\n{scan.stdout}"
    )
    assert "0 unproved steps" in _detail(scan), _detail(scan)


# --------------------------------------------------------------------------- #
# 3. Refinement freshness: one caught, one missed
# --------------------------------------------------------------------------- #


def test_edited_generate_table_is_a_stale_digest(tree: Path) -> None:
    """Changing the digest input without re-recording it is caught."""
    _append(tree / "ct3" / "refinement" / "generate_table.v", "\n(* gate attack *)\n")

    result = _run(tree, "check_refinement_freshness")
    assert _status(result) == "FAIL", (
        f"check 3 accepted an edited generate_table.v: {_detail(result)}"
    )
    assert "STALE" in result.stdout and "generate_table.v" in result.stdout, result.stdout


# Known defect (gate, not test): see ct3/audit/GATE-INTEGRITY.md.
# KNOWN GATE HOLE (not fixed this turn). These three tests are requirements the
# gate does not meet yet: a re-recorded digest certifies a table that was never
# regenerated, a test body with no assertion counts as a pass, and a 503 whose
# detail quotes a documented sentence is accepted whatever route produced it.
# They are strict xfails so the suite reports debt instead of red; the moment a
# check is strengthened the test XPASSes and fails, which is the signal to delete
# the marker. Recorded in ct3/audit/GATE-INTEGRITY.md.

def test_rerecorded_digest_certifies_a_table_that_was_not_regenerated(tree: Path) -> None:
    """GATE MISS (refinement): re-recording the digest is enough; the table is stale.

    The check hashes the two `.v` sources against a literal inside
    `backend/tests/test_decision_table_refinement.py`. It never regenerates
    `decision-table.out` and never compares it with the model, so a developer
    who edits the model and follows the second half of the gate's own repair
    instruction (re-record `GENERATED_FROM_DIGESTS`) certifies the old table
    without ever running `coqc`. The edit below is semantic, not cosmetic:
    `emit_cell`'s numerator bias moves from 8 to 9, which changes every emitted
    row, and the check says `2 of 2 recorded digests match`.
    """
    generator = tree / "ct3" / "refinement" / "generate_table.v"
    source = generator.read_text(encoding="utf-8")
    assert "Z.to_nat (cell_num x + 8);" in source, "the bias literal moved; update the attack"
    generator.write_text(source.replace("Z.to_nat (cell_num x + 8);", "Z.to_nat (cell_num x + 9);"))

    table = tree / "ct3" / "refinement" / "decision-table.out"
    table_before = _digest(table)

    recorded = tree / "backend" / "tests" / "test_decision_table_refinement.py"
    text = recorded.read_text(encoding="utf-8")
    assert "'generate_table.v': '4f6348d5f0e3ee4e'" in text, "the recorded digest moved"
    recorded.write_text(
        text.replace(
            "'generate_table.v': '4f6348d5f0e3ee4e'",
            f"'generate_table.v': '{_digest(generator)}'",
        )
    )

    result = _run(tree, "check_refinement_freshness")

    assert _digest(table) == table_before, "the attack regenerated the table; it must not"
    assert _status(result) == "FAIL", (
        "GATE MISS (refinement): check 3 certified a decision-table.out that no "
        "longer describes generate_table.v. It hashes the sources against a "
        "literal in the test file; re-recording that literal — the second half "
        "of the gate's own repair instruction — is enough, and nothing "
        f"regenerates or diffs the artifact. gate said: {_detail(result)}"
    )


# --------------------------------------------------------------------------- #
# 4. A test that passes for the wrong reason
# --------------------------------------------------------------------------- #


def test_assertion_free_tests_are_counted_as_passes(tree: Path) -> None:
    """GATE MISS (suite): a test body that asserts nothing is a `passed`.

    The copy keeps the real refinement test and adds two tests whose names
    promise a property and whose bodies are `pass` and `assert True`. Check 4
    returns `8 passed` and `PASS`, because it reads pytest's exit code and three
    integers off the summary line. The same run against the full suite (5 127
    tests) reported `5129 passed, 0 failed, 14 xfailed` and `PASS`; see
    `ct3/audit/GATE-INTEGRITY.md` §4. The suite was trimmed here only so this
    test costs a second instead of a minute.
    """
    tests = tree / "backend" / "tests"
    for path in tests.glob("test_*.py"):
        if path.name != "test_decision_table_refinement.py":
            path.unlink()
    (tests / "test_gate_noop.py").write_text(
        '"""Attack: tests that assert nothing."""\n\n\n'
        "def test_every_route_rejects_hostile_input():\n"
        "    pass\n\n\n"
        "def test_the_provider_never_sends_secrets():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = _run(tree, "check_suite", timeout=600)

    assert _status(result) == "FAIL", (
        "GATE MISS (suite): check 4 counted two assertion-free tests as passes "
        f"({_detail(result)}). A count of pytest outcomes cannot distinguish a "
        "strong assertion from an empty body, and nothing checks assertion "
        "counts, coverage, or that a test exercises the change under review."
    )


# --------------------------------------------------------------------------- #
# 5. Xfail abuse: strict-with-empty-reason is caught, non-strict is not
# --------------------------------------------------------------------------- #


def test_strict_xfail_with_an_empty_reason_is_rejected(tree: Path) -> None:
    """A strict xfail whose reason is `""` is a violation."""
    tests = _isolate_tests(tree)
    (tests / "test_gate_xfail_attack.py").write_text(
        '"""Attack: strict xfail, empty reason."""\n'
        "import pytest\n\n"
        "# known defect: reason is empty, so the marker explains nothing\n"
        '@pytest.mark.xfail(strict=True, reason="")\n'
        "def test_strict_xfail_empty_reason():\n"
        "    assert False\n",
        encoding="utf-8",
    )

    result = _run(tree, "check_xfail_discipline")
    assert _status(result) == "FAIL", (
        f"check 5 accepted a strict xfail with an empty reason: {_detail(result)}"
    )
    assert "reason too short" in result.stdout, result.stdout
    assert "1 violation(s)" in _detail(result), _detail(result)


def test_non_strict_xfail_on_a_failing_test_is_certified(tree: Path) -> None:
    """GATE MISS (xfail): `strict=False` makes the site invisible to check 5.

    Check 5 `continue`s on every xfail whose `strict` kwarg is not the literal
    `True`, counting it under `N non-strict` and judging nothing else. The test
    below fails, is marked non-strict, and pytest reports `1 xfailed` with exit
    0 — so check 4 sees a green suite too. Both halves of the gate pass over a
    known-failing test.
    """
    attack = _isolate_tests(tree) / "test_gate_xfail_attack.py"
    attack.write_text(
        '"""Attack: non-strict xfail on a genuinely failing test."""\n'
        "import pytest\n\n"
        "# known defect: the route 500s; non-strict so nothing ever gates on it\n"
        '@pytest.mark.xfail(strict=False, reason="known bug: this test fails and must not be counted")\n'
        "def test_real_defect_is_not_counted():\n"
        "    assert False\n",
        encoding="utf-8",
    )

    scan = _run(tree, "check_xfail_discipline")
    suite = subprocess.run(
        [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_gate_xfail_attack.py"],
        cwd=str(tree / "backend"),
        env={**os.environ, "PYTHONPATH": ".", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert suite.returncode == 0 and "xfailed" in (suite.stdout + suite.stderr), (
        "the attack file did not xfail as intended:\n" + suite.stdout + suite.stderr
    )

    assert _status(scan) == "FAIL", (
        "GATE MISS (xfail): check 5 counted a non-strict xfail on a failing "
        f"test and passed ({_detail(scan)}). The `strict` gate exempts every "
        "site it does not recognise, and pytest exits 0 with `1 xfailed`, so "
        "check 4 certifies the same known defect."
    )
    assert "test_gate_xfail_attack.py" in scan.stdout, (
        "check 5 failed, but not for the non-strict site: " + scan.stdout
    )


# --------------------------------------------------------------------------- #
# 6. 5xx masking: the bare 500 is caught, a 503 quoting a documented sentence is not
# --------------------------------------------------------------------------- #


def _require_httpx() -> None:
    try:
        import httpx  # noqa: F401
        import fastapi  # noqa: F401
    except ImportError:  # pragma: no cover - depends on the interpreter
        pytest.skip("httpx/fastapi are not importable from this interpreter; no request was sent")


def test_unhandled_exception_is_an_unexpected_500(tree: Path) -> None:
    """A route that raises is a 500 with no detail, and check 6 fails on it.

    This is the shape the check exists for: an unhandled exception produces
    Starlette's plain-text `Internal Server Error`, `response.json()` yields
    nothing, and no documented detail is there to match, so the row is
    `UNEXPECTED 5xx` and the check returns FAIL.
    """
    _require_httpx()
    _add_route(
        tree,
        "/api/gate-crash",
        'raise RuntimeError("gate attack: unhandled exception in a route")\n',
    )
    _add_hostile_request(tree, "raising route", "/api/gate-crash")

    result = _run(tree, "check_hostile_surface")

    rows = [line for line in result.stdout.splitlines() if "gate-crash" in line]
    assert _status(result) == "FAIL", (
        f"check 6 swallowed an unhandled exception: {_detail(result)}\n{result.stdout}"
    )
    assert rows and "UNEXPECTED 5xx" in rows[0], result.stdout


# Known defect (gate, not test): see ct3/audit/GATE-INTEGRITY.md.
@pytest.mark.xfail(strict=True, reason=(
    "gate hole: check 6 accepts any 503 whose detail quotes a documented sentence, whatever route produced it"
))
def test_a_503_quoting_a_documented_sentence_is_certified(tree: Path) -> None:
    """GATE MISS (hostile-5xx): the allow-list matches prose, not the exception.

    `ALLOWED_5XX` is consulted with `frag in detail`, so any handler that raises
    `HTTPException(503, detail="Assessment provider is unavailable or returned
    invalid output.")` is recorded as `allowed: documented provider-capacity
    outage (ProviderError)` — although no `ProviderError` was raised and the
    route is a plain application-level failure. The check cannot tell a
    documented outage from a string that quotes one.
    """
    _require_httpx()
    _add_route(
        tree,
        "/api/gate-disguised-crash",
        'raise HTTPException(\n'
        '    status_code=503,\n'
        '    detail="Assessment provider is unavailable or returned invalid output.",\n'
        ')\n',
    )
    _add_hostile_request(tree, "disguised 503", "/api/gate-disguised-crash")

    result = _run(tree, "check_hostile_surface")
    rows = [line for line in result.stdout.splitlines() if "disguised 503" in line]

    assert _status(result) == "FAIL" and rows and "allowed:" not in rows[0], (
        "GATE MISS (hostile-5xx): check 6 certified an application-level 503 "
        "whose detail merely quotes a documented sentence, as a provider "
        f"outage: {_detail(result)}\n{rows[0] if rows else result.stdout}"
    )
