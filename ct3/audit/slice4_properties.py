"""Slice-4 property harness: strict proposal parsing and provenance checks.

Run from the worktree root:

    PYTHONPATH=backend python ct3/audit/slice4_properties.py

Every property prints PASS, FAIL or DIVERGENCE. A FAIL exits non-zero. A
DIVERGENCE is recorded but does not fail the run: it means the code and its
docstring disagree about behaviour, which is a finding for the ledger, not a
broken invariant.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app import provider_safety as ps
from app.models import Record

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HYPOTHESIS = "CHECKLIST_UNAVAILABLE"

FAILURES: list[tuple[str, str]] = []
DIVERGENCES: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append((name, detail))


def divergence(name: str, detail: str) -> None:
    print(f"DIVERGENCE  {name}  [{detail}]")
    DIVERGENCES.append((name, detail))


def record(rid: str, text: str) -> Record:
    return Record(id=rid, timestamp=NOW, department="Front Office", text=text, tags=[])


RECORDS = [
    record("REC-1", "The handover checklist was unavailable at shift change."),
    record("REC-2", "The binder was missing during the handover."),
]


def request():
    return ps.serialize_provider_request(list(RECORDS), HYPOTHESIS)


def proposal(source_id="REC-1", quote="handover checklist was unavailable", stance="SUPPORTS",
             rationale="quoted support"):
    return {"source_record_id": source_id, "quote": quote, "stance": stance, "rationale": rationale}


def body(value) -> bytes:
    return json.dumps(value).encode("utf-8")


def expect_code(name: str, payload, code: str) -> None:
    """Assert the parser raises the documented code for this payload."""
    try:
        ps.parse_provider_proposals(payload, request())
    except ps.ProviderSafetyError as exc:
        check(name, exc.code == code, f"expected {code}, got {exc.code}")
        return
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"unclassified {type(exc).__name__}: {exc}")
        return
    check(name, False, f"expected {code}, nothing raised")


# ---------------------------------------------------------------- 1. shape

def property_shape() -> None:
    print("\n== 1 shape ==")
    check("1 a valid array of proposals is accepted",
          ps.parse_provider_proposals(body([proposal()]), request()) == [proposal()])
    check("1 an empty array is accepted as no proposals",
          ps.parse_provider_proposals(b"[]", request()) == [])
    expect_code("1 a JSON object instead of an array", body({"proposals": []}), "malformed_output")
    expect_code("1 an array of non-objects", body([1, 2]), "malformed_output")
    expect_code("1 JSON null", b"null", "malformed_output")
    expect_code("1 a non-bytes body", "[]", "malformed_response")
    expect_code("1 invalid UTF-8", b"\xff\xfe", "malformed_response")
    expect_code("1 an empty body", b"", "malformed_response")


# ---------------------------------------------------------------- 2. keys

def property_keys() -> None:
    print("\n== 2 keys ==")
    missing = proposal()
    missing.pop("rationale")
    expect_code("2 a missing key", body([missing]), "malformed_output")

    extra = proposal()
    extra["confidence"] = 0.9
    expect_code("2 an extra key", body([extra]), "malformed_output")

    non_string = proposal()
    non_string["source_record_id"] = 1
    expect_code("2 a non-string record id", body([non_string]), "invalid_source")

    expect_code("2 a non-string quote", body([proposal(quote=5)]), "invalid_quote")

    # duplicate JSON keys cannot be built from a dict, so the raw text is used.
    duplicate = ('[{"source_record_id": "REC-1", "quote": "handover checklist was unavailable",'
                 ' "stance": "SUPPORTS", "rationale": "a", "rationale": "b"}]').encode()
    expect_code("2 a duplicate JSON key", duplicate, "malformed_response")


# ---------------------------------------------------------------- 3. vocabulary

def property_vocabulary() -> None:
    print("\n== 3 vocabulary ==")
    expect_code("3 a lowercase stance", body([proposal(stance="supports")]), "invalid_stance")
    expect_code("3 an unknown stance", body([proposal(stance="MAYBE")]), "invalid_stance")
    expect_code("3 a non-string stance", body([proposal(stance=None)]), "invalid_stance")
    for stance in ("SUPPORTS", "CONTRADICTS", "NEUTRAL"):
        try:
            ps.parse_provider_proposals(body([proposal(stance=stance)]), request())
            check(f"3 {stance} passes through", True)
        except ps.ProviderSafetyError as exc:
            check(f"3 {stance} passes through", False, exc.code)


# ---------------------------------------------------------------- 4. grounding

def property_grounding() -> None:
    print("\n== 4 grounding ==")
    expect_code("4 an id absent from the request", body([proposal(source_id="REC-9")]), "invalid_source")
    expect_code("4 a quote absent from the cited record", body([proposal(quote="not in the text")]),
                "invalid_quote")
    expect_code("4 a two-character quote", body([proposal(quote="ab")]), "invalid_quote")
    expect_code("4 a whitespace-only quote", body([proposal(quote="      ")]), "invalid_quote")

    cross = proposal(source_id="REC-2", quote="handover checklist was unavailable")
    expect_code("4 a quote from a different record", body([cross]), "invalid_quote")

    # A string present in both records must be accepted for either id: provenance
    # is per-record substring, not per-record exclusivity.
    shared_text = [record("A", "the same phrase appears here"), record("B", "the same phrase appears here")]
    shared_request = ps.serialize_provider_request(shared_text, HYPOTHESIS)
    shared = [{"source_record_id": "A", "quote": "the same phrase", "stance": "SUPPORTS",
               "rationale": "r"}]
    try:
        ps.parse_provider_proposals(body(shared), shared_request)
        print("PASS  4 a quote shared by two records is accepted for either")
    except ps.ProviderSafetyError as exc:  # pragma: no cover - reported, not asserted
        divergence("4 a quote shared by two records", f"refused with {exc.code}")


# ---------------------------------------------------------------- 5. size

def property_size() -> None:
    print("\n== 5 size ==")
    at_cap = [proposal() for _ in range(ps.MAX_PROPOSALS)]
    parsed = ps.parse_provider_proposals(body(at_cap), request())
    check(f"5 {ps.MAX_PROPOSALS} valid proposals are accepted", len(parsed) == ps.MAX_PROPOSALS)

    over_cap = [proposal() for _ in range(ps.MAX_PROPOSALS + 1)]
    expect_code("5 one past the cap is refused", body(over_cap), "malformed_output")

    huge = "x" * (100 * 1024)
    expect_code("5 a 100 KiB quote is refused by grounding, not by size",
                body([proposal(quote=huge)]), "invalid_quote")


# ---------------------------------------------------------------- 6. json strictness

def property_json_strictness() -> None:
    print("\n== 6 json strictness ==")
    expect_code("6 NaN", b'[{"source_record_id": "REC-1", "quote": "handover checklist was unavailable",'
                        b' "stance": "SUPPORTS", "rationale": NaN}]', "malformed_response")
    expect_code("6 Infinity", b'[{"source_record_id": "REC-1", "quote": "handover checklist was unavailable",'
                              b' "stance": "SUPPORTS", "rationale": Infinity}]', "malformed_response")
    expect_code("6 a trailing comma", b'[{"source_record_id": "REC-1", "quote": "handover checklist'
                                      b' was unavailable", "stance": "SUPPORTS", "rationale": "r"},]',
                "malformed_response")
    expect_code("6 a single-quoted string", b"[{'source_record_id': 'REC-1'}]", "malformed_response")


# ---------------------------------------------------------------- main

def main() -> int:
    print(f"slice 4: provider_safety parse_provider_proposals ({ps.__name__})")
    for function in (
        property_shape,
        property_keys,
        property_vocabulary,
        property_grounding,
        property_size,
        property_json_strictness,
    ):
        try:
            function()
        except Exception as exc:  # noqa: BLE001
            check(f"{function.__name__}: harness raised", False, f"{type(exc).__name__}: {exc}")

    print()
    if DIVERGENCES:
        print(f"{len(DIVERGENCES)} divergence(s) recorded for the ledger:")
        for name, detail in DIVERGENCES:
            print(f"  ~ {name}: {detail}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILED property check(s):")
        for name, detail in FAILURES:
            print(f"  - {name} [{detail}]")
        return 1
    print("all property checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
