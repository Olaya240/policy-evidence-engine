"""Hand-authored synthetic scaffolding; not independent judgments or holdout data."""
from copy import deepcopy
from hashlib import sha256
import re

import pytest

from policy_compare import (
    Classification,
    PolicyCompareError,
    Relation,
    compare_candidate,
    scope_relation,
    time_relation,
    validate_citation,
    validate_policy_pair,
    validate_result,
)


OLD_TEXT = "Front Office must record each guest request before the shift ends."
NEW_TEXT = "Front Office must not record guest requests until the next shift begins."


def _passage_id(text, ordinal=1):
    return f"p{ordinal:06d}-{sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _version(version_id, text, *, departments=("FRONT_OFFICE",), procedures=("GUEST_REQUEST",),
             start="2026-01-01", end="2027-01-01", coverage="FULL_DOCUMENT", dependencies=None):
    first_paragraph = re.split(r"(?:\r\n|\r|\n)[\t ]*(?:(?:\r\n|\r|\n)[\t ]*)+", text)[0].strip()
    scope_passages = [_passage_id(first_paragraph)] if departments is not None or procedures is not None else []
    return {
        "document_id": "syn-policy-handover",
        "version_id": version_id,
        "original_text": text,
        "effective_from": start,
        "effective_to_exclusive": end,
        "scope": {
            "departments": {"state": "UNKNOWN", "ids": []} if departments is None else {"state": "KNOWN", "ids": list(departments)},
            "procedures": {"state": "UNKNOWN", "ids": []} if procedures is None else {"state": "KNOWN", "ids": list(procedures)},
            "property_id": "SYNTHETIC_HOTEL_01",
            "evidence_passage_ids": scope_passages,
        },
        "text_coverage": coverage,
        "impact_dependencies": dependencies or [],
    }


def _pair(old_text=OLD_TEXT, new_text=NEW_TEXT, **kwargs):
    return validate_policy_pair({
        "schema_version": 1,
        "comparison_id": "cmp-syn-001",
        "older": _version("v1", old_text, **kwargs),
        "newer": _version("v2", new_text, **kwargs),
    })


def _cite(version, quote=None):
    if quote is None:
        passage = version.passages[0]
        start, end = passage.start_cp, passage.end_cp
    else:
        start = version.original_text.index(quote)
        end = start + len(quote)
        passage = next(p for p in version.passages if p.start_cp <= start and end <= p.end_cp)
    return {
        "document_id": version.document_id,
        "version_id": version.version_id,
        "source_sha256": version.source_sha256,
        "passage_id": passage.passage_id,
        "start_cp": start,
        "end_cp": end,
        "quote": version.original_text[start:end],
    }


def _requirement(version, support="SUPPORTED"):
    return {"text": version.passages[0].text, "support": support, "citations": [_cite(version)]}


def _candidate(pair, classification="CONTRADICTION", *, old_support="SUPPORTED",
               new_support="SUPPORTED", coverage="COMPLETE", precedence=None,
               impact_coverage="COMPLETE", impact_targets=None, resolution="Ask the policy owner to review both passages."):
    new_rule = classification == "NEW_RULE"
    return {
        "candidate_id": "cand-syn-001",
        "classification": classification,
        "summary": "Synthetic candidate for contract testing.",
        "older_requirement": None if new_rule else _requirement(pair.older, old_support),
        "newer_requirement": _requirement(pair.newer, new_support),
        "comparison_coverage": coverage,
        "precedence": precedence or {"status": "NOT_REQUIRED", "support": "INSUFFICIENT", "citations": []},
        "impact_coverage": impact_coverage,
        "impact_targets": [] if impact_targets is None else impact_targets,
        "resolution_draft": resolution,
    }


def test_strict_input_unknown_keys_types_ids_and_duplicate_versions_reject():
    pair_input = {"schema_version": 1, "comparison_id": "cmp-syn-001",
                  "older": _version("v1", OLD_TEXT), "newer": _version("v2", NEW_TEXT)}
    for mutate in (
        lambda x: x.update(extra=True),
        lambda x: x.update(schema_version=True),
        lambda x: x.update(comparison_id="cmp-syn-BAD"),
        lambda x: x["newer"].update(version_id="v1"),
        lambda x: x["older"].update(original_text=123),
    ):
        bad = deepcopy(pair_input)
        mutate(bad)
        with pytest.raises(PolicyCompareError):
            validate_policy_pair(bad)


@pytest.mark.parametrize("bad_text", ["", " \t\r\n", "bad\x00text", "bad\ud800text"])
def test_invalid_source_text_is_rejected_with_fixed_error(bad_text):
    value = {"schema_version": 1, "comparison_id": "cmp-syn-001",
             "older": _version("v1", OLD_TEXT), "newer": _version("v2", bad_text, departments=None, procedures=None)}
    with pytest.raises(PolicyCompareError) as error:
        validate_policy_pair(value)
    assert error.value.code in {"invalid_text", "input_too_large"}
    if bad_text:
        assert bad_text not in str(error.value)


def test_unicode_crlf_and_combining_characters_are_preserved_exactly():
    text = "Réception 👋\r\n\r\nCafe\u0301 must log the guest’s note."
    pair = _pair(text, text)
    assert pair.older.original_text == text
    assert pair.older.source_sha256 == sha256(text.encode("utf-8")).hexdigest()
    assert [p.text for p in pair.older.passages] == ["Réception 👋", "Cafe\u0301 must log the guest’s note."]
    citation = _cite(pair.older, "Cafe\u0301")
    assert validate_citation(pair, citation, expected_side="OLDER")["quote"] == "Cafe\u0301"
    assert "Café" not in pair.older.original_text  # NFC normalization was not applied.


def test_passage_ids_and_hashes_are_deterministic_and_duplicate_text_has_distinct_ordinals():
    text = "Same rule.\n\nSame rule."
    first, second = validate_policy_pair({
        "schema_version": 1, "comparison_id": "cmp-syn-001",
        "older": _version("v1", text), "newer": _version("v2", text),
    }), validate_policy_pair({
        "schema_version": 1, "comparison_id": "cmp-syn-001",
        "older": _version("v1", text), "newer": _version("v2", text),
    })
    assert first.older == second.older
    assert first.older.passages[0].text_sha256 == first.older.passages[1].text_sha256
    assert first.older.passages[0].passage_id != first.older.passages[1].passage_id
    assert first.older.passages[0].ordinal == 1 and first.older.passages[1].ordinal == 2


@pytest.mark.parametrize("change", ["offset", "quote", "hash", "document", "version", "passage"])
def test_invalid_citation_components_are_rejected(change):
    pair = _pair()
    cite = _cite(pair.older)
    if change == "offset":
        cite["end_cp"] += 1
    elif change == "quote":
        cite["quote"] = "fabricated text"
    elif change == "hash":
        cite["source_sha256"] = "0" * 64
    elif change == "document":
        cite["document_id"] = "syn-policy-fabricated"
    elif change == "version":
        cite["version_id"] = "v9"
    else:
        cite["passage_id"] = "p000999-0000000000000000"
    with pytest.raises(PolicyCompareError) as error:
        validate_citation(pair, cite, expected_side="OLDER")
    assert error.value.code == "invalid_citation"
    assert "fabricated text" not in str(error.value)


def test_citation_offsets_reject_booleans_and_cross_passage_boundaries():
    pair = _pair("First passage.\n\nSecond passage.", "First passage.\n\nSecond passage.")
    cite = _cite(pair.older, "First passage.")
    cite["start_cp"] = True
    with pytest.raises(PolicyCompareError) as error:
        validate_citation(pair, cite)
    assert error.value.code == "invalid_citation"

    passage = pair.older.passages[0]
    cross_end = pair.older.original_text.index("Second passage.") + len("Second passage.")
    crossing = {**_cite(pair.older, "First passage."), "end_cp": cross_end,
                "quote": pair.older.original_text[passage.start_cp:cross_end]}
    with pytest.raises(PolicyCompareError) as error:
        validate_citation(pair, crossing)
    assert error.value.code == "invalid_citation"


def test_scope_relationship_and_unknown_metadata():
    overlap = _pair()
    assert scope_relation(overlap.older, overlap.newer) is Relation.OVERLAP
    unknown = _pair(departments=None)
    assert scope_relation(unknown.older, unknown.newer) is Relation.UNKNOWN
    disjoint = validate_policy_pair({
        "schema_version": 1, "comparison_id": "cmp-syn-001",
        "older": _version("v1", OLD_TEXT, departments=("FRONT_OFFICE",)),
        "newer": _version("v2", NEW_TEXT, departments=("HOUSEKEEPING",)),
    })
    assert scope_relation(disjoint.older, disjoint.newer) is Relation.DISJOINT


def test_explicit_global_scope_and_literal_all_identifier_are_distinct():
    value = {"schema_version": 1, "comparison_id": "cmp-syn-001",
             "older": _version("v1", OLD_TEXT), "newer": _version("v2", NEW_TEXT)}
    value["older"]["scope"]["departments"] = {"state": "ALL", "ids": []}
    value["newer"]["scope"]["departments"] = {"state": "KNOWN", "ids": ["HOUSEKEEPING"]}
    global_pair = validate_policy_pair(value)
    assert global_pair.older.scope.departments.state == "ALL"
    assert scope_relation(global_pair.older, global_pair.newer) is Relation.OVERLAP

    value["older"]["scope"]["departments"] = {"state": "KNOWN", "ids": ["ALL"]}
    literal_pair = validate_policy_pair(value)
    assert scope_relation(literal_pair.older, literal_pair.newer) is Relation.DISJOINT


def test_exclusive_date_end_and_unknown_dates():
    pair = validate_policy_pair({
        "schema_version": 1, "comparison_id": "cmp-syn-001",
        "older": _version("v1", OLD_TEXT, start="2026-01-01", end="2026-07-01"),
        "newer": _version("v2", NEW_TEXT, start="2026-07-01", end="2027-01-01"),
    })
    assert time_relation(pair.older, pair.newer) is Relation.DISJOINT
    unknown = _pair(start=None)
    assert time_relation(unknown.older, unknown.newer) is Relation.UNKNOWN


@pytest.mark.parametrize("bad_range", [("2026-02-30", "2027-01-01"), ("2027-01-01", "2026-01-01"), ("2026-1-01", "2027-01-01")])
def test_invalid_effective_dates_reject(bad_range):
    value = {"schema_version": 1, "comparison_id": "cmp-syn-001",
             "older": _version("v1", OLD_TEXT, start=bad_range[0], end=bad_range[1]),
             "newer": _version("v2", NEW_TEXT)}
    with pytest.raises(PolicyCompareError) as error:
        validate_policy_pair(value)
    assert error.value.code == "invalid_date_range"


def test_malformed_scope_and_dependency_reject():
    value = {"schema_version": 1, "comparison_id": "cmp-syn-001",
             "older": _version("v1", OLD_TEXT), "newer": _version("v2", NEW_TEXT)}
    bad_scope = deepcopy(value)
    bad_scope["older"]["scope"]["departments"] = {"state": "KNOWN", "ids": []}
    with pytest.raises(PolicyCompareError) as error:
        validate_policy_pair(bad_scope)
    assert error.value.code == "invalid_scope"
    bad_dependency = deepcopy(value)
    bad_dependency["older"]["impact_dependencies"] = [{"department_id": "FRONT_OFFICE", "procedure_id": None, "passage_ids": ["p000999-0000000000000000"]}]
    with pytest.raises(PolicyCompareError) as error:
        validate_policy_pair(bad_dependency)
    assert error.value.code == "invalid_dependency"


def test_excessive_text_and_passage_counts_reject_before_comparison():
    for oversized in ("x" * 100_001, "\n\n".join(["rule"] * 1_001)):
        value = {"schema_version": 1, "comparison_id": "cmp-syn-001",
                 "older": _version("v1", oversized, departments=None, procedures=None),
                 "newer": _version("v2", NEW_TEXT)}
        with pytest.raises(PolicyCompareError) as error:
            validate_policy_pair(value)
        assert error.value.code == "input_too_large"


@pytest.mark.parametrize("classification", [
    "CONTRADICTION", "COMPATIBLE_CHANGE", "NEW_RULE", "SCOPE_OR_TIME_DIFFERENCE", "INCONCLUSIVE",
])
def test_all_five_classification_values_are_returned_with_human_review(classification):
    if classification == "NEW_RULE":
        pair = _pair(new_text="New synthetic inspection rule.")
    elif classification == "SCOPE_OR_TIME_DIFFERENCE":
        pair = validate_policy_pair({
            "schema_version": 1, "comparison_id": "cmp-syn-001",
            "older": _version("v1", OLD_TEXT, departments=("FRONT_OFFICE",)),
            "newer": _version("v2", NEW_TEXT, departments=("HOUSEKEEPING",)),
        })
    else:
        pair = _pair()
    result = compare_candidate(pair, _candidate(pair, classification))
    assert result["classification"] == "INCONCLUSIVE"
    assert result["proposed_classification"] == classification
    assert result["assessment_status"] == "INCONCLUSIVE"
    assert "independent_assessment_unavailable" in result["uncertainty_reasons"]
    assert "coverage_unverified" in result["uncertainty_reasons"]
    assert result["human_review_required"] is True
    assert result["official_policy_mutated"] is False
    assert result["evidence_checks"]["semantic_assessment_origin"] == "UNTRUSTED_CALLER_ASSERTION"


def test_valid_quotes_with_unsupported_semantic_assessment_become_inconclusive():
    pair = _pair()
    candidate = _candidate(pair, old_support="SUPPORTED", new_support="UNSUPPORTED")
    result = compare_candidate(pair, candidate)
    assert result["citations"]  # Source provenance is valid.
    assert result["evidence_checks"]["source_spans"] == "VALID"
    assert result["classification"] == "INCONCLUSIVE"
    assert "unsupported_requirement" in result["uncertainty_reasons"]


def test_ambiguous_precedence_unknown_metadata_and_incomplete_coverage_abstain():
    pair = _pair()
    unresolved = _candidate(pair, precedence={"status": "UNRESOLVED", "support": "INSUFFICIENT", "citations": []})
    assert compare_candidate(pair, unresolved)["classification"] == "INCONCLUSIVE"
    incomplete = _candidate(pair, coverage="INCOMPLETE")
    assert compare_candidate(pair, incomplete)["classification"] == "INCONCLUSIVE"
    unknown = _pair(departments=None, start=None)
    assert compare_candidate(unknown, _candidate(unknown))["classification"] == "INCONCLUSIVE"


@pytest.mark.parametrize("side", ["older", "newer"])
def test_new_rule_rejected_as_classification_when_either_version_is_excerpt(side):
    old_coverage = "EXCERPT" if side == "older" else "FULL_DOCUMENT"
    new_coverage = "EXCERPT" if side == "newer" else "FULL_DOCUMENT"
    pair = validate_policy_pair({
        "schema_version": 1, "comparison_id": "cmp-syn-001",
        "older": _version("v1", OLD_TEXT, coverage=old_coverage),
        "newer": _version("v2", "New inspection rule.", coverage=new_coverage),
    })
    result = compare_candidate(pair, _candidate(pair, "NEW_RULE"))
    assert result["classification"] == "INCONCLUSIVE"
    assert result["proposed_classification"] == "NEW_RULE"
    assert "excerpt_coverage" in result["uncertainty_reasons"]


def test_new_rule_cannot_claim_validation_from_false_full_and_complete_flags():
    pair = _pair(old_text="Only one short excerpt.", new_text="Only the changed excerpt.")
    result = compare_candidate(pair, _candidate(pair, "NEW_RULE", coverage="COMPLETE"))
    assert result["classification"] == "INCONCLUSIVE"
    assert result["proposed_classification"] == "NEW_RULE"
    assert result["evidence_checks"]["comparison_coverage_assertion"] == "COMPLETE"
    assert result["evidence_checks"]["coverage_origin"] == "UNTRUSTED_CALLER_ASSERTION"
    assert "coverage_unverified" in result["uncertainty_reasons"]
    forged = deepcopy(result)
    forged["classification"] = "NEW_RULE"
    with pytest.raises(PolicyCompareError) as error:
        validate_result(pair, forged)
    assert error.value.code == "invalid_result"


def test_contradiction_and_compatible_change_remain_proposals_for_same_pair():
    pair = _pair()
    contradiction = compare_candidate(pair, _candidate(pair, "CONTRADICTION"))
    compatible = compare_candidate(pair, _candidate(pair, "COMPATIBLE_CHANGE"))
    assert contradiction["classification"] == compatible["classification"] == "INCONCLUSIVE"
    assert contradiction["proposed_classification"] == "CONTRADICTION"
    assert compatible["proposed_classification"] == "COMPATIBLE_CHANGE"


def test_supported_impact_without_matching_dependency_is_rejected():
    pair = _pair()
    claim = {"kind": "DEPARTMENT", "target_id": "HOUSEKEEPING", "support": "SUPPORTED",
             "citations": [_cite(pair.newer)]}
    with pytest.raises(PolicyCompareError) as error:
        compare_candidate(pair, _candidate(pair, impact_targets=[claim]))
    assert error.value.code == "invalid_candidate"
    assert str(error.value) == "A policy comparison candidate is invalid."
    assert "HOUSEKEEPING" not in str(error.value)


def test_supported_impact_requires_cited_dependency_evidence():
    text = "Inspect the handover log for missing room numbers."
    pid = _passage_id(text)
    dep = [{"department_id": "FRONT_OFFICE", "procedure_id": "ROOM_HANDOVER", "passage_ids": [pid]}]
    pair = _pair(old_text=text, new_text=text, dependencies=dep)
    claim = {"kind": "DEPARTMENT", "target_id": "FRONT_OFFICE", "support": "SUPPORTED",
             "citations": [_cite(pair.newer)]}
    result = compare_candidate(pair, _candidate(pair, "INCONCLUSIVE", impact_targets=[claim]))
    assert result["impact"]["status"] == "PROPOSED"
    assert result["impact"]["departments"] == []
    assert result["impact"]["proposed_targets"] == [{
        "kind": "DEPARTMENT", "target_id": "FRONT_OFFICE",
        "support_assertion": "SUPPORTED", "citations": [_cite(pair.newer)]}]


def test_impact_dependency_requires_exact_version_and_source_hash():
    old_text = "Shared dependency passage.\n\nOlder wording."
    new_text = "Shared dependency passage.\n\nNewer wording."
    pid = _passage_id("Shared dependency passage.")
    old = _version("v1", old_text, dependencies=[])
    new = _version("v2", new_text, dependencies=[{
        "department_id": "FRONT_OFFICE", "procedure_id": None, "passage_ids": [pid]}])
    pair = validate_policy_pair({"schema_version": 1, "comparison_id": "cmp-syn-001",
                                 "older": old, "newer": new})
    assert pair.older.passages[0].passage_id == pair.newer.passages[0].passage_id
    old_citation = _cite(pair.older, "Shared dependency passage.")
    claim = {"kind": "DEPARTMENT", "target_id": "FRONT_OFFICE", "support": "SUPPORTED",
             "citations": [old_citation]}
    with pytest.raises(PolicyCompareError) as error:
        compare_candidate(pair, _candidate(pair, "INCONCLUSIVE", impact_targets=[claim]))
    assert error.value.code == "invalid_candidate"

    newer_citation = _cite(pair.newer, "Shared dependency passage.")
    newer_citation["source_sha256"] = pair.older.source_sha256
    claim["citations"] = [newer_citation]
    with pytest.raises(PolicyCompareError) as error:
        compare_candidate(pair, _candidate(pair, "INCONCLUSIVE", impact_targets=[claim]))
    assert error.value.code == "invalid_citation"


def test_each_impact_target_requires_its_own_matching_dependency_citation():
    text = "Inspect the handover log for missing room numbers."
    pid = _passage_id(text)
    dep = [{"department_id": "FRONT_OFFICE", "procedure_id": None, "passage_ids": [pid]}]
    pair = _pair(old_text=text, new_text=text, dependencies=dep)
    citation = _cite(pair.newer)
    claims = [
        {"kind": "DEPARTMENT", "target_id": "FRONT_OFFICE", "support": "SUPPORTED", "citations": [citation]},
        {"kind": "DEPARTMENT", "target_id": "HOUSEKEEPING", "support": "SUPPORTED", "citations": [citation]},
    ]
    with pytest.raises(PolicyCompareError) as error:
        compare_candidate(pair, _candidate(pair, "INCONCLUSIVE", impact_targets=claims))
    assert error.value.code == "invalid_candidate"

    single_claim = claims[:1]
    valid_result = compare_candidate(pair, _candidate(pair, "INCONCLUSIVE", impact_targets=single_claim))
    forged_result = deepcopy(valid_result)
    forged_result["impact"]["proposed_targets"].append({
        "kind": "DEPARTMENT", "target_id": "HOUSEKEEPING",
        "support_assertion": "SUPPORTED", "citations": [_cite(pair.newer)]})
    with pytest.raises(PolicyCompareError) as error:
        validate_result(pair, forged_result)
    assert error.value.code == "invalid_result"


def test_malformed_candidate_and_result_rejected_with_fixed_codes():
    pair = _pair()
    candidate = _candidate(pair)
    candidate["classification"] = []  # Unhashable malformed value must not leak TypeError.
    with pytest.raises(PolicyCompareError) as error:
        compare_candidate(pair, candidate)
    assert error.value.code == "invalid_candidate"
    assert "[]" not in str(error.value)
    valid = compare_candidate(pair, _candidate(pair))
    valid["official_policy_mutated"] = True
    with pytest.raises(PolicyCompareError) as error:
        validate_result(pair, valid)
    assert error.value.code == "invalid_result"


def test_inconclusive_result_requires_recognized_coherent_uncertainty_reasons():
    pair = _pair()
    valid = compare_candidate(pair, _candidate(pair))
    assert "independent_assessment_unavailable" in valid["uncertainty_reasons"]
    assert "coverage_unverified" in valid["uncertainty_reasons"]
    assert "impact_coverage_unverified" in valid["uncertainty_reasons"]
    assert validate_result(pair, valid)["assessment_status"] == "INCONCLUSIVE"

    missing = deepcopy(valid)
    missing["uncertainty_reasons"].remove("impact_coverage_unverified")
    malformed = deepcopy(valid)
    malformed["uncertainty_reasons"] = ["raw assertion: secret-like diagnostic"]
    malformed_type = deepcopy(valid)
    malformed_type["uncertainty_reasons"] = [123]
    for result in (missing, malformed, malformed_type):
        with pytest.raises(PolicyCompareError) as error:
            validate_result(pair, result)
        assert error.value.code == "invalid_result"

    # No targets means no impact_not_grounded reason is needed; the lack of a
    # coverage verifier still requires impact_coverage_unverified.
    no_target = deepcopy(valid)
    if "impact_not_grounded" in no_target["uncertainty_reasons"]:
        no_target["uncertainty_reasons"].remove("impact_not_grounded")
    assert no_target["impact"]["proposed_targets"] == []
    assert "impact_not_grounded" not in no_target["uncertainty_reasons"]
    assert validate_result(pair, no_target)["impact"]["status"] == "INCONCLUSIVE"

    false_finding = deepcopy(valid)
    false_finding["classification"] = "CONTRADICTION"
    with pytest.raises(PolicyCompareError) as error:
        validate_result(pair, false_finding)
    assert error.value.code == "invalid_result"


def test_result_unknown_fields_and_wrong_side_citations_are_rejected():
    pair = _pair()
    wrong_side = _candidate(pair)
    wrong_side["older_requirement"]["citations"] = [_cite(pair.newer)]
    with pytest.raises(PolicyCompareError) as error:
        compare_candidate(pair, wrong_side)
    assert error.value.code == "invalid_citation"

    valid = compare_candidate(pair, _candidate(pair))
    valid["unexpected"] = "synthetic"
    with pytest.raises(PolicyCompareError) as error:
        validate_result(pair, valid)
    assert error.value.code == "invalid_result"


def test_resolution_draft_is_review_only_and_repeated_outputs_are_deterministic():
    pair = _pair()
    candidate = _candidate(pair)
    first = compare_candidate(pair, candidate)
    second = compare_candidate(pair, candidate)
    assert first == second
    assert first["resolution_draft"] == candidate["resolution_draft"]
    assert first["human_review_required"] is True
    assert first["official_policy_mutated"] is False
