"""Slice-7 contracts: `investigate` and `challenge` are pure and fail closed.

`investigate` hands records to the provider and builds new `Evidence` objects;
`challenge` rebuilds the claim rather than editing it. Both are easy to break
with an aliasing change, and neither was pinned before.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.engine import AssessmentEngine, AssessmentError
from app.mock_provider import MockProvider
from app.models import HYPOTHESES, Record, Status

FIXED = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
TEXT = "The checklist unavailable overnight during the night handover."
OTHER_TEXT = "The binder was missing at handover."


def record(rid: str = "A", text: str = TEXT, days: int = 1) -> Record:
    return Record(
        id=rid,
        timestamp=FIXED - timedelta(days=days),
        department="Front Office",
        text=text,
        tags=[],
    )


def supporting(records: list[Record]) -> MockProvider:
    """One SUPPORTS proposal for `records[0]` under every hypothesis."""
    return MockProvider(
        assessment_overrides={
            hypothesis.id: [
                {
                    "source_record_id": records[0].id,
                    "quote": "checklist unavailable",
                    "stance": "SUPPORTS",
                    "rationale": "synthetic proposal",
                }
            ]
            for hypothesis in HYPOTHESES
        }
    )


def snapshot(records: list[Record]) -> list[dict]:
    return [item.model_dump() for item in records]


def test_investigate_does_not_mutate_the_records_it_is_handed():
    records = [record("A"), record("B", OTHER_TEXT)]
    provider = supporting(records)
    before = snapshot(records)

    AssessmentEngine(provider, clock=lambda: FIXED).investigate(records)

    assert snapshot(records) == before
    assert [item.id for item in records] == ["A", "B"]


def test_challenge_does_not_mutate_the_claim_it_is_handed():
    records = [record("A"), record("B", OTHER_TEXT)]
    engine = AssessmentEngine(supporting(records), clock=lambda: FIXED)
    claim = engine.investigate(records)[0]
    assert claim["evidence"], "the fixture must produce assessable evidence"
    before = deepcopy(claim)

    changed = engine.challenge(claim, records, "A", "checklist unavailable")

    # The caller's dict is also its revision guard (`expected_claims`); an
    # in-place `disputed` write here is what makes a legacy challenge 409.
    assert claim == before
    assert changed["version"] == before["version"] + 1
    assert any(item.get("disputed") for item in changed["evidence"])


def test_challenge_refuses_an_unknown_record_with_a_named_code():
    records = [record("A")]
    engine = AssessmentEngine(supporting(records), clock=lambda: FIXED)
    claim = engine.investigate(records)[0]

    with pytest.raises(AssessmentError) as failure:
        engine.challenge(claim, records, "NOT-A-RECORD", "checklist unavailable")

    assert failure.value.code == "invalid_assessment"


def test_challenge_refuses_a_quote_absent_from_the_record():
    records = [record("A")]
    engine = AssessmentEngine(supporting(records), clock=lambda: FIXED)
    claim = engine.investigate(records)[0]

    with pytest.raises(AssessmentError) as failure:
        engine.challenge(claim, records, "A", "binder was full")

    assert failure.value.code == "invalid_assessment"


def test_challenge_refuses_a_two_character_quote_that_does_appear():
    """`"is"` occurs inside "checklist", so only the length floor refuses it."""
    records = [record("A")]
    engine = AssessmentEngine(supporting(records), clock=lambda: FIXED)
    claim = engine.investigate(records)[0]
    assert "is" in TEXT

    with pytest.raises(AssessmentError) as failure:
        engine.challenge(claim, records, "A", "is")

    assert failure.value.code == "invalid_assessment"


def test_investigate_with_no_records_returns_one_insufficient_claim_per_hypothesis():
    claims = AssessmentEngine(clock=lambda: FIXED).investigate([])

    assert [claim["id"] for claim in claims] == [hypothesis.id for hypothesis in HYPOTHESES]
    assert {claim["status"] for claim in claims} == {Status.INSUFFICIENT.value}
    assert all(claim["evidence"] == [] for claim in claims)


def test_two_clocks_change_the_trace_timestamps_but_not_the_verdict():
    records = [record("A"), record("B", OTHER_TEXT)]
    provider = supporting(records)
    early = FIXED - timedelta(hours=1)
    late = FIXED + timedelta(hours=1)

    first = AssessmentEngine(provider, clock=lambda: early).investigate(records)
    second = AssessmentEngine(provider, clock=lambda: late).investigate(records)

    assert [claim["status"] for claim in first] == [claim["status"] for claim in second]
    assert [claim["confidence"] for claim in first] == [claim["confidence"] for claim in second]

    def times(claims: list[dict]) -> list[str | None]:
        entries = claims[0]["explanation_trace"]["staleness_policy"]["evidence_evaluation_times"]
        return [entry["evaluated_at"] for entry in entries]

    assert all(times(first)) and all(times(second))
    assert times(first) != times(second)
    assert (first[0]["explanation_trace"]["generated_at"]
            != second[0]["explanation_trace"]["generated_at"])


# --------------------------------------------------------------------------
# Slice-7 fixes: the trace's own timestamps and its staleness table
# --------------------------------------------------------------------------

def test_iso_utc_reads_an_offset_less_value_as_utc_not_host_local():
    from app.engine import _iso_utc

    naive = datetime(2026, 6, 1, 12, 0)

    assert _iso_utc(naive) == "2026-06-01T12:00:00Z"


def test_a_short_evaluation_time_list_does_not_truncate_the_staleness_table():
    from app.engine import _staleness_row
    from app.models import Evidence, Stance

    def item(record_id):
        return Evidence(
            source_record_id=record_id,
            timestamp=FIXED,
            quote="binder",
            stance=Stance.SUPPORTS,
            rationale="because",
            department="Front Office",
            source_group=record_id,
        )

    rows = [_staleness_row(item(f"R{n}"), [FIXED], n) for n in range(3)]

    # One row per record, not one per supplied time: an audit trace must not
    # cover fewer records than the dispositions it sits beside.
    assert [row["source_record_id"] for row in rows] == ["R0", "R1", "R2"]
    assert [row["basis"] for row in rows] == [
        "ASSESSMENT_VALIDATION",
        "UNKNOWN_MISSING_EVALUATION_TIME",
        "UNKNOWN_MISSING_EVALUATION_TIME",
    ]
    assert rows[1]["evaluated_at"] is None
