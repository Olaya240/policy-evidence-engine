"""Text ingestion: `POST /api/records/ingest` over the existing record store.

Each test pins one required behaviour of the MVP: a stored record with an id,
`restricted` unreachable from a client, duplicate content collapsed to one row,
a bounded body, immediate visibility in the API and in an investigation, and a
timestamp taken from the injectable clock when the client supplies none.
"""
import asyncio
import gc
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app import ingest as ingest_module, store
from app.main import app
from app.models import INGEST_TEXT_MAX_CHARS, IngestCreate

INSERT = "/api/records/ingest"
FROZEN = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


class InProcessClient:
    """Same synchronous ASGI helper the other API tests use."""

    def __init__(self, application):
        self.app = application

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def request(self, method, path, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)


def _remove_sqlite_files(db_path: Path) -> None:
    gc.collect()
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = Path(str(db_path) + suffix)
        for _ in range(10):
            if not path.exists():
                break
            try:
                path.unlink()
                break
            except PermissionError:
                gc.collect()
                time.sleep(0.05)


@pytest.fixture
def client(monkeypatch):
    db_path = store.DATA_DIR / f".test-ingest-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    try:
        store.initialize_database()
        with InProcessClient(app) as test_client:
            test_client.app.state.test_database_path = db_path
            yield test_client
    finally:
        _remove_sqlite_files(db_path)


def _row_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as db:
        return db.execute("SELECT COUNT(*) FROM records").fetchone()[0]


def _stored_timestamps(db_path: Path, record_id: str) -> list[str]:
    with sqlite3.connect(db_path) as db:
        rows = db.execute("SELECT timestamp FROM records WHERE id=?", (record_id,)).fetchall()
    return [row[0] for row in rows]


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def test_parse_timestamp_accepts_z_suffix_as_aware_utc():
    parsed = _parse_timestamp("2026-10-25T06:00:00Z")

    assert parsed == datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_parse_timestamp_z_and_explicit_utc_offsets_are_equivalent():
    z_suffix = _parse_timestamp("2026-10-25T06:00:00Z")
    explicit_offset = _parse_timestamp("2026-10-25T06:00:00+00:00")

    assert z_suffix == explicit_offset


def test_parse_timestamp_preserves_non_utc_offset():
    parsed = _parse_timestamp("2026-10-25T06:00:00+05:30")

    assert parsed.utcoffset().total_seconds() == 5.5 * 60 * 60
    assert parsed.isoformat() == "2026-10-25T06:00:00+05:30"


def test_parse_timestamp_preserves_naive_timestamp_behavior():
    parsed = _parse_timestamp("2026-10-25T06:00:00")

    assert parsed == datetime(2026, 10, 25, 6, 0)
    assert parsed.tzinfo is None


def _seed_count(client) -> int:
    """Rows already present before a test ingests anything."""
    return _row_count(client.app.state.test_database_path)


def test_ingest_returns_201_with_the_id_and_the_stored_record(client):
    seeds = _seed_count(client)
    response = client.post(INSERT, json={
        "text": "  Morning handover: the checklist binder was on the back desk.  ",
        "department": "Front Office",
        "timestamp": "2026-10-25T06:00:00+00:00",
        "source_group": "SHIFT-2510",
        "tags": ["checklist", "handover"],
    })

    assert response.status_code == 201
    body = response.json()
    assert body["record"]["id"] == body["id"]
    assert body["record"]["text"] == "Morning handover: the checklist binder was on the back desk."
    assert body["record"]["department"] == "Front Office"
    assert body["record"]["tags"] == ["checklist", "handover"]
    assert body["record"]["source_group"] == "SHIFT-2510"
    assert body["record"]["restricted"] is False
    assert _parse_timestamp(body["record"]["timestamp"]) == datetime(
        2026, 10, 25, 6, 0, tzinfo=timezone.utc
    )
    assert _row_count(client.app.state.test_database_path) == seeds + 1


def test_restricted_is_not_client_settable_and_restricted_rows_are_never_reused(client):
    assert "restricted" not in IngestCreate.model_fields

    before = _row_count(client.app.state.test_database_path)
    rejected = client.post(INSERT, json={
        "text": "A note that asks to be hidden.",
        "department": "Front Office",
        "restricted": True,
    })
    assert rejected.status_code == 422
    assert "restricted" in str(rejected.json())
    assert _row_count(client.app.state.test_database_path) == before

    # The seeded restricted canary is not a dedupe target: the same content
    # ingested as plain text becomes a new, non-restricted record, and the
    # restricted row is never echoed back or reused.
    reused = client.post(INSERT, json={
        "text": "RESTRICTED_CANARY_DO_NOT_DISCLOSE_8f2b1d",
        "department": "Restricted",
    })
    assert reused.status_code == 201
    body = reused.json()
    assert body["id"] != "CANARY-RESTRICTED-001"
    assert body["record"]["restricted"] is False
    visible_ids = {record["id"] for record in client.get("/api/records").json()}
    assert "CANARY-RESTRICTED-001" not in visible_ids


def test_duplicate_normalised_content_returns_the_existing_id_and_one_row(client):
    seeds = _seed_count(client)
    first = client.post(INSERT, json={
        "text": "checklist binder was\n\nmissing at  the desk",
        "department": "Front Office",
        "source_group": "SHIFT-A",
    })
    assert first.status_code == 201
    assert first.json()["created"] is True

    second = client.post(INSERT, json={
        "text": "   checklist binder was missing at   the desk   ",
        "department": "Front Office",
        "source_group": "SHIFT-A",
    })

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["record"] == first.json()["record"]
    assert second.json()["created"] is False
    assert _row_count(client.app.state.test_database_path) == seeds + 1

    # A different source group is a different document, so it is stored.
    third = client.post(INSERT, json={
        "text": "checklist binder was missing at the desk",
        "department": "Front Office",
        "source_group": "SHIFT-B",
    })
    assert third.status_code == 201
    assert third.json()["id"] != first.json()["id"]
    assert _row_count(client.app.state.test_database_path) == seeds + 2


def test_oversized_text_is_refused_with_a_bounded_4xx(client):
    before = _row_count(client.app.state.test_database_path)

    just_over = client.post(INSERT, json={
        "text": "x" * (INGEST_TEXT_MAX_CHARS + 1),
        "department": "Front Office",
    })
    assert just_over.status_code == 422
    assert _row_count(client.app.state.test_database_path) == before

    # A body far past the bound is still a bounded rejection: no 500, no hang.
    started = time.monotonic()
    enormous = client.post(INSERT, json={
        "text": "x" * 2_000_000,
        "department": "Front Office",
    })
    elapsed = time.monotonic() - started
    assert enormous.status_code == 422
    assert elapsed < 10
    assert _row_count(client.app.state.test_database_path) == before


def test_ingested_record_is_visible_and_usable_in_a_new_investigation(client):
    created = client.post(INSERT, json={
        "text": "Night shift checklist binder was missing again from the desk.",
        "department": "Front Office",
        "tags": ["checklist"],
    })
    assert created.status_code == 201
    record_id = created.json()["id"]

    assert record_id in {record["id"] for record in client.get("/api/records").json()}

    investigation = client.post("/api/investigations", json={
        "question": "Did checklist availability contribute to missing handover information?",
    })
    assert investigation.status_code == 201
    cited = {
        evidence["source_record_id"]
        for claim in investigation.json()["claims"]
        for evidence in claim["evidence"]
    }
    assert record_id in cited


def test_timestamp_comes_from_the_injectable_clock_when_the_client_supplies_none(client, monkeypatch):
    monkeypatch.setattr(ingest_module, "write_clock", lambda: FROZEN)

    response = client.post(INSERT, json={
        "text": "Checklist binder was present for the whole shift.",
        "department": "Front Office",
    })

    assert response.status_code == 201
    record_id = response.json()["id"]
    assert _parse_timestamp(response.json()["record"]["timestamp"]) == FROZEN
    assert _stored_timestamps(client.app.state.test_database_path, record_id) == [FROZEN.isoformat()]


def test_a_restricted_row_is_never_a_duplicate_target(client):
    """The dedupe lookup must not hand back the id of a restricted row.

    This exists because a mutation of the lookup (dropping `AND restricted=0`) left the
    whole suite green: the seeded restricted row has no `source_group`, so its identity
    never matched. Here the restricted row is given the same text, department *and*
    group as the incoming document, which is the only case in which the filter matters.
    """
    text = "The checklist binder was not available during the handover."
    db_path = client.app.state.test_database_path
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO records(id,timestamp,department,text,tags_json,restricted,source_group)"
            " VALUES(?,?,?,?,?,?,?)",
            ("RESTRICTED-TWIN", "2026-05-01T09:00:00+00:00", "Front Office", text, "[]", 1, "twin-group"),
        )
        connection.commit()

    response = client.post(
        INSERT,
        json={"text": text, "department": "Front Office", "source_group": "twin-group"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["id"] != "RESTRICTED-TWIN"
    assert response.json()["created"] is True
