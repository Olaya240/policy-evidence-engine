# W3 — `app/store.py` write-path clock

Worker 3 of 10. Owns `backend/app/store.py`, `backend/tests/test_store_slices13_14.py` and
`backend/tests/test_store_clock.py` (new). Edited `store.py` and the new test file;
`test_store_slices13_14.py` is unchanged (it already passes against the new signature, which is
the compatibility claim that signature exists to make).

## Turn type

**Decide** (is the store's write path now a clock seam, or only a re-shaped function) wrapped
around an **edit**. The decision this answer feeds: whether a caller can make every row written
into the disposable evaluation database carry the run's frozen instant.

## The defect, re-read before editing

`backend/app/store.py` at the pre-edit copy in the working tree, two write sites:

```
$ grep -n "datetime.now(timezone.utc)" backend/app/store.py     # before this worker's edit
158:    now = datetime.now(timezone.utc).isoformat()
239:        now = datetime.now(timezone.utc).isoformat()
```

`backend/app/evaluate.py` claims the opposite for the whole run, at line 57–61, and stops at the
engine:

```
57:        # The clock is injected for the whole run, not just around `investigate`:
...
61:        engine = AssessmentEngine(semantic_guard=guarded, clock=lambda: EVALUATION_AS_OF)
64:        created = store.create_investigation("Phase 3.6 deterministic history evaluation", initial_claims)
80:        applied = store.apply_challenge(
```

So the engine got the frozen instant and `investigations.created_at` / `investigation_history.created_at`
got the wall clock.

## Diff

`git diff -- backend/app/store.py` (verbatim). The two `connect()` hunks at the top are **not**
this worker's: they were already in the working tree before it started (`git diff` at task start
showed `index c22803e..76e1fde` with only those hunks). Mine are the `typing.Callable` import,
`_wall_clock`/`_stamp` + `create_investigation`, and the `clock` parameter on `apply_challenge`.

```
diff --git a/backend/app/store.py b/backend/app/store.py
index c22803e..0cad651 100644
--- a/backend/app/store.py
+++ b/backend/app/store.py
@@ -5,6 +5,7 @@ import sqlite3
 from contextlib import contextmanager
 from datetime import datetime, timezone
 from pathlib import Path
+from typing import Callable
 from uuid import uuid4
 
 from .models import Record
@@ -53,8 +54,16 @@ def database_path() -> Path:
 @contextmanager
 def connect(*, write: bool = False):
     connection = None
+    # Path validation raises ValueError, and it happens before anything is opened.
+    # Its exception handler must therefore sit here and not around the body: when
+    # it wrapped the body, every ValueError a caller raised (a revision mismatch,
+    # a recomputed claim set that does not match) was relabelled "database
+    # unavailable", turning a 422 into a 503 and hiding the real cause.
     try:
         path = database_path()
+    except (OSError, ValueError) as exc:
+        raise DatabaseUnavailable("Prototype database is unavailable") from exc
+    try:
         if not path.is_file():
             raise DatabaseUnavailable("Prototype database is not initialized")
         connection = sqlite3.connect(path, timeout=5)
@@ -65,10 +74,10 @@ def connect(*, write: bool = False):
         yield connection
         if write:
             connection.commit()
-    except (OSError, ValueError) as exc:
+    except DatabaseUnavailable:
         _rollback_quietly(connection, write)
-        raise DatabaseUnavailable("Prototype database is unavailable") from exc
-    except sqlite3.Error as exc:
+        raise
+    except (OSError, sqlite3.Error) as exc:
         _rollback_quietly(connection, write)
         raise DatabaseUnavailable("Prototype database is unavailable") from exc
     except Exception:
@@ -145,9 +154,27 @@ def get_record(record_id: str) -> Record | None:
     return Record(id=row["id"], timestamp=row["timestamp"], department=row["department"], text=row["text"], tags=json.loads(row["tags_json"]), restricted=False, source_group=row["source_group"])
 
 
-def create_investigation(question: str, claims: list[dict]) -> dict:
+def _wall_clock() -> datetime:
+    """Default write clock: the real UTC instant.
+
+    Every row this module writes is stamped with an instant, and an evaluation
+    run has to write its own frozen instant rather than the moment the row
+    happened to be created. The clock is therefore a keyword-only argument with
+    this wall clock as its default, so every existing caller keeps the previous
+    behaviour unchanged.
+    """
+    return datetime.now(timezone.utc)
+
+
+def _stamp(clock: Callable[[], datetime] | None) -> str:
+    return (clock if clock is not None else _wall_clock)().isoformat()
+
+
+def create_investigation(
+    question: str, claims: list[dict], *, clock: Callable[[], datetime] | None = None
+) -> dict:
     investigation_id = str(uuid4())
-    now = datetime.now(timezone.utc).isoformat()
+    now = _stamp(clock)
     with connect(write=True) as db:
         db.execute("INSERT INTO investigations VALUES(?,?,?,1)", (investigation_id, question, now))
         for claim in claims:
@@ -208,6 +235,7 @@ def apply_challenge(
     expected_revision: int,
     expected_claims: dict[str, dict],
     revised_claims: dict[str, dict],
+    clock: Callable[[], datetime] | None = None,
 ) -> dict | None:
     """Persist precomputed affected claims iff the captured snapshot is still current."""
     with connect(write=True) as db:
@@ -228,7 +256,7 @@ def apply_challenge(
         if set(revised_claims) != affected:
             raise ValueError("Recomputed claim set does not match affected dependencies")
         before = {cid: current[cid] for cid in sorted(affected)}
-        now = datetime.now(timezone.utc).isoformat()
+        now = _stamp(clock)
         next_version = inv["version"] + 1
         after = {}
         for cid in sorted(affected):
```

Resulting sites, in the edited file: `store.py:157` `_wall_clock`, `:169` `_stamp`, `:173-174`
`create_investigation(..., *, clock=...)`, `:177` and `:259` `now = _stamp(clock)`, `:238` the
`clock` parameter of `apply_challenge`. `apply_challenge` is entirely keyword-only after its five
positional arguments, so adding `clock` there cannot reorder an existing call.

New test file, `git diff --no-index -- /dev/null backend/tests/test_store_clock.py`, shown as the
file's full content:

```python
"""Write-path clock injection for the local SQLite store.

`store.create_investigation` and `store.apply_challenge` used to call
`datetime.now(timezone.utc)` at their two write sites, so rows written into a
disposable evaluation database carried wall-clock instants even though
`evaluate.py` builds its engine with a frozen clock. These tests pin both halves
of the fix: an injected clock decides every instant a write records, and the
default is still the wall clock.

Everything runs against a temporary database directory, like
`test_store_slices13_14.py`.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app import store

EARLY = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
LATE = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(store, "DATA_DIR", data_dir)
    monkeypatch.setenv("HACKATHON_DB_PATH", str(data_dir / "prototype.sqlite3"))
    store.initialize_database()
    return data_dir / "prototype.sqlite3"


def claim(claim_id, *, dependencies, version=1, hypothesis="CHECKLIST_UNAVAILABLE"):
    return {
        "id": claim_id,
        "hypothesis_id": hypothesis,
        "version": version,
        "dependencies": list(dependencies),
        "status": "PARTIAL",
    }


def test_two_clocks_write_different_creation_instants(db):
    early = store.create_investigation(
        "q", [claim("claim-a", dependencies=["OPS-101"])], clock=lambda: EARLY
    )
    late = store.create_investigation(
        "q", [claim("claim-a", dependencies=["OPS-101"])], clock=lambda: LATE
    )

    assert early["created_at"] == EARLY.isoformat()
    assert late["created_at"] == LATE.isoformat()
    assert early["created_at"] != late["created_at"]

    # The stamp reaches the persisted row and its CREATED event, not just the
    # dict the call returns.
    assert store.get_investigation(early["id"])["created_at"] == EARLY.isoformat()
    assert store.get_investigation(late["id"])["created_at"] == LATE.isoformat()
    assert [event["created_at"] for event in store.get_history(early["id"])] == [
        EARLY.isoformat()
    ]
    assert [event["created_at"] for event in store.get_history(late["id"])] == [
        LATE.isoformat()
    ]


def test_a_challenge_is_stamped_by_its_own_clock_not_the_creation_clock(db):
    created = store.create_investigation(
        "q", [claim("claim-a", dependencies=["OPS-101"])], clock=lambda: EARLY
    )
    snapshot = store.get_challenge_snapshot(created["id"], "claim-a", "OPS-101")
    revised = {
        cid: dict(entry, status="CONTRADICTED") for cid, entry in snapshot["claims"].items()
    }

    store.apply_challenge(
        created["id"],
        "claim-a",
        "reason",
        "OPS-101",
        "binder",
        expected_revision=snapshot["revision"],
        expected_claims=snapshot["claims"],
        revised_claims=revised,
        clock=lambda: LATE,
    )

    history = store.get_history(created["id"])
    assert [event["created_at"] for event in history] == [EARLY.isoformat(), LATE.isoformat()]
    assert len({event["created_at"] for event in history}) == 2


def test_the_default_write_clock_is_the_wall_clock(db):
    before = datetime.now(timezone.utc)
    created = store.create_investigation("q", [claim("claim-a", dependencies=["OPS-101"])])
    after = datetime.now(timezone.utc)

    stamped = datetime.fromisoformat(created["created_at"])
    assert stamped.tzinfo is not None
    assert before - timedelta(seconds=1) <= stamped <= after + timedelta(seconds=1)
    # A fixed 2026-01-01 constant is in the past, so the default cannot be it.
    assert stamped > EARLY
    assert store.get_investigation(created["id"])["created_at"] == created["created_at"]
    assert store.get_history(created["id"])[0]["created_at"] == created["created_at"]

    # The challenge write site defaults the same way.
    snapshot = store.get_challenge_snapshot(created["id"], "claim-a", "OPS-101")
    revised = {cid: dict(entry) for cid, entry in snapshot["claims"].items()}
    challenge_started = datetime.now(timezone.utc)
    store.apply_challenge(
        created["id"],
        "claim-a",
        "reason",
        "OPS-101",
        "binder",
        expected_revision=snapshot["revision"],
        expected_claims=snapshot["claims"],
        revised_claims=revised,
    )
    challenge_finished = datetime.now(timezone.utc)

    challenged_at = datetime.fromisoformat(store.get_history(created["id"])[1]["created_at"])
    assert challenge_started - timedelta(seconds=1) <= challenged_at <= challenge_finished + timedelta(seconds=1)
    assert challenged_at > stamped


def test_the_clock_is_keyword_only_so_existing_callers_are_unchanged():
    for function in (store.create_investigation, store.apply_challenge):
        parameter = inspect.signature(function).parameters["clock"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is None

    with pytest.raises(TypeError):
        store.create_investigation("q", [], lambda: EARLY)
```

## Verbatim runs

Assigned set, plus `tests/test_evaluate_contracts.py` and `tests/test_evaluation.py`:

```
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_store_clock.py tests/test_store_slices13_14.py tests/test_evaluate_contracts.py tests/test_evaluation.py
```

```
..........................                                               [100%]
26 passed in 1.34s
```

Exit status 0. 4 of the 26 are the new clock tests (`--collect-only` → `4 tests collected`); the
other 22 are the untouched `test_store_slices13_14.py`, `test_evaluate_contracts.py` and
`test_evaluation.py`, which pass without an edit:

```
22 passed in 1.68s
```

Store's other callers (routers, challenge flow), to show the new keyword-only parameter did not
disturb an existing call:

```
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_store_path_safety.py tests/test_legacy_challenge.py tests/test_manifest_and_routes.py tests/test_api.py
```

```
........................................................................ [ 62%]
............................................                             [100%]
116 passed in 6.46s
```

Exit status 0.

Whole suite, for the record — 5 failures, all outside this worker's files and independent of
`store.py`: `tests/test_mock_provider_slice19.py` (1) and
`tests/test_semantic_guard_negation_corpus.py` (4), while `app/semantic_guard.py` and both of
those test files are other workers' in-flight edits. Neither test file nor `app/semantic_guard.py`
nor `app/mock_provider.py` mentions `store` (`grep -n "import store\|app.store"` over all four →
no matches), so they cannot be caused by this change.

```
5 failed, 1752 passed, 1 warning in 25.04s
```

That is **not** a pass and is not claimed as one; the failures belong to another worker.

## Negative control — the tests can fail

The new tests were run against a copy of the tree with only the two call sites reverted to
`datetime.now(timezone.utc).isoformat()` and nothing else changed (`/tmp/w3-neg`, `sed` on
`now = _stamp(clock)`, the helper kept so the signature still accepts `clock`):

```
FAILED tests/test_store_clock.py::test_two_clocks_write_different_creation_instants
FAILED tests/test_store_clock.py::test_a_challenge_is_stamped_by_its_own_clock_not_the_creation_clock
2 failed, 2 passed in 0.47s
```

```
E       AssertionError: assert ['2026-11-01T...489207+00:00'] == ['2026-01-01T...:00:00+00:00']
E         At index 0 diff: '2026-11-01T23:08:17.478558+00:00' != '2026-01-01T12:00:00+00:00'
```

So the two clock tests fail exactly when the write path ignores its clock; the keyword-only test
and the wall-clock-default test pass in both directions by design (they assert the default and the
signature, which the defect never changed).

In the real tree the same probe was done once, before the isolated copy existed, by `sed`-ing the
two lines in place and restoring from a saved copy; `cmp /tmp/store_clock_fixed.py backend/app/store.py`
now reports identical, both
`c41ad95297ea5daaf41500a31f0192fb7dd93b982d9179e914649fb46b99f70a`. The isolated run above supersedes
that probe.

## Residual gap — measured, and outside my files

The seam exists, but nothing passes a clock through it yet. `backend/app/evaluate.py:64` and `:80`
call `store.create_investigation` / `store.apply_challenge` with no `clock`, so the default path is
still what the evaluation run writes. Measured on the real module with a temporary database
directory:

```
cd /home/alex/policy-evidence-fix/backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python - <<'PY'
... store.DATA_DIR = <tmp>/data; store.initialize_database()
row = store.create_investigation("q", [{"id": "a", "hypothesis_id": "H", "version": 1, "dependencies": [], "status": "PARTIAL"}])
print("frozen evaluation instant :", "2026-10-27T12:00:00+00:00")
print("stored created_at         :", row["created_at"])
print("stored history created_at :", store.get_history(row["id"])[0]["created_at"])
PY
```

```
frozen evaluation instant : 2026-10-27T12:00:00+00:00
stored created_at         : 2026-11-01T23:05:52.841453+00:00
stored history created_at : 2026-11-01T23:05:52.841453+00:00
```

`evaluate.py` is not mine. Closing the defect end to end needs, at those two call sites,
`clock=lambda: EVALUATION_AS_OF` (the same callable already handed to `AssessmentEngine` at line
61), passed as a keyword so the signature stays as shipped here. Until that lands, the store can
write the frozen instant and the evaluation harness still writes the wall clock.

## What I did not do

- Did not edit `evaluate.py`, any router, or `test_store_slices13_14.py`; the latter needed no
  change, which is the evidence that the keyword-only default kept its calls working.
- Did not normalise an injected naive datetime before `isoformat()`: the default keeps the previous
  `+00:00` text, and an injected clock's own representation is written as given. No caller in the
  tree injects a naive clock, so this is a decision, not a measured compatibility result.
- Did not investigate the 5 whole-suite failures beyond establishing they cannot come from
  `store.py`; another worker owns them.
