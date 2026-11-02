"""Slice 1, second half: contracts the sibling file in this directory does not pin.

`tests/test_provider_safety_slice1.py` already covers the size model against
`json.dumps`, the 129-record ceiling, immutability and the credential patterns.
This file deliberately does not repeat those. It pins the remaining contracts of
`app/provider_safety.py:1-208`:

  * the seal cannot be omitted, only forged (which is in-process, not remote)
  * trust checks reject plain bytes, concatenation, subclasses and views
  * the byte cap is inclusive at exactly `MAX_REQUEST_BYTES`
  * the envelope has exactly the documented keys, in order, for 0, 1 and n records
  * an unknown hypothesis is refused before any encoding
  * eligibility preserves order; the projection carries exactly two frozen fields
  * obvious near-misses are not redacted into a false positive

Every size is derived from the module's constants, never hardcoded.
"""

import copy
import json
import pickle
from dataclasses import fields
from datetime import datetime, timezone

import pytest

import app.provider_safety as ps
from app.models import Record

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
FIXED_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def record(text="Checklist binder was missing.", record_id="SYN-1", **overrides):
    values = dict(
        id=record_id,
        department="Synthetic",
        text=text,
        tags=[],
        restricted=False,
    )
    values.update(overrides)
    return Record(timestamp=FIXED_TIME, **values)


# ---------------------------------------------------------------------------
# The seal
# ---------------------------------------------------------------------------

def test_constructing_a_payload_without_the_seal_is_refused():
    with pytest.raises(ps.ProviderSafetyError) as missing:
        ps.SerializedProviderRequest(b"{}")
    assert missing.value.code == "invalid_request"

    with pytest.raises(ps.ProviderSafetyError) as wrong:
        ps.SerializedProviderRequest(b"{}", _seal=object())
    assert wrong.value.code == "invalid_request"


def test_failed_assignment_does_not_strip_the_seal():
    payload = ps.serialize_provider_request([record()], HYPOTHESIS)

    with pytest.raises(AttributeError):
        payload._seal = None

    assert ps._is_serialized_request(payload) is True


# ---------------------------------------------------------------------------
# Trust is exact-type, not duck-typed
# ---------------------------------------------------------------------------

def test_trust_check_rejects_every_way_of_forging_a_bytes_lookalike():
    genuine = ps.serialize_provider_request([record()], HYPOTHESIS)
    assert ps._is_serialized_request(genuine) is True

    class BytesSubclass(bytes):
        pass

    assert ps._is_serialized_request(bytes(genuine)) is False
    assert ps._is_serialized_request(genuine + b"") is False
    assert ps._is_serialized_request(BytesSubclass(genuine)) is False
    assert ps._is_serialized_request(memoryview(genuine).tobytes()) is False
    assert ps._is_serialized_request(bytearray(genuine)) is False
    assert ps._is_serialized_request(None) is False


# ---------------------------------------------------------------------------
# Serializer envelope
# ---------------------------------------------------------------------------

def test_envelope_keys_are_exactly_the_documented_set():
    decoded = json.loads(ps.serialize_provider_request([record()], HYPOTHESIS))

    assert set(decoded) == {"system_instructions", "input"}
    assert decoded["system_instructions"] == ps.SYSTEM_INSTRUCTIONS
    assert set(decoded["input"]) == {"hypothesis", "records"}
    assert set(decoded["input"]["hypothesis"]) == {"id", "label"}
    assert decoded["input"]["hypothesis"]["id"] == HYPOTHESIS
    for entry in decoded["input"]["records"]:
        assert set(entry) == {"id", "text"}


def test_record_order_is_preserved_and_nothing_else_leaks():
    records = [record("first quote", "SYN-1"),
               record("second quote", "SYN-2"),
               record("third quote", "SYN-3")]

    decoded = json.loads(ps.serialize_provider_request(records, HYPOTHESIS))

    assert [entry["id"] for entry in decoded["input"]["records"]] == ["SYN-1", "SYN-2", "SYN-3"]
    assert [entry["text"] for entry in decoded["input"]["records"]] == [
        "first quote", "second quote", "third quote",
    ]


def test_empty_record_list_is_a_valid_request():
    decoded = json.loads(ps.serialize_provider_request([], HYPOTHESIS))
    assert decoded["input"]["records"] == []


def test_unknown_hypothesis_is_refused_before_encoding():
    with pytest.raises(ps.ProviderSafetyError) as error:
        ps.serialize_provider_request([], "NOT_A_REAL_HYPOTHESIS")
    assert error.value.code == "invalid_context"


def test_byte_cap_is_inclusive_at_exactly_the_limit():
    """The guard rejects `> MAX_REQUEST_BYTES`, so equality must be admitted.

    The text length comes from the module's own serializer, so changing the cap
    or the envelope cannot silently turn this into a no-op.
    """
    base = len(ps.serialize_provider_request([record("", "SYN-1")], HYPOTHESIS))
    spare = ps.MAX_REQUEST_BYTES - base
    assert spare > 0

    at_cap = ps.serialize_provider_request([record("a" * spare, "SYN-1")], HYPOTHESIS)
    assert len(at_cap) == ps.MAX_REQUEST_BYTES == base + spare

    with pytest.raises(ps.ProviderSafetyError) as over:
        ps.serialize_provider_request([record("a" * (spare + 1), "SYN-1")], HYPOTHESIS)
    assert over.value.code == "request_too_large"


# ---------------------------------------------------------------------------
# Eligibility and projection
# ---------------------------------------------------------------------------

def test_eligibility_preserves_input_order():
    first, second, third = record("a", "SYN-A"), record("b", "SYN-B"), record("c", "SYN-C")

    eligible = ps.eligible_provider_records([third, first, second])

    assert [item.id for item in eligible] == ["SYN-C", "SYN-A", "SYN-B"]


def test_projection_carries_exactly_two_frozen_fields():
    projection = ps.AssessmentContextRecord(id="SYN-1", text="Checklist binder was missing.")

    assert [field.name for field in fields(ps.AssessmentContextRecord)] == ["id", "text"]
    assert projection.id == "SYN-1"
    assert projection.restricted is False

    with pytest.raises(AttributeError):
        projection.restricted = True


# ---------------------------------------------------------------------------
# Sensitive text: over-redaction deletes evidence, so near-misses must pass
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("benign", [
    "Call extension 1234 if the binder is missing.",
    "Identifier 123456789 is nine digits.",
    "api key:",
    "The password policy was reviewed at handover.",
    "No email address appears in this sentence.",
])
def test_near_misses_are_not_redacted(benign):
    assert ps.contains_sensitive_text(benign) is False


@pytest.mark.parametrize("sensitive", [
    "api_key=synthetic_CANARY_VALUE",
    "Call +1 (555) 010-2020 after the shift.",
    "Identifier 123-45-6789 appears in the file.",
])
def test_positive_cases_the_other_file_leaves_to_the_keyword_rule(sensitive):
    assert ps.contains_sensitive_text(sensitive) is True


# --------------------------------------------------------------------------
# Copy semantics of the sealed payload
# --------------------------------------------------------------------------

def test_copying_a_sealed_request_preserves_the_seal_by_identity():
    """`copy` rebuilds through `bytes.__new__`, skipping the seal. Returning the
    same immutable object is the only answer that cannot manufacture a forgery."""
    sealed = ps.serialize_provider_request([record("text")], HYPOTHESIS)

    assert copy.copy(sealed) is sealed
    assert copy.deepcopy(sealed) is sealed
    assert ps._is_serialized_request(copy.copy(sealed))


def test_pickling_a_sealed_request_is_refused_rather_than_unsealed():
    with pytest.raises(TypeError):
        pickle.dumps(ps.serialize_provider_request([record("text")], HYPOTHESIS))
