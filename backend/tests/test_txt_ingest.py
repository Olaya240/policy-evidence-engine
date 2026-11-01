"""Tests for Bounded TXT Document Ingestion (Phase 23.1)."""
import asyncio
import gc
import hashlib
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from app import main as main_module, store
from app.engine import AssessmentEngine, AssessmentError, _validate_assessment_with_time, summarize_status
from app.ingest import (MAX_CHUNK_CHARS, MAX_CHUNKS, MAX_FILE_BYTES,
                        IngestError, chunk_text, compute_document_identity,
                        read_bounded_stream, sanitize_filename, validate_raw_document)
from app.main import app
from app.models import Evidence, EvidenceReviewState, Record, Stance, Status


class InProcessClient:
    """Synchronous test client over HTTPX ASGITransport."""

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
def disposable_db(monkeypatch):
    """Provide an isolated, disposable prototype SQLite database."""
    db_path = store.DATA_DIR / f".test-ingest-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    try:
        store.initialize_database()
        with InProcessClient(app) as test_client:
            yield test_client, db_path
    finally:
        _remove_sqlite_files(db_path)


def test_sanitize_filename():
    assert sanitize_filename("handover.txt") == "handover.txt"
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("..\\..\\windows\\notes.txt") == "notes.txt"
    assert sanitize_filename("report (front office) - final.txt") == "report (front office) - final.txt"
    assert sanitize_filename("   ") == "document.txt"
    assert sanitize_filename("") == "document.txt"

    with pytest.raises(IngestError) as exc_pdf:
        sanitize_filename("document.pdf")
    assert exc_pdf.value.code == "unsupported_extension"

    with pytest.raises(IngestError) as exc_bin:
        sanitize_filename("document.exe")
    assert exc_bin.value.code == "unsupported_extension"


def test_validate_raw_document():
    # Valid
    text, filename = validate_raw_document(b"Valid content.", "shift.txt")
    assert text == "Valid content."
    assert filename == "shift.txt"

    # Oversized
    with pytest.raises(IngestError) as exc_oversized:
        validate_raw_document(b"x" * (MAX_FILE_BYTES + 1), "big.txt")
    assert exc_oversized.value.code == "oversized_file"

    # PDF header
    with pytest.raises(IngestError) as exc_pdf:
        validate_raw_document(b"%PDF-1.4 binary data", "doc.txt")
    assert exc_pdf.value.code == "unsupported_format"

    # Binary null byte
    with pytest.raises(IngestError) as exc_null:
        validate_raw_document(b"hello\x00world", "doc.txt")
    assert exc_null.value.code == "binary_file_detected"

    # Invalid UTF-8
    with pytest.raises(IngestError) as exc_utf8:
        validate_raw_document(b"hello \xff\xfe world", "doc.txt")
    assert exc_utf8.value.code == "malformed_utf8"

    # Empty
    with pytest.raises(IngestError) as exc_empty:
        validate_raw_document(b"   \r\n\t  ", "doc.txt")
    assert exc_empty.value.code == "empty_document"


def test_chunking_deterministic_and_safe():
    p1 = "First paragraph about morning shift handover."
    p2 = "Second paragraph noting digital checklist opened normally."
    content = f"{p1}\n\n{p2}"

    chunks = chunk_text(content, max_chunk_chars=500, max_chunks=10)
    assert len(chunks) == 1
    assert p1 in chunks[0]
    assert p2 in chunks[0]

    # Multiple chunks when exceeding chunk size per paragraph
    chunks_split = chunk_text(content, max_chunk_chars=60, max_chunks=10)
    assert len(chunks_split) == 2
    assert p1 == chunks_split[0]
    assert p2 == chunks_split[1]

    # Oversized unbroken token handles safely without dropping characters
    huge_word = "A" * 150
    chunks_huge = chunk_text(huge_word, max_chunk_chars=100, max_chunks=10)
    assert len(chunks_huge) == 2
    assert chunks_huge[0] == "A" * 100
    assert chunks_huge[1] == "A" * 50


def test_valid_json_ingest(disposable_db):
    client, _ = disposable_db
    payload = {
        "filename": "night_handover.txt",
        "text": "Night checklist binder was missing from the desk.\n\nColleague wrote note on room 412.",
        "department": "Front Office",
    }
    res = client.post("/api/records/ingest", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["duplicate"] is False
    assert data["filename"] == "night_handover.txt"
    assert data["department"] == "Front Office"
    assert data["chunk_count"] >= 1
    assert data["document_id"].startswith("DOC-")

    # Verify records in database
    records_res = client.get("/api/records")
    assert records_res.status_code == 200
    records = records_res.json()
    ingested_record = next((r for r in records if r["id"] == data["records"][0]["id"]), None)
    assert ingested_record is not None
    assert ingested_record["source_group"] == data["document_id"]
    assert "Night checklist binder was missing" in ingested_record["text"]


def test_valid_text_plain_ingest(disposable_db):
    client, _ = disposable_db
    raw_text = "Afternoon handover briefing completed on time."
    res = client.post(
        "/api/records/ingest?filename=afternoon.txt&department=Housekeeping",
        content=raw_text.encode("utf-8"),
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["duplicate"] is False
    assert data["filename"] == "afternoon.txt"
    assert data["department"] == "Housekeeping"
    assert len(data["records"]) == 1
    assert data["records"][0]["source_group"] == data["document_id"]


def test_invalid_utf8_rejection(disposable_db):
    client, _ = disposable_db
    res = client.post(
        "/api/records/ingest",
        content=b"invalid \xff\xfe utf8",
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 422
    assert "UTF-8" in res.json()["detail"]


def test_empty_document_rejection(disposable_db):
    client, _ = disposable_db
    res = client.post(
        "/api/records/ingest",
        content=b"   \n\t  ",
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 422
    assert "empty" in res.json()["detail"].lower()


def test_oversized_upload_rejection(disposable_db):
    client, _ = disposable_db
    res = client.post(
        "/api/records/ingest",
        content=b"x" * (MAX_FILE_BYTES + 10),
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 413
    assert "limit" in res.json()["detail"].lower()


def test_pdf_media_type_rejection(disposable_db):
    client, _ = disposable_db
    res = client.post(
        "/api/records/ingest",
        content=b"%PDF-1.4 test",
        headers={"content-type": "application/pdf"},
    )
    assert res.status_code == 415


def test_pdf_content_rejection(disposable_db):
    client, _ = disposable_db
    res = client.post(
        "/api/records/ingest",
        content=b"%PDF-1.4 test",
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 422
    assert "PDF" in res.json()["detail"]


def test_unsafe_filename_in_json(disposable_db):
    client, _ = disposable_db
    # Traversal in filename is sanitized to basename
    payload = {
        "filename": "../../windows/system32/cmd.txt",
        "text": "Clean handover content.",
        "department": "Front Office",
    }
    res = client.post("/api/records/ingest", json=payload)
    assert res.status_code == 201
    assert res.json()["filename"] == "cmd.txt"

    # Non-txt is rejected
    payload_pdf = {
        "filename": "malicious.pdf",
        "text": "Some text content.",
        "department": "Front Office",
    }
    res_pdf = client.post("/api/records/ingest", json=payload_pdf)
    assert res_pdf.status_code == 422


def test_duplicate_document_idempotency(disposable_db):
    client, _ = disposable_db
    payload = {
        "filename": "duplicate_check.txt",
        "text": "Idempotent text record for duplicate testing.",
        "department": "Front Office",
    }
    res1 = client.post("/api/records/ingest", json=payload)
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["duplicate"] is False

    # Second ingest of identical content
    res2 = client.post("/api/records/ingest", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["duplicate"] is True
    assert data2["document_id"] == data1["document_id"]
    assert data2["sha256"] == data1["sha256"]
    assert len(data2["records"]) == len(data1["records"])
    assert data2["records"][0]["id"] == data1["records"][0]["id"]


def test_atomic_rollback_on_failure(disposable_db):
    _, db_path = disposable_db
    # Two records with identical ID will trigger SQLite PRIMARY KEY IntegrityError on the 2nd insert
    records = [
        Record(
            id="DOC-FAIL-COLLISION",
            timestamp="2026-11-01T10:00:00Z",
            department="Front Office",
            text="chunk 1",
            tags=[],
            source_group="DOC-FAIL",
        ),
        Record(
            id="DOC-FAIL-COLLISION",
            timestamp="2026-11-01T10:00:00Z",
            department="Front Office",
            text="chunk 2 duplicate id",
            tags=[],
            source_group="DOC-FAIL",
        ),
    ]

    with pytest.raises(store.DatabaseUnavailable):
        store.ingest_document("DOC-FAIL", "hash-fail", "fail.txt", "Front Office", 100, records)

    # Verify atomic rollback: neither document nor records persisted
    with store.connect() as db:
        doc = db.execute("SELECT * FROM documents WHERE id='DOC-FAIL'").fetchone()
        assert doc is None
        rec = db.execute("SELECT * FROM records WHERE source_group='DOC-FAIL'").fetchall()
        assert len(rec) == 0


def test_chunks_do_not_inflate_independent_support(disposable_db):
    """Verify that multiple supporting chunks from the same document do NOT inflate confidence."""
    client, _ = disposable_db
    p1 = "Shift A: night checklist binder was missing from the desk."
    p2 = "Shift B: printed checklist was unavailable on both desk terminals."
    payload = {
        "filename": "two_shifts.txt",
        "text": f"{p1}\n\n{p2}",
        "department": "Front Office",
    }
    # Force max_chunk_chars small enough to create 2 distinct chunks
    with patch("app.main.MAX_CHUNK_CHARS", 80):
        res = client.post("/api/records/ingest", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert len(data["records"]) == 2
    rec1 = data["records"][0]
    rec2 = data["records"][1]
    assert rec1["source_group"] == data["document_id"]
    assert rec2["source_group"] == data["document_id"]

    # Build evidence from both chunks supporting CHECKLIST_UNAVAILABLE
    ev1 = Evidence(
        source_record_id=rec1["id"],
        timestamp="2026-11-01T10:00:00Z",
        quote=p1,
        stance=Stance.SUPPORTS,
        review_state=EvidenceReviewState.ACCEPTED,
        rationale="first chunk support",
        department="Front Office",
        source_group=rec1["source_group"],
    )
    ev2 = Evidence(
        source_record_id=rec2["id"],
        timestamp="2026-11-01T10:00:00Z",
        quote=p2,
        stance=Stance.SUPPORTS,
        review_state=EvidenceReviewState.ACCEPTED,
        rationale="second chunk support",
        department="Front Office",
        source_group=rec2["source_group"],
    )

    status, confidence, uncertainty, conflicts, missing = summarize_status([ev1, ev2])

    # Status must be PARTIAL (0.55), NOT SUPPORTED (0.68 or 0.78), because both chunks
    # share the same source_group and thus count as only 1 independent support unit!
    assert status == Status.PARTIAL
    assert confidence == 0.55
    assert "single fresh source" in uncertainty.lower()


def test_quote_and_semantic_validation_on_ingested_records(disposable_db):
    client, _ = disposable_db
    text_content = "During night shift, night checklist binder was missing from the desk."
    res = client.post(
        "/api/records/ingest",
        json={"filename": "notes.txt", "text": text_content, "department": "Front Office"},
    )
    assert res.status_code == 201
    record_id = res.json()["records"][0]["id"]

    records_dict = {record_id: store.get_record(record_id)}

    # Valid exact quote passes
    raw_valid = {
        "source_record_id": record_id,
        "quote": "night checklist binder was missing",
        "stance": "SUPPORTS",
        "rationale": "Direct quote from ingested text",
    }
    evidence = _validate_assessment_with_time(raw_valid, records_dict)[0]
    assert evidence.quote == "night checklist binder was missing"
    assert evidence.source_group == res.json()["document_id"]

    # Inexact / invented quote fails
    raw_invalid = {
        "source_record_id": record_id,
        "quote": "binder was completely absent",
        "stance": "SUPPORTS",
        "rationale": "Hallucinated quote",
    }
    with pytest.raises(AssessmentError) as exc_quote:
        _validate_assessment_with_time(raw_invalid, records_dict)
    assert exc_quote.value.code == "invalid_quote"

    # Semantic Guard operates identically on ingested evidence
    engine = AssessmentEngine(semantic_guard=True)
    reviewed = engine._review_item(evidence, "CHECKLIST_UNAVAILABLE")
    assert reviewed.review_state == EvidenceReviewState.ACCEPTED


def test_existing_seed_records_remain_unchanged(disposable_db):
    client, _ = disposable_db
    res = client.get("/api/records")
    assert res.status_code == 200
    records = res.json()
    # 12 unrestricted seed records exist originally
    assert len(records) == 12
    assert any(r["id"] == "OPS-101" for r in records)


def test_protected_database_remains_untouched():
    """Verify that the designated protected database path was never opened or modified."""
    protected_path = store.DATA_DIR / store.PROTECTED_DATABASE_NAME
    with pytest.raises(ValueError) as exc:
        store.validate_database_path(protected_path)
    assert "protected local database" in str(exc.value)


def test_empty_document_rejection_json(disposable_db):
    client, _ = disposable_db
    res = client.post(
        "/api/records/ingest",
        json={"filename": "empty.txt", "text": "   \n\t  ", "department": "Front Office"},
    )
    assert res.status_code == 422
    assert "empty" in res.json()["detail"].lower()


def test_unsupported_extensions_rejection(disposable_db):
    client, _ = disposable_db
    for ext in ("notes.doc", "notes.docx", "script.sh", "archive.zip", "data.bin"):
        res = client.post(
            "/api/records/ingest",
            json={"filename": ext, "text": "Some text content.", "department": "Front Office"},
        )
        assert res.status_code == 422
        assert "txt" in res.json()["detail"].lower()

    # Query param unsupported extension in text/plain
    res_qp = client.post(
        "/api/records/ingest?filename=audit.pdf",
        content=b"Some valid plain text content.",
        headers={"content-type": "text/plain"},
    )
    assert res_qp.status_code == 422


def test_malformed_json_rejection(disposable_db):
    client, _ = disposable_db
    # Malformed JSON syntax
    res_syntax = client.post(
        "/api/records/ingest",
        content=b"{invalid json syntax",
        headers={"content-type": "application/json"},
    )
    assert res_syntax.status_code == 400
    assert "Invalid JSON" in res_syntax.json()["detail"]

    # Non-object JSON
    res_array = client.post(
        "/api/records/ingest",
        content=b'["an", "array"]',
        headers={"content-type": "application/json"},
    )
    assert res_array.status_code == 422

    # Extra forbidden field (ConfigDict(extra="forbid"))
    res_extra = client.post(
        "/api/records/ingest",
        json={"filename": "doc.txt", "text": "Valid text.", "forbidden_extra_field": 123},
    )
    assert res_extra.status_code == 422

    # Unsupported Media-Type
    res_media = client.post(
        "/api/records/ingest",
        content=b"<xml>not accepted</xml>",
        headers={"content-type": "application/xml"},
    )
    assert res_media.status_code == 415


def test_oversized_content_length_header(disposable_db):
    client, _ = disposable_db
    res = client.post(
        "/api/records/ingest",
        content=b"small content",
        headers={
            "content-type": "text/plain",
            "content-length": str(MAX_FILE_BYTES + 5000),
        },
    )
    assert res.status_code == 413
    assert "limit" in res.json()["detail"].lower()


def test_path_traversal_in_query_param(disposable_db):
    client, _ = disposable_db
    res = client.post(
        "/api/records/ingest?filename=../../../../etc/shadow.txt",
        content=b"Legitimate text payload from handover shift.",
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 201
    assert res.json()["filename"] == "shadow.txt"


def test_null_byte_in_filename_rejected(disposable_db):
    client, _ = disposable_db
    res = client.post(
        "/api/records/ingest",
        json={"filename": "doc\x00test.txt", "text": "Valid text.", "department": "Front Office"},
    )
    assert res.status_code == 422
    assert "null byte" in res.json()["detail"].lower()


def test_utf8_bom_stripped_safely(disposable_db):
    client, _ = disposable_db
    bom_bytes = b"\xef\xbb\xbfFirst word in morning shift handover."
    res = client.post(
        "/api/records/ingest?filename=bom_test.txt",
        content=bom_bytes,
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 201
    record = res.json()["records"][0]
    # BOM should be stripped from text
    assert record["text"].startswith("First word")
    assert not record["text"].startswith("\ufeff")


def test_ingested_records_used_in_live_investigation(disposable_db):
    client, _ = disposable_db
    # 1. Ingest a document containing relevant evidence
    ingest_payload = {
        "filename": "shift_investigation_log.txt",
        "text": "Night checklist binder was missing from the desk during handover inspection.",
        "department": "Front Office",
    }
    ingest_res = client.post("/api/records/ingest", json=ingest_payload)
    assert ingest_res.status_code == 201
    ingest_data = ingest_res.json()
    ingested_record_id = ingest_data["records"][0]["id"]

    # 2. Verify record is retrievable via GET /api/records
    records_res = client.get("/api/records")
    assert records_res.status_code == 200
    all_records = records_res.json()
    assert any(r["id"] == ingested_record_id for r in all_records)

    # 3. Create an investigation
    inv_payload = {
        "question": "Did checklist availability contribute to missing handover information?",
        "preset_id": "checklist_access",
    }
    inv_res = client.post("/api/investigations", json=inv_payload)
    assert inv_res.status_code == 201
    inv_data = inv_res.json()
    inv_id = inv_data["id"]
    assert "claims" in inv_data
    claim = next((c for c in inv_data["claims"] if c["id"] == "CHECKLIST_UNAVAILABLE"), None)
    assert claim is not None
    # Ingested record must be evaluated as part of investigation dependencies
    assert ingested_record_id in claim["dependencies"]

    # 4. Challenge a claim using the ingested record with exact quote
    challenge_payload = {
        "source_record_id": ingested_record_id,
        "quote": "Night checklist binder was missing",
        "reason": "Challenging the ingested night shift report binder finding.",
    }
    chal_res = client.post(
        f"/api/investigations/{inv_id}/claims/CHECKLIST_UNAVAILABLE/challenge",
        json=challenge_payload,
    )
    assert chal_res.status_code == 200
    chal_data = chal_res.json()
    assert chal_data["version"] >= 2
    assert "CHECKLIST_UNAVAILABLE" in chal_data["recomputed_claim_ids"]

    # 5. Challenge with inexact quote fails with 422
    bad_challenge = {
        "source_record_id": ingested_record_id,
        "quote": "completely fabricated non-existent text",
        "reason": "Invalid quote challenge attempt.",
    }
    bad_res = client.post(
        f"/api/investigations/{inv_id}/claims/CHECKLIST_UNAVAILABLE/challenge",
        json=bad_challenge,
    )
    assert bad_res.status_code == 422
    assert "exact source substring" in bad_res.json()["detail"].lower()


def test_errors_do_not_leak_internal_paths_or_secrets(disposable_db):
    client, _ = disposable_db
    # Test 400
    r400 = client.post("/api/records/ingest", content=b"{bad", headers={"content-type": "application/json"})
    assert r400.status_code == 400
    assert "hackathon" not in r400.text.lower()
    assert "\\" not in r400.text

    # Test 422
    r422 = client.post("/api/records/ingest", json={"filename": "bad.pdf", "text": "content"})
    assert r422.status_code == 422
    assert "hackathon" not in r422.text.lower()
    assert "\\" not in r422.text


def test_read_bounded_stream_stops_immediately_on_overflow():
    """Unit test: bounded stream reader stops reading chunks as soon as limit is exceeded."""
    chunks_yielded = 0

    async def gen():
        nonlocal chunks_yielded
        for _ in range(10):
            chunks_yielded += 1
            yield b"x" * 200

    async def run_test():
        # Limit = 350 bytes; should abort on chunk 2 (400 bytes) without reading chunks 3-10
        with pytest.raises(IngestError) as exc:
            await read_bounded_stream(gen(), max_bytes=350)
        assert exc.value.code == "oversized_file"
        assert chunks_yielded == 2, f"Expected 2 chunks yielded before abort, got {chunks_yielded}"

    asyncio.run(run_test())


def test_streaming_chunked_valid_body(disposable_db):
    """Chunked transfer encoding without Content-Length header is accepted if within 1 MB."""
    client, _ = disposable_db

    async def chunk_generator():
        yield b"Morning shift handover notes.\n\n"
        yield b"All digital checklists completed without error."

    res = client.post(
        "/api/records/ingest?filename=chunked_ok.txt",
        content=chunk_generator(),
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["filename"] == "chunked_ok.txt"
    assert len(data["records"]) >= 1


def test_streaming_oversized_without_content_length(disposable_db):
    """Chunked request with no Content-Length header that exceeds 1 MB aborts during streaming."""
    client, _ = disposable_db

    # 40 chunks of 30,000 bytes = 1.2 MB (> 1 MB limit)
    async def big_chunk_generator():
        for _ in range(40):
            yield b"x" * 30000

    res = client.post(
        "/api/records/ingest?filename=big_chunked.txt",
        content=big_chunk_generator(),
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 413
    assert "limit" in res.json()["detail"].lower()


def test_streaming_oversized_with_misleading_small_content_length(disposable_db):
    """Request with misleading small Content-Length header but oversized stream aborts with 413."""
    client, _ = disposable_db

    async def big_chunk_generator():
        for _ in range(40):
            yield b"x" * 30000

    res = client.post(
        "/api/records/ingest?filename=misleading_len.txt",
        content=big_chunk_generator(),
        headers={
            "content-type": "text/plain",
            "content-length": "100",  # Misleadingly small header
        },
    )
    assert res.status_code == 413
    assert "limit" in res.json()["detail"].lower()


def test_oversized_rejection_leaves_no_database_records(disposable_db):
    """Verify that an oversized streaming request creates no rows in documents or records."""
    client, db_path = disposable_db

    async def big_chunk_generator():
        for _ in range(40):
            yield b"x" * 30000

    res = client.post(
        "/api/records/ingest?filename=no_leak.txt",
        content=big_chunk_generator(),
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 413

    # Check database: 0 ingested documents and seed records only
    with store.connect() as db:
        docs = db.execute("SELECT * FROM documents").fetchall()
        assert len(docs) == 0
        ingested_records = db.execute("SELECT * FROM records WHERE source_group LIKE 'DOC-%'").fetchall()
        assert len(ingested_records) == 0
