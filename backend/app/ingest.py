"""Document ingestion MVP: one plain-text ingest path, and why it is this small.

The status entry said "not implemented". This module implements it as bounded
plain text over the existing ``records`` table, and the scope decision is written
down here so a later reader can tell a boundary from a gap:

- **No file upload, no PDF/DOCX extraction.** Each needs a parser dependency and
  an untrusted-binary threat model (decompression bombs, parser bugs) this
  prototype's trust model does not have. Text keeps every stored byte
  inspectable and quotable, which the challenge flow depends on: a challenge
  quote must be an exact substring of the stored text, so the stored form has to
  be the text the user submitted.
- **No new dependency and no configuration flag.** Stdlib plus the SQLite store
  already present; nothing here reads an environment variable.
- **No new table.** An ingested document *is* a ``Record``, so ``GET
  /api/records`` and a new investigation pick it up with no extra wiring.

Boundaries, each covered in ``tests/test_ingest.py``:

- ``restricted`` is absent from ``IngestCreate``; an attempt to set it is a 422.
- Duplicate content is not silently duplicated. The same normalised text,
  department and source group returns **200** with the record already stored
  (and ``created=False``) rather than 201 with a second row, or a 409. 200 was
  chosen over 409 because the caller needs the id for its next step, and a bare
  409 would force a lookup that can race with another ingest; the alternative is
  named here so the choice is not mistaken for an accident. Either way exactly
  one row exists.
- Text is bounded by ``INGEST_TEXT_MAX_CHARS`` at the schema boundary, so an
  oversized document is a 422 before SQLite is touched.
- A restricted record is never ingestible: it is not a dedupe target, so its id
  is never handed out, and no path lets a client create one.

Deliberately *not* done, because it is a later phase: chunking, embedding,
entity extraction, background processing, and provenance beyond the stored text.
Storing the text is what makes those possible.
"""
import re
from datetime import datetime, timezone
from typing import Callable, NamedTuple

from . import store
from .models import IngestCreate, Record

_WHITESPACE = re.compile(r"\s+")


def normalise_text(text: str) -> str:
    """Collapse whitespace runs so re-typed spacing does not create a new row."""
    return _WHITESPACE.sub(" ", text).strip()


def write_clock() -> datetime:
    """Default write clock, and the seam a test freezes.

    Ingestion must not read ``datetime.now()`` inline: a record's timestamp is
    evidence metadata, and an evaluation run has to write its own frozen
    instant. Callers may also inject a clock per call.
    """
    return datetime.now(timezone.utc)


class IngestOutcome(NamedTuple):
    record: Record
    created: bool


def ingest_text(
    payload: IngestCreate, *, clock: Callable[[], datetime] | None = None
) -> IngestOutcome:
    """Store one ingested document, or return the identical one already stored.

    The duplicate rule and the 200-vs-409 choice are stated in this module's
    docstring; ``created`` tells the caller which happened.
    """
    record, created = store.create_record(
        text=normalise_text(payload.text),
        department=payload.department,
        tags=list(payload.tags),
        source_group=payload.source_group,
        timestamp=payload.timestamp,
        clock=clock or write_clock,
    )
    return IngestOutcome(record=record, created=created)
