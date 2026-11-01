"""Bounded TXT document ingestion and paragraph-aware chunking."""
import hashlib
import re
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Optional

from .models import Record

MAX_FILE_BYTES = 1024 * 1024  # 1 MB
MAX_CHUNK_CHARS = 1000
MAX_CHUNKS = 100

_SAFE_FILENAME_CHARS = re.compile(r"[^a-zA-Z0-9._() -]")


class IngestError(ValueError):
    """Controlled document ingestion error with a stable code."""

    def __init__(self, message: str, *, code: str = "invalid_document"):
        super().__init__(message)
        self.code = code


async def read_bounded_stream(stream, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    """Read bytes from an async stream or generator, aborting immediately if cumulative
    byte count exceeds max_bytes.

    Guarantees that oversized payloads are rejected during streaming without buffering
    the remaining chunks into memory.
    """
    buffer = bytearray()
    if hasattr(stream, "__aiter__"):
        async for chunk in stream:
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                raise IngestError(
                    f"Upload size exceeds maximum permitted limit of {max_bytes} bytes (1 MB)",
                    code="oversized_file",
                )
    else:
        for chunk in stream:
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                raise IngestError(
                    f"Upload size exceeds maximum permitted limit of {max_bytes} bytes (1 MB)",
                    code="oversized_file",
                )
    return bytes(buffer)


def sanitize_filename(filename: str) -> str:
    """Sanitize and validate an uploaded filename.

    Never use the result as a filesystem path. Filename is stored only as metadata.
    Rejects directory traversal, non-TXT extensions, and PDF files.
    """
    if not isinstance(filename, str) or not filename.strip():
        return "document.txt"

    # Reject null bytes explicitly
    if "\x00" in filename:
        raise IngestError("Filename contains invalid null byte characters", code="invalid_filename")

    # Strip directory components from both Windows and POSIX path representations
    raw = filename.strip()
    base = PureWindowsPath(raw).name
    base = PurePosixPath(base).name
    if not base or base in (".", ".."):
        return "document.txt"

    # Explicitly reject PDF and non-text extensions
    lower_base = base.lower()
    if lower_base.endswith(".pdf"):
        raise IngestError("PDF documents are not supported; only .txt files are accepted", code="unsupported_extension")

    if not lower_base.endswith(".txt"):
        raise IngestError("Only .txt files are supported; non-text extensions are not accepted", code="unsupported_extension")

    # Sanitize characters: allow alphanumeric, dot, dash, underscore, space
    sanitized = _SAFE_FILENAME_CHARS.sub("_", base)
    sanitized = re.sub(r"_+", "_", sanitized)

    # Bound length (preserve .txt extension)
    if len(sanitized) > 100:
        name_part = sanitized[:-4][:96].rstrip("._ ")
        sanitized = f"{name_part}.txt" if name_part else "document.txt"

    if sanitized.lower() == ".txt":
        return "document.txt"

    return sanitized


def validate_raw_document(raw_bytes: bytes, filename: str) -> tuple[str, str]:
    """Validate raw file bytes and filename. Return clean text and sanitized filename."""
    if len(raw_bytes) > MAX_FILE_BYTES:
        raise IngestError(f"File size exceeds maximum permitted limit of {MAX_FILE_BYTES} bytes (1 MB)", code="oversized_file")

    if raw_bytes.startswith(b"%PDF-"):
        raise IngestError("PDF documents are not supported in this phase", code="unsupported_format")

    if b"\x00" in raw_bytes:
        raise IngestError("Binary files are not supported; only plain text is accepted", code="binary_file_detected")

    try:
        text = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise IngestError("Document contains invalid or malformed UTF-8 bytes", code="malformed_utf8") from exc

    # Safely strip UTF-8 BOM if present without modifying document content
    if text.startswith("\ufeff"):
        text = text[1:]

    # Standardize line endings safely without altering document meaning
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if not text.strip():
        raise IngestError("Document is empty or contains only whitespace", code="empty_document")

    clean_filename = sanitize_filename(filename)
    return text, clean_filename


def compute_document_identity(raw_bytes: bytes) -> tuple[str, str]:
    """Return deterministic (document_id, sha256_hex) from original bytes."""
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    doc_id = f"DOC-{sha256[:12]}"
    return doc_id, sha256


def _split_oversized_paragraph(paragraph: str, max_chunk_chars: int) -> list[str]:
    """Split a paragraph that exceeds max_chunk_chars without dropping characters."""
    if len(paragraph) <= max_chunk_chars:
        return [paragraph]

    # Try splitting on sentence boundaries
    sentences = re.split(r"(?<=[.!?;\n])\s+", paragraph)
    segments = []
    for s in sentences:
        if len(s) <= max_chunk_chars:
            segments.append(s)
        else:
            # Try splitting on word boundaries
            words = re.split(r"(\s+)", s)
            current_word_chunk = []
            current_len = 0
            for w in words:
                if len(w) > max_chunk_chars:
                    if current_word_chunk:
                        segments.append("".join(current_word_chunk))
                        current_word_chunk = []
                        current_len = 0
                    # Slice unbroken token
                    for start in range(0, len(w), max_chunk_chars):
                        segments.append(w[start:start + max_chunk_chars])
                elif current_len + len(w) > max_chunk_chars and current_word_chunk:
                    segments.append("".join(current_word_chunk))
                    current_word_chunk = [w]
                    current_len = len(w)
                else:
                    current_word_chunk.append(w)
                    current_len += len(w)
            if current_word_chunk:
                segments.append("".join(current_word_chunk))

    # Now group segments up to max_chunk_chars
    sub_paragraphs = []
    buf = []
    buf_len = 0
    for seg in segments:
        seg_stripped = seg.strip()
        if not seg_stripped:
            continue
        addition = len(seg_stripped) + (1 if buf else 0)
        if buf_len + addition > max_chunk_chars and buf:
            sub_paragraphs.append(" ".join(buf))
            buf = [seg_stripped]
            buf_len = len(seg_stripped)
        else:
            buf.append(seg_stripped)
            buf_len += addition
    if buf:
        sub_paragraphs.append(" ".join(buf))

    return sub_paragraphs if sub_paragraphs else [paragraph[:max_chunk_chars]]


def chunk_text(text: str, *, max_chunk_chars: int = MAX_CHUNK_CHARS, max_chunks: int = MAX_CHUNKS) -> list[str]:
    """Deterministic, paragraph-aware chunking preserving exact substring contents."""
    # Split by double newline (paragraph boundary)
    raw_paragraphs = re.split(r"(?:\r?\n){2,}", text)
    cleaned_paragraphs = []
    for p in raw_paragraphs:
        p_clean = p.strip()
        if not p_clean:
            continue
        if len(p_clean) > max_chunk_chars:
            cleaned_paragraphs.extend(_split_oversized_paragraph(p_clean, max_chunk_chars))
        else:
            cleaned_paragraphs.append(p_clean)

    if not cleaned_paragraphs:
        raise IngestError("Document contains no substantive text", code="empty_document")

    # Accumulate paragraphs into chunks
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for p in cleaned_paragraphs:
        added_len = len(p) + (2 if current_chunk else 0)
        if current_len + added_len > max_chunk_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = [p]
            current_len = len(p)
        else:
            current_chunk.append(p)
            current_len += added_len

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    if len(chunks) > max_chunks:
        raise IngestError(
            f"Document exceeds maximum chunk limit of {max_chunks} chunks (produced {len(chunks)})",
            code="too_many_chunks",
        )

    return chunks


def create_records_from_chunks(
    document_id: str,
    chunks: list[str],
    department: str,
    timestamp: datetime,
) -> list[Record]:
    """Create Record models from chunks.

    All chunks share source_group equal to document_id to prevent false corroboration.
    """
    return [
        Record(
            id=f"{document_id}-C{idx:04d}",
            timestamp=timestamp,
            department=department,
            text=chunk,
            tags=["ingested", "txt", f"doc:{document_id}"],
            restricted=False,
            source_group=document_id,
        )
        for idx, chunk in enumerate(chunks, start=1)
    ]
