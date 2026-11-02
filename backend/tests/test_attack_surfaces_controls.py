"""Eleventh probe batch: localised read corruption, and the control-character boundary.

Two gaps, both measured on the running API before this file existed.

**Gap A — one unreadable row used to fail the endpoint wholesale.** Setting a
`claim_versions.claim_json` to `{"id": "x", `, `not json at all`, `[]` or `` made
*every* investigation read answer 500, and a `records.timestamp` of
`yesterday-ish` made `GET /api/records` and `POST /api/investigations` answer 500.
The bad row was not named anywhere a caller could act on.

The contract these tests hold the store to:

- A read that needs one specific row (an investigation, its history, a challenge
  snapshot, one record) **fails closed** with `store.CorruptStoredRow` naming the
  table, the row id and the column. Through HTTP that is the existing bounded
  `DatabaseUnavailable` answer — 503, one fixed sentence, no traceback, no SQLite
  or stored text in the body.
- A read that needs many rows (`GET /api/records`, and every write path that
  assesses the corpus) **degrades**: the unreadable rows are skipped, the readable
  ones are still served, and the skip is reported through
  `store.list_records_with_report()` rather than swallowed.
- A healthy investigation created after the corruption is unaffected — the failure
  is localised to the row that is actually bad.

**Gap B — control characters were accepted.** A NUL byte and other C0/C1 controls
survived into stored record text, challenge quotes and questions. They are now
refused at the schema boundary with a 422 that names the character class
(`Cc` + code point). The positive controls in this file exist so the rule cannot
quietly become "no non-ASCII": NFC, NFD, combining marks, RTL marks, U+2028 /
U+2029, emoji and ZWJ sequences must keep working.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app import store
from app.main import app
from app.models import ChallengeCreate

QUESTION = "Why was the checklist unavailable during handover?"


def call(method: str, path: str, *, json_body=None):
    async def send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json_body)

    return asyncio.run(send())


@pytest.fixture()
def db(monkeypatch):
    path = store.DATA_DIR / f".controls-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()
    return path


def _write(db_path, statement: str, parameters: tuple) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(statement, parameters)
        connection.commit()
    finally:
        connection.close()


def _new_investigation() -> dict:
    response = call("POST", "/api/investigations", json_body={"question": QUESTION})
    assert response.status_code == 201, response.status_code
    return response.json()


def _assert_bounded_failure(response) -> None:
    """503 with one fixed sentence: no traceback, no SQL, no stored content."""
    assert response.status_code == 503, response.status_code
    body = response.json()
    assert set(body) == {"detail"}, body
    assert isinstance(body["detail"], str)
    assert len(body["detail"]) <= 200, body["detail"]
    text = response.text
    for leak in ("Traceback", "sqlite3", "claim_versions", "claim_json", "not json"):
        assert leak not in text, leak


# ---------------------------------------------------------------------------
# Gap A: a corrupt claim row is named, and only that investigation suffers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "corrupt", ['{"id": "x", ', "not json at all", "[]", "", "null", '"a string"']
)
def test_a_corrupt_claim_row_is_named_and_isolated(db, corrupt):
    first = _new_investigation()
    investigation_id = first["id"]
    claim_id = first["claims"][0]["id"]

    _write(
        db,
        "UPDATE claim_versions SET claim_json=? WHERE investigation_id=? AND claim_id=?",
        (corrupt, investigation_id, claim_id),
    )

    response = call("GET", f"/api/investigations/{investigation_id}")
    _assert_bounded_failure(response)

    # The failure is bounded for the client, and specific for the operator: the
    # error names the table and the row that has to be repaired.
    with pytest.raises(store.CorruptStoredRow) as error:
        store.get_investigation(investigation_id)
    assert isinstance(error.value, store.DatabaseUnavailable)
    assert error.value.table == "claim_versions"
    assert error.value.row_id == claim_id
    assert error.value.field == "claim_json"
    assert "claim_versions" in str(error.value)
    assert claim_id in str(error.value)

    # Localised, not contagious: a healthy investigation written after the
    # corruption is still created and still readable.
    second = _new_investigation()
    assert second["id"] != investigation_id
    healthy = call("GET", f"/api/investigations/{second['id']}")
    assert healthy.status_code == 200, healthy.status_code
    assert healthy.json()["claims"]


def test_a_claim_row_that_is_json_but_not_a_claim_is_named(db):
    created = _new_investigation()
    claim_id = created["claims"][0]["id"]

    _write(
        db,
        "UPDATE claim_versions SET claim_json=? WHERE investigation_id=? AND claim_id=?",
        (json.dumps({"id": claim_id, "version": 1}), created["id"], claim_id),
    )

    _assert_bounded_failure(call("GET", f"/api/investigations/{created['id']}"))
    with pytest.raises(store.CorruptStoredRow) as error:
        store.get_investigation(created["id"])
    assert error.value.table == "claim_versions"
    assert error.value.row_id == claim_id
    # The reason says which required field the row does not carry.
    assert "missing" in error.value.reason
    assert "dependencies" in error.value.reason


def test_a_claim_row_whose_id_disagrees_with_its_key_is_named(db):
    created = _new_investigation()
    claim = created["claims"][0]
    forged = dict(claim, id="SOMEONE-ELSE")

    _write(
        db,
        "UPDATE claim_versions SET claim_json=? WHERE investigation_id=? AND claim_id=?",
        (json.dumps(forged), created["id"], claim["id"]),
    )

    _assert_bounded_failure(call("GET", f"/api/investigations/{created['id']}"))
    with pytest.raises(store.CorruptStoredRow) as error:
        store.get_investigation(created["id"])
    assert error.value.row_id == claim["id"]
    assert "id" in error.value.reason


@pytest.mark.parametrize(
    "column,value,field",
    [
        ("timestamp", "yesterday-ish", "timestamp"),
        ("tags_json", "not json", "tags_json"),
        ("tags_json", '{"a": 1}', "tags_json"),
    ],
)
def test_an_unreadable_record_is_skipped_with_a_report_not_a_500(db, column, value, field):
    before = call("GET", "/api/records")
    assert before.status_code == 200, before.status_code
    healthy_ids = {record["id"] for record in before.json()}
    assert healthy_ids

    _write(
        db,
        "INSERT OR REPLACE INTO records(id,timestamp,department,text,tags_json,restricted,source_group)"
        " VALUES(?,?,?,?,?,?,?)",
        ("BAD-ROW", "2026-06-01T12:00:00+00:00", "Front Office",
         "The checklist binder was missing.", "[]", 0, "BAD-ROW"),
    )
    _write(db, f"UPDATE records SET {column}=? WHERE id=?", (value, "BAD-ROW"))

    # The list degrades instead of failing: every readable row is still served.
    after = call("GET", "/api/records")
    assert after.status_code == 200, after.status_code
    assert {record["id"] for record in after.json()} == healthy_ids
    assert "BAD-ROW" not in {record["id"] for record in after.json()}

    # ... and the skip is reported to the caller, not swallowed by the server log.
    assert after.headers["X-Unreadable-Rows"] == "1"
    assert after.headers["X-Unreadable-Row-Ids"] == "BAD-ROW"

    records, skipped = store.list_records_with_report()
    assert [row.row_id for row in skipped] == ["BAD-ROW"]
    assert skipped[0].table == "records"
    assert skipped[0].field == field
    assert {record.id for record in records} == healthy_ids

    # The write path no longer assesses a corpus it cannot fully read: a verdict is a
    # claim about the whole corpus, so a short corpus must not be turned into one. This
    # is a deliberate reversal of the earlier behaviour (201 over the readable rows),
    # because "skipped and reported" was only true in the server log.
    refused = call("POST", "/api/investigations", json_body={"question": QUESTION})
    assert refused.status_code == 503, refused.status_code
    assert "BAD-ROW" not in refused.text


def test_a_corrupt_history_row_is_named_and_leaves_other_history_readable(db):
    first = _new_investigation()
    _write(
        db,
        "UPDATE history SET event_json=? WHERE investigation_id=? AND version=?",
        ('{"version": 1, ', first["id"], 1),
    )

    _assert_bounded_failure(call("GET", f"/api/investigations/{first['id']}/history"))
    with pytest.raises(store.CorruptStoredRow) as error:
        store.get_history(first["id"])
    assert error.value.table == "history"
    assert error.value.row_id == f"{first['id']}@1"
    assert error.value.field == "event_json"

    second = _new_investigation()
    history = call("GET", f"/api/investigations/{second['id']}/history")
    assert history.status_code == 200, history.status_code
    assert history.json()


def test_a_challenge_against_a_corrupt_claim_row_is_a_bounded_503(db):
    created = _new_investigation()
    claim = created["claims"][0]
    record_id = claim["evidence"][0]["source_record_id"]
    record = store.get_record(record_id)
    assert record is not None
    quote = record.text[:60]

    _write(
        db,
        "UPDATE claim_versions SET claim_json=? WHERE investigation_id=? AND claim_id=?",
        ("not json at all", created["id"], claim["id"]),
    )

    response = call(
        "POST",
        f"/api/investigations/{created['id']}/claims/{claim['id']}/challenge",
        json_body={"source_record_id": record_id, "quote": quote, "reason": "corrupt row probe"},
    )
    _assert_bounded_failure(response)
    with pytest.raises(store.CorruptStoredRow) as error:
        store.get_challenge_snapshot(created["id"], claim["id"], record_id)
    assert error.value.row_id == claim["id"]


# ---------------------------------------------------------------------------
# Gap B: control characters are refused at the input boundary ...
# ---------------------------------------------------------------------------

CONTROL_CHARACTERS = ["\x00", "\x01", "\x07", "\x0b", "\x1b", "\x7f", "\x85", "\x9f"]


@pytest.mark.parametrize("control", CONTROL_CHARACTERS)
def test_control_characters_in_ingested_text_are_refused(db, control):
    text = f"The checklist binder{control} was missing at the handover."

    response = call("POST", "/api/records/ingest",
                    json_body={"text": text, "department": "Front Office"})

    assert response.status_code == 422, response.status_code
    detail = json.dumps(response.json())
    assert "control character" in detail, detail
    # The refusal names the class and the offending code point, so the caller can
    # find the byte without the server echoing the stored text back.
    assert f"U+{ord(control):04X}" in detail, detail
    assert "Cc" in detail, detail
    # Nothing was stored.
    assert text not in [record["text"] for record in call("GET", "/api/records").json()]


def test_a_nul_in_the_question_is_refused(db):
    response = call("POST", "/api/investigations",
                    json_body={"question": QUESTION + "\x00suffix"})

    assert response.status_code == 422, response.status_code
    detail = json.dumps(response.json())
    assert "control character" in detail, detail
    assert "U+0000" in detail, detail


def test_a_nul_in_a_challenge_quote_is_refused(db):
    response = call(
        "POST",
        "/api/investigations/any/claims/any/challenge",
        json_body={"reason": "control character probe", "source_record_id": "OPS-101",
                   "quote": "binder\x00 was missing"},
    )

    assert response.status_code == 422, response.status_code
    detail = json.dumps(response.json())
    assert "control character" in detail, detail
    assert "U+0000" in detail, detail


# ---------------------------------------------------------------------------
# ... and legitimate Unicode still works. Without these, the rule above could
# become "reject anything that is not ASCII" and every test would still pass.
# ---------------------------------------------------------------------------

LEGITIMATE_UNICODE = (
    "Réception 👋 Cafe\u0301  \u05e9\u05dc\u05d5\u05dd \u200f\u200e "
    "line\u2028separator\u2029family 👨\u200d👩\u200d👧\u200d👦"
)


def test_legitimate_unicode_is_still_accepted_by_ingest(db):
    response = call("POST", "/api/records/ingest",
                    json_body={"text": LEGITIMATE_UNICODE, "department": "Réception 👋",
                               "tags": ["Cafe\u0301", "👋"]})

    assert response.status_code == 201, response.text
    stored = response.json()["record"]
    assert stored["department"] == "Réception 👋"
    assert "👋" in stored["text"]
    assert {record["id"] for record in call("GET", "/api/records").json()} >= {stored["id"]}


def test_legitimate_unicode_is_still_accepted_and_kept_verbatim_by_a_question(db):
    question = "Did \u05e9\u05dc\u05d5\u05dd time pressure \u2028 affect Cafe\u0301 \u200f handover 👋?"

    response = call("POST", "/api/investigations", json_body={"question": question})

    assert response.status_code == 201, response.text
    assert response.json()["question"] == question


def test_legitimate_unicode_is_still_accepted_in_a_challenge_quote():
    quote = "Cafe\u0301 \u200f 👋\u2028\u2029"

    payload = ChallengeCreate(reason="Unicode quote probe for the boundary",
                              source_record_id="OPS-101", quote=quote)

    assert payload.quote == quote
    with pytest.raises(ValidationError) as error:
        ChallengeCreate(reason="Unicode quote probe for the boundary",
                        source_record_id="OPS-101", quote="Cafe\u0301 \x00 👋")
    assert "control character" in str(error.value)


def test_nfc_and_nfd_are_not_conflated_by_the_boundary(db):
    nfc = "Café au lait"
    nfd = "Cafe\u0301 au lait"
    assert nfc != nfd

    for text in (nfc, nfd):
        response = call("POST", "/api/records/ingest",
                        json_body={"text": text, "department": "Front Office"})
        assert response.status_code == 201, response.text

    stored = {record["text"] for record in call("GET", "/api/records").json()}
    assert {nfc, nfd} <= stored
