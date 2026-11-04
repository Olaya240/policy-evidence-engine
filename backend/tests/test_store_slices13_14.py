"""Contracts of the local SQLite store (slices 13-14).

Everything here runs against a temporary database directory, so the protected
`.e2e-phase34.sqlite3` and the real `data/prototype.sqlite3` are never opened.
"""

from __future__ import annotations

import pytest

from app import store


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


def test_initialize_is_idempotent_and_keeps_the_seed_count(db):
    before = len(store.list_records(include_restricted=True))
    store.initialize_database()
    assert len(store.list_records(include_restricted=True)) == before


def test_a_path_outside_the_data_directory_is_refused(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(store, "DATA_DIR", data_dir)
    monkeypatch.setenv("HACKATHON_DB_PATH", str(tmp_path / "elsewhere.sqlite3"))

    with pytest.raises(ValueError):
        store.database_path()
    with pytest.raises(ValueError):
        store.initialize_database()


def test_connecting_to_an_uninitialised_database_is_unavailable(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(store, "DATA_DIR", data_dir)
    monkeypatch.setenv("HACKATHON_DB_PATH", str(data_dir / "missing.sqlite3"))

    with pytest.raises(store.DatabaseUnavailable):
        with store.connect():
            pass


def test_restricted_records_are_hidden_from_reads(db):
    everything = store.list_records(include_restricted=True)
    visible = store.list_records()
    restricted = [record for record in everything if record.restricted]

    assert restricted, "the seed fixture must contain a restricted record"
    assert len(visible) == len(everything) - len(restricted)
    for record in restricted:
        assert record.id not in {entry.id for entry in visible}
        assert store.get_record(record.id) is None


def test_an_investigation_round_trips_with_its_creation_event(db):
    claims = [
        claim("claim-a", dependencies=["OPS-101"]),
        claim("claim-b", dependencies=[]),
    ]
    created = store.create_investigation("Why was the checklist unavailable?", claims)

    loaded = store.get_investigation(created["id"])
    history = store.get_history(created["id"])

    assert loaded["version"] == 1
    assert {entry["id"] for entry in loaded["claims"]} == {"claim-a", "claim-b"}
    assert [event["event"] for event in history] == ["CREATED"]
    assert history[0]["recomputed_claim_ids"] == ["claim-a", "claim-b"]
    assert store.get_investigation("does-not-exist") is None


def test_a_challenge_bumps_the_revision_and_both_claims(db):
    store.create_investigation(
        "Why was the checklist unavailable?",
        [
            claim("claim-a", dependencies=["OPS-101"]),
            claim("claim-b", dependencies=["OPS-101"]),
            claim("claim-c", dependencies=["OPS-110"]),
        ],
    )
    investigation_id = _only_investigation()

    snapshot = store.get_challenge_snapshot(investigation_id, "claim-a", "OPS-101")
    assert snapshot["revision"] == 1
    assert snapshot["affected_claim_ids"] == ["claim-a", "claim-b"]

    revised = {
        cid: dict(entry, status="CONTRADICTED") for cid, entry in snapshot["claims"].items()
    }
    result = store.apply_challenge(
        investigation_id,
        "claim-a",
        "the binder was present",
        "OPS-101",
        "binder",
        expected_revision=snapshot["revision"],
        expected_claims=snapshot["claims"],
        revised_claims=revised,
    )

    assert result["version"] == 2
    assert set(result["recomputed_claim_ids"]) == {"claim-a", "claim-b"}
    assert all(entry["version"] == 2 for entry in result["after"].values())

    loaded = store.get_investigation(investigation_id)
    assert loaded["version"] == 2
    by_id = {entry["id"]: entry for entry in loaded["claims"]}
    assert by_id["claim-a"]["status"] == "CONTRADICTED"
    assert by_id["claim-c"]["status"] == "PARTIAL"
    assert by_id["claim-c"]["version"] == 1
    assert [event["event"] for event in store.get_history(investigation_id)] == [
        "CREATED",
        "CHALLENGE",
    ]


def _only_investigation() -> str:
    with store.connect() as handle:
        row = handle.execute("SELECT id FROM investigations").fetchone()
    return row["id"]


def test_a_stale_revision_writes_nothing(db):
    store.create_investigation("q", [claim("claim-a", dependencies=["OPS-101"])])
    investigation_id = _only_investigation()
    snapshot = store.get_challenge_snapshot(investigation_id, "claim-a", "OPS-101")

    with pytest.raises(store.StaleRevision):
        store.apply_challenge(
            investigation_id,
            "claim-a",
            "reason",
            "OPS-101",
            "binder",
            expected_revision=snapshot["revision"] + 1,
            expected_claims=snapshot["claims"],
            revised_claims=snapshot["claims"],
        )

    assert store.get_investigation(investigation_id)["version"] == 1
    assert [event["event"] for event in store.get_history(investigation_id)] == ["CREATED"]


def test_changed_claims_behind_the_revision_are_stale(db):
    store.create_investigation("q", [claim("claim-a", dependencies=["OPS-101"])])
    investigation_id = _only_investigation()
    snapshot = store.get_challenge_snapshot(investigation_id, "claim-a", "OPS-101")

    tampered = {"claim-a": dict(snapshot["claims"]["claim-a"], status="SUPPORTED")}

    with pytest.raises(store.StaleRevision):
        store.apply_challenge(
            investigation_id,
            "claim-a",
            "reason",
            "OPS-101",
            "binder",
            expected_revision=snapshot["revision"],
            expected_claims=tampered,
            revised_claims=snapshot["claims"],
        )


def test_a_recomputed_set_that_does_not_match_the_affected_claims_is_refused(db):
    store.create_investigation(
        "q",
        [
            claim("claim-a", dependencies=["OPS-101"]),
            claim("claim-b", dependencies=["OPS-110"]),
        ],
    )
    investigation_id = _only_investigation()
    snapshot = store.get_challenge_snapshot(investigation_id, "claim-a", "OPS-101")

    with pytest.raises(ValueError):
        store.apply_challenge(
            investigation_id,
            "claim-a",
            "reason",
            "OPS-101",
            "binder",
            expected_revision=snapshot["revision"],
            expected_claims=snapshot["claims"],
            revised_claims={
                "claim-a": snapshot["claims"]["claim-a"],
                "claim-extra": claim("claim-extra", dependencies=[]),
            },
        )
