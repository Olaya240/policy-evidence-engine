"""Explicit local SQLite initialization and repository helpers."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import Record
from .mock_provider import SEED_RECORDS

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PROTECTED_DATABASE_NAME = ".e2e-phase34.sqlite3"


def validate_database_path(path: str | Path) -> Path:
    """Normalize a data path and reject the designated protected database."""
    # First compare lexically, without asking the filesystem about the target.
    # abspath/normpath resolve relative paths and `..` but do not open/stat the
    # protected database. Only non-protected candidates proceed to symlink-aware
    # resolution and later file/directory operations.
    raw = Path(path).expanduser()
    protected = DATA_DIR / PROTECTED_DATABASE_NAME
    candidate_lexical = Path(os.path.abspath(os.path.normpath(str(raw))))
    protected_lexical = Path(os.path.abspath(os.path.normpath(str(protected))))
    if os.path.normcase(str(candidate_lexical)) == os.path.normcase(str(protected_lexical)):
        raise ValueError("The protected local database path is not available to the prototype.")
    candidate = raw.resolve(strict=False)
    if os.path.normcase(str(candidate)) == os.path.normcase(str(protected_lexical)):
        raise ValueError("The protected local database path is not available to the prototype.")
    try:
        candidate.relative_to(DATA_DIR.resolve())
    except ValueError as exc:
        raise ValueError("HACKATHON_DB_PATH must stay inside hackathon/data") from exc
    return candidate


class DatabaseUnavailable(RuntimeError):
    """A local prototype database cannot be safely read or written."""


class StaleRevision(RuntimeError):
    """A challenge was computed from an investigation revision that is no longer current."""


def database_path() -> Path:
    configured = Path(os.environ.get("HACKATHON_DB_PATH", DATA_DIR / "prototype.sqlite3"))
    return validate_database_path(configured)


@contextmanager
def connect(*, write: bool = False):
    connection = None
    try:
        path = database_path()
        if not path.is_file():
            raise DatabaseUnavailable("Prototype database is not initialized")
        connection = sqlite3.connect(path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if write:
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        if write:
            connection.commit()
    except (OSError, ValueError) as exc:
        _rollback_quietly(connection, write)
        raise DatabaseUnavailable("Prototype database is unavailable") from exc
    except sqlite3.Error as exc:
        _rollback_quietly(connection, write)
        raise DatabaseUnavailable("Prototype database is unavailable") from exc
    except Exception:
        _rollback_quietly(connection, write)
        raise
    finally:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error as exc:
                raise DatabaseUnavailable("Prototype database is unavailable") from exc


def _rollback_quietly(connection: sqlite3.Connection | None, write: bool) -> None:
    if write and connection is not None:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass


def initialize_database() -> Path:
    """Create schema and synthetic records only when explicitly invoked."""
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, department TEXT NOT NULL,
                text TEXT NOT NULL, tags_json TEXT NOT NULL, restricted INTEGER NOT NULL DEFAULT 0,
                source_group TEXT
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
                ingested_at TEXT NOT NULL, department TEXT NOT NULL, chunk_count INTEGER NOT NULL,
                byte_size INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS investigations (
                id TEXT PRIMARY KEY, question TEXT NOT NULL, created_at TEXT NOT NULL,
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claim_versions (
                investigation_id TEXT NOT NULL REFERENCES investigations(id),
                claim_id TEXT NOT NULL, version INTEGER NOT NULL, hypothesis_id TEXT NOT NULL,
                claim_json TEXT NOT NULL, dependencies_json TEXT NOT NULL,
                PRIMARY KEY(investigation_id, claim_id, version)
            );
            CREATE TABLE IF NOT EXISTS history (
                investigation_id TEXT NOT NULL REFERENCES investigations(id),
                version INTEGER NOT NULL, created_at TEXT NOT NULL, event_json TEXT NOT NULL,
                PRIMARY KEY(investigation_id, version)
            );
            CREATE INDEX IF NOT EXISTS claim_versions_latest
                ON claim_versions(investigation_id, claim_id, version DESC);
        """)
        db.executemany(
            "INSERT OR IGNORE INTO records(id,timestamp,department,text,tags_json,restricted,source_group) VALUES(?,?,?,?,?,?,?)",
            [(r.id, r.timestamp.isoformat(), r.department, r.text, json.dumps(r.tags), int(r.restricted), r.source_group or r.id) for r in SEED_RECORDS],
        )
        db.commit()
    finally:
        db.close()
    return path


def list_records(*, include_restricted: bool = False) -> list[Record]:
    with connect() as db:
        rows = db.execute("SELECT * FROM records ORDER BY timestamp DESC, id").fetchall()
    return [Record(id=r["id"], timestamp=r["timestamp"], department=r["department"], text=r["text"], tags=json.loads(r["tags_json"]), restricted=bool(r["restricted"]), source_group=r["source_group"]) for r in rows if include_restricted or not r["restricted"]]


def get_record(record_id: str) -> Record | None:
    with connect() as db:
        row = db.execute("SELECT * FROM records WHERE id=? AND restricted=0", (record_id,)).fetchone()
    if row is None:
        return None
    return Record(id=row["id"], timestamp=row["timestamp"], department=row["department"], text=row["text"], tags=json.loads(row["tags_json"]), restricted=False, source_group=row["source_group"])


def _ensure_documents_table(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
            ingested_at TEXT NOT NULL, department TEXT NOT NULL, chunk_count INTEGER NOT NULL,
            byte_size INTEGER NOT NULL
        )
    """)


def ingest_document(
    document_id: str,
    sha256: str,
    filename: str,
    department: str,
    byte_size: int,
    records: list[Record],
) -> tuple[dict, list[Record], bool]:
    """Atomically insert document metadata and all chunk records.

    Handles duplicate SHA-256 documents idempotently by returning existing data.
    """
    with connect(write=True) as db:
        _ensure_documents_table(db)
        existing = db.execute("SELECT * FROM documents WHERE sha256=?", (sha256,)).fetchone()
        if existing is not None:
            doc_dict = {
                "id": existing["id"],
                "sha256": existing["sha256"],
                "filename": existing["filename"],
                "ingested_at": existing["ingested_at"],
                "department": existing["department"],
                "chunk_count": existing["chunk_count"],
                "byte_size": existing["byte_size"],
            }
            rows = db.execute(
                "SELECT * FROM records WHERE source_group=? ORDER BY id",
                (existing["id"],),
            ).fetchall()
            existing_records = [
                Record(
                    id=r["id"],
                    timestamp=r["timestamp"],
                    department=r["department"],
                    text=r["text"],
                    tags=json.loads(r["tags_json"]),
                    restricted=bool(r["restricted"]),
                    source_group=r["source_group"],
                )
                for r in rows
            ]
            return doc_dict, existing_records, True

        now_iso = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO documents(id, sha256, filename, ingested_at, department, chunk_count, byte_size) "
            "VALUES(?,?,?,?,?,?,?)",
            (document_id, sha256, filename, now_iso, department, len(records), byte_size),
        )
        for r in records:
            db.execute(
                "INSERT INTO records(id, timestamp, department, text, tags_json, restricted, source_group) "
                "VALUES(?,?,?,?,?,?,?)",
                (r.id, r.timestamp.isoformat(), r.department, r.text, json.dumps(r.tags), int(r.restricted), r.source_group or r.id),
            )
        doc_dict = {
            "id": document_id,
            "sha256": sha256,
            "filename": filename,
            "ingested_at": now_iso,
            "department": department,
            "chunk_count": len(records),
            "byte_size": byte_size,
        }
        return doc_dict, records, False


def get_document(document_id: str) -> dict | None:
    with connect() as db:
        _ensure_documents_table(db)
        row = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if row is None:
        return None
    return dict(row)


def list_documents() -> list[dict]:
    with connect() as db:
        _ensure_documents_table(db)
        rows = db.execute("SELECT * FROM documents ORDER BY ingested_at DESC, id").fetchall()
    return [dict(r) for r in rows]


def create_investigation(question: str, claims: list[dict]) -> dict:
    investigation_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with connect(write=True) as db:
        db.execute("INSERT INTO investigations VALUES(?,?,?,1)", (investigation_id, question, now))
        for claim in claims:
            _save_claim(db, investigation_id, claim)
        event = {"version": 1, "created_at": now, "event": "CREATED", "recomputed_claim_ids": [c["id"] for c in claims]}
        db.execute("INSERT INTO history(investigation_id,version,created_at,event_json) VALUES(?,?,?,?)", (investigation_id, 1, now, json.dumps(event)))
    return {"id": investigation_id, "question": question, "created_at": now, "version": 1, "claims": claims}


def _save_claim(db: sqlite3.Connection, investigation_id: str, claim: dict) -> None:
    db.execute("INSERT INTO claim_versions VALUES(?,?,?,?,?,?)", (investigation_id, claim["id"], claim["version"], claim["hypothesis_id"], json.dumps(claim), json.dumps(claim["dependencies"])))


def get_investigation(investigation_id: str) -> dict | None:
    with connect() as db:
        investigation = db.execute("SELECT * FROM investigations WHERE id=?", (investigation_id,)).fetchone()
        if investigation is None:
            return None
        rows = db.execute("""SELECT cv.claim_json FROM claim_versions cv
            JOIN (SELECT claim_id,MAX(version) version FROM claim_versions
                 WHERE investigation_id=? GROUP BY claim_id) latest
            ON cv.claim_id=latest.claim_id AND cv.version=latest.version
            WHERE cv.investigation_id=? ORDER BY cv.claim_id""", (investigation_id, investigation_id)).fetchall()
    return {"id": investigation["id"], "question": investigation["question"], "created_at": investigation["created_at"], "version": investigation["version"], "claims": [json.loads(row["claim_json"]) for row in rows]}


def _latest_claims(db: sqlite3.Connection, investigation_id: str) -> dict[str, dict]:
    rows = db.execute("""SELECT cv.claim_id, cv.claim_json FROM claim_versions cv JOIN
        (SELECT claim_id,MAX(version) version FROM claim_versions WHERE investigation_id=? GROUP BY claim_id) latest
        ON cv.claim_id=latest.claim_id AND cv.version=latest.version WHERE cv.investigation_id=?""",
        (investigation_id, investigation_id)).fetchall()
    return {row["claim_id"]: json.loads(row["claim_json"]) for row in rows}


def get_challenge_snapshot(investigation_id: str, claim_id: str, record_id: str) -> dict | None:
    """Read the revision and all affected claims before provider computation begins."""
    with connect() as db:
        # Pin revision and claim versions to one coherent SQLite read snapshot.
        db.execute("BEGIN")
        inv = db.execute("SELECT version FROM investigations WHERE id=?", (investigation_id,)).fetchone()
        if inv is None:
            return None
        current = _latest_claims(db, investigation_id)
    if claim_id not in current:
        return None
    affected = {claim_id} | {cid for cid, claim in current.items() if record_id in claim["dependencies"]}
    claims = {cid: current[cid] for cid in sorted(affected)}
    return {"revision": inv["version"], "claims": claims, "affected_claim_ids": sorted(affected)}


def apply_challenge(
    investigation_id: str,
    claim_id: str,
    reason: str,
    record_id: str,
    quote: str,
    *,
    expected_revision: int,
    expected_claims: dict[str, dict],
    revised_claims: dict[str, dict],
) -> dict | None:
    """Persist precomputed affected claims iff the captured snapshot is still current."""
    with connect(write=True) as db:
        inv = db.execute("SELECT * FROM investigations WHERE id=?", (investigation_id,)).fetchone()
        if inv is None:
            return None
        current = _latest_claims(db, investigation_id)
        if claim_id not in current:
            return None
        if inv["version"] != expected_revision:
            raise StaleRevision("Investigation revision changed during challenge computation")
        affected = {claim_id}
        for cid, claim in current.items():
            if record_id in claim["dependencies"]:
                affected.add(cid)
        if affected != set(expected_claims) or any(current[cid] != expected_claims[cid] for cid in affected):
            raise StaleRevision("Investigation claims changed during challenge computation")
        if set(revised_claims) != affected:
            raise ValueError("Recomputed claim set does not match affected dependencies")
        before = {cid: current[cid] for cid in sorted(affected)}
        now = datetime.now(timezone.utc).isoformat()
        next_version = inv["version"] + 1
        after = {}
        for cid in sorted(affected):
            revised = dict(revised_claims[cid])
            if revised.get("id") != cid:
                raise ValueError("Recomputed claim ID does not match its stored claim")
            revised["version"] = current[cid]["version"] + 1
            _save_claim(db, investigation_id, revised)
            after[cid] = revised
        changed = db.execute("UPDATE investigations SET version=? WHERE id=? AND version=?",
                             (next_version, investigation_id, expected_revision)).rowcount
        if changed != 1:
            raise StaleRevision("Investigation revision changed before challenge commit")
        event = {"version": next_version, "created_at": now, "event": "CHALLENGE", "claim_id": claim_id, "reason": reason, "source_record_id": record_id, "before": before, "after": after, "evidence_changes": [f"{record_id}: exact quote revalidated and claim reassessed"], "recomputed_claim_ids": sorted(affected)}
        db.execute("INSERT INTO history(investigation_id,version,created_at,event_json) VALUES(?,?,?,?)", (investigation_id, next_version, now, json.dumps(event)))
    return {"version": next_version, "before": before, "after": after, "recomputed_claim_ids": sorted(affected)}


def get_history(investigation_id: str) -> list[dict] | None:
    with connect() as db:
        if db.execute("SELECT 1 FROM investigations WHERE id=?", (investigation_id,)).fetchone() is None:
            return None
        rows = db.execute("SELECT event_json FROM history WHERE investigation_id=? ORDER BY version", (investigation_id,)).fetchall()
    return [json.loads(row["event_json"]) for row in rows]


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["init"]:
        raise SystemExit("Usage: python -m app.store init")
    print(f"Initialized local synthetic database: {initialize_database()}")

