"""Third probe batch: data-shape integrity.

These are the attacks that arrive as legitimate-looking records and proposals. They
matter because the verdict is computed from *group identity* and *substring grounding*,
both of which are string operations with unicode and control-character edge cases.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone

import pytest

from app.decision_table import decide_evidence
from app.engine import AssessmentEngine
from app.models import Evidence, EvidenceReviewState, Record, Stance

CLOCK = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
TEXT = "The checklist binder was missing at the handover."


def record(record_id: str, *, text: str = TEXT, group: str | None = None) -> Record:
    return Record(id=record_id, timestamp=CLOCK, department="Front Office",
                  text=text, tags=[], source_group=group)


def evidence(record_id: str, group: str, *, stance=Stance.SUPPORTS) -> Evidence:
    return Evidence(source_record_id=record_id, timestamp=CLOCK, quote=TEXT[:10],
                    stance=stance, review_state=EvidenceReviewState.ACCEPTED,
                    rationale="because", department="Front Office", source_group=group)


# 1. Unicode normalisation: NFC and NFD are the same string to a reader and two
# strings to ==. Group identity is normalised (`group_key`), so a canonically
# equivalent pair is one source and cannot corroborate itself.
def test_nfc_and_nfd_group_names_count_as_one_source():
    nfc = unicodedata.normalize("NFC", "café-team")
    nfd = unicodedata.normalize("NFD", "café-team")
    assert nfc != nfd  # the premise: two distinct strings

    decision = decide_evidence([evidence("R1", nfc), evidence("R2", nfd)])

    assert decision.support_groups == 1
    assert decision.status.value == "PARTIAL"


# 2. Invisible characters in a group name do the same thing more cheaply.
def test_a_zero_width_space_does_not_make_a_second_group():
    decision = decide_evidence([
        evidence("R1", "ops-team"),
        evidence("R2", "ops-team\u200b"),
    ])

    assert decision.support_groups == 1, "a zero-width space created a second source"
    assert decision.status.value == "PARTIAL"


# 3. An ambiguous quote: the same sentence exists in two records. The challenge
# must pick deterministically, and it must pick a record it was actually given.
def test_a_quote_present_in_two_records_resolves_deterministically():
    records = [record("R1"), record("R2")]
    engine = AssessmentEngine(clock=lambda: CLOCK)
    claim = engine.assess_hypothesis(records, "CHECKLIST_UNAVAILABLE")

    first = engine.challenge(claim, records, "R1", "binder was missing")
    second = engine.challenge(claim, records, "R1", "binder was missing")

    assert first["version"] == second["version"] == claim["version"] + 1
    assert [item["source_record_id"] for item in first["evidence"]] == \
           [item["source_record_id"] for item in second["evidence"]]


# 4. A NUL byte inside record text: legal in JSON once escaped, and it must not
# break grounding or the provider request.
def test_a_nul_byte_in_record_text_does_not_break_assessment():
    hostile = record("R1", text="The checklist binder\x00 was missing at the handover.")
    engine = AssessmentEngine(clock=lambda: CLOCK)

    claim = engine.assess_hypothesis([hostile], "CHECKLIST_UNAVAILABLE")

    assert claim["evidence"], "the record was dropped instead of assessed"


# 5. A zero-width character inserted into the quote must fail grounding, because
# it is not a substring of the record.
def test_a_zero_width_insertion_breaks_the_quote_grounding():
    engine = AssessmentEngine(clock=lambda: CLOCK)
    claim = engine.assess_hypothesis([record("R1")], "CHECKLIST_UNAVAILABLE")

    with pytest.raises(Exception) as excinfo:
        engine.challenge(claim, [record("R1")], "R1", "binder\u200b was missing")

    assert "quote" in str(excinfo.value).lower()


# 6. Homoglyphs in a record id: a Cyrillic 'а' looks identical and is a different
# record. The engine must treat it as unknown, not as the record it resembles.
def test_a_homoglyph_record_id_is_not_the_record():
    engine = AssessmentEngine(clock=lambda: CLOCK)
    records = [record("OPS-101")]
    claim = engine.assess_hypothesis(records, "CHECKLIST_UNAVAILABLE")

    homoglyph = "OPS-1\u04301"  # Cyrillic 'а' standing in for the zero-adjacent '1'? see note

    with pytest.raises(Exception) as excinfo:
        engine.challenge(claim, records, homoglyph, "binder was missing")

    assert homoglyph not in {item["source_record_id"] for item in claim["evidence"]}
    assert getattr(excinfo.value, "code", None) == "invalid_source" or "source" in str(excinfo.value).lower()


# 5. The verdict and the coverage report must agree about how many sources there
# are. They are computed in different modules; if only one normalises group
# identity, the report can claim independence the verdict denies.
def test_coverage_and_verdict_agree_on_invisible_group_names():
    from app.evidence_coverage import evidence_coverage  # noqa: PLC0415

    pair = [
        evidence("R1", "ops-team").model_copy(update={"semantic_relation": Stance.SUPPORTS}),
        evidence("R2", "ops-team\u200b").model_copy(update={"semantic_relation": Stance.SUPPORTS}),
    ]
    decision = decide_evidence(pair)
    coverage = evidence_coverage("CHECKLIST_UNAVAILABLE", pair)

    primary = next(
        category for category in coverage["categories"]
        if category["role"] == "CORROBORATION"
    )
    assert decision.support_groups == 1
    assert primary["independent_source_groups"] == ["ops-team"]
    assert primary["non_independent"] is True
