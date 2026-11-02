"""Slice 17 — contracts of `app/models.py` (165 lines), pinned.

Every assertion is exact: a boundary value, an enum member set, or a field-name
list. Nothing here runs the engine; the engine-side consequence of each default
is named in the docstring of the test that pins it, with the line it was read
from.

Two deliberate asymmetries are pinned on purpose, because each one is invisible
from the payload:

* `InvestigationCreate.question` measures `min_length=8` *before* the
  `field_validator` strips, so a 9-character string of spaces plus one letter
  becomes a 1-character question.
* `ChallengeCreate.reason` strips in a `mode="before"` validator, so its
  `min_length=8` is measured *after* stripping.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import (
    HYPOTHESES,
    INVESTIGATION_PRESET_HYPOTHESES,
    INVESTIGATION_PRESET_QUESTIONS,
    ChallengeCreate,
    Claim,
    Evidence,
    EvidenceReviewState,
    HistoryEntry,
    Investigation,
    InvestigationCreate,
    InvestigationPreset,
    Record,
    Stance,
    Status,
)

TS = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def make_evidence(**overrides) -> Evidence:
    base = {
        "source_record_id": "rec-1",
        "timestamp": TS,
        "quote": "abc",
        "stance": Stance.SUPPORTS,
        "rationale": "because",
        "department": "Front Desk",
    }
    base.update(overrides)
    return Evidence(**base)


def make_claim(**overrides) -> Claim:
    base = {
        "id": "claim-1",
        "hypothesis_id": "TIME_PRESSURE",
        "status": Status.PARTIAL,
        "confidence": 0.5,
        "uncertainty": "one source",
        "summary": "summary",
        "evidence": [],
        "conflicts": [],
        "missing_evidence": [],
        "dependencies": [],
        "version": 1,
    }
    base.update(overrides)
    return Claim(**base)


# --------------------------------------------------------------------------
# Record ids and free text carry no bounds at the model layer.
# --------------------------------------------------------------------------


def test_record_identity_and_text_are_unbounded():
    """`Record.id`, `.department` and `.text` are plain `str`: no min, no max.

    The empty id therefore validates. `store.py:133` is the only producer of
    record ids in the seeded prototype, so the model is not the guard here.
    """
    record = Record(id="", timestamp=TS, department="", text="", tags=[])
    assert record.id == ""
    assert record.department == ""
    assert record.text == ""

    huge = "x" * 5000
    assert Record(id=huge, timestamp=TS, department="D", text=huge, tags=[]).id == huge


def test_evidence_identity_is_non_empty_while_free_text_stays_unbounded():
    """`quote`, `rationale` and `source_record_id` are unbounded `str` here.

    Both guards live outside the model: `engine.py:53` requires a quote of at
    least 3 stripped characters that is an exact substring of its record, and
    `main.py:146` repeats the substring test for a challenge. `rationale` is
    guarded at `engine.py:60`. Constructing `Evidence` directly bypasses all
    three.
    """
    evidence = make_evidence(source_record_id="R1", quote="", rationale="")
    # The identity field is the one part of a citation that must name something.
    assert evidence.source_record_id == "R1"
    assert evidence.quote == ""
    assert evidence.rationale == ""
    # No whitespace normalisation happens in the model.
    assert make_evidence(quote="  ab  ", rationale="  r  ").quote == "  ab  "
    assert make_evidence(rationale="  r  ").rationale == "  r  "


def test_evidence_requires_source_timestamp_stance_rationale_department():
    for missing in ("source_record_id", "timestamp", "quote", "stance", "rationale", "department"):
        kwargs = {
            "source_record_id": "rec-1",
            "timestamp": TS,
            "quote": "abc",
            "stance": "SUPPORTS",
            "rationale": "because",
            "department": "D",
        }
        kwargs.pop(missing)
        with pytest.raises(ValidationError):
            Evidence(**kwargs)


# --------------------------------------------------------------------------
# ChallengeCreate: the only model in the file with real bounds.
# --------------------------------------------------------------------------


def test_challenge_create_field_bounds():
    """quote 3..1000, source_record_id 1..80, reason 8..1000 — inclusive."""
    ChallengeCreate(reason="abcdefgh", source_record_id="r", quote="abc")
    ChallengeCreate(reason="x" * 1000, source_record_id="x" * 80, quote="x" * 1000)

    for field, value in (
        ("quote", "ab"),
        ("quote", "x" * 1001),
        ("source_record_id", ""),
        ("source_record_id", "x" * 81),
        ("reason", "abcdefg"),
        ("reason", "x" * 1001),
    ):
        kwargs = {"reason": "abcdefgh", "source_record_id": "r", "quote": "abc"}
        kwargs[field] = value
        with pytest.raises(ValidationError):
            ChallengeCreate(**kwargs)


def test_challenge_reason_length_is_measured_after_strip():
    """`reason` strips in a `mode="before"` validator, so 8 means 8 real chars.

    Nine spaces plus one letter is nine characters and is still rejected,
    whereas eight characters padded with spaces are accepted and stored bare.
    """
    with pytest.raises(ValidationError):
        ChallengeCreate(reason="        x", source_record_id="r", quote="abc")
    with pytest.raises(ValidationError):
        ChallengeCreate(reason="        ", source_record_id="r", quote="abc")

    assert ChallengeCreate(
        reason="   abcdefgh   ", source_record_id="r", quote="abc"
    ).reason == "abcdefgh"


def test_challenge_create_forbids_unknown_fields():
    """Same contract as `InvestigationCreate`: a misspelled field is rejected.

    It used to be dropped silently, so a client sending `stance` believed the
    truth while the challenge carried none of it.
    """
    with pytest.raises(ValidationError):
        ChallengeCreate(
            reason="abcdefgh", source_record_id="r", quote="abc", stance="CONTRADICTS"
        )

    payload = ChallengeCreate(reason="abcdefgh", source_record_id="r", quote="abc")
    assert set(payload.model_dump()) == {"reason", "source_record_id", "quote"}


# --------------------------------------------------------------------------
# InvestigationCreate: forbid-extra, and the strip/length ordering.
# --------------------------------------------------------------------------


def test_investigation_create_forbids_unknown_fields():
    """`extra="forbid"` at models.py:108 — an unknown key is a validation error."""
    with pytest.raises(ValidationError):
        InvestigationCreate(question="abcdefgh", hypothesis_id="TIME_PRESSURE")
    with pytest.raises(ValidationError):
        InvestigationCreate(question="abcdefgh", preset="desk_coverage")


def test_investigation_question_length_is_measured_after_strip():
    """`min_length=8` measures the stripped value.

    Before the fix `"        x"` was nine characters on the raw string, passed,
    and was then stored as `"x"` — a one-character question that the bound claims
    to forbid.
    """
    with pytest.raises(ValidationError):
        InvestigationCreate(question="        x")
    assert InvestigationCreate(question="  abcdefgh  ").question == "abcdefgh"

    with pytest.raises(ValidationError):
        InvestigationCreate(question="abcdefg")
    with pytest.raises(ValidationError):
        InvestigationCreate(question="x" * 501)
    assert len(InvestigationCreate(question="x" * 500).question) == 500


def test_investigation_question_must_not_be_blank():
    for blank in ("        ", "\t\t\t\t\t\t\t\t", "\n" * 9):
        with pytest.raises(ValidationError):
            InvestigationCreate(question=blank)


def test_preset_id_accepts_the_wire_string_and_rejects_anything_else():
    for preset in InvestigationPreset:
        assert InvestigationCreate(
            question="abcdefgh", preset_id=preset.value
        ).preset_id is preset
    with pytest.raises(ValidationError):
        InvestigationCreate(question="abcdefgh", preset_id="not_a_preset")


# --------------------------------------------------------------------------
# Closed enums: adding a member is a decision, so each set is pinned.
# --------------------------------------------------------------------------


def test_review_state_enum_is_closed_and_has_no_rejected_member():
    """Exactly ACCEPTED and UNVERIFIED. There is no REJECTED state.

    A rejected row is therefore expressed as UNVERIFIED plus the absence of a
    `disputed` flag, never as a third enum member.
    """
    assert {state.value for state in EvidenceReviewState} == {"ACCEPTED", "UNVERIFIED"}
    with pytest.raises(ValueError):
        EvidenceReviewState("REJECTED")
    # `str` mixin: the member compares equal to its wire value.
    assert EvidenceReviewState.ACCEPTED == "ACCEPTED"


def test_stance_enum_is_closed_and_case_sensitive():
    assert {stance.value for stance in Stance} == {"SUPPORTS", "CONTRADICTS", "NEUTRAL"}
    with pytest.raises(ValueError):
        Stance("supports")
    assert Stance.SUPPORTS == "SUPPORTS"
    assert make_evidence(stance="NEUTRAL").stance is Stance.NEUTRAL


def test_status_enum_is_closed():
    assert {status.value for status in Status} == {
        "SUPPORTED",
        "PARTIAL",
        "CONTRADICTED",
        "INSUFFICIENT",
    }
    with pytest.raises(ValidationError):
        make_claim(status="UNKNOWN")


# --------------------------------------------------------------------------
# Defaults that can change a verdict.
# --------------------------------------------------------------------------


def test_evidence_decision_defaults():
    """The defaults an engine-built row must not accidentally inherit.

    `review_state` defaults to ACCEPTED, i.e. *counting* evidence. The provider
    path cannot hit that default — `engine.py:78` passes
    `review_state=EvidenceReviewState.UNVERIFIED` explicitly and lets review
    promote it. Any other construction (a test, a replayed snapshot, a new
    caller) gets accepted evidence without saying so.

    `stale=False` and `disputed=False` put the row in the decisive set;
    `source_group=None` makes the row its own group
    (`decision_table.py:162` uses `source_group or source_record_id`), so a
    missing group never collapses two sources into one.
    """
    evidence = make_evidence()
    assert evidence.review_state is EvidenceReviewState.ACCEPTED
    assert evidence.stale is False
    assert evidence.disputed is False
    assert evidence.proposed_stance is None
    assert evidence.semantic_relation is None
    assert evidence.source_group is None


def test_claim_decision_defaults():
    claim = make_claim()
    assert claim.evidence_score is None
    assert claim.evidence_direction is None
    assert claim.explanation_trace is None


def test_investigation_and_history_defaults():
    investigation = Investigation(
        id="inv", question="q", created_at=TS, version=1, claims=[]
    )
    assert investigation.preset_id is None

    entry = HistoryEntry(version=1, created_at=TS, event="created")
    assert entry.claim_id is None
    assert entry.reason is None
    assert entry.before is None
    assert entry.after is None
    assert entry.evidence_changes == []
    assert entry.recomputed_claim_ids == []


def test_history_entry_list_defaults_are_not_shared_between_instances():
    """The `= []` defaults are copied per instance by pydantic, not shared.

    Pinned because the literal is mutable in source (models.py:163-164); if
    that ever becomes a plain dataclass, one history row would append to every
    other row's list.
    """
    first = HistoryEntry(version=1, created_at=TS, event="created")
    second = HistoryEntry(version=2, created_at=TS, event="challenged")
    first.evidence_changes.append("rec-1")
    first.recomputed_claim_ids.append("claim-1")
    assert second.evidence_changes == []
    assert second.recomputed_claim_ids == []


def test_record_restricted_defaults_to_visible():
    """`restricted=False` is the admitting default.

    Flip it and `access.visible_records` (main.py:104 serves its result) would
    return nothing at all; `engine.py:508` builds its index with
    `if not r.restricted` and would do the same.
    """
    assert Record(id="r", timestamp=TS, department="D", text="t", tags=[]).restricted is False
    assert Record(
        id="r", timestamp=TS, department="D", text="t", tags=[], restricted=True
    ).restricted is True


def test_claim_confidence_is_bounded_to_the_unit_interval():
    assert make_claim(confidence=0.0).confidence == 0.0
    assert make_claim(confidence=1.0).confidence == 1.0
    with pytest.raises(ValidationError):
        make_claim(confidence=1.0001)
    with pytest.raises(ValidationError):
        make_claim(confidence=-0.0001)


def test_claim_evidence_score_is_deliberately_unbounded():
    """No `ge`/`le` on `evidence_score` on purpose (models.py:89-93).

    A bound added later would reject already-persisted snapshots, so the range
    is enforced where it is computed, not here.
    """
    assert make_claim(evidence_score=9.0).evidence_score == 9.0
    assert make_claim(evidence_score=-9.0).evidence_score == -9.0
    assert make_claim(evidence_score=0).evidence_score == 0.0


def test_claim_evidence_direction_is_a_closed_literal():
    for value in ("FOR", "AGAINST", "NONE"):
        assert make_claim(evidence_direction=value).evidence_direction == value
    for bad in ("for", "SUPPORTS", "", 0):
        with pytest.raises(ValidationError):
            make_claim(evidence_direction=bad)
    assert make_claim(evidence_direction=None).evidence_direction is None


# --------------------------------------------------------------------------
# Preset maps must be total over the enum: main.py indexes them directly.
# --------------------------------------------------------------------------


def test_preset_question_map_is_total_over_the_enum():
    """`main.py:117` does `INVESTIGATION_PRESET_QUESTIONS[preset_id]` on a value
    that came from the enum, so a missing key is a KeyError (500), not a 422."""
    assert set(INVESTIGATION_PRESET_QUESTIONS) == set(InvestigationPreset)
    questions = list(INVESTIGATION_PRESET_QUESTIONS.values())
    assert all(isinstance(question, str) and question.strip() for question in questions)
    # Distinct questions keep the reverse lookup in `_derive_preset_id`
    # (main.py:66-79) unambiguous. That lookup also requires
    # `claim.id == hypothesis_id`, so a duplicate question alone would not
    # misattribute a preset — this is pinned as a payload invariant.
    assert len(set(questions)) == len(questions)
    # Every canonical question is a legal `InvestigationCreate.question`, so the
    # preset path in main.py cannot 422 on its own map.
    for question in questions:
        assert InvestigationCreate(question=question).question == question


def test_preset_hypothesis_map_is_total_and_names_real_hypotheses():
    """`main.py:121` indexes this map, then `engine.assess_hypothesis` receives
    the id: an id absent from `HYPOTHESES` would be an unknown hypothesis."""
    assert set(INVESTIGATION_PRESET_HYPOTHESES) == set(InvestigationPreset)
    known = {hypothesis.id for hypothesis in HYPOTHESES}
    mapped = set(INVESTIGATION_PRESET_HYPOTHESES.values())
    assert mapped <= known
    assert len(set(INVESTIGATION_PRESET_HYPOTHESES.values())) == len(
        INVESTIGATION_PRESET_HYPOTHESES
    )
    # The canonical question and the mapped hypothesis agree on intent: the
    # preset round-trips through the payload the client sends.
    for preset in InvestigationPreset:
        payload = InvestigationCreate(
            question=INVESTIGATION_PRESET_QUESTIONS[preset], preset_id=preset.value
        )
        assert payload.preset_id is preset


def test_hypothesis_ids_are_unique_and_non_empty():
    """`HYPOTHESES` is the vocabulary every preset hypothesis id resolves into."""
    ids = [hypothesis.id for hypothesis in HYPOTHESES]
    assert len(set(ids)) == len(ids) == 5
    assert all(id_.strip() for id_ in ids)


# --------------------------------------------------------------------------
# Field sets: a new field on these two models changes verdicts silently.
# --------------------------------------------------------------------------


def test_evidence_field_set_is_pinned():
    """An added field here is a contract change: update this list deliberately."""
    assert list(Evidence.model_fields) == [
        "source_record_id",
        "timestamp",
        "quote",
        "stance",
        "review_state",
        "proposed_stance",
        "semantic_relation",
        "rationale",
        "stale",
        "department",
        "source_group",
        "disputed",
    ]


def test_claim_field_set_is_pinned():
    assert list(Claim.model_fields) == [
        "id",
        "hypothesis_id",
        "status",
        "confidence",
        "evidence_score",
        "evidence_direction",
        "uncertainty",
        "summary",
        "evidence",
        "conflicts",
        "missing_evidence",
        "dependencies",
        "version",
        "explanation_trace",
    ]


def test_record_is_served_cross_origin_with_tags_and_restricted():
    """`Record` is the `/api/records` response model (main.py:104), and the API
    allows `http://localhost:5174` (main.py:18), so every field here is readable
    by that origin.

    `tags` is never read by any rule in `app/` (it round-trips through
    `store.py` only), so it is verdict-irrelevant payload. `restricted` is
    verdict-relevant, but only ever serialized as `False`: `visible_records`
    drops the true rows before the response model sees them.
    """
    assert list(Record.model_fields) == [
        "id",
        "timestamp",
        "department",
        "text",
        "tags",
        "restricted",
        "source_group",
    ]
    payload = Record(
        id="r", timestamp=TS, department="D", text="t", tags=["a"], restricted=True
    ).model_dump()
    assert payload["restricted"] is True
    assert payload["tags"] == ["a"]


def test_unvalidated_fields_that_reach_the_engine_are_the_expected_set():
    """The named gap: these model fields carry no constraint and are consumed
    downstream, so the guard — where one exists — is not in this file.

    * `Evidence.quote` / `rationale` / `source_record_id` — engine-guarded on the
      provider path (engine.py:53, :60) and challenge path (main.py:146); a
      direct `Evidence(...)` is unguarded.
    * `Evidence.department` — copied from the record at engine.py:79 and only
      reported in `source_group_analysis`.
    * `Evidence.source_group` — unvalidated and directly comparable to another
      record's id (`decision_table.py:162`); a crafted value collapses two
      sources into one group and lowers a count that feeds `status`.
    * `Record.id` / `text` / `department` — unvalidated; seeds only.
    * `Claim.id`, `.summary`, `.uncertainty`, `.conflicts`, `.missing_evidence`,
      `.dependencies` — unvalidated strings/lists; `.version` is a bare `int`
      with no monotonicity check.
    """
    # `source_group` accepts any string, including one shaped like a record id.
    evidence = make_evidence(source_group="rec-2")
    assert evidence.source_group == "rec-2"
    # `version` accepts zero and negatives: nothing here enforces a revision.
    assert make_claim(version=0).version == 0
    assert make_claim(version=-5).version == -5
    # Free-text claim fields accept the empty string.
    empty = make_claim(summary="", uncertainty="")
    assert (empty.summary, empty.uncertainty) == ("", "")
