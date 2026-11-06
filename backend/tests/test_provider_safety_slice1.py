"""Slice 1 audit tests — `app/provider_safety.py:1-208`.

Written from a line-by-line read, not from a run. Each test pins a contract that
the audit found under-specified or unexercised. Where a test documents a
limitation rather than a guarantee it says so in the docstring, because a test
that asserts the boundary is at process level is only honest if it names that.
"""

from datetime import datetime, timezone

import pytest

from app import provider_safety as ps
from app.models import Record

NOW = datetime.now(timezone.utc)


def record(record_id="R1", text="The checklist was unavailable.", *, restricted=False):
    return Record(
        id=record_id,
        timestamp=NOW,
        department="Front Office",
        text=text,
        tags=[],
        restricted=restricted,
    )


# --------------------------------------------------------------------------
# The size model must agree with json.dumps byte-for-byte, or the self-check
# at serialize_provider_request fails closed on a legitimate payload.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("codepoint", [
    0x00, 0x01, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1F, 0x20,
    0x22, 0x5C, 0x7E, 0x7F, 0x80, 0xA0, 0xFF, 0x2028, 0x2029,
    0x20AC, 0x1F600, 0x10FFFF,
])
def test_string_size_model_matches_json_dumps(codepoint):
    import json

    value = chr(codepoint)
    assert ps._json_string_size(value) == len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def test_lone_surrogate_is_rejected_rather_than_encoded():
    with pytest.raises(ps.ProviderSafetyError) as excinfo:
        ps._json_string_size("\ud800")
    assert excinfo.value.code == "invalid_context"


def test_oversized_single_string_fails_before_allocation():
    with pytest.raises(ps.ProviderSafetyError) as excinfo:
        ps._json_string_size("a" * (ps.MAX_REQUEST_BYTES + 1))
    assert excinfo.value.code == "request_too_large"


# --------------------------------------------------------------------------
# The sealed request: immutability holds, isolation does not — say which
# --------------------------------------------------------------------------

def test_serialized_request_is_immutable_once_built():
    request = ps.serialize_provider_request([record()], "CHECKLIST_UNAVAILABLE")
    with pytest.raises(AttributeError):
        request.anything = 1


def test_a_payload_that_would_exceed_the_cap_is_refused():
    # 129 empty records is ~2.6 kB, well under 16 kB, so the record-count guard
    # is what fires. This test exists to prove that guard is reachable and not
    # dead code behind the byte guard.
    records = [record(record_id="", text="") for _ in range(129)]
    with pytest.raises(ps.ProviderSafetyError) as excinfo:
        ps.serialize_provider_request(records, "CHECKLIST_UNAVAILABLE")
    assert excinfo.value.code == "request_too_large"


def test_the_seal_is_module_level_so_this_is_not_an_isolation_boundary():
    """Documents the boundary rather than pretending it is stronger.

    `_SERIALIZATION_SEAL` is importable, so in-process code can construct a
    request the boundary would accept. The guarantee is "no accidental caller
    reaches a provider", not "hostile in-process code cannot".
    """
    forged = ps.SerializedProviderRequest(b"{}", _seal=ps._SERIALIZATION_SEAL)
    assert ps._is_serialized_request(forged) is True
    assert type(forged) is ps.SerializedProviderRequest


def test_bytes_new_bypasses_the_seal_and_is_still_rejected():
    """The runtime check is `type(...) is SerializedProviderRequest and _seal`.

    `bytes.__new__` skips `__new__`, so the instance exists without a seal and
    `_is_serialized_request` refuses it until someone copies a real seal onto it.
    """
    bypass = bytes.__new__(ps.SerializedProviderRequest, b"{}")
    assert ps._is_serialized_request(bypass) is False


# --------------------------------------------------------------------------
# Context eligibility
# --------------------------------------------------------------------------

def test_eligible_accepts_list_and_tuple_only():
    assert [r.id for r in ps.eligible_provider_records([record()])] == ["R1"]
    assert len(ps.eligible_provider_records((record(),))) == 1
    for bad in (iter([record()]), "not-a-record-list", None):
        with pytest.raises(ps.ProviderSafetyError) as excinfo:
            ps.eligible_provider_records(bad)
        assert excinfo.value.code == "invalid_context"


def test_restricted_and_non_record_inputs_are_excluded_or_rejected():
    assert ps.eligible_provider_records([record(restricted=True)]) == []
    with pytest.raises(ps.ProviderSafetyError):
        ps.eligible_provider_records([{"id": "x"}])


def test_partition_reports_why_a_record_was_withheld():
    """A fully filtered corpus must be distinguishable from an empty one."""
    eligible, excluded = ps.partition_provider_records([
        record("R1"),
        record("R2", restricted=True),
        record("R3", "Contact 555-123-4567 about the handover."),
    ])
    assert [r.id for r in eligible] == ["R1"]
    assert excluded == [("R2", "restricted"), ("R3", "sensitive_text")]
    assert [r.id for r in ps.eligible_provider_records([record("R9")])] == ["R9"]


def test_partition_and_eligibility_cannot_disagree():
    corpus = [record("A"), record("B", restricted=True), record("C")]
    assert ps.partition_provider_records(corpus)[0] == ps.eligible_provider_records(corpus)


def test_the_projection_constant_is_only_safe_because_of_that_filter():
    """`AssessmentContextRecord.restricted` is always False by construction.

    It is a compatibility shim: only records that already passed the eligibility
    filter are projected, so a restricted record cannot reach it.
    """
    projected = ps.AssessmentContextRecord(id="R1", text="t")
    assert projected.restricted is False
    assert ps.eligible_provider_records([record(restricted=True)]) == []


# --------------------------------------------------------------------------
# Sensitive text: the keyword rule missed credentials without a keyword
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Authorization: Bearer abcdefgh12345678",
    "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
    "sk-abcdefghijklmnop1234",
    "ghp_" + "a" * 36,
    "xoxb-1234567890-abcdef",
    "AKIAIOSFODNN7EXAMPLE",
])
def test_credentials_without_a_keyword_are_filtered(text):
    assert ps.contains_sensitive_text(text) is True


@pytest.mark.parametrize("text", [
    "The checklist was unavailable during handover.",
    "Risk register updated; no gaps found.",
    "Task complete after the desk review.",
])
def test_ordinary_operational_text_is_not_filtered(text):
    """Over-redaction is a defect too: it silently removes evidence."""
    assert ps.contains_sensitive_text(text) is False
