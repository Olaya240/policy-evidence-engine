"""Slice-5 contracts: `MandatoryProviderBoundary` construction, sealing, and the
local-provider `assess` projection.

The boundary is the only object allowed to call a provider, so these tests pin
what it accepts, what it refuses, and what it hands to a local provider.
"""

from datetime import datetime, timezone

import pytest

from app import provider_safety as ps
from app.mock_provider import MockProvider
from app.models import Record

NOW = datetime.now(timezone.utc)


def record(record_id, text, *, restricted=False, department="Front Office"):
    return Record(
        id=record_id,
        timestamp=NOW,
        department=department,
        text=text,
        tags=[],
        restricted=restricted,
    )


def test_a_boundary_is_immutable_after_construction():
    boundary = ps.MandatoryProviderBoundary(MockProvider())
    with pytest.raises(AttributeError):
        boundary._provider = MockProvider()


def test_a_boundary_refuses_an_unapproved_provider():
    with pytest.raises(ps.ProviderSafetyError) as raised:
        ps.MandatoryProviderBoundary(object())
    assert raised.value.code == "unsupported_provider"


def test_a_local_provider_only_sees_allowlisted_fields():
    """`assess` projects from the serialized envelope, so a local provider cannot
    observe department, tags, timestamps or a restricted record's text."""
    boundary = ps.MandatoryProviderBoundary(MockProvider())
    records = [
        record("R1", "The handover checklist was unavailable at shift change."),
        record("R2", "RESTRICTED SECRET TEXT about the checklist.", restricted=True),
    ]

    proposals = boundary.assess(records, "CHECKLIST_UNAVAILABLE")

    assert isinstance(proposals, list)
    seen = ps.eligible_provider_records(records)
    request = ps.serialize_provider_request(seen, "CHECKLIST_UNAVAILABLE")
    assert all(item["source_record_id"] in {r.id for r in seen} for item in proposals)
    assert not any(item["source_record_id"] == "R2" for item in proposals)
    # A projected record carries exactly the two fields the serializer emits.
    assert set(json_keys(request)) == {"id", "text"}


def json_keys(request):
    import json

    return json.loads(bytes(request))["input"]["records"][0].keys()
