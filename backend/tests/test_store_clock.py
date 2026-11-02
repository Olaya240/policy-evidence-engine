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
