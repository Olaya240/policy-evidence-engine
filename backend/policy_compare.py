"""Pure offline contracts for synthetic policy-version comparisons.

This module validates input and source provenance only. It does not establish
semantic support, policy relations, precedence, scope semantics, or complete
comparison coverage. Candidate labels remain proposals; absent trusted
assessment mechanisms, returned classifications are INCONCLUSIVE. Every
result requires human review. No function writes or publishes policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
import re
from typing import Any


MAX_TEXT_CODEPOINTS = 100_000
MAX_PASSAGES = 1_000
MAX_CANDIDATE_TEXT = 4_000
MAX_SUMMARY = 1_000
MAX_RESOLUTION = 2_000

_DOC_ID = re.compile(r"syn-policy-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_VERSION_ID = re.compile(r"v[A-Za-z0-9][A-Za-z0-9.-]{0,23}\Z")
_COMPARISON_ID = re.compile(r"cmp-syn-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_CANDIDATE_ID = re.compile(r"cand-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SCOPE_ID = re.compile(r"(?:ALL|[A-Z][A-Z0-9_]{1,63})\Z")
_PASSAGE_ID = re.compile(r"p[0-9]{6}-[0-9a-f]{16}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class PolicyCompareError(ValueError):
    """Fixed, sanitized validation failure; ``code`` is safe to expose."""

    _MESSAGES = {
        "invalid_input": "Policy comparison input is invalid.",
        "invalid_identifier": "A policy comparison identifier is invalid.",
        "invalid_text": "Policy source text is invalid.",
        "input_too_large": "Policy comparison input exceeds its limit.",
        "invalid_date_range": "A policy effective-date range is invalid.",
        "invalid_scope": "Policy scope metadata is invalid.",
        "invalid_dependency": "Policy impact dependency metadata is invalid.",
        "invalid_citation": "A policy citation is invalid.",
        "invalid_candidate": "A policy comparison candidate is invalid.",
        "invalid_result": "A policy comparison result is invalid.",
        "unverified_assessment": "Policy assessment is not independently verified.",
    }

    def __init__(self, code: str):
        if code not in self._MESSAGES:
            code = "invalid_input"
        self.code = code
        super().__init__(self._MESSAGES[code])


class Classification(str, Enum):
    CONTRADICTION = "CONTRADICTION"
    COMPATIBLE_CHANGE = "COMPATIBLE_CHANGE"
    NEW_RULE = "NEW_RULE"
    SCOPE_OR_TIME_DIFFERENCE = "SCOPE_OR_TIME_DIFFERENCE"
    INCONCLUSIVE = "INCONCLUSIVE"


class Relation(str, Enum):
    OVERLAP = "OVERLAP"
    DISJOINT = "DISJOINT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Passage:
    passage_id: str
    ordinal: int
    start_cp: int
    end_cp: int
    text: str
    text_sha256: str


@dataclass(frozen=True)
class ScopeSet:
    """Scope state: KNOWN, UNKNOWN, or ALL (global wildcard for this dimension)."""
    state: str
    ids: tuple[str, ...]


@dataclass(frozen=True)
class Scope:
    departments: ScopeSet
    procedures: ScopeSet
    property_id: str | None
    evidence_passage_ids: tuple[str, ...]


@dataclass(frozen=True)
class ImpactDependency:
    department_id: str | None
    procedure_id: str | None
    passage_ids: tuple[str, ...]


@dataclass(frozen=True)
class PolicyVersion:
    document_id: str
    version_id: str
    original_text: str
    source_sha256: str
    effective_from: date | None
    effective_to_exclusive: date | None
    scope: Scope
    text_coverage: str
    passages: tuple[Passage, ...]
    impact_dependencies: tuple[ImpactDependency, ...]

    def passage(self, passage_id: str) -> Passage | None:
        return next((item for item in self.passages if item.passage_id == passage_id), None)


@dataclass(frozen=True)
class PolicyPair:
    schema_version: int
    comparison_id: str
    older: PolicyVersion
    newer: PolicyVersion


def _object(value: Any, keys: set[str], code: str = "invalid_input") -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise PolicyCompareError(code)
    return value


def _string(value: Any, *, maximum: int, nonblank: bool = True,
            code: str = "invalid_input") -> str:
    if type(value) is not str:
        raise PolicyCompareError(code)
    if len(value) > maximum:
        raise PolicyCompareError("input_too_large" if code == "invalid_text" else code)
    if nonblank and not value.strip():
        raise PolicyCompareError(code)
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        raise PolicyCompareError(code) from None
    if "\x00" in value:
        raise PolicyCompareError(code)
    return value


def _identifier(value: Any, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise PolicyCompareError("invalid_identifier")
    return value


def _string_list(value: Any, *, pattern: re.Pattern[str], allow_empty: bool = False) -> tuple[str, ...]:
    if type(value) is not list or (not allow_empty and not value):
        raise PolicyCompareError("invalid_input")
    result = tuple(_identifier(item, pattern) for item in value)
    if len(set(result)) != len(result):
        raise PolicyCompareError("invalid_input")
    return result


def _date_value(value: Any) -> date | None:
    if value is None:
        return None
    if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise PolicyCompareError("invalid_date_range")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise PolicyCompareError("invalid_date_range") from None
    if parsed.isoformat() != value:
        raise PolicyCompareError("invalid_date_range")
    return parsed


def _scope_set(value: Any) -> ScopeSet:
    obj = _object(value, {"state", "ids"}, "invalid_scope")
    state = obj["state"]
    if type(state) is not str:
        raise PolicyCompareError("invalid_scope")
    if state in {"UNKNOWN", "ALL"} and type(obj["ids"]) is list and not obj["ids"]:
        return ScopeSet(state, ())
    if state == "KNOWN":
        try:
            identifiers = _string_list(obj["ids"], pattern=_SCOPE_ID)
        except PolicyCompareError:
            raise PolicyCompareError("invalid_scope") from None
        return ScopeSet("KNOWN", identifiers)
    raise PolicyCompareError("invalid_scope")


def _passages(text: str) -> tuple[Passage, ...]:
    # Blank-line separators are recognized without rewriting source newlines.
    separator = re.compile(r"(?:\r\n|\r|\n)[\t ]*(?:(?:\r\n|\r|\n)[\t ]*)+")
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in separator.finditer(text):
        spans.append((cursor, match.start()))
        cursor = match.end()
    spans.append((cursor, len(text)))

    output: list[Passage] = []
    for raw_start, raw_end in spans:
        start, end = raw_start, raw_end
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start == end:
            continue
        passage_text = text[start:end]
        digest = sha256(passage_text.encode("utf-8", "strict")).hexdigest()
        ordinal = len(output) + 1
        passage_id = f"p{ordinal:06d}-{digest[:16]}"
        output.append(Passage(passage_id, ordinal, start, end, passage_text, digest))
        if len(output) > MAX_PASSAGES:
            raise PolicyCompareError("input_too_large")
    return tuple(output)


def _parse_version(value: Any) -> PolicyVersion:
    keys = {
        "document_id", "version_id", "original_text", "effective_from",
        "effective_to_exclusive", "scope", "text_coverage", "impact_dependencies",
    }
    obj = _object(value, keys)
    document_id = _identifier(obj["document_id"], _DOC_ID)
    version_id = _identifier(obj["version_id"], _VERSION_ID)
    text = _string(obj["original_text"], maximum=MAX_TEXT_CODEPOINTS, code="invalid_text")
    if len(text) > MAX_TEXT_CODEPOINTS:
        raise PolicyCompareError("input_too_large")
    if not text.strip():
        raise PolicyCompareError("invalid_text")
    start = _date_value(obj["effective_from"])
    end = _date_value(obj["effective_to_exclusive"])
    if start is not None and end is not None and start >= end:
        raise PolicyCompareError("invalid_date_range")

    scope_obj = _object(obj["scope"], {"departments", "procedures", "property_id", "evidence_passage_ids"}, "invalid_scope")
    departments = _scope_set(scope_obj["departments"])
    procedures = _scope_set(scope_obj["procedures"])
    property_id = scope_obj["property_id"]
    if property_id is not None:
        property_id = _identifier(property_id, _SCOPE_ID)
    evidence_ids = _string_list(scope_obj["evidence_passage_ids"], pattern=_PASSAGE_ID, allow_empty=True)

    coverage = obj["text_coverage"]
    if type(coverage) is not str or coverage not in ("FULL_DOCUMENT", "EXCERPT"):
        raise PolicyCompareError("invalid_input")
    passage_tuple = _passages(text)
    known_scope = departments.state in {"KNOWN", "ALL"} or procedures.state in {"KNOWN", "ALL"} or property_id is not None
    if known_scope and not evidence_ids:
        raise PolicyCompareError("invalid_scope")

    dependency_raw = obj["impact_dependencies"]
    if type(dependency_raw) is not list:
        raise PolicyCompareError("invalid_dependency")
    dependencies: list[ImpactDependency] = []
    dependency_keys: set[tuple[str | None, str | None]] = set()
    passage_ids = {passage.passage_id for passage in passage_tuple}
    for item in dependency_raw:
        dep = _object(item, {"department_id", "procedure_id", "passage_ids"}, "invalid_dependency")
        department_id, procedure_id = dep["department_id"], dep["procedure_id"]
        if department_id is None and procedure_id is None:
            raise PolicyCompareError("invalid_dependency")
        if department_id is not None:
            department_id = _identifier(department_id, _SCOPE_ID)
        if procedure_id is not None:
            procedure_id = _identifier(procedure_id, _SCOPE_ID)
        try:
            dep_passages = _string_list(dep["passage_ids"], pattern=_PASSAGE_ID)
        except PolicyCompareError:
            raise PolicyCompareError("invalid_dependency") from None
        if any(pid not in passage_ids for pid in dep_passages):
            raise PolicyCompareError("invalid_dependency")
        key = (department_id, procedure_id)
        if key in dependency_keys:
            raise PolicyCompareError("invalid_dependency")
        dependency_keys.add(key)
        dependencies.append(ImpactDependency(department_id, procedure_id, dep_passages))

    if any(pid not in passage_ids for pid in evidence_ids):
        raise PolicyCompareError("invalid_scope")
    return PolicyVersion(
        document_id, version_id, text, sha256(text.encode("utf-8", "strict")).hexdigest(),
        start, end, Scope(departments, procedures, property_id, evidence_ids), coverage,
        passage_tuple, tuple(dependencies),
    )


def validate_policy_pair(value: Any) -> PolicyPair:
    """Validate a strict JSON-shaped pair and freeze all nested state."""
    obj = _object(value, {"schema_version", "comparison_id", "older", "newer"})
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        raise PolicyCompareError("invalid_input")
    comparison_id = _identifier(obj["comparison_id"], _COMPARISON_ID)
    older, newer = _parse_version(obj["older"]), _parse_version(obj["newer"])
    if older.document_id != newer.document_id or older.version_id == newer.version_id:
        raise PolicyCompareError("invalid_identifier")
    return PolicyPair(1, comparison_id, older, newer)


def validate_citation(pair: PolicyPair, value: Any, *, expected_side: str | None = None) -> dict[str, Any]:
    """Return a canonical copy after exact provenance validation only."""
    obj = _object(value, {"document_id", "version_id", "source_sha256", "passage_id", "start_cp", "end_cp", "quote"}, "invalid_citation")
    document_id, version_id = obj["document_id"], obj["version_id"]
    if type(document_id) is not str or type(version_id) is not str:
        raise PolicyCompareError("invalid_citation")
    if expected_side is not None and type(expected_side) is not str:
        raise PolicyCompareError("invalid_citation")
    side = None
    for name, version in (("OLDER", pair.older), ("NEWER", pair.newer)):
        if document_id == version.document_id and version_id == version.version_id:
            side = name
            selected = version
            break
    if side is None or (expected_side is not None and side != expected_side):
        raise PolicyCompareError("invalid_citation")
    if (type(obj["source_sha256"]) is not str or _HASH.fullmatch(obj["source_sha256"]) is None
            or obj["source_sha256"] != selected.source_sha256):
        raise PolicyCompareError("invalid_citation")
    passage_id = obj["passage_id"]
    passage = selected.passage(passage_id) if type(passage_id) is str else None
    start, end = obj["start_cp"], obj["end_cp"]
    quote = obj["quote"]
    if (passage is None or type(start) is not int or type(end) is not int
            or start < passage.start_cp or end <= start or end > passage.end_cp
            or end > len(selected.original_text) or type(quote) is not str
            or selected.original_text[start:end] != quote):
        raise PolicyCompareError("invalid_citation")
    return {
        "document_id": selected.document_id, "version_id": selected.version_id,
        "source_sha256": selected.source_sha256, "passage_id": passage.passage_id,
        "start_cp": start, "end_cp": end, "quote": quote,
    }


def _dimension_relation(left: ScopeSet, right: ScopeSet) -> Relation:
    if left.state == "ALL" or right.state == "ALL":
        return Relation.OVERLAP
    if left.state != "KNOWN" or right.state != "KNOWN":
        return Relation.UNKNOWN
    if set(left.ids) & set(right.ids):
        return Relation.OVERLAP
    return Relation.DISJOINT


def scope_relation(older: PolicyVersion, newer: PolicyVersion) -> Relation:
    relations = [
        _dimension_relation(older.scope.departments, newer.scope.departments),
        _dimension_relation(older.scope.procedures, newer.scope.procedures),
    ]
    if older.scope.property_id is None or newer.scope.property_id is None:
        relations.append(Relation.UNKNOWN)
    elif older.scope.property_id == newer.scope.property_id:
        relations.append(Relation.OVERLAP)
    else:
        relations.append(Relation.DISJOINT)
    if Relation.DISJOINT in relations:
        return Relation.DISJOINT
    if Relation.UNKNOWN in relations:
        return Relation.UNKNOWN
    return Relation.OVERLAP


def time_relation(older: PolicyVersion, newer: PolicyVersion) -> Relation:
    values = (older.effective_from, older.effective_to_exclusive,
              newer.effective_from, newer.effective_to_exclusive)
    if any(value is None for value in values):
        return Relation.UNKNOWN
    assert older.effective_from and older.effective_to_exclusive
    assert newer.effective_from and newer.effective_to_exclusive
    if max(older.effective_from, newer.effective_from) < min(older.effective_to_exclusive, newer.effective_to_exclusive):
        return Relation.OVERLAP
    return Relation.DISJOINT


_SUPPORT = {"SUPPORTED", "UNSUPPORTED", "INSUFFICIENT"}
_CLASSIFICATIONS = {item.value for item in Classification}
_UNCERTAINTY = {
    "unsupported_requirement", "insufficient_support", "unknown_scope",
    "unknown_effective_dates", "scope_disjoint", "time_disjoint",
    "precedence_unresolved", "incomplete_comparison", "excerpt_coverage",
    "classification_not_established", "impact_not_grounded", "impact_incomplete",
    "independent_assessment_unavailable", "coverage_unverified",
    "impact_coverage_unverified",
}


def _requirement(value: Any, *, side: str, pair: PolicyPair) -> tuple[dict[str, Any], ...] | None:
    if value is None:
        return None
    obj = _object(value, {"text", "support", "citations"}, "invalid_candidate")
    _string(obj["text"], maximum=MAX_CANDIDATE_TEXT, code="invalid_candidate")
    if type(obj["support"]) is not str or obj["support"] not in _SUPPORT:
        raise PolicyCompareError("invalid_candidate")
    raw_citations = obj["citations"]
    if type(raw_citations) is not list:
        raise PolicyCompareError("invalid_candidate")
    if obj["support"] == "SUPPORTED" and not raw_citations:
        raise PolicyCompareError("invalid_candidate")
    citations = tuple(validate_citation(pair, item, expected_side=side) for item in raw_citations)
    return citations


def _precedence(value: Any, pair: PolicyPair) -> tuple[str, tuple[dict[str, Any], ...]]:
    obj = _object(value, {"status", "support", "citations"}, "invalid_candidate")
    if type(obj["status"]) is not str or obj["status"] not in {"NOT_REQUIRED", "DEFINED", "UNRESOLVED"}:
        raise PolicyCompareError("invalid_candidate")
    if type(obj["support"]) is not str or obj["support"] not in _SUPPORT or type(obj["citations"]) is not list:
        raise PolicyCompareError("invalid_candidate")
    citations = tuple(validate_citation(pair, item) for item in obj["citations"])
    if obj["status"] == "NOT_REQUIRED" and (obj["support"] != "INSUFFICIENT" or citations):
        raise PolicyCompareError("invalid_candidate")
    if obj["status"] == "DEFINED" and (obj["support"] != "SUPPORTED" or not citations):
        raise PolicyCompareError("invalid_candidate")
    return obj["status"], citations


def _impact_claims(value: Any, pair: PolicyPair) -> tuple[dict[str, Any], ...]:
    if type(value) is not list:
        raise PolicyCompareError("invalid_candidate")
    result = []
    seen = set()
    for item in value:
        obj = _object(item, {"kind", "target_id", "support", "citations"}, "invalid_candidate")
        if type(obj["kind"]) is not str or obj["kind"] not in {"DEPARTMENT", "PROCEDURE"}:
            raise PolicyCompareError("invalid_candidate")
        target = _identifier(obj["target_id"], _SCOPE_ID)
        if type(obj["support"]) is not str or obj["support"] not in _SUPPORT or type(obj["citations"]) is not list:
            raise PolicyCompareError("invalid_candidate")
        citations = tuple(validate_citation(pair, citation) for citation in obj["citations"])
        if obj["support"] == "SUPPORTED" and not citations:
            raise PolicyCompareError("invalid_candidate")
        key = (obj["kind"], target)
        if key in seen:
            raise PolicyCompareError("invalid_candidate")
        seen.add(key)
        result.append({"kind": obj["kind"], "target_id": target,
                       "support": obj["support"], "citations": citations})
    return tuple(result)


def _candidate(value: Any, pair: PolicyPair) -> dict[str, Any]:
    keys = {"candidate_id", "classification", "summary", "older_requirement",
            "newer_requirement", "comparison_coverage", "precedence",
            "impact_coverage", "impact_targets", "resolution_draft"}
    obj = _object(value, keys, "invalid_candidate")
    _identifier(obj["candidate_id"], _CANDIDATE_ID)
    if type(obj["classification"]) is not str or obj["classification"] not in _CLASSIFICATIONS:
        raise PolicyCompareError("invalid_candidate")
    summary = _string(obj["summary"], maximum=MAX_SUMMARY, code="invalid_candidate")
    old = _requirement(obj["older_requirement"], side="OLDER", pair=pair)
    new = _requirement(obj["newer_requirement"], side="NEWER", pair=pair)
    classification = obj["classification"]
    if classification == "NEW_RULE":
        if obj["older_requirement"] is not None or obj["newer_requirement"] is None:
            raise PolicyCompareError("invalid_candidate")
    elif classification != "INCONCLUSIVE" and (obj["older_requirement"] is None or obj["newer_requirement"] is None):
        raise PolicyCompareError("invalid_candidate")
    if type(obj["comparison_coverage"]) is not str or obj["comparison_coverage"] not in {"COMPLETE", "INCOMPLETE"}:
        raise PolicyCompareError("invalid_candidate")
    if type(obj["impact_coverage"]) is not str or obj["impact_coverage"] not in {"COMPLETE", "INCOMPLETE"}:
        raise PolicyCompareError("invalid_candidate")
    precedence_status, precedence_citations = _precedence(obj["precedence"], pair)
    impacts = _impact_claims(obj["impact_targets"], pair)
    draft = obj["resolution_draft"]
    if draft is not None:
        draft = _string(draft, maximum=MAX_RESOLUTION, code="invalid_candidate")
    return {"id": obj["candidate_id"], "classification": classification,
            "summary": summary, "old": old, "new": new,
            "old_support": "INSUFFICIENT" if obj["older_requirement"] is None else obj["older_requirement"]["support"],
            "new_support": "INSUFFICIENT" if obj["newer_requirement"] is None else obj["newer_requirement"]["support"],
            "coverage": obj["comparison_coverage"], "precedence": precedence_status,
            "precedence_citations": precedence_citations,
            "impact_coverage": obj["impact_coverage"], "impacts": impacts,
            "resolution": draft}


def _scoped_dependency(pair: PolicyPair, kind: str, target: str, citation: dict[str, Any]) -> PolicyVersion | None:
    for version in (pair.older, pair.newer):
        if (citation["document_id"] != version.document_id
                or citation["version_id"] != version.version_id
                or citation["source_sha256"] != version.source_sha256):
            continue
        for dependency in version.impact_dependencies:
            target_match = (dependency.department_id == target if kind == "DEPARTMENT"
                            else dependency.procedure_id == target)
            if target_match and citation["passage_id"] in dependency.passage_ids:
                return version
    return None


def _citation_with_role(citation: dict[str, Any], role: str) -> dict[str, Any]:
    return {"role": role, **citation}


def compare_candidate(pair: PolicyPair, value: Any) -> dict[str, Any]:
    """Validate provenance and retain candidate assertions as proposals only."""
    candidate = _candidate(value, pair)
    scope = scope_relation(pair.older, pair.newer)
    time = time_relation(pair.older, pair.newer)
    proposed = candidate["classification"]
    reasons: list[str] = ["independent_assessment_unavailable", "coverage_unverified",
                          "impact_coverage_unverified"]
    if candidate["old_support"] == "UNSUPPORTED" or candidate["new_support"] == "UNSUPPORTED":
        reasons.append("unsupported_requirement")
    if candidate["old_support"] == "INSUFFICIENT" or candidate["new_support"] == "INSUFFICIENT":
        reasons.append("insufficient_support")
    if scope == Relation.UNKNOWN:
        reasons.append("unknown_scope")
    if time == Relation.UNKNOWN:
        reasons.append("unknown_effective_dates")
    if scope == Relation.DISJOINT:
        reasons.append("scope_disjoint")
    if time == Relation.DISJOINT:
        reasons.append("time_disjoint")
    if candidate["precedence"] == "UNRESOLVED":
        reasons.append("precedence_unresolved")
    if candidate["coverage"] == "INCOMPLETE":
        reasons.append("incomplete_comparison")
    if proposed == "NEW_RULE" and (pair.older.text_coverage != "FULL_DOCUMENT" or pair.newer.text_coverage != "FULL_DOCUMENT"):
        reasons.append("excerpt_coverage")

    citations: list[dict[str, Any]] = []
    for role, items in (("OLDER", candidate["old"] or ()), ("NEWER", candidate["new"] or ())):
        citations.extend(_citation_with_role(item, role) for item in items)
    citations.extend(_citation_with_role(item, "PRECEDENCE") for item in candidate["precedence_citations"])

    proposed_targets: list[dict[str, Any]] = []
    for item in candidate["impacts"]:
        kind, target = item["kind"], item["target_id"]
        valid = item["support"] == "SUPPORTED" and bool(item["citations"])
        for citation in item["citations"]:
            if _scoped_dependency(pair, kind, target, citation) is None:
                valid = False
                break
        if item["support"] == "SUPPORTED" and not valid:
            raise PolicyCompareError("invalid_candidate")
        if valid:
            proposed_targets.append({"kind": kind, "target_id": target,
                                    "support_assertion": item["support"],
                                    "citations": list(item["citations"])})
        elif item["support"] != "UNSUPPORTED":
            reasons.append("impact_not_grounded")
    if candidate["impact_coverage"] == "INCOMPLETE":
        reasons.append("impact_incomplete")
    impact_status = "PROPOSED" if proposed_targets else "INCONCLUSIVE"

    result = {
        "schema_version": 1,
        "comparison_id": pair.comparison_id,
        "candidate_id": candidate["id"],
        "classification": "INCONCLUSIVE",
        "proposed_classification": proposed,
        "assessment_status": "INCONCLUSIVE",
        "summary": candidate["summary"],
        "citations": citations,
        "evidence_checks": {
            "older_requirement_support_assertion": candidate["old_support"],
            "newer_requirement_support_assertion": candidate["new_support"],
            "source_spans": "VALID",
            "semantic_assessment_origin": "UNTRUSTED_CALLER_ASSERTION",
            "comparison_coverage_assertion": candidate["coverage"],
            "coverage_origin": "UNTRUSTED_CALLER_ASSERTION",
        },
        "scope_time": {"scope_relation": scope.value, "time_relation": time.value,
                       "precedence_assertion": candidate["precedence"],
                       "precedence_origin": "UNTRUSTED_CALLER_ASSERTION"},
        "uncertainty_reasons": sorted(set(reasons)),
        "impact": {"status": impact_status,
                   "coverage_assertion": candidate["impact_coverage"],
                   "coverage_origin": "UNTRUSTED_CALLER_ASSERTION",
                   "departments": [], "procedures": [], "citations": [],
                   "proposed_targets": proposed_targets},
        "resolution_draft": candidate["resolution"],
        "human_review_required": True,
        "official_policy_mutated": False,
    }
    return validate_result(pair, result)


def validate_result(pair: PolicyPair, value: Any) -> dict[str, Any]:
    """Validate a proposal envelope; caller assertions cannot become findings."""
    keys = {"schema_version", "comparison_id", "candidate_id", "classification", "proposed_classification",
            "assessment_status", "summary",
            "citations", "evidence_checks", "scope_time", "uncertainty_reasons", "impact",
            "resolution_draft", "human_review_required", "official_policy_mutated"}
    obj = _object(value, keys, "invalid_result")
    try:
        if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
            raise PolicyCompareError("invalid_result")
        if type(obj["comparison_id"]) is not str or obj["comparison_id"] != pair.comparison_id:
            raise PolicyCompareError("invalid_result")
        _identifier(obj["candidate_id"], _CANDIDATE_ID)
        if (type(obj["classification"]) is not str or obj["classification"] != "INCONCLUSIVE"
                or type(obj["proposed_classification"]) is not str
                or obj["proposed_classification"] not in _CLASSIFICATIONS
                or type(obj["assessment_status"]) is not str
                or obj["assessment_status"] != "INCONCLUSIVE"):
            raise PolicyCompareError("invalid_result")
        _string(obj["summary"], maximum=MAX_SUMMARY, code="invalid_result")
        if type(obj["human_review_required"]) is not bool or obj["human_review_required"] is not True:
            raise PolicyCompareError("invalid_result")
        if type(obj["official_policy_mutated"]) is not bool or obj["official_policy_mutated"] is not False:
            raise PolicyCompareError("invalid_result")
        resolution = obj["resolution_draft"]
        if resolution is not None:
            _string(resolution, maximum=MAX_RESOLUTION, code="invalid_result")

        evidence = _object(obj["evidence_checks"], {"older_requirement_support_assertion", "newer_requirement_support_assertion",
            "source_spans", "semantic_assessment_origin", "comparison_coverage_assertion", "coverage_origin"}, "invalid_result")
        if (type(evidence["older_requirement_support_assertion"]) is not str or evidence["older_requirement_support_assertion"] not in _SUPPORT
                or type(evidence["newer_requirement_support_assertion"]) is not str or evidence["newer_requirement_support_assertion"] not in _SUPPORT
                or type(evidence["source_spans"]) is not str or evidence["source_spans"] != "VALID"
                or type(evidence["semantic_assessment_origin"]) is not str or evidence["semantic_assessment_origin"] != "UNTRUSTED_CALLER_ASSERTION"
                or type(evidence["comparison_coverage_assertion"]) is not str
                or evidence["comparison_coverage_assertion"] not in {"COMPLETE", "INCOMPLETE"}
                or type(evidence["coverage_origin"]) is not str or evidence["coverage_origin"] != "UNTRUSTED_CALLER_ASSERTION"):
            raise PolicyCompareError("invalid_result")
        scope_time = _object(obj["scope_time"], {"scope_relation", "time_relation", "precedence_assertion", "precedence_origin"}, "invalid_result")
        expected_scope, expected_time = scope_relation(pair.older, pair.newer), time_relation(pair.older, pair.newer)
        if (type(scope_time["scope_relation"]) is not str or scope_time["scope_relation"] != expected_scope.value
                or type(scope_time["time_relation"]) is not str or scope_time["time_relation"] != expected_time.value
                or type(scope_time["precedence_assertion"]) is not str
                or scope_time["precedence_assertion"] not in {"NOT_REQUIRED", "DEFINED", "UNRESOLVED"}
                or type(scope_time["precedence_origin"]) is not str
                or scope_time["precedence_origin"] != "UNTRUSTED_CALLER_ASSERTION"):
            raise PolicyCompareError("invalid_result")
        reasons = obj["uncertainty_reasons"]
        if (type(reasons) is not list or not reasons
                or any(type(reason) is not str or reason not in _UNCERTAINTY for reason in reasons)
                or len(set(reasons)) != len(reasons)
                or "independent_assessment_unavailable" not in reasons
                or "coverage_unverified" not in reasons):
            raise PolicyCompareError("invalid_result")

        raw_citations = obj["citations"]
        if type(raw_citations) is not list:
            raise PolicyCompareError("invalid_result")
        citations: list[dict[str, Any]] = []
        role_counts = {"OLDER": 0, "NEWER": 0, "PRECEDENCE": 0}
        for raw in raw_citations:
            if type(raw) is not dict or "role" not in raw:
                raise PolicyCompareError("invalid_result")
            role = raw["role"]
            if type(role) is not str or role not in role_counts:
                raise PolicyCompareError("invalid_result")
            citation_obj = {key: item for key, item in raw.items() if key != "role"}
            expected = "OLDER" if role == "OLDER" else "NEWER" if role == "NEWER" else None
            canonical = validate_citation(pair, citation_obj, expected_side=expected)
            citations.append(_citation_with_role(canonical, role))
            role_counts[role] += 1

        if role_counts["PRECEDENCE"] and scope_time["precedence_assertion"] != "DEFINED":
            raise PolicyCompareError("invalid_result")
        if scope_time["precedence_assertion"] == "DEFINED" and not role_counts["PRECEDENCE"]:
            raise PolicyCompareError("invalid_result")
        impact = _object(obj["impact"], {"status", "coverage_assertion", "coverage_origin", "departments", "procedures", "citations", "proposed_targets"}, "invalid_result")
        if (type(impact["status"]) is not str or impact["status"] not in {"PROPOSED", "INCONCLUSIVE"}
                or type(impact["coverage_assertion"]) is not str or impact["coverage_assertion"] not in {"COMPLETE", "INCOMPLETE"}
                or type(impact["coverage_origin"]) is not str or impact["coverage_origin"] != "UNTRUSTED_CALLER_ASSERTION"):
            raise PolicyCompareError("invalid_result")
        if (impact["status"] in {"PROPOSED", "INCONCLUSIVE"}
                and "impact_coverage_unverified" not in reasons):
            raise PolicyCompareError("invalid_result")
        departments = _string_list(impact["departments"], pattern=_SCOPE_ID, allow_empty=True)
        procedures = _string_list(impact["procedures"], pattern=_SCOPE_ID, allow_empty=True)
        if (departments or procedures or type(impact["citations"]) is not list or impact["citations"]
                or type(impact["proposed_targets"]) is not list):
            raise PolicyCompareError("invalid_result")
        target_evidence = []
        seen_targets = set()
        for raw_target in impact["proposed_targets"]:
            target = _object(raw_target, {"kind", "target_id", "support_assertion", "citations"}, "invalid_result")
            if (type(target["kind"]) is not str or target["kind"] not in {"DEPARTMENT", "PROCEDURE"}
                    or type(target["support_assertion"]) is not str or target["support_assertion"] != "SUPPORTED"):
                raise PolicyCompareError("invalid_result")
            target_id = _identifier(target["target_id"], _SCOPE_ID)
            target_key = (target["kind"], target_id)
            if target_key in seen_targets or type(target["citations"]) is not list or not target["citations"]:
                raise PolicyCompareError("invalid_result")
            seen_targets.add(target_key)
            target_citations = []
            for raw_citation in target["citations"]:
                ref = validate_citation(pair, raw_citation)
                if _scoped_dependency(pair, target["kind"], target_id, ref) is None:
                    raise PolicyCompareError("invalid_result")
                target_citations.append(ref)
            target_evidence.append({"kind": target["kind"], "target_id": target_id,
                                    "support_assertion": "SUPPORTED", "citations": target_citations})
        if (impact["status"] == "PROPOSED") != bool(target_evidence):
            raise PolicyCompareError("invalid_result")

        return {
            **obj,
            "citations": citations,
            "evidence_checks": dict(evidence),
            "scope_time": dict(scope_time),
            "uncertainty_reasons": list(reasons),
            "impact": {"status": impact["status"], "coverage_assertion": impact["coverage_assertion"],
                       "coverage_origin": impact["coverage_origin"],
                       "departments": list(departments), "procedures": list(procedures),
                       "citations": [], "proposed_targets": target_evidence},
        }
    except PolicyCompareError as exc:
        if exc.code == "invalid_result":
            raise
        raise PolicyCompareError("invalid_result") from None
    except (KeyError, TypeError, ValueError):
        raise PolicyCompareError("invalid_result") from None
