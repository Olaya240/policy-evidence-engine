"""Deterministic evidence validation, status calculation, and dependency recomputation."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .decision_table import decide as decide_table, group_key
from .mock_provider import MockProvider
from .models import EvidenceReviewState, HYPOTHESES, Claim, Evidence, Record, Status, Stance
from .evidence_coverage import advisory_missing_evidence, evidence_coverage
from .provider_safety import (ApprovedProviderAdapter, LocalAssessmentProvider,
                              MandatoryProviderBoundary, ProviderSafetyError,
                              eligible_provider_records)
from .semantic_guard import reviewed_relation_details

STALE_DAYS = 90


def _is_stale(timestamp: datetime, evaluated_at: datetime) -> bool:
    """Freshness of one record at one instant, in one place.

    Persisted records can carry an offset-less timestamp, and a record dated after
    the evaluation instant has a negative age that would otherwise read as fresh
    forever. Both the first validation and a later challenge must agree, so the
    rule lives here rather than in each caller.
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = (evaluated_at - timestamp).days
    return age > STALE_DAYS or age < 0


class AssessmentError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_assessment"):
        super().__init__(message)
        self.code = code


class ProviderError(RuntimeError):
    """A provider failed or returned a proposal that cannot be validated."""

    def __init__(self, code: str):
        self.code = code
        super().__init__("Assessment provider failed or returned invalid output")


def _validate_assessment_with_time(raw: dict, records: dict[str, Record], *, now: datetime | None = None) -> tuple[Evidence, datetime]:
    record_id = raw.get("source_record_id")
    if not isinstance(record_id, str) or record_id not in records or records[record_id].restricted:
        raise AssessmentError("Assessment references an unknown or inadmissible source record", code="invalid_source")
    record = records[record_id]
    quote = raw.get("quote")
    if not isinstance(quote, str) or len(quote.strip()) < 3 or quote not in record.text:
        raise AssessmentError("Assessment quote must be an exact substring of its source record", code="invalid_quote")
    try:
        stance = Stance(raw.get("stance"))
    except (ValueError, TypeError):
        raise AssessmentError("Assessment stance must be SUPPORTS, CONTRADICTS, or NEUTRAL", code="invalid_stance")
    rationale = raw.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise AssessmentError("Assessment rationale is required", code="invalid_rationale")
    # Callers that need a reproducible trace supply the clock; the default is
    # unchanged so existing behaviour and tests keep their timestamps.
    evaluated_at = now if now is not None else datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
    # Persisted records can carry a timestamp without an offset (store.py passes
    # the stored text through). Subtracting that from an aware clock raises
    # TypeError, so a single legacy row would turn every citing assessment into
    # an unclassified failure. Stored text is UTC by convention.
    timestamp = record.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    # A record dated after the evaluation instant is not current evidence: the
    # staleness test alone would leave it fresh forever, so a typo'd year would
    # sit in the decisive set indefinitely. It is non-current, not invalid —
    # callers that evaluate against a historical clock would otherwise fail.
    evidence = Evidence(source_record_id=record_id, timestamp=timestamp, quote=quote, stance=stance,
                        review_state=EvidenceReviewState.UNVERIFIED, rationale=rationale.strip(),
                        stale=_is_stale(timestamp, evaluated_at), department=record.department,
                        source_group=record.source_group or record.id)
    return evidence, evaluated_at


def validate_assessment(raw: dict, records: dict[str, Record]) -> Evidence:
    """Validate a proposal while retaining the established public return type."""
    evidence, _evaluated_at = _validate_assessment_with_time(raw, records)
    return evidence


@dataclass
class _StatusDecision:
    status: Status
    confidence: float
    uncertainty: str
    conflicts: list[str]
    missing: list[str]
    status_rule_id: str
    confidence_rule_id: str
    evidence_score: float
    contested: bool
    supports: list[Evidence]
    contradicts: list[Evidence]
    neutrals: list[Evidence]
    stale_support: list[Evidence]
    stale_contradictions: list[Evidence]
    stale_accepted: list[Evidence]
    disputed: list[Evidence]
    unverified: list[Evidence]
    independent_groups: list[dict]
    dependent_support_ids: list[str]


def _summarize_status_decision(evidence: list[Evidence]) -> _StatusDecision:
    fresh = [e for e in evidence if not e.stale]
    accepted = [e for e in fresh if e.review_state == EvidenceReviewState.ACCEPTED]
    supports = [e for e in accepted if e.stance == Stance.SUPPORTS and not e.disputed]
    contradicts = [e for e in accepted if e.stance == Stance.CONTRADICTS and not e.disputed]
    neutrals = [e for e in accepted if e.stance == Stance.NEUTRAL]
    stale_accepted = [
        e for e in evidence
        if e.stale and e.review_state == EvidenceReviewState.ACCEPTED
    ]
    stale_support = [e for e in stale_accepted if e.stance == Stance.SUPPORTS]
    stale_contradictions = [e for e in stale_accepted if e.stance == Stance.CONTRADICTS]
    disputed = [e for e in evidence if e.disputed]
    conflicts = []
    if disputed:
        conflicts.append(f"The user challenged evidence from {', '.join(e.source_record_id for e in disputed)}; retain it for review but do not count it as uncontested evidence.")
    unverified = [e for e in evidence if e.review_state == EvidenceReviewState.UNVERIFIED]
    if unverified:
        conflicts.append(f"Unverified proposals from {', '.join(e.source_record_id for e in unverified)} are retained for human review and do not count as accepted support or contradiction.")
    if supports and contradicts:
        conflicts.append(f"Fresh records point both ways: {', '.join(e.source_record_id for e in supports)} support and {', '.join(e.source_record_id for e in contradicts)} contradict.")
    if stale_support or stale_contradictions:
        stale_parts = []
        if stale_support:
            stale_parts.append(f"supporting: {', '.join(e.source_record_id for e in stale_support)}")
        if stale_contradictions:
            stale_parts.append(f"contradicting: {', '.join(e.source_record_id for e in stale_contradictions)}")
        conflicts.append("Stale evidence is retained as historical context and does not count as current proof (" + "; ".join(stale_parts) + ").")
    independent_support = len({group_key(e) for e in supports})
    departments_by_source = {group_key(e): e for e in supports}
    diverse = len({getattr(e, "department", None) for e in departments_by_source.values()}) > 1 if departments_by_source else False
    group_members: dict[str, list[Evidence]] = {}
    for item in supports:
        group_members.setdefault(group_key(item), []).append(item)
    independent_groups = [
        {
            "source_group_id": group_id,
            "representative_source_record_id": members[-1].source_record_id,
            "member_source_record_ids": [item.source_record_id for item in members],
            "independent_support_count": 1,
        }
        for group_id, members in group_members.items()
    ]
    dependent_support_objects = {id(item) for members in group_members.values() for item in members[:-1]}
    dependent_support_ids = [item.source_record_id for item in supports if id(item) in dependent_support_objects]
    # One signed score replaces the ordered branch table. The proofs are in
    # ct3/DecisionTable.v; `app.decision_table` is the same rule in Python.
    contradiction_groups = len({group_key(e) for e in contradicts})
    disputed_fresh_accepted = [
        e for e in disputed
        if e.review_state == EvidenceReviewState.ACCEPTED and not e.stale
    ]
    disputed_support_groups = {
        group_key(e) for e in disputed_fresh_accepted
        if e.stance is Stance.SUPPORTS
    }
    disputed_contradiction_groups = {
        group_key(e) for e in disputed_fresh_accepted
        if e.stance is Stance.CONTRADICTS
    }
    # The as-if evaluation counts challenged groups *in addition to* the
    # undisputed ones, so a group holding both a disputed and an undisputed
    # record would be counted twice and report a score its evidence cannot
    # reach. Pass only the challenged groups the undisputed counts miss.
    decision = decide_table(
        independent_support,
        contradiction_groups,
        disputed_support=len(disputed_support_groups - set(group_members)),
        disputed_contradiction=len(
            disputed_contradiction_groups
            - {group_key(e) for e in contradicts}
        ),
        disputed_total=len(disputed_support_groups | disputed_contradiction_groups),
    )
    status, confidence = decision.status, decision.confidence
    status_rule_id, confidence_rule_id = decision.status_rule_id, decision.confidence_rule_id
    if status == Status.SUPPORTED:
        uncertainty = ("Fresh, mutually consistent records support this hypothesis; "
                       + ("the sources disagree in direction and the support outweighs it. " if decision.contested else "")
                       + "check source independence and operational context.")
    elif status == Status.CONTRADICTED:
        uncertainty = "Fresh evidence conflicts with this hypothesis; this does not establish an alternative cause."
    elif supports and contradicts:
        uncertainty = "Fresh supporting and contradicting evidence remains unresolved; review both sources."
    elif disputed_fresh_accepted:
        uncertainty = "A user challenged one or more source records; the evidence remains visible pending human review."
    elif supports:
        uncertainty = "A single fresh source is relevant but is not enough to establish the recurring cause."
    elif stale_support or stale_contradictions:
        uncertainty = "Only stale evidence is available; it remains historical context and is not treated as current proof or automatically false."
    elif unverified and not accepted:
        uncertainty = "Only unverified proposals are available; they remain for human review and do not establish support or contradiction."
    else:
        uncertainty = "No admissible, relevant evidence establishes support or contradiction." if not evidence or neutrals else "Only stale or non-decisive evidence is available."
    missing = []
    if not supports and not contradicts:
        missing.append("A recent handover record that directly addresses this hypothesis.")
    if supports and independent_support < 2:
        missing.append("An independent, recent corroborating source or an operational check.")
    if contradicts and not supports:
        missing.append("Evidence about the specific recurring missing-information incidents being investigated.")
    return _StatusDecision(
        status=status, confidence=confidence, uncertainty=uncertainty,
        conflicts=conflicts, missing=missing,
        status_rule_id=status_rule_id, confidence_rule_id=confidence_rule_id,
        evidence_score=decision.score, contested=decision.contested,
        supports=supports, contradicts=contradicts, neutrals=neutrals,
        stale_support=stale_support, stale_contradictions=stale_contradictions,
        stale_accepted=stale_accepted,
        disputed=disputed, unverified=unverified,
        independent_groups=independent_groups,
        dependent_support_ids=dependent_support_ids,
    )


def summarize_status(evidence: list[Evidence]) -> tuple[Status, float, str, list[str], list[str]]:
    """Return the established public result from the shared decision path."""
    decision = _summarize_status_decision(evidence)
    return decision.status, decision.confidence, decision.uncertainty, decision.conflicts, decision.missing


def _iso_utc(value: datetime) -> str:
    # Offset-less values are UTC by convention (see _validate_assessment_with_time).
    # `astimezone` would read a naive value as host-local time and still label the
    # result "Z", so an injected naive clock wrote an instant that depended on TZ.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _staleness_row(item: Evidence, evaluation_times: list[datetime | None], index: int) -> dict:
    """One row of the trace's per-record staleness table.

    A short `evaluation_times` list used to truncate the table with `zip`, so an
    audit trace silently covered fewer records than its own dispositions. Every
    record now gets a row, and a missing time says so instead of being read as a
    preserved flag.
    """
    evaluated_at = evaluation_times[index] if index < len(evaluation_times) else None
    if evaluated_at is not None:
        basis = "ASSESSMENT_VALIDATION"
    elif index < len(evaluation_times):
        basis = "PRESERVED_STORED_STALE_FLAG"
    else:
        basis = "UNKNOWN_MISSING_EVALUATION_TIME"
    return {
        "source_record_id": item.source_record_id,
        "stale_value_used": item.stale,
        "evaluated_at": _iso_utc(evaluated_at) if evaluated_at is not None else None,
        "basis": basis,
    }


def _evidence_dispositions(evidence: list[Evidence], decision: _StatusDecision) -> list[dict]:
    support_ids = {id(item) for item in decision.supports}
    contradiction_ids = {id(item) for item in decision.contradicts}
    neutral_ids = {id(item) for item in decision.neutrals}
    stale_directional_ids = {id(item) for item in (*decision.stale_support, *decision.stale_contradictions)}
    stale_neutral_ids = {id(item) for item in decision.stale_accepted if item.stance == Stance.NEUTRAL}
    # Recover dependent items by matching their source-group membership and the
    # exact representative rule used by the status branch.
    support_groups: dict[str, list[Evidence]] = {}
    for item in decision.supports:
        support_groups.setdefault(group_key(item), []).append(item)
    dependent_ids = {id(item) for members in support_groups.values() for item in members[:-1]}
    dispositions = []
    for item in evidence:
        codes = []
        if id(item) in support_ids:
            codes.append("COUNTED_SUPPORT")
        if id(item) in contradiction_ids:
            codes.append("COUNTED_CONTRADICTION")
        if id(item) in neutral_ids:
            codes.append("NEUTRAL_NOT_DIRECTIONAL")
        if item.review_state == EvidenceReviewState.UNVERIFIED:
            codes.append("UNVERIFIED_EXCLUDED")
        if id(item) in stale_directional_ids:
            codes.append("STALE_HISTORICAL_CONTEXT")
        if id(item) in stale_neutral_ids:
            codes.append("STALE_NON_DIRECTIONAL_CONTEXT")
        if item.disputed:
            codes.append("DISPUTED_REVIEW_REQUIRED")
        if id(item) in dependent_ids and id(item) in support_ids:
            codes.append("DEPENDENT_SOURCE_GROUP")
        if not codes:
            codes.append("UNCLASSIFIED_REVIEW_REQUIRED")
        dispositions.append({"source_record_id": item.source_record_id, "codes": codes})
    return dispositions


def _advisory_coverage_trace(hypothesis_id: str, evidence: list[Evidence]) -> dict:
    coverage = evidence_coverage(hypothesis_id, evidence)
    return {
        "advisory_only": True,
        "formal_evidence_sufficiency": False,
        "hypothesis_id": coverage["hypothesis_id"],
        "categories": [
            {
                "category_id": category["category_id"],
                "coverage_state": "COVERED" if category["covered_by_fresh_accepted"] else "NOT_COVERED",
                "covered_by_fresh_accepted": category["covered_by_fresh_accepted"],
                "matching_evidence_ids": [item["source_record_id"] for item in category["matching_evidence"]],
                "fresh_accepted_support_ids": category["fresh_accepted_support_ids"],
                "fresh_accepted_contradiction_ids": category["fresh_accepted_contradiction_ids"],
                "neutral_evidence_ids": category["neutral_evidence_ids"],
                "unclassified_evidence_ids": category["unclassified_evidence_ids"],
                "independent_source_groups": category["independent_source_groups"],
            }
            for category in coverage["categories"]
        ],
    }


def _score_direction(score: float) -> str:
    """Sign of the signed evidence score, as the trace and a Claim both report it.

    Kept as one function so the trace and the claim cannot disagree about the
    direction of the same number.
    """
    if score > 0:
        return "FOR"
    if score < 0:
        return "AGAINST"
    return "NONE"


def _build_explanation_trace(
    hypothesis_id: str,
    evidence: list[Evidence],
    decision: _StatusDecision,
    semantic_decisions: list[dict],
    evidence_evaluation_times: list[datetime | None],
    generated_at: datetime,
    semantic_guard_enabled: bool,
) -> dict:
    """Observe the shared status decision without changing any engine outputs.

    ``STATUS.*`` and ``CONFIDENCE.*`` values emitted by the signed decision
    table are stable trace identifiers for rule set
    ``story-connect-status-v2``. Semantic changes require a new reasoning-rule
    version instead of reinterpreting persisted traces; v1 traces remain
    readable because every id is recorded, not inferred.
    """
    group_analysis = {
        "independence_rule": "SOURCE_GROUP_OR_SOURCE_RECORD_ID_FALLBACK",
        "independent_support_group_count": len(decision.independent_groups),
        "independent_support_groups": decision.independent_groups,
        "dependent_support_record_ids": decision.dependent_support_ids,
        "dependent_support_records": [
            {
                "source_record_id": record_id,
                "reason_code": "SAME_SOURCE_GROUP_AS_OTHER_SUPPORT",
            }
            for record_id in decision.dependent_support_ids
        ],
        "department_diversity_uses_last_support_record_per_group": True,
    }
    return {
        "trace_schema_version": "1.0",
        "reasoning_rule_version": "story-connect-status-v2",
        "generated_at": _iso_utc(generated_at),
        "status_rule_id": decision.status_rule_id,
        "confidence_rule_id": decision.confidence_rule_id,
        "confidence_kind": "SIGNED_EVIDENCE_MARGIN_NOT_CALIBRATED_PROBABILITY",
        "evidence_score": decision.evidence_score,
        "evidence_direction": _score_direction(decision.evidence_score),
        "contested": decision.contested,
        "evidence_disposition_semantics": {
            "COUNTED_SUPPORT": "Included in the fresh accepted support set; source-group counting remains separate.",
            "COUNTED_CONTRADICTION": "Included in the fresh accepted contradiction set.",
            "NEUTRAL_NOT_DIRECTIONAL": "Accepted fresh neutral evidence; it is not directional support or contradiction.",
            "UNVERIFIED_EXCLUDED": "Excluded from directional support/contradiction sets but retained in review annotations and existing uncertainty text.",
            "STALE_HISTORICAL_CONTEXT": "Accepted stale evidence supplied to the existing stale-context branches, not current directional proof.",
            "STALE_NON_DIRECTIONAL_CONTEXT": "Accepted stale neutral evidence is non-directional and does not enter the stale support/contradiction sets.",
            "DISPUTED_REVIEW_REQUIRED": "Disputed evidence is retained for review and follows the existing disputed-evidence branch rules.",
            "DEPENDENT_SOURCE_GROUP": "Support record shares a group; it does not add an independent source-group unit.",
            "UNCLASSIFIED_REVIEW_REQUIRED": "No directional, neutral, stale-accepted, disputed, or unverified disposition applied.",
        },
        "evidence_dispositions": _evidence_dispositions(evidence, decision),
        "semantic_guard": {
            "rule_set_version": "phrase-guard-v1",
            "enabled": semantic_guard_enabled,
            "decisions": semantic_decisions,
        },
        "source_group_analysis": group_analysis,
        "staleness_policy": {
            "policy_id": "STALE_AFTER_90_DAYS_UTC",
            "threshold_days": STALE_DAYS,
            "comparison": "AGE_DAYS_GREATER_THAN_THRESHOLD",
            "timezone": "UTC",
            "decision_evaluated_at": _iso_utc(generated_at),
            "evidence_evaluation_times": [
                _staleness_row(item, evidence_evaluation_times, index)
                for index, item in enumerate(evidence)
            ],
        },
        "advisory_coverage": _advisory_coverage_trace(hypothesis_id, evidence),
    }


class AssessmentEngine:
    __slots__ = ("provider", "provider_boundary", "semantic_guard", "clock", "_sealed")

    def __init__(self, provider: LocalAssessmentProvider | ApprovedProviderAdapter | None = None, *, semantic_guard: bool = True, clock: Callable[[], datetime] | None = None):
        selected_provider = MockProvider() if provider is None else provider
        object.__setattr__(self, "provider", selected_provider)
        object.__setattr__(self, "provider_boundary", MandatoryProviderBoundary(selected_provider))
        object.__setattr__(self, "semantic_guard", semantic_guard)
        # The engine stamps wall-clock times into every trace, which made
        # `challenge` and `investigate` impure: two identical calls produced
        # different bytes. An injectable clock restores reproducibility without
        # changing the default behaviour.
        object.__setattr__(self, "clock", clock if clock is not None else lambda: datetime.now(timezone.utc))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("assessment engine configuration is immutable")
        object.__setattr__(self, name, value)

    def _provider_assess(self, records: list[Record], hypothesis_id: str) -> list[dict]:
        # This is the final permission boundary before any provider sees records.
        permitted = eligible_provider_records(records)
        indexed = {record.id: record for record in permitted}
        try:
            proposals = self.provider_boundary.assess(records, hypothesis_id)
        except ProviderSafetyError as exc:
            # Preserve only the controlled category, never transport details.
            raise ProviderError(exc.code) from None
        except Exception:
            # Provider exceptions may contain prompts or record content. Keep
            # those details out of API errors and logs at this boundary.
            raise ProviderError("provider_failure") from None
        if not isinstance(proposals, list):
            raise ProviderError("malformed_output")
        for proposal in proposals:
            if not isinstance(proposal, dict) or set(proposal) != {"source_record_id", "quote", "stance", "rationale"}:
                raise ProviderError("malformed_output")
            try:
                validate_assessment(proposal, indexed)
            except AssessmentError as exc:
                # Includes invented IDs, inadmissible records, invalid quotes,
                # malformed fields, and values outside the response contract.
                raise ProviderError(exc.code) from None
            except Exception:
                raise ProviderError("malformed_output") from None
        return proposals

    def _review_item_with_trace(self, item: Evidence, hypothesis_id: str) -> tuple[Evidence, dict]:
        """Apply local review and return bounded metadata from that same decision."""
        if not self.semantic_guard:
            # Preserve the intentionally unguarded baseline explicitly instead
            # of relying on Evidence.review_state's model default.
            item.review_state = EvidenceReviewState.ACCEPTED
            return item, {
                "source_record_id": item.source_record_id,
                "review_state": item.review_state.value,
                "proposed_stance": item.stance.value,
                "semantic_relation": None,
                "guard_enabled": False,
                "cue_ids": [],
                "reason_code": "GUARD_DISABLED_BY_ENGINE_CONFIGURATION",
                "decision_source": "ASSESSMENT_REVIEW",
            }
        item.proposed_stance = item.stance
        guard_decision = reviewed_relation_details(item.quote, hypothesis_id)
        relation = guard_decision["relation"]
        item.semantic_relation = relation
        if relation == item.stance:
            item.review_state = EvidenceReviewState.ACCEPTED
            if relation == Stance.NEUTRAL:
                item.rationale = "An explicit neutral phrase cue agrees with the proposal; this does not prove broader irrelevance."
            else:
                item.rationale = "Reviewed phrase-level cues agree with the proposal; this is not proof of causation."
        else:
            item.review_state = EvidenceReviewState.UNVERIFIED
            item.rationale = "The proposal is retained for human review because phrase-level cues did not verify its direction."
        reason_code = ("CUE_MATCHES_PROPOSAL" if relation == item.stance else
                       "CUE_MISMATCHES_PROPOSAL" if relation is not None else guard_decision["reason_code"])
        return item, {
            "source_record_id": item.source_record_id,
            "review_state": item.review_state.value,
            "proposed_stance": item.stance.value,
            "semantic_relation": relation.value if relation is not None else None,
            "guard_enabled": True,
            "cue_ids": guard_decision["cue_ids"],
            "reason_code": reason_code,
            "decision_source": "ASSESSMENT_REVIEW",
        }

    def _review_item(self, item: Evidence, hypothesis_id: str) -> Evidence:
        """Compatibility wrapper preserving the established method result."""
        return self._review_item_with_trace(item, hypothesis_id)[0]

    def _claim(self, claim_id: str, hypothesis_id: str, records: list[Record], *, version: int = 1, extra: list[dict] | None = None) -> dict:
        indexed = {r.id: r for r in records if not r.restricted}
        raw_items = self._provider_assess(records, hypothesis_id)
        if extra:
            raw_items.extend(extra)
        evidence = []
        semantic_decisions = []
        evaluation_times = []
        seen = set()
        now = self.clock()
        for raw in raw_items:
            item, evaluated_at = _validate_assessment_with_time(raw, indexed, now=now)
            # Never promote a proposal or flip it to the opposite stance.
            item, semantic_decision = self._review_item_with_trace(item, hypothesis_id)
            key = (item.source_record_id, item.quote, item.stance, item.review_state)
            if key not in seen:
                seen.add(key)
                evidence.append(item)
                semantic_decisions.append(semantic_decision)
                evaluation_times.append(evaluated_at)
        generated_at = evaluation_times[-1] if evaluation_times else now
        status_decision = _summarize_status_decision(evidence)
        missing = advisory_missing_evidence(hypothesis_id, evidence)
        trace = _build_explanation_trace(hypothesis_id, evidence, status_decision,
                                         semantic_decisions, evaluation_times, generated_at,
                                         self.semantic_guard)
        return Claim(id=claim_id, hypothesis_id=hypothesis_id, status=status_decision.status,
                     confidence=status_decision.confidence, uncertainty=status_decision.uncertainty,
                     evidence_score=status_decision.evidence_score,
                     evidence_direction=_score_direction(status_decision.evidence_score),
                     summary=f"{status_decision.status.value.title()} evidence for {hypothesis_id.replace('_', ' ').lower()}.", evidence=evidence,
                     conflicts=status_decision.conflicts, missing_evidence=missing,
                     dependencies=sorted({e.source_record_id for e in evidence}), version=version,
                     explanation_trace=trace).model_dump(mode="json")

    def investigate(self, records: list[Record]) -> list[dict]:
        return [self._claim(h.id, h.id, records) for h in HYPOTHESES]

    def assess_hypothesis(self, records: list[Record], hypothesis_id: str) -> dict:
        """Assess exactly one known hypothesis without creating or persisting an investigation."""
        if not any(item.id == hypothesis_id for item in HYPOTHESES):
            raise AssessmentError("Unknown hypothesis")
        return self._claim(hypothesis_id, hypothesis_id, records)

    def challenge(self, current: dict, records: list[Record], record_id: str, quote: str) -> dict:
        now = self.clock()
        record = next((r for r in records if r.id == record_id and not r.restricted), None)
        if record is None:
            raise AssessmentError("Source record was not found")
        if quote not in record.text or len(quote.strip()) < 3:
            raise AssessmentError("Challenge quote must be an exact source substring")
        # Challenge marks a claim dependency as disputed; it never rewrites its
        # quote, stance, source, or history. A human decides whether to resolve it.
        raw = current.copy()
        matching_evidence = False
        raw["evidence"] = []
        for item in current["evidence"]:
            matches_request = item["source_record_id"] == record_id and quote in item["quote"]
            matching_evidence = matching_evidence or matches_request
            # Copy unconditionally: the caller's dict is also the caller's
            # `expected_claims`, so aliasing let the guard below write into it.
            raw["evidence"].append(dict(item, disputed=True) if matches_request else dict(item))
        if not matching_evidence:
            candidates = [a for a in self._provider_assess([record], current["hypothesis_id"]) if a["source_record_id"] == record_id and quote in a["quote"]]
            if not candidates:
                raise AssessmentError("This source is not an assessed dependency for the selected claim")
            evidence, new_evidence_evaluated_at = _validate_assessment_with_time(
                dict(candidates[0], quote=quote), {record.id: record}, now=now
            )
            evidence, new_semantic_decision = self._review_item_with_trace(evidence, current["hypothesis_id"])
            evidence.disputed = True
            raw["evidence"].append(evidence.model_dump(mode="json"))
        else:
            new_evidence_evaluated_at = None
            new_semantic_decision = None
        if self.semantic_guard:
            # Resolve legacy omission while the raw dictionary still records
            # whether the field was absent. Explicit states are preserved.
            for item in raw["evidence"]:
                if "review_state" not in item:
                    item["review_state"] = EvidenceReviewState.UNVERIFIED.value
        evidence_models = [Evidence.model_validate(item) for item in raw["evidence"]]
        # A challenge is a re-assessment at `now`, so the persisted freshness flags
        # are stale by construction. Keeping them meant a claim challenged months
        # later could report INSUFFICIENT with every row still marked as written
        # under the old clock, while `assess_hypothesis` over the same records at
        # the same instant said otherwise.
        record_index = {r.id: r for r in records}
        for raw_item, item in zip(raw["evidence"], evidence_models):
            record = record_index.get(item.source_record_id)
            if record is not None:
                item.stale = _is_stale(record.timestamp, now)
                # The claim is serialised from the raw dicts, so the verdict and
                # the rows it counts must not disagree about freshness.
                raw_item["stale"] = item.stale
        status_decision = _summarize_status_decision(evidence_models)
        missing = advisory_missing_evidence(current["hypothesis_id"], evidence_models)
        previous_trace = current.get("explanation_trace") or {}
        previous_guard = previous_trace.get("semantic_guard", {})
        previous_semantic_decisions = previous_guard.get("decisions", [])
        semantic_decisions = []
        previous_times = (previous_trace.get("staleness_policy", {})
                          .get("evidence_evaluation_times", []))
        evaluation_times: list[datetime | None] = []
        for index, item in enumerate(evidence_models):
            if index < len(previous_semantic_decisions):
                prior = previous_semantic_decisions[index]
                if prior.get("source_record_id") == item.source_record_id:
                    semantic_decisions.append(dict(prior))
                else:
                    semantic_decisions.append({
                        "source_record_id": item.source_record_id,
                        "review_state": item.review_state.value,
                        "proposed_stance": item.proposed_stance.value if item.proposed_stance else None,
                        "semantic_relation": item.semantic_relation.value if item.semantic_relation else None,
                        "guard_enabled": None,
                        "cue_ids": [],
                        "reason_code": "PRIOR_GUARD_DECISION_UNAVAILABLE",
                        "decision_source": "PRESERVED_LEGACY_EVIDENCE",
                    })
            elif new_semantic_decision is not None and index == len(evidence_models) - 1:
                semantic_decisions.append(new_semantic_decision)
            else:
                semantic_decisions.append({
                    "source_record_id": item.source_record_id,
                    "review_state": item.review_state.value,
                    "proposed_stance": item.proposed_stance.value if item.proposed_stance else None,
                    "semantic_relation": item.semantic_relation.value if item.semantic_relation else None,
                    "guard_enabled": None,
                    "cue_ids": [],
                    "reason_code": "PRIOR_GUARD_DECISION_UNAVAILABLE",
                    "decision_source": "PRESERVED_LEGACY_EVIDENCE",
                })
            timestamp_value = None
            if item.source_record_id in record_index:
                # The row above was just re-evaluated at `now`; reporting the
                # previous instant under an ASSESSMENT_VALIDATION label would
                # describe a check that did not happen at that time.
                timestamp_value = now
            elif index < len(previous_times):
                previous = previous_times[index]
                if previous.get("source_record_id") == item.source_record_id and previous.get("evaluated_at"):
                    timestamp_value = datetime.fromisoformat(previous["evaluated_at"].replace("Z", "+00:00"))
            if new_semantic_decision is not None and index == len(evidence_models) - 1:
                timestamp_value = new_evidence_evaluated_at
            evaluation_times.append(timestamp_value)
        trace = _build_explanation_trace(
            current["hypothesis_id"], evidence_models, status_decision,
            semantic_decisions, evaluation_times, now, self.semantic_guard,
        )
        raw.update(status=status_decision.status.value, confidence=status_decision.confidence,
                   evidence_score=status_decision.evidence_score,
                   evidence_direction=_score_direction(status_decision.evidence_score),
                   uncertainty=status_decision.uncertainty, conflicts=status_decision.conflicts,
                   missing_evidence=missing,
                   summary=f"{status_decision.status.value.title()} evidence for {current['hypothesis_id'].replace('_', ' ').lower()}.",
                   dependencies=sorted({e.source_record_id for e in evidence_models}),
                   explanation_trace=trace, version=current["version"] + 1)
        return Claim.model_validate(raw).model_dump(mode="json")
