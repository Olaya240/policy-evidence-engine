"""Slice-8 contracts: what the provider boundary refuses, and with which code.

`AssessmentEngine._provider_assess` (app/engine.py:420-446) is the only door
between a provider and a claim. Three properties have to hold there, and each is
invisible from the happy path:

* A provider that raises anything other than a `ProviderSafetyError` is reported
  as `provider_failure`, and neither the exception text nor the record content it
  was talking about may reach the caller.
* A `ProviderSafetyError` raised by the boundary keeps *its own* code; collapsing
  it into `provider_failure` would erase the difference between "the provider
  broke" and "the provider returned something the boundary rejected".
* Output the boundary does not project is refused rather than partially used: a
  non-list result, an item whose key set is not exactly the four-key contract,
  and a proposal naming a record the caller is not allowed to cite.

The record citable by the provider is the *projected* one
(`MandatoryProviderBoundary.assess` serializes `records` without the restricted
ones), so a proposal naming a restricted record is refused by the same
`invalid_source` branch as an invented id. That collapse is pinned here rather
than papered over: the caller can distinguish neither case from the code alone.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.engine import AssessmentEngine, ProviderError
from app.models import Record
from app.mock_provider import MockProvider, SEED_RECORDS
from app.provider_safety import ProviderSafetyError

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
TEXT = "The checklist binder was unavailable during handover."
QUOTE = "binder was unavailable"


def record(rid: str = "T1", text: str = TEXT, restricted: bool = False) -> Record:
    return Record(
        id=rid,
        timestamp=datetime.now(timezone.utc) - timedelta(days=1),
        department="Front Office",
        text=text,
        tags=[],
        restricted=restricted,
    )


def proposal(**overrides) -> dict:
    item = {
        "source_record_id": "T1",
        "quote": QUOTE,
        "stance": "SUPPORTS",
        "rationale": "synthetic slice-8 fixture",
    }
    item.update(overrides)
    return item


def refusal(provider: MockProvider, records: list[Record] | None = None) -> ProviderError:
    engine = AssessmentEngine(provider)
    with pytest.raises(ProviderError) as error:
        engine.assess_hypothesis([record()] if records is None else records, HYPOTHESIS)
    return error.value


# (a) an exception from inside the boundary is a sanitized provider_failure ----


CANARY = "guest pass 4417 was left at the desk"


def test_provider_exception_inside_the_boundary_becomes_a_sanitized_provider_failure():
    provider = MockProvider(
        assessment_overrides={},
        failure_message=f"transport exploded while reading: {CANARY}",
    )

    error = refusal(provider, [record("T1", CANARY)])

    assert type(error) is ProviderError
    assert error.code == "provider_failure"
    # The fixture only raises once the boundary has called the provider, so the
    # failure is on the boundary's side of the door.
    assert provider.assessment_call_count == 1
    # Neither the provider's text nor the record it was reading is echoed back.
    assert CANARY not in str(error)
    assert CANARY not in repr(error)
    # The original exception is not chained onto the caller-visible error.
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


def test_provider_failure_message_is_fixed_for_every_underlying_exception():
    first = refusal(MockProvider(failure_message="boom"))
    second = refusal(MockProvider(failure_message=f"leak {CANARY}"))

    assert first.code == second.code == "provider_failure"
    assert str(first) == str(second)


# (b) a ProviderSafetyError keeps its own code ---------------------------------


@pytest.mark.parametrize(
    "item,expected_code",
    [
        (proposal(stance="MAYBE"), "invalid_stance"),
        (proposal(quote="a fabricated quote"), "invalid_quote"),
        (proposal(rationale="   "), "invalid_rationale"),
    ],
    ids=["stance", "quote", "rationale"],
)
def test_boundary_safety_refusal_surfaces_with_its_own_code(item, expected_code):
    provider = MockProvider(assessment_overrides={HYPOTHESIS: [item]})

    error = refusal(provider)

    assert type(error) is ProviderError
    assert error.code == expected_code
    assert error.code != "provider_failure"
    assert error.__cause__ is None


def test_provider_safety_error_is_distinguishable_from_a_provider_exception():
    boundary_code = refusal(MockProvider(assessment_overrides={HYPOTHESIS: [proposal(stance="MAYBE")]}))
    provider_code = refusal(MockProvider(failure_message="boom"))

    assert boundary_code.code != provider_code.code
    assert ProviderSafetyError("invalid_stance").code == boundary_code.code


# (c) a non-list proposals result is malformed_output -------------------------


@pytest.mark.parametrize(
    "output",
    [{"unexpected": "not a proposal list"}, "not a proposal list", None, 7],
    ids=["mapping", "string", "null", "integer"],
)
def test_non_list_proposals_result_is_malformed_output(output):
    provider = MockProvider(assessment_overrides={HYPOTHESIS: output})

    error = refusal(provider)

    assert error.code == "malformed_output"


def test_empty_proposal_list_is_still_a_valid_abstention():
    engine = AssessmentEngine(MockProvider(assessment_overrides={HYPOTHESIS: []}))

    claim = engine.assess_hypothesis([record()], HYPOTHESIS)

    assert claim["evidence"] == []


# (d) a proposal with an extra or a missing key is refused --------------------


@pytest.mark.parametrize(
    "item",
    [
        proposal(status="SUPPORTED"),
        proposal(confidence=0.9),
        {key: value for key, value in proposal().items() if key != "rationale"},
        {key: value for key, value in proposal().items() if key != "quote"},
        {"source_record_id": "T1", "quote": QUOTE, "stance": "SUPPORTS", "rationale": "ok", "review_state": "ACCEPTED"},
    ],
    ids=["extra-status", "extra-confidence", "missing-rationale", "missing-quote", "extra-review-state"],
)
def test_proposal_key_set_must_match_the_four_key_contract(item):
    # Every other field is valid, so the key set is the only thing that can fail.
    provider = MockProvider(assessment_overrides={HYPOTHESIS: [item]})

    error = refusal(provider)

    assert error.code == "malformed_output"


def test_the_unmodified_four_key_proposal_is_accepted_by_the_same_engine():
    # Control for the parametrised refusals above: the fixture itself is usable,
    # so those refusals came from the key set and not from the fixture.
    engine = AssessmentEngine(MockProvider(assessment_overrides={HYPOTHESIS: [proposal()]}))

    claim = engine.assess_hypothesis([record()], HYPOTHESIS)

    assert [item["source_record_id"] for item in claim["evidence"]] == ["T1"]


# (e) a proposal naming a restricted record is refused -----------------------


def restricted_seed() -> Record:
    return next(item for item in SEED_RECORDS if item.restricted)


def test_proposal_naming_a_restricted_record_is_refused_and_the_code_is_recorded():
    canary = restricted_seed()
    # The quote is a genuine substring of the withheld record, so the refusal
    # cannot be blamed on the quote.
    item = proposal(source_record_id=canary.id, quote=canary.text[:20], rationale="restricted fixture")

    error = refusal(MockProvider(assessment_overrides={HYPOTHESIS: [item]}), SEED_RECORDS)

    assert error.code == "invalid_source"
    # The code is recorded on the raised error, not swallowed at the boundary.
    assert getattr(error, "code", None) == "invalid_source"
    # The withheld content is not echoed back in the caller-visible message.
    assert canary.text not in str(error)
    assert canary.id not in str(error)


def test_a_restricted_record_is_indistinguishable_from_an_invented_one_by_code():
    canary = restricted_seed()
    restricted = refusal(
        MockProvider(assessment_overrides={HYPOTHESIS: [proposal(source_record_id=canary.id, quote=canary.text[:20])]}),
        SEED_RECORDS,
    )
    invented = refusal(
        MockProvider(assessment_overrides={HYPOTHESIS: [proposal(source_record_id="INVENTED-RECORD")]}),
        SEED_RECORDS,
    )

    assert restricted.code == invented.code == "invalid_source"


def test_the_same_proposal_against_an_unrestricted_record_is_accepted():
    # Control: the refusal above is about the record being withheld, not about
    # the proposal's shape or the caller's access path.
    eligible = next(item for item in SEED_RECORDS if not item.restricted)
    item = proposal(source_record_id=eligible.id, quote=eligible.text[:20], rationale="eligible fixture")
    engine = AssessmentEngine(MockProvider(assessment_overrides={HYPOTHESIS: [item]}))

    claim = engine.assess_hypothesis(SEED_RECORDS, HYPOTHESIS)

    assert [evidence["source_record_id"] for evidence in claim["evidence"]] == [eligible.id]
