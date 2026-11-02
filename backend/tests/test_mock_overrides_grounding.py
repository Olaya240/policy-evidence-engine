"""A configured override may only cite evidence the provider was actually given.

`MockProvider.assess` echoes `assessment_overrides` (and `assessment_sequences`)
verbatim, so before this fix a fixture naming a record the call never supplied
returned a proposal citing it: the mock itself manufactured fabricated evidence,
and only the engine boundary later refused it. These tests pin the provider-side
rule instead — an override proposal must name a record from *this* call's input
and quote text that appears in that record — and pin that the feature still works
for the ordinary case, including an empty override list.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.engine import AssessmentEngine, ProviderError
from app.mock_provider import MockProvider, SEED_RECORDS
from app.models import Record
from app.provider_safety import ProviderSafetyError

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
TEXT = "The checklist binder was unavailable during handover."
OTHER_TEXT = "The digital checklist opened normally on both desk terminals."
QUOTE = "binder was unavailable"


def record(rid: str = "T1", text: str = TEXT) -> Record:
    return Record(
        id=rid,
        timestamp=datetime.now(timezone.utc) - timedelta(days=1),
        department="Front Office",
        text=text,
        tags=[],
    )


def proposal(**overrides) -> dict:
    item = {
        "source_record_id": "T1",
        "quote": QUOTE,
        "stance": "SUPPORTS",
        "rationale": "grounding fixture",
    }
    item.update(overrides)
    return item


def test_an_override_naming_a_record_this_call_was_not_given_is_refused():
    provider = MockProvider(assessment_overrides={HYPOTHESIS: [proposal(source_record_id="INVENTED")]})

    with pytest.raises(ProviderSafetyError) as raised:
        provider.assess([record()], HYPOTHESIS)

    # Refused, not echoed and not silently dropped down to an empty list.
    assert raised.value.code == "invalid_source"


def test_a_quote_absent_from_the_cited_record_is_refused():
    # The id is legitimate for this call; the quote belongs to a different record.
    provider = MockProvider(assessment_overrides={HYPOTHESIS: [proposal(quote=OTHER_TEXT)]})

    with pytest.raises(ProviderSafetyError) as raised:
        provider.assess([record(), record("T2", OTHER_TEXT)], HYPOTHESIS)

    assert raised.value.code == "invalid_quote"


def test_a_record_supplied_to_an_earlier_call_is_not_citable_in_a_later_one():
    provider = MockProvider(assessment_overrides={HYPOTHESIS: [proposal()]})

    # Grounded against T1, so the same fixture is legitimate here.
    assert provider.assess([record(), record("T2", OTHER_TEXT)], HYPOTHESIS) == [proposal()]

    # T1 is absent from this call's input, so the fixture is now fabrication.
    with pytest.raises(ProviderSafetyError) as raised:
        provider.assess([record("T2", OTHER_TEXT)], HYPOTHESIS)

    assert raised.value.code == "invalid_source"


def test_a_sequence_fixture_naming_an_unreceived_record_is_refused_too():
    provider = MockProvider(assessment_sequences={HYPOTHESIS: [[proposal(source_record_id="INVENTED")]]})

    with pytest.raises(ProviderSafetyError) as raised:
        provider.assess([record()], HYPOTHESIS)

    assert raised.value.code == "invalid_source"


def test_the_engine_reports_the_provider_refusal_with_its_own_code():
    provider = MockProvider(assessment_overrides={HYPOTHESIS: [proposal(source_record_id="INVENTED")]})

    with pytest.raises(ProviderError) as raised:
        AssessmentEngine(provider).assess_hypothesis([record()], HYPOTHESIS)

    # Not collapsed into provider_failure: the provider refused a citation.
    assert raised.value.code == "invalid_source"


def test_a_legitimate_override_still_produces_the_claim_evidence():
    eligible = next(item for item in SEED_RECORDS if not item.restricted)
    item = proposal(source_record_id=eligible.id, quote=eligible.text[:20], rationale="eligible fixture")
    engine = AssessmentEngine(MockProvider(assessment_overrides={HYPOTHESIS: [item]}))

    claim = engine.assess_hypothesis(SEED_RECORDS, HYPOTHESIS)

    assert [evidence["source_record_id"] for evidence in claim["evidence"]] == [eligible.id]


def test_an_empty_override_list_is_still_accepted():
    provider = MockProvider(assessment_overrides={HYPOTHESIS: []})

    assert provider.assess([record()], HYPOTHESIS) == []
