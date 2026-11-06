"""Explicit local SQLite initialization and repository helpers."""
import json
import logging
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from pydantic import ValidationError

from .dependency_graph import transitive_dependents
from .models import Record
from .mock_provider import SEED_RECORDS

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PROTECTED_DATABASE_NAME = ".e2e-phase34.sqlite3"
E2E_MODE_ENV = "STORY_CONNECT_E2E_MODE"
E2E_WORKSPACE_ENV = "STORY_CONNECT_E2E_WORKSPACE"
E2E_DATABASE_PATH_ENV = "STORY_CONNECT_E2E_DATABASE_PATH"
E2E_OWNER_FILE = ".story-connect-e2e-owner.json"


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


def validate_e2e_database_path(path: str | Path, workspace: str | Path) -> Path:
    """Validate the separate disposable E2E database boundary without opening it."""
    raw_workspace = Path(workspace)
    raw_path = Path(path)
    if not raw_workspace.is_absolute() or not raw_path.is_absolute():
        raise ValueError("E2E workspace and database paths must be absolute")
    if ".." in raw_workspace.parts or ".." in raw_path.parts:
        raise ValueError("E2E paths cannot contain traversal components")
    if raw_workspace.name.casefold().startswith("story-connect-e2e-") is False:
        raise ValueError("E2E workspace name is invalid")
    system_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    canonical_workspace = raw_workspace.resolve(strict=False)
    if canonical_workspace != system_temp and system_temp not in canonical_workspace.parents:
        raise ValueError("E2E workspace must be inside the system temporary directory")
    if raw_workspace.is_symlink() or not raw_workspace.is_dir():
        raise ValueError("E2E workspace must be an existing non-symlink directory")

    expected = raw_workspace / "database" / "e2e.sqlite3"
    if raw_path != expected:
        raise ValueError("E2E database path must be the workspace database/e2e.sqlite3 path")
    components = (raw_workspace / E2E_OWNER_FILE, raw_workspace / "database", expected)
    for component in components:
        if component.exists() or component.is_symlink():
            info = component.lstat()
            if component.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("E2E paths cannot contain symlinks or reparse points")
    owner = raw_workspace / E2E_OWNER_FILE
    try:
        import json
        metadata = json.loads(owner.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("E2E workspace ownership metadata is unavailable") from exc
    if (type(metadata) is not dict or metadata.get("schema") != 1
            or not isinstance(metadata.get("run_id"), str)
            or metadata.get("workspace") != str(raw_workspace.resolve(strict=True))):
        raise ValueError("E2E workspace ownership metadata is invalid")
    resolved_workspace = raw_workspace.resolve(strict=True)
    resolved_path = raw_path.resolve(strict=False)
    if resolved_path != resolved_workspace / "database" / "e2e.sqlite3":
        raise ValueError("E2E database path escaped its canonical workspace")
    return resolved_path


class DatabaseUnavailable(RuntimeError):
    """A local prototype database cannot be safely read or written."""


class StaleRevision(RuntimeError):
    """A challenge was computed from an investigation revision that is no longer current."""


@dataclass(frozen=True)
class UnreadableRow:
    """A stored row that cannot be read as the schema requires.

    Deliberately excludes the stored value: the point of naming a row is to say
    where to look, not to copy the bad content into a log or an error body.
    """

    table: str
    row_id: str
    field: str
    reason: str


class CorruptStoredRow(DatabaseUnavailable):
    """One stored row cannot be decoded, and the read that needed it is refused.

    It subclasses ``DatabaseUnavailable`` on purpose: the local file is the whole
    trust boundary, an unreadable row is a failure of that store rather than of the
    request, and the existing HTTP handler already answers it as a bounded 503
    instead of a 500 with a traceback.

    The message names the table, the row id and the column. That naming is the
    reason this class exists — a generic decode error made every other row in the
    table unreadable while saying nothing about which row was bad.
    """

    def __init__(self, *, table: str, row_id: str, field: str, reason: str):
        self.row = UnreadableRow(table=table, row_id=str(row_id), field=field, reason=reason)
        super().__init__(
            f"Unreadable stored row {self.row.table}:{self.row.row_id} "
            f"(column {self.row.field}): {self.row.reason}"
        )
        # The HTTP body is one fixed sentence, so the row identity has to reach the
        # operator some other way. Only the coordinates are logged, never the value.
        logger.warning("Unreadable stored row %s:%s (column %s): %s",
                       self.row.table, self.row.row_id, self.row.field, self.row.reason)

    @property
    def table(self) -> str:
        return self.row.table

    @property
    def row_id(self) -> str:
        return self.row.row_id

    @property
    def field(self) -> str:
        return self.row.field

    @property
    def reason(self) -> str:
        return self.row.reason


def _corrupt(table: str, row_id: object, field: str, reason: str) -> CorruptStoredRow:
    return CorruptStoredRow(table=table, row_id=str(row_id), field=field, reason=reason)


def _first_failing_field(error: ValidationError, default: str) -> str:
    """Name the column a schema failure is about, from the model's own locator."""
    for item in error.errors():
        location = item.get("loc") or ()
        if location and isinstance(location[0], str):
            return location[0]
    return default


def database_path() -> Path:
    e2e_values = (os.environ.get(E2E_MODE_ENV), os.environ.get(E2E_WORKSPACE_ENV),
                  os.environ.get(E2E_DATABASE_PATH_ENV))
    if any(value is not None for value in e2e_values):
        mode, workspace, database = e2e_values
        if mode != "1" or not workspace or not database:
            raise ValueError("Incomplete E2E database configuration")
        if os.environ.get("HACKATHON_DB_PATH"):
            raise ValueError("Normal database override is forbidden in E2E mode")
        return validate_e2e_database_path(database, workspace)
    configured = Path(os.environ.get("HACKATHON_DB_PATH", DATA_DIR / "prototype.sqlite3"))
    return validate_database_path(configured)


@contextmanager
def connect(*, write: bool = False):
    connection = None
    # Path validation raises ValueError, and it happens before anything is opened.
    # Its exception handler must therefore sit here and not around the body: when
    # it wrapped the body, every ValueError a caller raised (a revision mismatch,
    # a recomputed claim set that does not match) was relabelled "database
    # unavailable", turning a 422 into a 503 and hiding the real cause.
    try:
        path = database_path()
    except (OSError, ValueError) as exc:
        raise DatabaseUnavailable("Prototype database is unavailable") from exc
    try:
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
    except DatabaseUnavailable:
        _rollback_quietly(connection, write)
        raise
    except (OSError, sqlite3.Error) as exc:
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
    """Every readable record, for the callers that need no skip report."""
    records, _ = list_records_with_report(include_restricted=include_restricted)
    return records


def list_records_with_report(
    *, include_restricted: bool = False
) -> tuple[list[Record], tuple[UnreadableRow, ...]]:
    """Read the corpus, skipping unreadable rows and reporting which were skipped.

    A list read needs many rows and no single one in particular, so one corrupt
    record must not make the whole corpus unreadable: the readable rows are
    returned and the skipped ones are named. ``list_records`` is the same read
    without the report, for callers that only serve the rows.

    Restricted rows are filtered before decoding, so a corrupt restricted row —
    which no caller could be shown anyway — is not reported to a caller that is
    not allowed to see it.
    """
    with connect() as db:
        rows = db.execute("SELECT * FROM records ORDER BY timestamp DESC, id").fetchall()
    records: list[Record] = []
    skipped: list[UnreadableRow] = []
    for row in rows:
        if not include_restricted and row["restricted"]:
            continue
        try:
            records.append(_record_from_row(row))
        except CorruptStoredRow as error:
            skipped.append(error.row)
    return records, tuple(skipped)


def get_record(record_id: str) -> Record | None:
    with connect() as db:
        row = db.execute("SELECT * FROM records WHERE id=? AND restricted=0", (record_id,)).fetchone()
    if row is None:
        return None
    return _record_from_row(row)


def _wall_clock() -> datetime:
    """Default write clock: the real UTC instant.

    Every row this module writes is stamped with an instant, and an evaluation
    run has to write its own frozen instant rather than the moment the row
    happened to be created. The clock is therefore a keyword-only argument with
    this wall clock as its default, so every existing caller keeps the previous
    behaviour unchanged.
    """
    return datetime.now(timezone.utc)


def _stamp(clock: Callable[[], datetime] | None) -> str:
    return (clock if clock is not None else _wall_clock)().isoformat()


def _record_from_row(row: sqlite3.Row) -> Record:
    """Decode one record row, naming it if it cannot be decoded.

    The column has to stay inspectable, so the tags are decoded before the model is
    built: a ``tags_json`` that is not a JSON array of strings is reported against
    that column rather than as an anonymous schema failure.
    """
    record_id = row["id"]
    try:
        tags = json.loads(row["tags_json"])
    except (TypeError, ValueError) as exc:
        raise _corrupt("records", record_id, "tags_json", "not valid JSON") from exc
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise _corrupt("records", record_id, "tags_json", "not a JSON array of strings")
    try:
        return Record(id=record_id, timestamp=row["timestamp"], department=row["department"],
                      text=row["text"], tags=tags,
                      restricted=bool(row["restricted"]), source_group=row["source_group"])
    except ValidationError as exc:
        raise _corrupt("records", record_id, _first_failing_field(exc, "timestamp"),
                       "value does not match the record schema") from exc


def create_record(
    *,
    text: str,
    department: str,
    tags: list[str],
    source_group: str | None = None,
    timestamp: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[Record, bool]:
    """Insert one non-restricted record, or return the identical one already stored.

    Identity is exact: the stored text (the caller normalises spacing before this
    call), the department and the source group. Lookup and insert share one
    ``BEGIN IMMEDIATE`` transaction, so two ingests arriving together cannot both
    insert and produce a silent duplicate.

    Restricted rows are never matched. They are not readable by the caller, so
    reusing one would leak its id and hand back a record the caller cannot
    fetch; the same content ingested as plain text becomes a new row.

    ``timestamp`` is the client's value when supplied; otherwise the row is
    stamped by ``clock`` through the same ``_stamp`` seam every other write in
    this module uses. Returns ``(record, created)``.
    """
    with connect(write=True) as db:
        row = db.execute(
            "SELECT * FROM records WHERE restricted=0 AND department=? AND text=? "
            "AND COALESCE(source_group,'')=? ORDER BY timestamp, id LIMIT 1",
            (department, text, source_group or ""),
        ).fetchone()
        if row is not None:
            return _record_from_row(row), False
        record_id = str(uuid4())
        stamp = timestamp.isoformat() if timestamp is not None else _stamp(clock)
        db.execute(
            "INSERT INTO records(id,timestamp,department,text,tags_json,restricted,source_group) "
            "VALUES(?,?,?,?,?,?,?)",
            (record_id, stamp, department, text, json.dumps(tags), 0, source_group),
        )
    return Record(id=record_id, timestamp=stamp, department=department, text=text,
                  tags=list(tags), restricted=False, source_group=source_group), True


def create_investigation(
    question: str, claims: list[dict], *, clock: Callable[[], datetime] | None = None
) -> dict:
    investigation_id = str(uuid4())
    now = _stamp(clock)
    with connect(write=True) as db:
        db.execute("INSERT INTO investigations VALUES(?,?,?,1)", (investigation_id, question, now))
        for claim in claims:
            _save_claim(db, investigation_id, claim)
        event = {"version": 1, "created_at": now, "event": "CREATED", "recomputed_claim_ids": [c["id"] for c in claims]}
        db.execute("INSERT INTO history(investigation_id,version,created_at,event_json) VALUES(?,?,?,?)", (investigation_id, 1, now, json.dumps(event)))
    return {"id": investigation_id, "question": question, "created_at": now, "version": 1, "claims": claims}


def _save_claim(db: sqlite3.Connection, investigation_id: str, claim: dict) -> None:
    db.execute("INSERT INTO claim_versions VALUES(?,?,?,?,?,?)", (investigation_id, claim["id"], claim["version"], claim["hypothesis_id"], json.dumps(claim), json.dumps(claim["dependencies"])))


def _decode_claim(claim_id: str, raw: object) -> dict:
    """Decode one stored claim, or name the row that cannot be decoded.

    The contract checked here is this table's, not the HTTP response schema's: a
    stored claim must be a JSON object whose ``id`` matches its row key and which
    carries the fields every reader in this module dereferences — ``version``,
    ``hypothesis_id`` and ``dependencies``. Checking the row's own contract is what
    keeps a hand-written store caller (and the store's own tests, which persist
    minimal claims) working, while still turning a truncated or overwritten row
    into a named failure instead of an exception deep inside a comprehension.

    The stored dictionary is returned unchanged: a read never rewrites what was
    written.
    """
    try:
        value = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
    except (TypeError, ValueError) as exc:
        raise _corrupt("claim_versions", claim_id, "claim_json", "not valid JSON") from exc
    if not isinstance(value, dict):
        raise _corrupt("claim_versions", claim_id, "claim_json", "not a JSON object")
    if value.get("id") != claim_id:
        raise _corrupt("claim_versions", claim_id, "claim_json",
                       "stored claim id does not match its row key")
    missing = [name for name in ("version", "hypothesis_id", "dependencies")
               if name not in value]
    if missing:
        raise _corrupt("claim_versions", claim_id, "claim_json",
                       f"claim JSON is missing required fields: {', '.join(missing)}")
    if not isinstance(value["version"], int) or isinstance(value["version"], bool):
        raise _corrupt("claim_versions", claim_id, "claim_json", "version is not an integer")
    if not isinstance(value["hypothesis_id"], str) or not value["hypothesis_id"]:
        raise _corrupt("claim_versions", claim_id, "claim_json", "hypothesis_id is not a string")
    dependencies = value["dependencies"]
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        raise _corrupt("claim_versions", claim_id, "claim_json",
                       "dependencies is not a JSON array of record ids")
    return value


def _latest_claims(db: sqlite3.Connection, investigation_id: str) -> dict[str, dict]:
    rows = db.execute("""SELECT cv.claim_id, cv.claim_json FROM claim_versions cv JOIN
        (SELECT claim_id,MAX(version) version FROM claim_versions WHERE investigation_id=? GROUP BY claim_id) latest
        ON cv.claim_id=latest.claim_id AND cv.version=latest.version WHERE cv.investigation_id=?""",
        (investigation_id, investigation_id)).fetchall()
    return {row["claim_id"]: _decode_claim(row["claim_id"], row["claim_json"]) for row in rows}


def _validated_investigation(investigation: sqlite3.Row) -> dict:
    """Decode one investigation row, naming it on the column that fails."""
    investigation_id = investigation["id"]
    try:
        datetime.fromisoformat(investigation["created_at"])
    except (TypeError, ValueError) as exc:
        raise _corrupt("investigations", investigation_id, "created_at",
                       "not an ISO-8601 instant") from exc
    try:
        version = int(investigation["version"])
    except (TypeError, ValueError) as exc:
        raise _corrupt("investigations", investigation_id, "version",
                       "not an integer revision") from exc
    return {"id": investigation_id, "question": investigation["question"],
            "created_at": investigation["created_at"], "version": version}


def get_investigation(investigation_id: str) -> dict | None:
    with connect() as db:
        investigation = db.execute("SELECT * FROM investigations WHERE id=?", (investigation_id,)).fetchone()
        if investigation is None:
            return None
        decoded = _validated_investigation(investigation)
        rows = db.execute("""SELECT cv.claim_id, cv.claim_json FROM claim_versions cv
            JOIN (SELECT claim_id,MAX(version) version FROM claim_versions
                 WHERE investigation_id=? GROUP BY claim_id) latest
            ON cv.claim_id=latest.claim_id AND cv.version=latest.version
            WHERE cv.investigation_id=? ORDER BY cv.claim_id""", (investigation_id, investigation_id)).fetchall()
    return dict(decoded, claims=[_decode_claim(row["claim_id"], row["claim_json"]) for row in rows])


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
    # One notion of "affected": the transitively dependent claims come from
    # `dependency_graph`, and the challenged claim itself is always included. Keeping
    # the comprehension here would be a second definition that could drift from the
    # module the evaluator checks against.
    affected = {claim_id} | set(transitive_dependents(current, record_id))
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
    clock: Callable[[], datetime] | None = None,
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
        now = _stamp(clock)
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
        rows = db.execute("SELECT version, event_json FROM history WHERE investigation_id=? ORDER BY version", (investigation_id,)).fetchall()
    events: list[dict] = []
    for row in rows:
        row_id = f"{investigation_id}@{row['version']}"
        try:
            event = json.loads(row["event_json"])
        except (TypeError, ValueError) as exc:
            raise _corrupt("history", row_id, "event_json", "not valid JSON") from exc
        if not isinstance(event, dict):
            raise _corrupt("history", row_id, "event_json", "not a JSON object")
        events.append(event)
    return events


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["init"]:
        raise SystemExit("Usage: python -m app.store init")
    print(f"Initialized local synthetic database: {initialize_database()}")

