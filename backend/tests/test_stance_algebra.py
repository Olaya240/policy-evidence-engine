"""Laws of the clause composition algebra (`app/stance_algebra.py`).

Each test here is one proof obligation, not one example. Nothing is asserted on a
hand-picked pair when it can be asserted on the whole carrier: the carrier has
four elements, so associativity is all 64 triples and the table is all 16 pairs.

The laws, in the order they are needed:

1. the carrier is closed and generated (``test_carrier_is_the_powerset_of...``);
2. the table is total over all 16 pairs and every cell is the *least* upper bound
   of the pair in the lattice order (``test_each_table_cell_is_the_least...``);
3. ``compose`` — the algebraic definition, union of direction sets — equals that
   order-theoretic table on all 16 pairs (``test_compose_agrees_with_the_table``);
4. the table is *forced* by the laws: identity, idempotence, absorption and the
   single opposing product derive every one of the 16 cells, so no cell was
   chosen (``test_the_table_is_forced_by_the_laws``);
5. associativity, commutativity, idempotence, `ABSTAIN_INFO` as identity;
6. monotone refinement: an informational clause never changes a direction, and no
   clause can ever *produce* a conflict or flip a direction;
7. the map onto the guard's return shape is total, and the guard itself reports
   only algebra reason codes.

A note on (4): a table is not a law. The point of deriving the table from the
axioms is that a later edit to the table alone cannot pass this file without also
changing the laws, which is the check that keeps the two in step.
"""
import ast
import inspect
import itertools

import pytest

import app.stance_algebra as algebra
from app.models import Stance
from app.semantic_guard import reviewed_relation_details
from app.stance_algebra import (
    ALL_MATCHED_CUES_REJECTED,
    AMBIGUOUS_CUE_RELATIONS,
    COMPOSITION_TABLE,
    CONDITIONAL_CUE,
    CONTRAST_CHANGED_CURRENT_STATE,
    CUE_IN_QUESTION,
    EVIDENCE_ABOUTNESS_FRAME,
    HEDGED_CUE,
    NEGATED_CUE,
    NEUTRAL,
    NO_CUE_MATCH,
    Clause,
    GuardReading,
    Modality,
    NegationScope,
    Polarity,
    QuantifierScope,
    Verdict,
    combine_reasons,
    compose,
    compose_all,
    is_abstention,
    is_direction,
    lattice_join,
    lattice_meet,
    leq,
    to_guard_reading,
)
from tests.test_semantic_guard_negation_corpus import CORPUS

VERDICTS = tuple(Verdict)
PAIRS = tuple(itertools.product(VERDICTS, VERDICTS))
TRIPLES = tuple(itertools.product(VERDICTS, VERDICTS, VERDICTS))


def _every_clause():
    """All 240 typed clause shapes reachable by the detector."""
    for polarity in Polarity:
        for modality in Modality:
            for negation in NegationScope:
                for quantifier in QuantifierScope:
                    for superseded in (False, True):
                        yield Clause(
                            polarity=polarity,
                            modality=modality,
                            negation=negation,
                            quantifier=quantifier,
                            superseded=superseded,
                        )


# --- 1. the carrier -------------------------------------------------------

def test_carrier_is_the_powerset_of_the_two_direction_atoms():
    # Four elements: the empty set, each atom, and their union. Nothing else is
    # reachable, which is why "compose two verdicts" is a total operation.
    assert len(VERDICTS) == 4
    assert {frozenset({Verdict.SUPPORTS}), frozenset({Verdict.CONTRADICTS})} <= {
        frozenset({v}) for v in VERDICTS if is_direction(v)
    }
    assert sum(1 for v in VERDICTS if is_abstention(v)) == 2
    assert {compose(a, b) for a, b in PAIRS} <= set(VERDICTS)


def test_the_order_is_a_lattice_on_every_pair():
    for left, right in PAIRS:
        join, meet = lattice_join(left, right), lattice_meet(left, right)
        assert leq(left, join) and leq(right, join)
        assert leq(meet, left) and leq(meet, right)
        assert join in VERDICTS and meet in VERDICTS
    # ABSTAIN_INFO is the bottom and ABSTAIN_CONFLICT the top of that order.
    for verdict in VERDICTS:
        assert leq(Verdict.ABSTAIN_INFO, verdict)
        assert leq(verdict, Verdict.ABSTAIN_CONFLICT)


# --- 2. the table is the join, cell by cell -------------------------------

def test_the_composition_table_is_total_over_all_sixteen_pairs():
    assert set(COMPOSITION_TABLE) == set(PAIRS)
    assert len(COMPOSITION_TABLE) == 16


def test_each_table_cell_is_the_least_upper_bound_of_its_pair():
    for (left, right), cell in COMPOSITION_TABLE.items():
        assert leq(left, cell) and leq(right, cell)
        for candidate in VERDICTS:
            if leq(left, candidate) and leq(right, candidate):
                assert leq(cell, candidate), (left, right, cell, candidate)


# --- 3. the algebraic definition agrees with the order-theoretic one -------

def test_compose_agrees_with_the_table_on_all_sixteen_pairs():
    for left, right in PAIRS:
        assert compose(left, right) is COMPOSITION_TABLE[(left, right)], (left, right)


def test_the_table_is_forced_by_the_laws():
    # Identity, idempotence, absorption and one opposing product determine all
    # sixteen cells. Every derivation must agree with every other: a second
    # derivation of the same cell with a different answer fails here.
    derived: dict[tuple[Verdict, Verdict], Verdict] = {}

    def put(pair, value):
        assert derived.setdefault(pair, value) is value, ("two laws disagree", pair)

    for verdict in VERDICTS:
        put((Verdict.ABSTAIN_INFO, verdict), verdict)   # identity
        put((verdict, Verdict.ABSTAIN_INFO), verdict)
        put((verdict, verdict), verdict)                # idempotence
        put((Verdict.ABSTAIN_CONFLICT, verdict), Verdict.ABSTAIN_CONFLICT)  # absorbing
        put((verdict, Verdict.ABSTAIN_CONFLICT), Verdict.ABSTAIN_CONFLICT)
    put((Verdict.SUPPORTS, Verdict.CONTRADICTS), Verdict.ABSTAIN_CONFLICT)
    put((Verdict.CONTRADICTS, Verdict.SUPPORTS), Verdict.ABSTAIN_CONFLICT)

    assert len(derived) == 16
    assert derived == dict(COMPOSITION_TABLE)


# --- 4. the laws themselves ----------------------------------------------

def test_composition_is_associative():
    for a, b, c in TRIPLES:
        assert compose(compose(a, b), c) is compose(a, compose(b, c)), (a, b, c)


def test_composition_is_commutative():
    for left, right in PAIRS:
        assert compose(left, right) is compose(right, left), (left, right)


def test_composition_is_idempotent():
    for verdict in VERDICTS:
        assert compose(verdict, verdict) is verdict


def test_abstain_info_is_the_identity():
    for verdict in VERDICTS:
        assert compose(verdict, Verdict.ABSTAIN_INFO) is verdict
        assert compose(Verdict.ABSTAIN_INFO, verdict) is verdict


# --- 5. monotone refinement ----------------------------------------------

def test_adding_an_informational_clause_never_changes_a_committed_direction():
    informational = [c for c in _every_clause() if c.verdict() is Verdict.ABSTAIN_INFO]
    assert informational, "no informational clause shapes; the test would prove nothing"
    for polarity in (Polarity.SUPPORTS, Polarity.CONTRADICTS):
        committed = Clause(polarity=polarity)
        base = compose_all([committed])
        assert base is not Verdict.ABSTAIN_INFO
        for clause in informational:
            assert compose_all([committed, clause]) is base
            assert compose_all([clause, committed]) is base
            assert compose_all([clause, committed, clause]) is base


def test_a_clause_never_produces_a_conflict_and_never_flips_a_direction():
    verdicts = {clause.verdict() for clause in _every_clause()}
    assert verdicts == {
        Verdict.SUPPORTS,
        Verdict.CONTRADICTS,
        Verdict.ABSTAIN_INFO,
    }
    # A CONTRADICTS-polarity clause can reach CONTRADICTS, never SUPPORTS: the
    # algebra has no operation that inverts a direction.
    for clause in _every_clause():
        if clause.polarity is Polarity.CONTRADICTS:
            assert clause.verdict() is not Verdict.SUPPORTS
        if clause.polarity is Polarity.SUPPORTS:
            assert clause.verdict() is not Verdict.CONTRADICTS


def test_two_opposing_assertions_compose_to_conflict_not_to_a_winner():
    support = Clause(polarity=Polarity.SUPPORTS)
    contradict = Clause(polarity=Polarity.CONTRADICTS)
    assert compose_all([support, contradict]) is Verdict.ABSTAIN_CONFLICT
    assert compose_all([contradict, support]) is Verdict.ABSTAIN_CONFLICT
    # No third clause breaks the tie: conflict absorbs later directions.
    for extra in (support, contradict):
        assert compose_all([support, contradict, extra]) is Verdict.ABSTAIN_CONFLICT
        assert compose_all([extra, support, contradict]) is Verdict.ABSTAIN_CONFLICT


def test_a_sentence_verdict_is_independent_of_clause_order():
    sentence = [
        Clause(polarity=Polarity.SUPPORTS),
        Clause(polarity=Polarity.SUPPORTS, modality=Modality.HEDGED),
        Clause(polarity=Polarity.CONTRADICTS, negation=NegationScope.ADJACENT),
        Clause(polarity=Polarity.NONE),
        Clause(polarity=Polarity.CONTRADICTS),
    ]
    verdicts = {compose_all(order) for order in itertools.permutations(sentence)}
    assert verdicts == {Verdict.ABSTAIN_CONFLICT}


# --- 6. per-clause typing: every scope withholds, with its own reason -----

@pytest.mark.parametrize("modality, reason", [
    (Modality.INTERROGATIVE, CUE_IN_QUESTION),
    (Modality.CONDITIONAL, CONDITIONAL_CUE),
    (Modality.EVIDENTIAL_FRAME, EVIDENCE_ABOUTNESS_FRAME),
    (Modality.HEDGED, HEDGED_CUE),
])
def test_a_withholding_modality_abstains_with_its_own_reason(modality, reason):
    for polarity in (Polarity.SUPPORTS, Polarity.CONTRADICTS, Polarity.NONE):
        clause = Clause(polarity=polarity, modality=modality)
        assert clause.verdict() is Verdict.ABSTAIN_INFO
        assert clause.withheld_by() == reason
        assert not clause.certifies()


@pytest.mark.parametrize("negation", [
    NegationScope.ADJACENT,
    NegationScope.FRAME,
    NegationScope.VERB_SEPARATED,
])
def test_every_negation_scope_withholds_rather_than_inverting(negation):
    for polarity in (Polarity.SUPPORTS, Polarity.CONTRADICTS):
        clause = Clause(polarity=polarity, negation=negation)
        assert clause.verdict() is Verdict.ABSTAIN_INFO
        assert clause.withheld_by() == NEGATED_CUE


def test_a_subject_wide_quantifier_withholds_like_a_negation():
    clause = Clause(polarity=Polarity.SUPPORTS, quantifier=QuantifierScope.SUBJECT_WIDE)
    assert clause.verdict() is Verdict.ABSTAIN_INFO
    assert clause.withheld_by() == NEGATED_CUE


def test_a_superseded_clause_withholds_with_the_contrast_reason():
    clause = Clause(polarity=Polarity.CONTRADICTS, superseded=True)
    assert clause.verdict() is Verdict.ABSTAIN_INFO
    assert clause.withheld_by() == CONTRAST_CHANGED_CURRENT_STATE


def test_reason_precedence_is_the_order_the_guard_reads_scopes():
    # A question inside a conditional is reported as a question, because the
    # interrogative reading dominates; a negated hedge is reported as a negation.
    assert Clause(Polarity.SUPPORTS, Modality.INTERROGATIVE, NegationScope.ADJACENT
                  ).withheld_by() == CUE_IN_QUESTION
    assert Clause(polarity=Polarity.SUPPORTS, modality=Modality.CONDITIONAL,
                  superseded=True).withheld_by() == CONDITIONAL_CUE
    assert Clause(Polarity.SUPPORTS, Modality.HEDGED, NegationScope.ADJACENT
                  ).withheld_by() == NEGATED_CUE
    assert Clause(Polarity.SUPPORTS, Modality.HEDGED, superseded=True
                  ).withheld_by() == HEDGED_CUE
    assert Clause(Polarity.SUPPORTS, Modality.EVIDENTIAL_FRAME, superseded=True
                  ).withheld_by() == EVIDENCE_ABOUTNESS_FRAME
    # An asserted, unnegated, unquantified, unsuperseded clause commits.
    assert Clause(Polarity.SUPPORTS).certifies()
    assert Clause(Polarity.NONE).withheld_by() is None  # informational, not a rejection


# --- 7. the map onto the guard's return shape -----------------------------

def test_the_four_elements_map_onto_the_guard_return_shape():
    assert to_guard_reading(Verdict.SUPPORTS) == GuardReading("SUPPORTS", None)
    assert to_guard_reading(Verdict.CONTRADICTS) == GuardReading("CONTRADICTS", None)
    assert to_guard_reading(Verdict.ABSTAIN_CONFLICT) == GuardReading(
        None, AMBIGUOUS_CUE_RELATIONS
    )
    assert to_guard_reading(Verdict.ABSTAIN_INFO, abstain_reason=NEGATED_CUE) == GuardReading(
        None, NEGATED_CUE
    )
    assert to_guard_reading(
        Verdict.ABSTAIN_INFO, explicit_neutral_information=True
    ) == GuardReading(NEUTRAL, None)
    assert to_guard_reading(Verdict.ABSTAIN_INFO) == GuardReading(None, NO_CUE_MATCH)
    # A direction never carries a reason, an abstention never carries a relation.
    for verdict in VERDICTS:
        reading = to_guard_reading(verdict, abstain_reason=HEDGED_CUE)
        if is_direction(verdict):
            assert reading.reason_code is None
        if reading.reason_code == AMBIGUOUS_CUE_RELATIONS:
            assert reading.relation is None


def test_combine_reasons_reports_one_reason_and_collapses_several():
    assert combine_reasons([], saw_cue=False) == NO_CUE_MATCH
    assert combine_reasons([], saw_cue=True) == ALL_MATCHED_CUES_REJECTED
    assert combine_reasons([NEGATED_CUE], saw_cue=True) == NEGATED_CUE
    assert combine_reasons([NEGATED_CUE, NEGATED_CUE], saw_cue=True) == NEGATED_CUE
    for order in itertools.permutations([NEGATED_CUE, HEDGED_CUE, CONDITIONAL_CUE]):
        assert combine_reasons(order, saw_cue=True) == ALL_MATCHED_CUES_REJECTED


# --- 8. purity and determinism -------------------------------------------

def test_the_module_imports_nothing_but_stdlib_support_code():
    tree = ast.parse(inspect.getsource(algebra))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "itertools", "dataclasses", "enum", "types", "typing"}
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not calls & {"open", "print", "input", "eval", "exec"}


def test_results_are_frozen_and_composition_does_not_mutate_its_inputs():
    clause = Clause(polarity=Polarity.SUPPORTS, modality=Modality.HEDGED)
    with pytest.raises(Exception):
        clause.modality = Modality.ASSERTED  # type: ignore[misc]
    sequence = [clause, Clause(polarity=Polarity.CONTRADICTS)]
    before = list(sequence)
    results = {compose_all(sequence) for _ in range(100)}
    assert sequence == before
    assert len(results) == 1
    assert compose_all(sequence) is compose_all(tuple(sequence))
    with pytest.raises(TypeError):
        COMPOSITION_TABLE[(Verdict.SUPPORTS, Verdict.SUPPORTS)] = Verdict.CONTRADICTS


# --- 9. the shipped guard goes through the algebra ------------------------

# Derived, not listed. A hand-maintained mirror drifts: the attributed-denial reason
# was added to the algebra and this set did not know about it, which is exactly the
# failure mode the test exists to catch — one level too late. Reading the module's own
# SCREAMING_CASE string constants makes a new reason visible here by construction.
_ALGEBRA_REASON_CODES = {
    value
    for name, value in vars(algebra).items()
    if name.isupper() and isinstance(value, str) and value.isupper()
}


def test_guard_reports_only_reason_codes_the_algebra_can_produce():
    for case_id, sentence, hypothesis_id, *_ in CORPUS:
        detail = reviewed_relation_details(sentence, hypothesis_id)
        assert set(detail) == {"relation", "cue_ids", "reason_code"}, case_id
        if detail["relation"] is None:
            assert detail["reason_code"] in _ALGEBRA_REASON_CODES, case_id
        else:
            assert detail["reason_code"] is None, case_id


def test_guard_reading_is_deterministic_over_the_corpus():
    for case_id, sentence, hypothesis_id, *_ in CORPUS:
        first = reviewed_relation_details(sentence, hypothesis_id)
        second = reviewed_relation_details(sentence, hypothesis_id)
        assert first == second, case_id


def test_guard_reads_an_informational_clause_without_blocking_a_direction():
    # Under set-cardinality selection this sentence abstained as ambiguous: the
    # neutral cue and the directional cue were simply two members of a set. The
    # neutral clause is the join identity, so it cannot block the direction.
    detail = reviewed_relation_details(
        "The report says nothing about checklist availability; "
        "the checklist was unavailable.",
        "CHECKLIST_UNAVAILABLE",
    )
    assert detail["relation"] is Stance.SUPPORTS
    assert detail["reason_code"] is None


def test_guard_composition_does_not_depend_on_clause_order():
    forward = reviewed_relation_details(
        "The checklist was unavailable and the binder was at the desk.",
        "CHECKLIST_UNAVAILABLE",
    )
    backward = reviewed_relation_details(
        "The binder was at the desk and the checklist was unavailable.",
        "CHECKLIST_UNAVAILABLE",
    )
    assert forward["relation"] is None
    assert backward["relation"] is None
    assert forward["reason_code"] == backward["reason_code"] == AMBIGUOUS_CUE_RELATIONS
