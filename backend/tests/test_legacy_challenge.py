"""End-to-end proof that the caller-mutation fix removes the permanent 409.

`main.py` passes `snapshot["claims"]` into `engine.challenge` and then hands the
same objects to `store.apply_challenge` as `expected_claims`. Before the copy
fix, `challenge` appended *references* to evidence items it did not touch and
the semantic guard then wrote `review_state` into them, so the expected bytes
changed before the comparison and every challenge to an investigation persisted
before `review_state` existed raised `StaleRevision` — a 409 that never clears.

This test builds that exact shape: a stored investigation whose evidence rows
have no `review_state`, a challenge computed from it, and the compare-and-swap
that used to fail.
"""

import copy
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app import store
from app.engine import AssessmentEngine

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
RECORD_ID = "OPS-101"
QUOTE = "binder was missing"


@pytest.fixture()
def db(monkeypatch):
    # The store only accepts a path inside its own data directory.
    db_path = store.DATA_DIR / f".test-legacy-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    store.initialize_database()
    try:
        yield db_path
    finally:
        for suffix in ("", "-wal", "-shm"):
            path = db_path.with_name(db_path.name + suffix)
            if path.exists():
                path.unlink()


def legacy_claims(claims):
    """Strip the field an older build never wrote."""
    legacy = copy.deepcopy(claims)
    for claim in legacy.values():
        for item in claim["evidence"]:
            item.pop("review_state", None)
    return legacy


def test_a_pre_upgrade_investigation_can_still_be_challenged(db):
    records = store.list_records()
    engine = AssessmentEngine(clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    claims = engine.investigate(records)
    investigation = store.create_investigation("Legacy investigation", claims)

    # Rewrite the stored rows the way an older build left them: a new claim
    # version whose evidence carries no `review_state`, plus a revision bump so
    # the snapshot is coherent.
    stored = store.get_investigation(investigation["id"])
    with store.connect(write=True) as conn:
        for claim in stored["claims"]:
            legacy = copy.deepcopy(claim)
            for item in legacy["evidence"]:
                item.pop("review_state", None)
            legacy["version"] = claim["version"] + 1
            store._save_claim(conn, investigation["id"], legacy)
        conn.execute("UPDATE investigations SET version=2 WHERE id=?", (investigation["id"],))

    reloaded = store.get_challenge_snapshot(investigation["id"], HYPOTHESIS, RECORD_ID)
    expected = copy.deepcopy(reloaded["claims"])
    assert all("review_state" not in item for claim in expected.values() for item in claim["evidence"])

    # main.py's exact sequence.
    revised = {
        claim_id: engine.challenge(claim, records, RECORD_ID, QUOTE)
        for claim_id, claim in expected.items()
    }
    # The fix: computing the revision must not have touched what we will compare.
    assert expected == reloaded["claims"]

    result = store.apply_challenge(
        investigation["id"],
        HYPOTHESIS,
        "review the binder record",
        RECORD_ID,
        QUOTE,
        expected_revision=reloaded["revision"],
        expected_claims=expected,
        revised_claims=revised,
    )

    assert result is not None
    assert result["version"] == reloaded["revision"] + 1
    assert result["recomputed_claim_ids"]


def test_the_same_sequence_raises_if_the_expected_bytes_are_stale(db):
    """Contrast case: the compare-and-swap is still armed. If the caller's bytes
    disagree with storage for any other reason, StaleRevision is raised — the fix
    removed the self-inflicted mismatch, not the protection."""
    records = store.list_records()
    engine = AssessmentEngine()
    claims = engine.investigate(records)
    investigation = store.create_investigation("Armed CAS", claims)
    snapshot = store.get_challenge_snapshot(investigation["id"], HYPOTHESIS, RECORD_ID)

    expected = copy.deepcopy(snapshot["claims"])
    tampered = copy.deepcopy(expected)
    tampered[HYPOTHESIS]["summary"] = "edited elsewhere"

    revised = {
        claim_id: engine.challenge(claim, records, RECORD_ID, QUOTE)
        for claim_id, claim in tampered.items()
    }

    with pytest.raises(store.StaleRevision):
        store.apply_challenge(
            investigation["id"],
            HYPOTHESIS,
            "review",
            RECORD_ID,
            QUOTE,
            expected_revision=snapshot["revision"],
            expected_claims=tampered,
            revised_claims=revised,
        )
