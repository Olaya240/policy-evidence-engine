# The three failing tests — diagnosis

Nothing here was executed: this worker has no terminal. Every quotation is Read from the
working tree; every mechanism is a code path traced by hand plus documented SQLite/CPython
behaviour. The falsifying observation for each is named at the end of its section so a single
command can overturn any diagnosis.

Branch: `fix/evidence-decision-table` at `/home/alex/policy-evidence-fix`.

---

## Failure 1 and 2 share one root cause

`tests/test_launcher.py::test_process_identity_accepts_exact_expected_launch`
`tests/test_launcher.py::test_termination_uses_fake_killer_only_for_exact_identity`

### The assertions

`test_launcher.py:497-500`:

```python
    expected = _make_expected()
    info = _make_identity(12345, expected)
    ok, _ = launcher.verify_process_ownership(12345, "Demo API", lambda _pid: info, expected)
    assert ok
```

`test_launcher.py:566-578` (the termination test) ends with:

```python
    assert result is True
    assert killed == [55555]
```

### The mechanism

`scripts/launch_policy_demo.py:56-57`:

```python
def expected_identity(command: list[str]) -> dict[str, Any]:
    return {"executable": str(Path(command[0]).resolve()), "argv": command}
```

The recorded `executable` is the **resolved** path; the recorded `argv[0]` is the original,
unresolved string. `verify_process_ownership` then compares them unresolved-to-resolved:

```python
    if ntpath.normcase(ntpath.normpath(argv[0])) != ntpath.normcase(ntpath.normpath(executable)):
        return False, f"Recorded {service_name} executable and command line disagree."
```

On Windows, `.venv/Scripts/python.exe` (`PYTHON_EXE`, `launch_policy_demo.py:33`) is a real file,
so `Path(...).resolve()` returns the same string and the check passes. On POSIX the interpreter
is `Path(sys.executable)` (`:40-41`, because the `Scripts/python.exe` path does not exist) and a
venv's `bin/python` is a symlink to the base interpreter, so `resolve()` returns a different
path. `argv[0]` and `executable` then disagree, `verify_process_ownership` returns `(False, ...)`,
and the second test's `terminate_launcher_process` returns `False` without ever calling the
killer, because termination refuses to proceed on a failed identity check.

Note the very next check in the same function compares resolved-to-resolved
(`executable` against `Path(canonical[0]).resolve()`), so the resolved form is already the
intended canonical comparison. Only the `argv[0]` comparison was left uncanonicalised.

### Classification

**A real defect, exposed only by the platform.** The check is a self-consistency test between
two fields the launcher itself wrote, so it should be platform-independent; as written it is a
false negative for every POSIX launch whose interpreter path contains a symlink. The module
declares `Platform: Windows with Python 3.12` in its docstring, which is why nobody saw it —
but the failure is not a test that assumes the wrong platform, it is a comparison that resolves
one side and not the other.

Evidence that it is not "the code intentionally changed": the check is unchanged from its
origin, nothing in `git log` was consulted, and the producing line is a pure normalisation
asymmetry. Evidence that it is not merely a test bug: the same false negative would block
`terminate_launcher_process` in production on POSIX, which is the safety path this file exists
to provide.

### Minimal correct fix

`scripts/launch_policy_demo.py`, one line inside `verify_process_ownership` — canonicalise the
left side so both are resolved:

```python
    if ntpath.normcase(ntpath.normpath(str(Path(argv[0]).resolve()))) != ntpath.normcase(ntpath.normpath(executable)):
```

This is a no-op on Windows (`resolve()` is identity there), so recorded identities and the
Windows behaviour are unchanged. Do **not** change `expected_identity` to stop resolving:
`actual_executable` comes from the OS and *is* canonical, so the other checks depend on the
recorded executable being canonical too.

If the project intends the launcher to be Windows-only and wants the suite green on Linux
without touching the launcher, the alternative is a `pytest.mark.skipif(os.name != "nt")` on the
two tests — but that hides a real portability bug rather than fixing it, so it is the second
choice.

### What would falsify this

`readlink -f <venv>/bin/python` returning the same path as `<venv>/bin/python` (i.e. the venv was
created with `--copies`) would make `resolve()` an identity and this diagnosis wrong; then the
failure would be elsewhere in `verify_process_ownership` and the next candidate is the
`CommandLine` comparison built by `_make_identity`.

---

## Failure 3

`tests/test_api.py::test_corrupt_database_returns_sanitized_controlled_error`

### The assertion

`test_api.py:504-509`:

```python
def test_corrupt_database_returns_sanitized_controlled_error(client):
    db_path = client.app.state.test_database_path
    db_path.write_bytes(b"not a sqlite database")
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "degraded" and health.json()["database_available"] is False
```

### The mechanism

`app/main.py`, the `/api/health` handler:

```python
    available = False
    if initialized:
        try:
            with store.connect() as db:
                db.execute("SELECT 1").fetchone()
            available = True
        except store.DatabaseUnavailable:
            pass
```

`store.connect()` (`app/store.py`, `connect`) does three things that touch the file: an
`is_file()` stat, `sqlite3.connect(path)`, which is lazy and does not read the file, and
`PRAGMA foreign_keys = ON`, which is a per-connection setting and does not read page 1.
`SELECT 1` is a constant expression: SQLite answers it without opening the database header.
So a file containing `b"not a sqlite database"` is reported `available: True` and the handler
returns `"status": "ok"` with `"database_available": true`. The test's first two assertions pass
and the third fails.

The rest of the test's scenario still behaves: `/api/records` calls `require_database()`, which
only checks `path.is_file()` and so passes, then `store.list_records()` hits the corrupt file,
raises `sqlite3.DatabaseError`, `connect` converts it to `store.DatabaseUnavailable`
(`except sqlite3.Error` → `raise DatabaseUnavailable(...)`) and the exception handler returns
503. That is why only the health half of the test is red.

### Classification

**A real defect: a health check that cannot see corruption.** The test is correct and its
expectation is the right one — "corrupt database" must not read as healthy. The code path is
wrong, not the assertion.

### Minimal correct fix

`app/main.py`, replace the constant probe with one that reads the database header:

```python
                db.execute("PRAGMA schema_version").fetchone()
```

`PRAGMA schema_version` reads page 1, so a non-SQLite file raises `sqlite3.DatabaseError`
("file is not a database"), `connect` converts it to `DatabaseUnavailable`, the handler's
`except` catches it, `available` stays `False`, and the endpoint returns `degraded`. Cost is one
page read, no scan.

If the intent of `database_available` is also "the schema exists", use
`db.execute("SELECT count(*) FROM sqlite_master").fetchone()` instead — same page, and it also
fails on a valid-but-uninitialised empty database, which the current probe also mis-reports as
available.

Residual limitation to record, not fix here: a zero-byte file is a *valid* empty SQLite database,
so it will still report available after this change. That is arguably correct at the file level
and is caught downstream by the 503 path.

### What would falsify this

If `sqlite3.connect()` followed by `PRAGMA foreign_keys = ON` actually read page 1, the probe
would already raise and the endpoint would already say `degraded`; the test would then be failing
for a different assertion. One command settles it: open a file of garbage with `sqlite3` and run
`PRAGMA foreign_keys = ON; SELECT 1;` — if that succeeds, this diagnosis holds.

---

## Summary

| Failure | Root cause | Verdict | Fix in |
|---|---|---|---|
| `test_process_identity_accepts_exact_expected_launch` | `argv[0]` compared unresolved against a resolved `executable`; POSIX venv interpreter is a symlink | real defect, platform-exposed | `scripts/launch_policy_demo.py`, one line |
| `test_termination_uses_fake_killer_only_for_exact_identity` | same check refuses, so the killer is never called | same defect | same line |
| `test_corrupt_database_returns_sanitized_controlled_error` | `SELECT 1` never reads the database file | real defect | `app/main.py` health handler, one line |

Both are one-line fixes and neither requires a test change. The two launcher tests are one root
cause, so there are two defects behind three failures.

## Memory

Correction: an earlier draft of this section said no `local_memory_*` tool was bound to this
session. That was wrong — I inferred it from the tool list instead of attempting the call. The
store accepted the batch (`inserted: 2`), and the two facts below are in memory as well as here.
A refused or un-attempted call is not a missing tool; several workers made this same false
report today.

- `policy-evidence-engine launcher identity` · `COMPARES_UNRESOLVED_ARGV0` · `argv[0]` is
  compared to a `Path(...).resolve()` executable, so a symlinked POSIX interpreter fails the
  self-consistency check and termination is refused.
- `policy-evidence-engine health probe` · `USES_CONSTANT_SELECT` · `SELECT 1` does not read the
  database file, so a corrupt database is reported available; `PRAGMA schema_version` is the
  minimal probe that reads page 1.
