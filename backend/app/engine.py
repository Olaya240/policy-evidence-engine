"""Deterministic evidence validation, status calculation, and dependency recomputation."""
from datetime import datetime, timezone

from .mock_provider import MockProvider
from .models import EvidenceReviewState, HYPOTHESES, Claim, Evidence, Record, Status, Stance
from .provider_safety import (BoundedTransportProvider, LocalAssessmentProvider,
                              MandatoryProviderBoundary, ProviderSafetyError,
                              eligible_provider_records)
from .semantic_guard import reviewed_relation

STALE_DAYS = 90


class AssessmentError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_assessment"):
        super().__init__(message)
        self.code = code


class ProviderError(RuntimeError):
    """A provider failed or returned a proposal that cannot be validated."""

    def __init__(self, code: str):
        self.code = code
        super().__init__("Assessment provider failed or returned invalid output")


def validate_assessment(raw: dict, records: dict[str, Record]) -> Evidence:
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
    age = (datetime.now(timezone.utc) - record.timestamp).days
    return Evidence(source_record_id=record_id, timestamp=record.timestamp, quote=quote, stance=stance, rationale=rationale.strip(), stale=age > STALE_DAYS, department=record.department, source_group=record.source_group or record.id)


def summarize_status(evidence: list[Evidence]) -> tuple[Status, float, str, list[str], list[str]]:
    fresh = [e for e in evidence if not e.stale]
    accepted = [e for e in fresh if e.review_state == EvidenceReviewState.ACCEPTED]
    supports = [e for e in accepted if e.stance == Stance.SUPPORTS and not e.disputed]
    contradicts = [e for e in accepted if e.stance == Stance.CONTRADICTS and not e.disputed]
    neutrals = [e for e in accepted if e.stance == Stance.NEUTRAL]
    stale_support = [e for e in evidence if e.stale and e.stance == Stance.SUPPORTS]
    stale_contradictions = [e for e in evidence if e.stale and e.stance == Stance.CONTRADICTS]
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
    independent_support = len({e.source_group or e.source_record_id for e in supports})
    departments_by_source = {e.source_group or e.source_record_id: e for e in supports}
    diverse = len({getattr(e, "department", None) for e in departments_by_source.values()}) > 1 if departments_by_source else False
    # Strong direct conflicts prevent SUPPORTED. Multiple independent fresh records
    # increase confidence but no fixed count alone establishes adequacy.
    if supports and contradicts:
        status, confidence = Status.PARTIAL, 0.52
        uncertainty = "Fresh supporting and contradicting evidence remains unresolved; review both sources."
    elif any(e.review_state == EvidenceReviewState.ACCEPTED for e in disputed):
        status, confidence = Status.PARTIAL, 0.48
        uncertainty = "A user challenged one or more source records; the evidence remains visible pending human review."
    elif (supports or contradicts) and (stale_support or stale_contradictions):
        status, confidence = Status.PARTIAL, 0.54
        stale_direction = []
        if stale_support:
            stale_direction.append("supporting")
        if stale_contradictions:
            stale_direction.append("contradictory")
        uncertainty = "Fresh evidence is available, but stale " + " and ".join(stale_direction) + " records remain relevant historical context and are not treated as current proof or automatically false."
    elif supports and independent_support >= 2:
        status, confidence = Status.SUPPORTED, 0.78 if diverse else 0.68
        uncertainty = "Fresh, mutually consistent records support this hypothesis; check source independence and operational context."
    elif supports:
        status, confidence = Status.PARTIAL, 0.55
        uncertainty = "A single fresh source is relevant but is not enough to establish the recurring cause."
    elif contradicts:
        status, confidence = Status.CONTRADICTED, 0.68 if len(contradicts) > 1 else 0.58
        uncertainty = "Fresh evidence conflicts with this hypothesis; this does not establish an alternative cause."
    elif stale_support or stale_contradictions:
        status, confidence = Status.INSUFFICIENT, 0.25
        uncertainty = "Only stale evidence is available; it remains historical context and is not treated as current proof or automatically false."
    else:
        status, confidence = Status.INSUFFICIENT, 0.2 if not evidence else 0.3
        if unverified:
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
    return status, confidence, uncertainty, conflicts, missing


class AssessmentEngine:
    __slots__ = ("provider", "provider_boundary", "semantic_guard", "_sealed")

    def __init__(self, provider: LocalAssessmentProvider | BoundedTransportProvider | None = None, *, semantic_guard: bool = True):
        selected_provider = MockProvider() if provider is None else provider
        object.__setattr__(self, "provider", selected_provider)
        object.__setattr__(self, "provider_boundary", MandatoryProviderBoundary(selected_provider))
        object.__setattr__(self, "semantic_guard", semantic_guard)
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

    def _review_item(self, item: Evidence, hypothesis_id: str) -> Evidence:
        """Apply the same local review to ordinary and challenge-added proposals."""
        if not self.semantic_guard:
            return item
        item.proposed_stance = item.stance
        relation = reviewed_relation(item.quote, hypothesis_id)
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
        return item

    def _claim(self, claim_id: str, hypothesis_id: str, records: list[Record], *, version: int = 1, extra: list[dict] | None = None) -> dict:
        indexed = {r.id: r for r in records if not r.restricted}
        raw_items = self._provider_assess(records, hypothesis_id)
        if extra:
            raw_items.extend(extra)
        evidence = []
        seen = set()
        for raw in raw_items:
            item = validate_assessment(raw, indexed)
            # Never promote a proposal or flip it to the opposite stance.
            self._review_item(item, hypothesis_id)
            key = (item.source_record_id, item.quote, item.stance, item.review_state)
            if key not in seen:
                seen.add(key)
                evidence.append(item)
        status, confidence, uncertainty, conflicts, missing = summarize_status(evidence)
        return Claim(id=claim_id, hypothesis_id=hypothesis_id, status=status, confidence=confidence, uncertainty=uncertainty,
                     summary=f"{status.value.title()} evidence for {hypothesis_id.replace('_', ' ').lower()}.", evidence=evidence,
                     conflicts=conflicts, missing_evidence=missing, dependencies=sorted({e.source_record_id for e in evidence}), version=version).model_dump(mode="json")

    def investigate(self, records: list[Record]) -> list[dict]:
        return [self._claim(h.id, h.id, records) for h in HYPOTHESES]

    def assess_hypothesis(self, records: list[Record], hypothesis_id: str) -> dict:
        """Assess exactly one known hypothesis without creating or persisting an investigation."""
        if not any(item.id == hypothesis_id for item in HYPOTHESES):
            raise AssessmentError("Unknown hypothesis")
        return self._claim(hypothesis_id, hypothesis_id, records)

    def challenge(self, current: dict, records: list[Record], record_id: str, quote: str) -> dict:
        record = next((r for r in records if r.id == record_id and not r.restricted), None)
        if record is None:
            raise AssessmentError("Source record was not found")
        if quote not in record.text or len(quote.strip()) < 3:
            raise AssessmentError("Challenge quote must be an exact source substring")
        # Challenge marks a claim dependency as disputed; it never rewrites its
        # quote, stance, source, or history. A human decides whether to resolve it.
        raw = current.copy()
        raw["evidence"] = [dict(item, disputed=True) if item["source_record_id"] == record_id and quote in item["quote"] else item for item in current["evidence"]]
        if not any(item.get("disputed") for item in raw["evidence"]):
            candidates = [a for a in self._provider_assess([record], current["hypothesis_id"]) if a["source_record_id"] == record_id and quote in a["quote"]]
            if not candidates:
                raise AssessmentError("This source is not an assessed dependency for the selected claim")
            evidence = validate_assessment(dict(candidates[0], quote=quote), {record.id: record})
            self._review_item(evidence, current["hypothesis_id"])
            evidence.disputed = True
            raw["evidence"].append(evidence.model_dump(mode="json"))
        evidence_models = [Evidence.model_validate(item) for item in raw["evidence"]]
        status, confidence, uncertainty, conflicts, missing = summarize_status(evidence_models)
        raw.update(status=status.value, confidence=confidence, uncertainty=uncertainty, conflicts=conflicts, missing_evidence=missing,
                   summary=f"{status.value.title()} evidence for {current['hypothesis_id'].replace('_', ' ').lower()}.",
                   dependencies=sorted({e.source_record_id for e in evidence_models}), version=current["version"] + 1)
        return Claim.model_validate(raw).model_dump(mode="json")
