"""Deterministic evidence rules and challenge behavior (synthetic records only)."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.access import AccessContext, visible_records
from app.engine import AssessmentEngine, AssessmentError, ProviderError, summarize_status, validate_assessment
from app.evidence_coverage import evidence_coverage
from app.mock_provider import MockProvider, SEED_RECORDS
from app.models import ChallengeCreate, Evidence, EvidenceReviewState, HYPOTHESES, Record, Status, Stance
from app.provider_safety import LocalAssessmentProvider, ProviderSafetyError
from app.semantic_guard import reviewed_relation


def record(rid="T1", text="Checklist binder was unavailable during handover.", department="Front Office", days=1, restricted=False):
    return Record(id=rid, timestamp=datetime.now(timezone.utc)-timedelta(days=days), department=department, text=text, tags=[], restricted=restricted)


@pytest.mark.parametrize("stance, expected", [
    (Stance.SUPPORTS, Status.PARTIAL),
    (Stance.CONTRADICTS, Status.CONTRADICTED),
    (Stance.NEUTRAL, Status.INSUFFICIENT),
])
def test_stance_status_matrix(stance, expected):
    e = Evidence(source_record_id="T1", timestamp=datetime.now(timezone.utc), quote="binder", stance=stance, rationale="fixture", department="Front Office")
    assert summarize_status([e])[0] == expected


CASES = [
    ("missing", [], Status.INSUFFICIENT),
    ("neutral-only", ["neutral"], Status.INSUFFICIENT),
    ("one-support", ["support"], Status.PARTIAL),
    ("duplicate-support-same-id", ["support", "support"], Status.PARTIAL),
    ("conflicting", ["support", "contradict"], Status.PARTIAL),
    ("contradiction-only", ["contradict"], Status.CONTRADICTED),
    ("stale-support", ["stale"], Status.INSUFFICIENT),
    ("fresh-contradiction", ["contradict", "contradict"], Status.CONTRADICTED),
]


@pytest.mark.parametrize("case, kinds, expected", CASES, ids=[c[0] for c in CASES])
def test_status_fixtures(case, kinds, expected):
    now = datetime.now(timezone.utc)
    evidences = []
    for kind in kinds:
        stances = {"neutral": Stance.NEUTRAL, "support": Stance.SUPPORTS, "contradict": Stance.CONTRADICTS, "stale": Stance.SUPPORTS}
        evidences.append(Evidence(source_record_id="DUP" if kind in ("support", "stale") else kind, timestamp=now-timedelta(days=365 if kind == "stale" else 1), quote="exact quote", stance=stances[kind], rationale=case, department="Front Office", stale=(kind == "stale")))
    assert summarize_status(evidences)[0] == expected


def test_dispute_and_fresh_conflict_annotations_are_both_preserved():
    now = datetime.now(timezone.utc)
    evidence = [
        Evidence(source_record_id="SUP", timestamp=now, quote="support", stance=Stance.SUPPORTS, rationale="support", department="Front Office", disputed=True),
        Evidence(source_record_id="OTHER-SUP", timestamp=now, quote="support too", stance=Stance.SUPPORTS, rationale="support", department="Housekeeping"),
        Evidence(source_record_id="CON", timestamp=now, quote="contradict", stance=Stance.CONTRADICTS, rationale="conflict", department="Front Office"),
    ]
    status, _, uncertainty, conflicts, _ = summarize_status(evidence)
    assert status == Status.PARTIAL
    assert any("challenged evidence" in item for item in conflicts)
    assert any("point both ways" in item for item in conflicts)
    assert "unresolved" in uncertainty


@pytest.mark.parametrize("reason", ["", "        ", " \t \n "])
def test_challenge_schema_rejects_blank_reason(reason):
    with pytest.raises(ValueError, match="must not be blank"):
        ChallengeCreate(reason=reason, source_record_id="OPS-101", quote="binder")


def test_challenge_schema_trims_valid_reason():
    payload = ChallengeCreate(reason="  Review this source carefully.  ", source_record_id="OPS-101", quote="binder")
    assert payload.reason == "Review this source carefully."


def test_multiple_independent_departments_support_without_count_alone_as_proof():
    a = Evidence(source_record_id="A", timestamp=datetime.now(timezone.utc), quote="one", stance=Stance.SUPPORTS, rationale="direct", department="Front Office")
    b = Evidence(source_record_id="B", timestamp=datetime.now(timezone.utc), quote="two", stance=Stance.SUPPORTS, rationale="direct", department="Housekeeping")
    status, confidence, *_ = summarize_status([a, b])
    assert status == Status.SUPPORTED and confidence < 1


def test_same_department_independent_records_are_not_treated_as_diverse():
    a = Evidence(source_record_id="A", timestamp=datetime.now(timezone.utc), quote="one", stance=Stance.SUPPORTS, rationale="direct", department="Front Office")
    b = Evidence(source_record_id="B", timestamp=datetime.now(timezone.utc), quote="two", stance=Stance.SUPPORTS, rationale="direct", department="Front Office")
    assert summarize_status([a, b])[0] == Status.SUPPORTED
    assert summarize_status([a, b])[1] < .78


def test_copied_dependent_records_do_not_count_as_independent_support():
    now = datetime.now(timezone.utc)
    a = Evidence(source_record_id="A", timestamp=now, quote="one", stance=Stance.SUPPORTS, rationale="direct", department="Front Office", source_group="original")
    b = Evidence(source_record_id="B", timestamp=now, quote="two", stance=Stance.SUPPORTS, rationale="copied from A", department="Front Office", source_group="original")
    assert summarize_status([a, b])[0] == Status.PARTIAL


def test_neutral_is_not_negative_proof():
    e = Evidence(source_record_id="N", timestamp=datetime.now(timezone.utc), quote="x", stance=Stance.NEUTRAL, rationale="unrelated", department="Front Office")
    status = summarize_status([e])[0]
    assert status == Status.INSUFFICIENT
    assert status != Status.CONTRADICTED


def test_exact_substring_and_source_id_are_validated():
    source = record()
    assert validate_assessment({"source_record_id": "T1", "quote": "binder was unavailable", "stance": "SUPPORTS", "rationale": "direct"}, {"T1": source}).source_record_id == "T1"
    with pytest.raises(AssessmentError, match="source record"):
        validate_assessment({"source_record_id": "missing", "quote": "binder", "stance": "SUPPORTS", "rationale": "direct"}, {"T1": source})


def test_quote_must_be_exact_substring():
    source = record()
    with pytest.raises(AssessmentError, match="exact substring"):
        validate_assessment({"source_record_id": "T1", "quote": "binder was not unavailable", "stance": "SUPPORTS", "rationale": "direct"}, {"T1": source})


def test_invalid_stance_is_rejected():
    with pytest.raises(AssessmentError, match="stance"):
        validate_assessment({"source_record_id": "T1", "quote": "binder", "stance": "MAYBE", "rationale": "direct"}, {"T1": record()})


def test_stale_direct_evidence_is_marked_and_not_current_support():
    evidence = validate_assessment({"source_record_id": "OLD", "quote": "checklist", "stance": "SUPPORTS", "rationale": "old"}, {"OLD": record("OLD", "checklist missing", days=365)})
    assert evidence.stale and summarize_status([evidence])[0] == Status.INSUFFICIENT


@pytest.mark.parametrize("fresh_stance", [Stance.SUPPORTS, Stance.CONTRADICTS])
def test_stale_contradiction_is_reported_without_being_counted_as_fresh(fresh_stance):
    now = datetime.now(timezone.utc)
    fresh = Evidence(source_record_id="CURRENT", timestamp=now, quote="current", stance=fresh_stance, rationale="current", department="Front Office")
    stale = Evidence(source_record_id="OLD-OPPOSITE", timestamp=now-timedelta(days=365), quote="old opposite", stance=Stance.CONTRADICTS if fresh_stance == Stance.SUPPORTS else Stance.SUPPORTS, rationale="historical", department="Front Office", stale=True)
    status, _, uncertainty, conflicts, _ = summarize_status([fresh, stale])
    assert status == Status.PARTIAL
    assert summarize_status([fresh, stale])[1] == 0.54
    assert "stale" in uncertainty
    assert any("OLD-OPPOSITE" in item and "historical context" in item for item in conflicts)


def test_stale_only_contradiction_is_insufficient_but_not_called_false():
    stale = Evidence(source_record_id="OLD", timestamp=datetime.now(timezone.utc)-timedelta(days=365), quote="old contradiction", stance=Stance.CONTRADICTS, rationale="historical", department="Front Office", stale=True)
    status, _, uncertainty, conflicts, _ = summarize_status([stale])
    assert status == Status.INSUFFICIENT
    assert "not treated as current proof or automatically false" in uncertainty
    assert any("OLD" in item for item in conflicts)


def _status_evidence(source_id, stance, *, review_state=EvidenceReviewState.ACCEPTED,
                     stale=False, department="Front Office"):
    return Evidence(
        source_record_id=source_id,
        timestamp=datetime.now(timezone.utc) - timedelta(days=365 if stale else 1),
        quote=f"quote from {source_id}",
        stance=stance,
        review_state=review_state,
        rationale="status regression fixture",
        stale=stale,
        department=department,
    )


def test_stale_unverified_contradiction_does_not_change_supported_status_or_confidence():
    accepted_support = [
        _status_evidence("SUPPORT-A", Stance.SUPPORTS, department="Front Office"),
        _status_evidence("SUPPORT-B", Stance.SUPPORTS, department="Housekeeping"),
    ]
    baseline = summarize_status(accepted_support)
    stale_unverified_contradiction = _status_evidence(
        "UNVERIFIED-OLD-CONTRADICTION", Stance.CONTRADICTS,
        review_state=EvidenceReviewState.UNVERIFIED, stale=True,
    )

    result = summarize_status([*accepted_support, stale_unverified_contradiction])

    assert baseline[0:2] == (Status.SUPPORTED, 0.78)
    assert result[0:2] == baseline[0:2]
    assert any("UNVERIFIED-OLD-CONTRADICTION" in item for item in result[3])


def test_stale_unverified_support_does_not_change_contradiction_status_or_confidence():
    accepted_contradiction = _status_evidence("CONTRADICTION", Stance.CONTRADICTS)
    baseline = summarize_status([accepted_contradiction])
    stale_unverified_support = _status_evidence(
        "UNVERIFIED-OLD-SUPPORT", Stance.SUPPORTS,
        review_state=EvidenceReviewState.UNVERIFIED, stale=True,
    )

    result = summarize_status([accepted_contradiction, stale_unverified_support])

    assert baseline[0:2] == (Status.CONTRADICTED, 0.58)
    assert result[0:2] == baseline[0:2]
    assert any("UNVERIFIED-OLD-SUPPORT" in item for item in result[3])


@pytest.mark.parametrize("unverified_stance", [Stance.SUPPORTS, Stance.CONTRADICTS])
def test_fresh_unverified_evidence_does_not_change_status_or_confidence_and_is_annotated(
    unverified_stance,
):
    accepted_support = _status_evidence("ACCEPTED-SUPPORT", Stance.SUPPORTS)
    baseline = summarize_status([accepted_support])
    unverified = _status_evidence(
        f"UNVERIFIED-{unverified_stance.value}", unverified_stance,
        review_state=EvidenceReviewState.UNVERIFIED,
    )

    result = summarize_status([accepted_support, unverified])

    assert baseline[0:2] == (Status.PARTIAL, 0.55)
    assert result[0:2] == baseline[0:2]
    assert any("unverified proposals" in item.casefold() for item in result[3])
    assert any(unverified.source_record_id in item for item in result[3])


@pytest.mark.parametrize("unverified_stance", [Stance.SUPPORTS, Stance.CONTRADICTS])
def test_only_fresh_unverified_evidence_has_same_status_and_confidence_as_no_evidence(
    unverified_stance,
):
    unverified = _status_evidence(
        f"UNVERIFIED-ONLY-{unverified_stance.value}", unverified_stance,
        review_state=EvidenceReviewState.UNVERIFIED,
    )

    baseline = summarize_status([])
    result = summarize_status([unverified])

    assert result[0:2] == baseline[0:2] == (Status.INSUFFICIENT, 0.2)
    assert any(unverified.source_record_id in item for item in result[3])


@pytest.mark.parametrize(
    "stance",
    [Stance.SUPPORTS, Stance.CONTRADICTS, Stance.NEUTRAL],
    ids=["support", "contradiction", "neutral"],
)
def test_stale_unverified_only_does_not_change_empty_status_or_confidence(stance):
    baseline = summarize_status([])
    stale_unverified = _status_evidence(
        f"STALE-UNVERIFIED-{stance.value}", stance,
        review_state=EvidenceReviewState.UNVERIFIED, stale=True,
    )

    result = summarize_status([stale_unverified])

    assert baseline[0:2] == (Status.INSUFFICIENT, 0.2)
    assert result[0:2] == baseline[0:2]
    assert any("unverified proposals" in item.casefold() for item in result[3])
    assert any(stale_unverified.source_record_id in item for item in result[3])


@pytest.mark.parametrize(
    "stance,stale,source_id",
    [
        (Stance.SUPPORTS, True, "UNVERIFIED-STALE-SUPPORT"),
        (Stance.CONTRADICTS, True, "UNVERIFIED-STALE-CONTRADICTION"),
        (Stance.SUPPORTS, False, "UNVERIFIED-FRESH-SUPPORT"),
        (Stance.CONTRADICTS, False, "UNVERIFIED-FRESH-CONTRADICTION"),
    ],
    ids=["stale-support", "stale-contradiction", "fresh-support", "fresh-contradiction"],
)
def test_stale_accepted_contradiction_behavior_is_unchanged_by_unverified_evidence(
    stance, stale, source_id,
):
    accepted_evidence = [
        _status_evidence("CURRENT-ACCEPTED-SUPPORT", Stance.SUPPORTS),
        _status_evidence("OLD-ACCEPTED-CONTRADICTION", Stance.CONTRADICTS, stale=True),
    ]
    baseline = summarize_status(accepted_evidence)
    unverified = _status_evidence(
        source_id, stance, review_state=EvidenceReviewState.UNVERIFIED, stale=stale,
    )

    result = summarize_status([*accepted_evidence, unverified])

    assert baseline[0:2] == (Status.PARTIAL, 0.54)
    assert result[0:2] == baseline[0:2]
    assert any("unverified proposals" in item.casefold() for item in result[3])
    assert any(source_id in item for item in result[3])


def test_both_unverified_stances_do_not_change_accepted_status_or_confidence():
    accepted_support = _status_evidence("ACCEPTED-SUPPORT-BASELINE", Stance.SUPPORTS)
    baseline = summarize_status([accepted_support])
    unverified_support = _status_evidence(
        "UNVERIFIED-SUPPORT-TOGETHER", Stance.SUPPORTS,
        review_state=EvidenceReviewState.UNVERIFIED,
    )
    unverified_contradiction = _status_evidence(
        "UNVERIFIED-CONTRADICTION-TOGETHER", Stance.CONTRADICTS,
        review_state=EvidenceReviewState.UNVERIFIED,
    )

    result = summarize_status([
        accepted_support, unverified_support, unverified_contradiction,
    ])

    assert baseline[0:2] == (Status.PARTIAL, 0.55)
    assert result[0:2] == baseline[0:2]
    assert any("unverified proposals" in item.casefold() for item in result[3])
    assert any(unverified_support.source_record_id in item for item in result[3])
    assert any(unverified_contradiction.source_record_id in item for item in result[3])


@pytest.mark.parametrize("hypothesis_id,quote", [
    ("CHECKLIST_UNAVAILABLE", "binder was missing"),
    ("TRAINING_GAP", "colleague was unsure"),
    ("STAFFING_CONSTRAINTS", "understaffed"),
    ("PMS_SYSTEM_ISSUE", "system timed out"),
    ("TIME_PRESSURE", "not enough time"),
])
def test_claim_missing_evidence_uses_hypothesis_advisory_without_changing_reasoning(hypothesis_id, quote):
    source = record("COVERAGE-SOURCE", quote)
    provider = MockProvider(assessment_overrides={
        hypothesis_id: [{"source_record_id": source.id, "quote": quote,
                         "stance": "SUPPORTS", "rationale": "synthetic fixture"}],
    })
    claim = AssessmentEngine(provider).assess_hypothesis([source], hypothesis_id)
    expected = summarize_status([Evidence.model_validate(item) for item in claim["evidence"]])
    coverage = evidence_coverage(hypothesis_id, [Evidence.model_validate(item) for item in claim["evidence"]])
    primary = coverage["categories"][0]

    assert (claim["status"], claim["confidence"], claim["uncertainty"], claim["conflicts"]) == (
        expected[0].value, expected[1], expected[2], expected[3],
    )
    assert claim["dependencies"] == [source.id]
    assert claim["evidence"][0]["review_state"] == "ACCEPTED"
    assert primary["covered_by_fresh_accepted"] is True
    assert all("A recent handover record that directly addresses this hypothesis." not in item
               for item in claim["missing_evidence"])
    assert any(coverage["categories"][1]["description"] in item
               for item in claim["missing_evidence"])


def test_challenge_recomputation_keeps_coverage_advisory_only():
    source = record("CHALLENGE-COVERAGE", "The checklist was unavailable during handover.")
    provider = MockProvider(assessment_overrides={"CHECKLIST_UNAVAILABLE": [
        {"source_record_id": source.id, "quote": source.text,
         "stance": "SUPPORTS", "rationale": "synthetic fixture"},
    ]})
    engine = AssessmentEngine(provider)
    before = engine.assess_hypothesis([source], "CHECKLIST_UNAVAILABLE")

    after = engine.challenge(before, [source], source.id, "checklist was unavailable")
    recomputed = summarize_status([Evidence.model_validate(item) for item in after["evidence"]])

    assert (after["status"], after["confidence"], after["uncertainty"], after["conflicts"]) == (
        recomputed[0].value, recomputed[1], recomputed[2], recomputed[3],
    )
    assert after["evidence"][0]["review_state"] == before["evidence"][0]["review_state"] == "ACCEPTED"
    assert after["evidence"][0]["disputed"] is True
    assert after["dependencies"] == before["dependencies"] == [source.id]
    assert any("challenged evidence" in item for item in after["missing_evidence"])


def test_provider_emits_neutral_for_related_but_nonsemantic_match():
    pair = MockProvider().assess([next(r for r in SEED_RECORDS if r.id == "OPS-108")], "CHECKLIST_UNAVAILABLE")
    assert pair and pair[0]["stance"] == "NEUTRAL"


def test_semantic_guard_disabled_accepts_unmatched_proposal_and_default_application_is_guarded():
    source = record("GUARD-DISABLED", "A desk lamp was replaced before dinner.")
    proposal = {
        "source_record_id": source.id,
        "quote": source.text,
        "stance": Stance.SUPPORTS.value,
        "rationale": "synthetic proposal",
    }
    provider = MockProvider(assessment_overrides={
        "CHECKLIST_UNAVAILABLE": [proposal],
        **{item.id: [] for item in HYPOTHESES if item.id != "CHECKLIST_UNAVAILABLE"},
    })

    baseline_engine = AssessmentEngine(provider, semantic_guard=False)
    baseline_item = Evidence(
        source_record_id=source.id,
        timestamp=source.timestamp,
        quote=source.text,
        stance=Stance.SUPPORTS,
        rationale="synthetic baseline evidence",
        department=source.department,
    )
    assert "review_state" not in baseline_item.model_fields_set
    baseline_engine._review_item(baseline_item, "CHECKLIST_UNAVAILABLE")
    assert baseline_item.review_state == EvidenceReviewState.ACCEPTED
    assert "review_state" in baseline_item.model_fields_set

    provisional_item = validate_assessment(proposal, {source.id: source})
    assert provisional_item.review_state == EvidenceReviewState.UNVERIFIED
    assert "review_state" in provisional_item.model_fields_set
    baseline_engine._review_item(provisional_item, "CHECKLIST_UNAVAILABLE")
    assert provisional_item.review_state == EvidenceReviewState.ACCEPTED

    disabled = baseline_engine.assess_hypothesis(
        [source], "CHECKLIST_UNAVAILABLE"
    )
    disabled_evidence = disabled["evidence"][0]
    assert disabled_evidence["review_state"] == EvidenceReviewState.ACCEPTED.value
    assert disabled_evidence["proposed_stance"] is None
    assert disabled["status"] == Status.PARTIAL.value
    assert disabled["confidence"] == 0.55
    assert not any("unverified proposals" in item.casefold() for item in disabled["conflicts"])

    enabled = AssessmentEngine(provider).assess_hypothesis(
        [source], "CHECKLIST_UNAVAILABLE"
    )
    enabled_evidence = enabled["evidence"][0]
    assert enabled_evidence["review_state"] == EvidenceReviewState.UNVERIFIED.value
    assert enabled_evidence["proposed_stance"] == Stance.SUPPORTS.value
    assert enabled["status"] == Status.INSUFFICIENT.value
    assert enabled["confidence"] == 0.2
    assert any("unverified proposals" in item.casefold() for item in enabled["conflicts"])

    from app.main import engine as application_engine
    assert application_engine.semantic_guard is True


def test_evaluation_entrypoint_runs_unguarded_baseline_then_guarded_pass(monkeypatch):
    from app import evaluate

    guarded_modes = []

    def fake_run_evaluation(*, guarded=True, failure_injector=None):
        guarded_modes.append(guarded)
        return {"semantic_guard": guarded}

    monkeypatch.setattr(evaluate, "run_evaluation", fake_run_evaluation)
    monkeypatch.setattr(evaluate.json, "dumps", lambda *_args, **_kwargs: "{}")

    evaluate.main()

    assert guarded_modes == [False, True]


def test_omitted_review_state_defaults_to_accepted_and_counts_in_status():
    omitted = Evidence(
        source_record_id="OMITTED-STATE",
        timestamp=datetime.now(timezone.utc),
        quote="short staffed",
        stance=Stance.SUPPORTS,
        rationale="legacy construction without review state",
        department="Front Office",
    )

    assert omitted.review_state == EvidenceReviewState.ACCEPTED
    assert summarize_status([omitted])[0] == Status.PARTIAL


def test_explicit_review_state_values_control_status_counting():
    base = {
        "timestamp": datetime.now(timezone.utc),
        "quote": "short staffed",
        "stance": Stance.SUPPORTS,
        "rationale": "explicit review state",
        "department": "Front Office",
    }
    accepted = Evidence(source_record_id="EXPLICIT-ACCEPTED", **base,
                        review_state=EvidenceReviewState.ACCEPTED)
    unverified = Evidence(source_record_id="EXPLICIT-UNVERIFIED", **base,
                         review_state=EvidenceReviewState.UNVERIFIED)

    assert summarize_status([accepted])[0] == Status.PARTIAL
    assert summarize_status([unverified])[0] == Status.INSUFFICIENT


def _claim_with_challenge_evidence(source, review_state_marker=...):
    evidence = {
        "source_record_id": source.id,
        "timestamp": source.timestamp.isoformat(),
        "quote": source.text,
        "stance": Stance.SUPPORTS.value,
        "rationale": "legacy evidence for challenge revalidation",
        "stale": False,
        "department": source.department,
        "source_group": source.id,
        "disputed": False,
    }
    if review_state_marker is not ...:
        evidence["review_state"] = review_state_marker
    return {
        "id": "CHECKLIST_UNAVAILABLE",
        "hypothesis_id": "CHECKLIST_UNAVAILABLE",
        "status": Status.PARTIAL.value,
        "confidence": 0.55,
        "uncertainty": "legacy claim",
        "summary": "legacy claim",
        "evidence": [evidence],
        "conflicts": [],
        "missing_evidence": [],
        "dependencies": [source.id],
        "version": 1,
    }


@pytest.mark.parametrize(
    "state_marker,expected_state,expected_status",
    [
        (..., EvidenceReviewState.UNVERIFIED, Status.INSUFFICIENT),
        (EvidenceReviewState.ACCEPTED.value, EvidenceReviewState.ACCEPTED, Status.PARTIAL),
        (EvidenceReviewState.UNVERIFIED.value, EvidenceReviewState.UNVERIFIED, Status.INSUFFICIENT),
    ],
    ids=["missing-becomes-unverified", "explicit-accepted-preserved", "explicit-unverified-preserved"],
)
def test_guarded_challenge_revalidation_preserves_explicit_states_and_marks_omission_unverified(
    state_marker, expected_state, expected_status,
):
    source = record("LEGACY-CHALLENGE", "The checklist was unavailable during handover.")
    current = _claim_with_challenge_evidence(source, state_marker)

    engine = AssessmentEngine()
    revised = engine.challenge(current, [source], source.id, source.text)
    evidence = revised["evidence"][0]

    assert evidence["review_state"] == expected_state.value
    assert evidence["disputed"] is True
    assert revised["status"] == expected_status.value
    if state_marker is ...:
        assert any("unverified proposals" in item.casefold() for item in revised["conflicts"])

    # The serialized reconstruction has an explicit state, so a second challenge
    # cannot silently restore the model's ACCEPTED default.
    repeated = engine.challenge(revised, [source], source.id, source.text)
    assert repeated["evidence"][0]["review_state"] == expected_state.value
    assert repeated["status"] == expected_status.value


def test_unverified_legacy_support_does_not_override_explicit_contradiction_on_challenge():
    support_source = record(
        "LEGACY-SUPPORT", "The checklist was unavailable during handover."
    )
    contradiction_source = record(
        "EXPLICIT-CONTRADICTION", "The checklist was available during handover."
    )
    current = _claim_with_challenge_evidence(support_source)
    current["evidence"].append({
        "source_record_id": contradiction_source.id,
        "timestamp": contradiction_source.timestamp.isoformat(),
        "quote": contradiction_source.text,
        "stance": Stance.CONTRADICTS.value,
        "review_state": EvidenceReviewState.ACCEPTED.value,
        "rationale": "explicit contradiction retained",
        "stale": False,
        "department": contradiction_source.department,
        "source_group": contradiction_source.id,
        "disputed": False,
    })
    current["dependencies"].append(contradiction_source.id)

    revised = AssessmentEngine().challenge(
        current, [support_source, contradiction_source],
        support_source.id, support_source.text,
    )

    assert revised["evidence"][0]["review_state"] == EvidenceReviewState.UNVERIFIED.value
    assert revised["evidence"][1]["review_state"] == EvidenceReviewState.ACCEPTED.value
    assert revised["status"] == Status.CONTRADICTED.value


@pytest.mark.parametrize(
    "quote,stance,expected_state,expected_status,expected_confidence,has_review_annotation",
    [
        ("The checklist was unavailable during handover.", Stance.SUPPORTS,
         EvidenceReviewState.ACCEPTED, Status.PARTIAL, 0.55, False),
        ("A desk lamp was replaced before dinner.", Stance.SUPPORTS,
         EvidenceReviewState.UNVERIFIED, Status.INSUFFICIENT, 0.2, True),
    ],
    ids=["guard-accepts-matching-cue", "guard-abstains-on-unmatched-cue"],
)
def test_new_guarded_assessment_serializes_explicit_review_state(
    quote, stance, expected_state, expected_status, expected_confidence,
    has_review_annotation,
):
    source = record("NEW-GUARDED", quote)
    proposal = {
        "source_record_id": source.id,
        "quote": quote,
        "stance": stance.value,
        "rationale": "synthetic proposal",
    }
    provider = MockProvider(assessment_overrides={
        "CHECKLIST_UNAVAILABLE": [proposal],
        **{item.id: [] for item in HYPOTHESES if item.id != "CHECKLIST_UNAVAILABLE"},
    })

    claim = AssessmentEngine(provider).assess_hypothesis([source], "CHECKLIST_UNAVAILABLE")

    assert claim["evidence"][0]["review_state"] == expected_state.value
    assert claim["status"] == expected_status.value
    assert claim["confidence"] == expected_confidence
    assert any("unverified proposals" in item.casefold() for item in claim["conflicts"]) is has_review_annotation


@pytest.mark.parametrize("text,stance,expected_state", [
    ("The binder stayed on its shelf throughout the shift.", "SUPPORTS", EvidenceReviewState.UNVERIFIED),
    ("Everyone had the handover checklist in front of them.", "CONTRADICTS", EvidenceReviewState.UNVERIFIED),
    ("The binder was missing, but the checklist was available.", "SUPPORTS", EvidenceReviewState.UNVERIFIED),
    ("The desk lamp was replaced; this says nothing about checklist availability.", "NEUTRAL", EvidenceReviewState.ACCEPTED),
    ("The checklist was unavailable during handover.", "NEUTRAL", EvidenceReviewState.UNVERIFIED),
    ("The checklist was available during handover.", "NEUTRAL", EvidenceReviewState.UNVERIFIED),
    ("The checklist was unavailable, but also available at handover.", "NEUTRAL", EvidenceReviewState.UNVERIFIED),
    ("A desk lamp was replaced before dinner.", "NEUTRAL", EvidenceReviewState.UNVERIFIED),
])
def test_neutral_and_directional_guard_proposals_require_matching_explicit_cues(text, stance, expected_state):
    source = record("SEMANTIC", text)
    proposal = {"source_record_id": source.id, "quote": text, "stance": stance, "rationale": "synthetic proposal"}
    provider = MockProvider(assessment_overrides={
        "CHECKLIST_UNAVAILABLE": [proposal],
        **{item.id: [] for item in HYPOTHESES if item.id != "CHECKLIST_UNAVAILABLE"},
    })
    claim = AssessmentEngine(provider, semantic_guard=True).assess_hypothesis([source], "CHECKLIST_UNAVAILABLE")
    evidence = claim["evidence"][0]
    assert evidence["review_state"] == expected_state.value
    assert evidence["proposed_stance"] == stance
    if expected_state == EvidenceReviewState.UNVERIFIED:
        assert evidence["stance"] == stance
        assert claim["status"] == Status.INSUFFICIENT.value
        assert "human review" in " ".join(claim["conflicts"]).casefold()
    else:
        assert evidence["stance"] == "NEUTRAL"
        assert claim["status"] == Status.INSUFFICIENT.value


@pytest.mark.parametrize("text,stance", [
    ("The team was not short staffed during the shift.", Stance.SUPPORTS),
    ("The team was not understaffed during the shift.", Stance.SUPPORTS),
    ("There were not enough people on duty.", Stance.CONTRADICTS),
])
def test_directly_negated_supporting_or_contradicting_cue_abstains(text, stance):
    source = record("NEGATED-CUE", text)
    proposal = {
        "source_record_id": source.id,
        "quote": text,
        "stance": stance.value,
        "rationale": "synthetic proposal",
    }
    provider = MockProvider(assessment_overrides={
        "STAFFING_CONSTRAINTS": [proposal],
        **{item.id: [] for item in HYPOTHESES if item.id != "STAFFING_CONSTRAINTS"},
    })

    claim = AssessmentEngine(provider, semantic_guard=True).assess_hypothesis(
        [source], "STAFFING_CONSTRAINTS"
    )

    evidence = claim["evidence"][0]
    assert evidence["proposed_stance"] == stance.value
    assert evidence["review_state"] == EvidenceReviewState.UNVERIFIED.value
    assert evidence["stance"] == stance.value
    assert claim["status"] == Status.INSUFFICIENT.value


@pytest.mark.parametrize("quote,expected", [
    ("The department is short staffed.", Stance.SUPPORTS),
    ("We are experiencing understaffing.", None),  # Not an existing cue phrase.
    ("not bad, team short staffed", Stance.SUPPORTS),
    ("we were short staffed, but are not now", None),
    ("not short staffed, but short staffed again", Stance.SUPPORTS),
    ("Not bad. The team was short staffed.", Stance.SUPPORTS),
    ("The team was not, short staffed.", None),
    ("THE TEAM WAS   NOT   SHORT   STAFFED.", None),
    ("THE DEPARTMENT IS   SHORT   STAFFED.", Stance.SUPPORTS),
    ("There are enough people on duty.", Stance.CONTRADICTS),
    ("There are not enough people on duty.", None),
])
def test_staffing_phrase_guard_exact_outcomes(quote, expected):
    assert reviewed_relation(quote, "STAFFING_CONSTRAINTS") == expected


@pytest.mark.parametrize("quote,expected", [
    ("The checklist was available during handover.", Stance.CONTRADICTS),
    ("The checklist was not available during handover.", None),
    ("The checklist was unavailable during handover.", Stance.SUPPORTS),
    ("The checklist was not unavailable during handover.", None),
    ("The checklist was unavailable, but available now.", None),
])
def test_checklist_support_and_contradiction_cues_keep_stance_direction(quote, expected):
    assert reviewed_relation(quote, "CHECKLIST_UNAVAILABLE") == expected


@pytest.mark.parametrize("quote", [
    "The department is short staffed.",
    "not bad, team short staffed",
    "we were short staffed, but are not now",
])
def test_staffing_guard_outcomes_keep_engine_proposals_for_review(quote):
    source = record("STAFFING-REVIEW", quote)
    proposal = {
        "source_record_id": source.id,
        "quote": quote,
        "stance": Stance.SUPPORTS.value,
        "rationale": "synthetic proposal",
    }
    provider = MockProvider(assessment_overrides={
        "STAFFING_CONSTRAINTS": [proposal],
        **{item.id: [] for item in HYPOTHESES if item.id != "STAFFING_CONSTRAINTS"},
    })
    claim = AssessmentEngine(provider, semantic_guard=True).assess_hypothesis(
        [source], "STAFFING_CONSTRAINTS"
    )
    evidence = claim["evidence"][0]
    assert evidence["proposed_stance"] == Stance.SUPPORTS.value
    if reviewed_relation(quote, "STAFFING_CONSTRAINTS") == Stance.SUPPORTS:
        assert evidence["review_state"] == EvidenceReviewState.ACCEPTED.value
        assert claim["status"] == Status.PARTIAL.value
    else:
        assert evidence["review_state"] == EvidenceReviewState.UNVERIFIED.value
        assert evidence["stance"] == Stance.SUPPORTS.value
        assert claim["status"] == Status.INSUFFICIENT.value
        assert "human review" in " ".join(claim["conflicts"]).casefold()


def test_unverified_challenge_proposal_remains_unaccepted_and_insufficient():
    source = record("CHALLENGE-SEMANTIC", "The checklist was unavailable during handover.")
    empty = MockProvider(assessment_overrides={h.id: [] for h in HYPOTHESES})
    current = AssessmentEngine(empty).assess_hypothesis([source], "CHECKLIST_UNAVAILABLE")
    proposal = {"source_record_id": source.id, "quote": source.text, "stance": "CONTRADICTS", "rationale": "synthetic proposal"}
    proposing = MockProvider(assessment_overrides={
        "CHECKLIST_UNAVAILABLE": [proposal],
        **{h.id: [] for h in HYPOTHESES if h.id != "CHECKLIST_UNAVAILABLE"},
    })
    changed = AssessmentEngine(proposing).challenge(current, [source], source.id, source.text)
    added = changed["evidence"][0]
    assert added["proposed_stance"] == "CONTRADICTS"
    assert added["semantic_relation"] == "SUPPORTS"
    assert added["review_state"] == EvidenceReviewState.UNVERIFIED.value
    assert added["disputed"] is True
    assert changed["status"] == Status.INSUFFICIENT.value
    assert "unverified proposals" in " ".join(changed["conflicts"]).casefold()


def test_restricted_record_is_excluded_by_provider_and_default_access():
    canary = next(r for r in SEED_RECORDS if r.restricted)
    assert canary not in visible_records(SEED_RECORDS)
    assert canary in visible_records(SEED_RECORDS, AccessContext(can_view_restricted=True))
    assert canary.id not in [a["source_record_id"] for a in MockProvider().assess(SEED_RECORDS, "TIME_PRESSURE")]


def test_engine_filters_restricted_records_before_provider_call():
    claims = AssessmentEngine().investigate(SEED_RECORDS)
    assert len(claims) == 5
    assert all("CANARY-RESTRICTED-001" not in {item["source_record_id"] for item in claim["evidence"]} for claim in claims)


@pytest.mark.parametrize("proposal", [
    {"source_record_id": "INVENTED", "quote": "binder", "stance": "SUPPORTS", "rationale": "direct"},
    {"source_record_id": "T1", "quote": "a fabricated quote", "stance": "SUPPORTS", "rationale": "direct"},
    {"source_record_id": "T1", "quote": "binder", "stance": "SUPPORTS", "rationale": "direct", "status": "SUPPORTED"},
    None,
])
def test_provider_proposals_with_unknown_sources_bad_quotes_or_bad_shape_fail_closed(proposal):
    provider = MockProvider(assessment_overrides={hypothesis.id: [proposal] for hypothesis in HYPOTHESES})
    with pytest.raises(ProviderError):
        AssessmentEngine(provider).investigate([record("T1", "The binder is available.")])


def test_provider_abstention_produces_insufficient_claims():
    provider = MockProvider(assessment_overrides={hypothesis.id: [] for hypothesis in HYPOTHESES})
    claims = AssessmentEngine(provider).investigate([record()])
    assert all(claim["status"] == Status.INSUFFICIENT.value for claim in claims)


def test_challenge_marks_evidence_disputed_and_changes_supported_to_partial():
    provider = MockProvider(assessment_overrides={
        "CHECKLIST_UNAVAILABLE": [
            {"source_record_id": "A", "quote": "checklist unavailable", "stance": "SUPPORTS", "rationale": "direct"},
            {"source_record_id": "B", "quote": "binder was missing", "stance": "SUPPORTS", "rationale": "direct"},
        ],
        **{hypothesis.id: [] for hypothesis in HYPOTHESES if hypothesis.id != "CHECKLIST_UNAVAILABLE"},
    })
    records = [record("A", "The checklist unavailable overnight.", "Front Office"), record("B", "The binder was missing at handover.", "Housekeeping")]
    engine = AssessmentEngine(provider)
    claim = engine.investigate(records)[0]
    assert claim["status"] == Status.SUPPORTED.value
    changed = engine.challenge(claim, records, "A", "checklist unavailable")
    assert changed["status"] == Status.PARTIAL.value
    assert changed["evidence"][0]["disputed"] is True


def test_second_assessed_dependency_can_be_challenged_after_first_is_disputed():
    engine = AssessmentEngine()
    records = SEED_RECORDS
    claim = next(
        item for item in engine.investigate(records)
        if item["id"] == "CHECKLIST_UNAVAILABLE"
    )
    assert {item["source_record_id"] for item in claim["evidence"]} >= {"OPS-101", "OPS-102"}

    first = engine.challenge(claim, records, "OPS-101", "binder was missing")
    second = engine.challenge(first, records, "OPS-102", "checklist opened normally")

    assert first["version"] == 2
    assert second["version"] == 3
    disputed_sources = {
        item["source_record_id"]
        for item in second["evidence"]
        if item["disputed"]
    }
    assert {"OPS-101", "OPS-102"} <= disputed_sources


def test_unassessed_source_remains_rejected_after_an_unrelated_prior_dispute():
    engine = AssessmentEngine()
    claim = next(
        item for item in engine.investigate(SEED_RECORDS)
        if item["id"] == "CHECKLIST_UNAVAILABLE"
    )
    challenged = engine.challenge(claim, SEED_RECORDS, "OPS-101", "binder was missing")
    before_rejected_request = deepcopy(challenged)

    with pytest.raises(AssessmentError, match="not an assessed dependency"):
        engine.challenge(challenged, SEED_RECORDS, "OPS-111", "guest called about a lamp")

    assert challenged == before_rejected_request


def test_invalid_quote_remains_rejected_after_a_prior_dispute():
    engine = AssessmentEngine()
    claim = next(
        item for item in engine.investigate(SEED_RECORDS)
        if item["id"] == "CHECKLIST_UNAVAILABLE"
    )
    challenged = engine.challenge(claim, SEED_RECORDS, "OPS-101", "binder was missing")

    with pytest.raises(AssessmentError, match="exact source substring"):
        engine.challenge(challenged, SEED_RECORDS, "OPS-102", "fabricated checklist wording")


def test_challenge_requires_exact_quote_and_assessed_dependency():
    claim = AssessmentEngine().investigate(SEED_RECORDS)[0]
    with pytest.raises(AssessmentError, match="exact source substring"):
        AssessmentEngine().challenge(claim, SEED_RECORDS, "OPS-101", "fabricated quote")
    with pytest.raises(AssessmentError, match="not an assessed dependency"):
        AssessmentEngine().challenge(claim, SEED_RECORDS, "OPS-111", "guest called about a lamp")


def test_each_required_hypothesis_is_present():
    ids = {c["hypothesis_id"] for c in AssessmentEngine().investigate(SEED_RECORDS)}
    assert ids == {"CHECKLIST_UNAVAILABLE", "TRAINING_GAP", "STAFFING_CONSTRAINTS", "PMS_SYSTEM_ISSUE", "TIME_PRESSURE"}


@pytest.mark.parametrize(
    "hypothesis_id",
    ["TIME_PRESSURE", "CHECKLIST_UNAVAILABLE", "STAFFING_CONSTRAINTS", "PMS_SYSTEM_ISSUE"],
)
def test_assess_hypothesis_returns_only_the_requested_supported_hypothesis(hypothesis_id):
    engine = AssessmentEngine()

    claim = engine.assess_hypothesis(SEED_RECORDS, hypothesis_id)

    assert claim["id"] == hypothesis_id
    assert claim["hypothesis_id"] == hypothesis_id
    assert engine.provider.assessment_history == (hypothesis_id,)


def test_assess_hypothesis_rejects_unknown_hypothesis():
    with pytest.raises(AssessmentError, match="Unknown hypothesis"):
        AssessmentEngine().assess_hypothesis(SEED_RECORDS, "CLIENT_DEFINED_HYPOTHESIS")


def test_evidence_quotes_are_verbatim_and_never_empty():
    claims = AssessmentEngine().investigate(SEED_RECORDS)
    source_by_id = {r.id: r.text for r in SEED_RECORDS}
    for claim in claims:
        for evidence in claim["evidence"]:
            assert evidence["quote"] in source_by_id[evidence["source_record_id"]]
            assert evidence["quote"].strip()


def test_duplicate_provider_assessments_are_deduplicated():
    proposal = {"source_record_id": "A", "quote": "checklist missing", "stance": "SUPPORTS", "rationale": "direct"}
    provider = MockProvider(assessment_overrides={
        "CHECKLIST_UNAVAILABLE": [proposal, proposal],
        **{hypothesis.id: [] for hypothesis in HYPOTHESES if hypothesis.id != "CHECKLIST_UNAVAILABLE"},
    })
    claims = AssessmentEngine(provider).investigate([record("A", "checklist missing")])
    assert len(claims[0]["evidence"]) == 1


def test_arbitrary_local_provider_is_rejected_before_assessment():
    class UntrustedProvider(LocalAssessmentProvider):
        calls = 0
        def assess(self, records, hypothesis_id):
            self.calls += 1
            return []

    provider = UntrustedProvider()
    with pytest.raises(ProviderSafetyError) as error:
        AssessmentEngine(provider)
    assert error.value.code == "unsupported_provider"
    assert provider.calls == 0


def test_mock_provider_subclass_cannot_replace_the_approved_provider_type():
    class ReplacedMockProvider(MockProvider):
        pass
    with pytest.raises(ProviderSafetyError) as error:
        AssessmentEngine(ReplacedMockProvider())
    assert error.value.code == "unsupported_provider"


def test_mock_provider_assess_method_cannot_be_reassigned_per_instance():
    provider = MockProvider()
    with pytest.raises(AttributeError):
        provider.assess = lambda *_args: []


def test_engine_configuration_is_immutable_and_runtime_default_is_mock():
    from app.main import engine as runtime_engine
    assert type(runtime_engine.provider) is MockProvider
    engine = AssessmentEngine()
    with pytest.raises(AttributeError):
        engine.provider_boundary = object()

