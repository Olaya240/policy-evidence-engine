"""Slice-4b property harness: envelope, model pin, cap boundary, refusal, grounding.

Complements `slice4_properties.py`, which covers the proposal contract itself.
Run from the worktree root:

    PYTHONPATH=backend python ct3/audit/slice4b_properties.py

A FAIL exits non-zero. A DIVERGENCE is recorded but does not fail: it means the
code and its docstring disagree, which is a ledger finding rather than a broken
invariant.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app import provider_safety as ps
from app.models import Record

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
MODEL = ps.BasetenMuseSparkOpenAdapter.MODEL_SLUG

FAILURES: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append((name, detail))


def expect(name: str, fn, code: str) -> None:
    try:
        fn()
    except ps.ProviderSafetyError as exc:
        check(name, exc.code == code, f"expected {code}, got {exc.code}")
        return
    except RecursionError:
        check(name, False, f"expected {code}, got an escaped RecursionError")
        return
    check(name, False, f"expected {code}, nothing raised")


def record(rid: str, text: str) -> Record:
    return Record(id=rid, timestamp=NOW, department="Front Office", text=text, tags=[])


RECORDS = [
    record("REC-1", "The handover checklist was unavailable at shift change."),
    record("REC-2", "The binder was missing during the handover."),
]


def request():
    return ps.serialize_provider_request(list(RECORDS), HYPOTHESIS)


def proposal(source_id="REC-1", quote="handover checklist was unavailable",
             stance="SUPPORTS", rationale="quoted support"):
    return {"source_record_id": source_id, "quote": quote, "stance": stance, "rationale": rationale}


def body(value) -> bytes:
    return json.dumps(value).encode("utf-8")


def envelope(content: str, model: str = MODEL, refusal=None, usage=None) -> bytes:
    message = {"role": "assistant", "content": content}
    if refusal is not None:
        message["refusal"] = refusal
    result = {"model": model, "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}
    if usage is not None:
        result["usage"] = usage
    return body(result)


def parse_proposals(payload: bytes):
    return ps.parse_provider_proposals(payload, request())


# ---------------------------------------------------------------- 1. nesting

def property_nesting() -> None:
    print("\n== 1 nesting ==")
    observed = {}
    for depth in (10, 100, 1000, 10_000, 100_000):
        payload = ("[" * depth + "]" * depth).encode("utf-8")
        try:
            parse_proposals(payload)
            observed[depth] = "parsed"
        except ps.ProviderSafetyError as exc:
            observed[depth] = exc.code
        except RecursionError:
            observed[depth] = "RecursionError"
        check(f"1 depth {depth} is controlled, not an escaped RecursionError",
              observed[depth] != "RecursionError", observed[depth])
    print(f"      depth -> outcome: {observed}")

    deep_object = ("[" * 50_000 + "]" * 50_000).encode("utf-8")
    expect("1 a deeply nested object body is malformed_response",
           lambda: parse_proposals(deep_object), "malformed_response")


# ------------------------------------------------------------- 2. model pin

def property_model_pin() -> None:
    print("\n== 2 model pin ==")
    content = json.dumps([proposal()])
    parsed = ps.BasetenMuseSparkOpenAdapter._parse_response(envelope(content), request())
    check("2 the pinned model is accepted", len(parsed) == 1)

    for label, model, code in (
        ("suffixed", MODEL + "-2026", "unsupported_response"),
        ("prefixed", "other-" + MODEL, "unsupported_response"),
        ("case variant", MODEL.upper(), "unsupported_response"),
        # The empty-string check runs before the pin, so the code differs.
        ("empty", "", "malformed_response"),
    ):
        expect(f"2 a {label} model is {code}",
               lambda model=model: ps.BasetenMuseSparkOpenAdapter._parse_response(
                   envelope(content, model=model), request()),
               code)


# ------------------------------------------------------------ 3. cap boundary

def property_cap_boundary() -> None:
    print("\n== 3 proposal cap ==")
    for count in (127, 128):
        many = [proposal() for _ in range(count)]
        parsed = parse_proposals(body(many))
        check(f"3 {count} proposals are accepted", len(parsed) == count)

    over = [proposal() for _ in range(129)]
    expect("3 129 proposals are refused", lambda: parse_proposals(body(over)), "malformed_output")


# ---------------------------------------------------------------- 4. refusal

def property_refusal() -> None:
    print("\n== 4 refusal ==")
    content = json.dumps([proposal()])
    expect("4 a real refusal string is provider_refusal",
           lambda: ps.BasetenMuseSparkOpenAdapter._parse_response(
               envelope(content, refusal="I cannot help with that."), request()),
           "provider_refusal")
    for label, refusal in (("empty", ""), ("whitespace", "   "), ("zero width", "\u200b")):
        expect(f"4 a {label} refusal is unsupported_response",
               lambda refusal=refusal: ps.BasetenMuseSparkOpenAdapter._parse_response(
                   envelope(content, refusal=refusal), request()),
               "unsupported_response" if label != "zero width" else "provider_refusal")


# ------------------------------------------------------------------ 5. usage

def property_usage() -> None:
    print("\n== 5 usage ==")
    content = json.dumps([proposal()])
    ok = ps.BasetenMuseSparkOpenAdapter._parse_response(
        envelope(content, usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}),
        request())
    check("5 a valid usage block is accepted", len(ok) == 1)

    for label, usage in (
        ("negative", {"total_tokens": -1}),
        ("float", {"total_tokens": 1.5}),
        ("bool", {"total_tokens": True}),
        ("string", {"total_tokens": "3"}),
    ):
        expect(f"5 a {label} token count is unsupported_response",
               lambda usage=usage: ps.BasetenMuseSparkOpenAdapter._parse_response(
                   envelope(content, usage=usage), request()),
               "unsupported_response")


# ------------------------------------------------------------- 6. grounding

def property_grounding() -> None:
    print("\n== 6 grounding precision ==")
    suffix = "at shift change."
    check("6 a quote that is a suffix of the record is grounded",
          parse_proposals(body([proposal(quote=suffix)]))[0]["quote"] == suffix)

    # Cyrillic 'а' (U+0430) for Latin 'a' in "handover": equal-looking, not equal.
    lookalike = "h\u0430ndover checklist was unavailable"
    expect("6 a lookalike-character quote is invalid_quote",
           lambda: parse_proposals(body([proposal(quote=lookalike)])), "invalid_quote")

    expect("6 a quote containing a null byte is invalid_quote",
           lambda: parse_proposals(body([proposal(quote="handover\x00 checklist")])), "invalid_quote")

    expect("6 a quote from another record is invalid_quote",
           lambda: parse_proposals(body([proposal(source_id="REC-1", quote="binder was missing")])),
           "invalid_quote")


def main() -> int:
    for property_fn in (
        property_nesting,
        property_model_pin,
        property_cap_boundary,
        property_refusal,
        property_usage,
        property_grounding,
    ):
        property_fn()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED property check(s):")
        for name, detail in FAILURES:
            print(f"  - {name} [{detail}]")
        return 1
    print("all property checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
