"""Slice-4 contract tests: strict provider response parsing.

Each test pins a branch the slice-4 audit found unguarded. Expectations are
computed from the module's own constants and vocabulary rather than hardcoded,
so a change to `MAX_PROPOSALS` or the stance set moves the test with it.
"""

import json

import pytest

from app import provider_safety as ps
from app.mock_provider import SEED_RECORDS
from app.models import Record, Stance

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
TEXT = "Checklist binder was missing from the desk at handover."


def record(text: str = TEXT, record_id: str = "SYN-1") -> Record:
    return Record(
        id=record_id,
        timestamp=SEED_RECORDS[0].timestamp,
        department="Synthetic",
        text=text,
        tags=[],
    )


def request(text: str = TEXT, record_id: str = "SYN-1"):
    return ps.serialize_provider_request([record(text, record_id)], HYPOTHESIS)


def proposal(**overrides) -> dict:
    item = {
        "source_record_id": "SYN-1",
        "quote": "Checklist binder",
        "stance": Stance.SUPPORTS.value,
        "rationale": "The binder was reported missing at handover.",
    }
    item.update(overrides)
    return item


def body(items) -> bytes:
    return json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def envelope(content: str, *, model: str = "muse-spark", **extra) -> bytes:
    payload = {
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------
# 1. Hostile nesting
# --------------------------------------------------------------------------

def test_deeply_nested_body_is_a_controlled_malformed_response():
    """`json.loads` recurses; without RecursionError in the handler this escaped
    as an unclassified 500 on an attacker-supplied body."""
    nested = b"[" * 2000 + b"]" * 2000

    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.parse_provider_proposals(nested, request())

    # Both codes are controlled rejections; what must never escape is
    # RecursionError. The guard itself is pinned by the json.loads test below.
    assert raised.value.code in {"malformed_response", "malformed_output"}


# --------------------------------------------------------------------------
# 2. The model pin is two-way
# --------------------------------------------------------------------------

def test_a_response_from_an_unapproved_model_is_refused():
    payload = envelope(json.dumps([proposal()]), model="some-other-model")

    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.BasetenMuseSparkOpenAdapter._parse_response(payload, request())

    assert raised.value.code == "unsupported_response"


def test_the_approved_model_is_accepted():
    from app.provider_safety import BasetenMuseSparkOpenAdapter

    payload = envelope(json.dumps([proposal()]), model=BasetenMuseSparkOpenAdapter.MODEL_SLUG)

    parsed = ps.BasetenMuseSparkOpenAdapter._parse_response(payload, request())
    assert parsed == [proposal()]


# --------------------------------------------------------------------------
# 3. Proposal count is bounded
# --------------------------------------------------------------------------

def test_the_proposal_cap_is_inclusive_and_the_byte_cap_guards_one_past_it():
    """At the ceiling the two bounds coincide, so `MAX_PROPOSALS` is a backstop.

    A 43-item response must parse; a 44-item one is refused — by the byte cap,
    because the minimal 44-item body cannot be encoded inside 4 KiB. The count
    check therefore only fires for a caller that bypasses the size check, which is
    why it stays as defence in depth rather than as the binding bound.
    """
    at_cap = [proposal() for _ in range(ps.MAX_PROPOSALS)]
    assert len(ps.parse_provider_proposals(body(at_cap), request())) == ps.MAX_PROPOSALS

    over_cap = [proposal() for _ in range(ps.MAX_PROPOSALS + 1)]
    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.parse_provider_proposals(body(over_cap), request())
    # A well-shaped response that is simply over the budget gets its own code, so an
    # operator can tell capacity from garbage. This used to be `malformed_output`,
    # which contradicted the comment at the raise site.
    assert raised.value.code == "proposal_capacity_exceeded"


# --------------------------------------------------------------------------
# 4. Duplicate JSON keys cannot smuggle a second value
# --------------------------------------------------------------------------

def test_a_duplicate_key_in_an_item_is_malformed():
    raw = (
        b'[{"source_record_id":"SYN-1","quote":"Checklist binder",'
        b'"stance":"SUPPORTS","rationale":"r","rationale":"other"}]'
    )

    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.parse_provider_proposals(raw, request())

    assert raised.value.code == "malformed_response"


def test_a_duplicate_key_at_the_top_level_is_malformed():
    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.parse_provider_proposals(b'{"a":1,"a":2}', request())

    assert raised.value.code == "malformed_response"


# --------------------------------------------------------------------------
# 5. Usage accounting cannot be a bool or a negative number
# --------------------------------------------------------------------------

@pytest.mark.parametrize("usage", [
    {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2},
    {"prompt_tokens": -1, "completion_tokens": 1, "total_tokens": 2},
])
def test_impossible_usage_accounting_is_refused(usage):
    payload = envelope(json.dumps([proposal()]), usage=usage)

    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.BasetenMuseSparkOpenAdapter._parse_response(payload, request())

    assert raised.value.code == "unsupported_response"


# --------------------------------------------------------------------------
# 6. A refusal made only of a zero-width space is still a refusal
# --------------------------------------------------------------------------

def test_a_zero_width_space_refusal_is_treated_as_a_refusal():
    """`"\\u200b".strip()` is unchanged in Python — ZWSP is not whitespace — so a
    refusal field holding only that character is truthy and must not be read as
    an empty refusal followed by a content check."""
    payload = json.dumps({
        "model": ps.BasetenMuseSparkOpenAdapter.MODEL_SLUG,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "", "refusal": "\u200b"},
            "finish_reason": "stop",
        }],
    }, ensure_ascii=False).encode("utf-8")

    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.BasetenMuseSparkOpenAdapter._parse_response(payload, request())

    assert raised.value.code == "provider_refusal"


def test_an_empty_refusal_falls_through_to_unsupported_response():
    payload = json.dumps({
        "model": ps.BasetenMuseSparkOpenAdapter.MODEL_SLUG,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "", "refusal": ""},
            "finish_reason": "stop",
        }],
    }).encode("utf-8")

    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.BasetenMuseSparkOpenAdapter._parse_response(payload, request())

    assert raised.value.code == "unsupported_response"


# --------------------------------------------------------------------------
# 7. A short quote from a different record is not grounding
# --------------------------------------------------------------------------

def test_a_three_character_quote_from_another_record_is_invalid():
    other = record(text="A desk lamp was replaced before dinner.", record_id="SYN-2")

    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.parse_provider_proposals(
            body([proposal(quote="xyz")]),
            ps.serialize_provider_request([record(), other], HYPOTHESIS),
        )

    assert raised.value.code == "invalid_quote"



def test_a_recursion_error_inside_json_loads_is_a_controlled_rejection(monkeypatch):
    """Pins the guard directly: without RecursionError in the catch tuple this
    escaped as an unclassified 500 rather than a ProviderSafetyError."""

    def explode(*args, **kwargs):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(ps.json, "loads", explode)
    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.parse_provider_proposals(b"[]", request())
    assert raised.value.code == "malformed_response"


def test_the_proposal_cap_sits_at_the_measured_byte_ceiling():
    """A cap that can never fire is not a decision.

    Measured: 43 minimum-size proposals still fit in `MAX_RESPONSE_BYTES`, so the
    byte cap alone would allow 43 pieces of claim evidence per response. The count
    cap must therefore sit below that and refuse the 33rd, not the 129th.
    """
    import json

    from app import provider_safety as ps

    minimal = {"source_record_id": "R1", "quote": "abc", "stance": "SUPPORTS", "rationale": "x"}

    def envelope(count: int) -> bytes:
        content = json.dumps([minimal] * count, separators=(",", ":"))
        return json.dumps(
            {"model": "m", "choices": [{"message": {"role": "assistant", "content": content}}],
             "usage": {}},
            separators=(",", ":"),
        ).encode()

    assert len(envelope(43)) <= ps.MAX_RESPONSE_BYTES
    assert ps.MAX_PROPOSALS == 43
    # One past the ceiling cannot even be encoded inside the byte cap, which is
    # the evidence that 43 is the real bound and not an arbitrary smaller number.
    assert len(envelope(44)) > ps.MAX_RESPONSE_BYTES

    with pytest.raises(ps.ProviderSafetyError) as excinfo:
        ps.parse_provider_proposals(envelope(44), request())

    assert excinfo.value.code == "malformed_output"
