"""Deterministic evidence rules and challenge behavior (synthetic records only)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.access import AccessContext, visible_records
from app.engine import AssessmentEngine, AssessmentError, ProviderError, summarize_status, validate_assessment
from app.mock_provider import MockProvider, SEED_RECORDS
from app.models import ChallengeCreate, Evidence, EvidenceReviewState, HYPOTHESES, Record, Status, Stance
from app.provider_safety import LocalAssessmentProvider, ProviderSafetyError


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
    assert "stale" in uncertainty
    assert any("OLD-OPPOSITE" in item and "historical context" in item for item in conflicts)


def test_stale_only_contradiction_is_insufficient_but_not_called_false():
    stale = Evidence(source_record_id="OLD", timestamp=datetime.now(timezone.utc)-timedelta(days=365), quote="old contradiction", stance=Stance.CONTRADICTS, rationale="historical", department="Front Office", stale=True)
    status, _, uncertainty, conflicts, _ = summarize_status([stale])
    assert status == Status.INSUFFICIENT
    assert "not treated as current proof or automatically false" in uncertainty
    assert any("OLD" in item for item in conflicts)


def test_provider_emits_neutral_for_related_but_nonsemantic_match():
    pair = MockProvider().assess([next(r for r in SEED_RECORDS if r.id == "OPS-108")], "CHECKLIST_UNAVAILABLE")
    assert pair and pair[0]["stance"] == "NEUTRAL"


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


def test_challenge_requires_exact_quote_and_assessed_dependency():
    claim = AssessmentEngine().investigate(SEED_RECORDS)[0]
    with pytest.raises(AssessmentError, match="exact source substring"):
        AssessmentEngine().challenge(claim, SEED_RECORDS, "OPS-101", "fabricated quote")
    with pytest.raises(AssessmentError, match="not an assessed dependency"):
        AssessmentEngine().challenge(claim, SEED_RECORDS, "OPS-111", "guest called about a lamp")


def test_each_required_hypothesis_is_present():
    ids = {c["hypothesis_id"] for c in AssessmentEngine().investigate(SEED_RECORDS)}
    assert ids == {"CHECKLIST_UNAVAILABLE", "TRAINING_GAP", "STAFFING_CONSTRAINTS", "PMS_SYSTEM_ISSUE", "TIME_PRESSURE"}


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

