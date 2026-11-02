"""The affected-claim set had exactly one implementation, and it was not a graph.

`store.get_challenge_snapshot` and `store.apply_challenge` each recompute which
claims a challenged record touches, inside their own SQLite read, and
`app/evaluate.py` only ever checks that the persisted `recomputed_claim_ids`
matches the snapshot's set. Nothing outside that read pair could answer "which
claims depend on this record?" — so the "transitive dependency graph" was an
implicit two-line comprehension, unnameable and unprovable.

These tests prove the pure module answers that question, that the closure
terminates, and — the part that matters — that its answer is the *same set* the
evaluator reports as recomputed for the same input. Two notions of "affected"
is the failure this file exists to prevent.

What the stored data actually carries is asserted, not assumed:
`test_stored_claims_have_no_claim_to_claim_edge` reads the claims the engine
produces and shows that `dependencies` holds source *record* ids only, which is
why `transitive_dependents` legitimately collapses to the direct set.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app import dependency_graph, evaluate, store
from app.engine import AssessmentEngine

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
RECORD_ID = "OPS-101"
QUOTE = "binder was missing"


def claim(claim_id, *record_ids):
    """A claim dict shaped like the ones the engine and the store exchange."""
    return {"id": claim_id, "dependencies": sorted(record_ids),
            "evidence": [dict(source_record_id=rid) for rid in record_ids]}


def by_id(*claims):
    return {item["id"]: item for item in claims}


@pytest.fixture()
def db(monkeypatch):
    # The store only accepts a path inside its own data directory.
    db_path = store.DATA_DIR / f".test-dependency-graph-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
    store.initialize_database()
    try:
        yield db_path
    finally:
        for suffix in ("", "-wal", "-shm"):
            path = db_path.with_name(db_path.name + suffix)
            if path.exists():
                path.unlink()


# --- direct set -------------------------------------------------------------


def test_record_cited_by_two_claims_returns_both():
    claims = by_id(claim("A", RECORD_ID), claim("B", RECORD_ID), claim("C", "OPS-202"))
    assert dependency_graph.direct_dependents(claims, RECORD_ID) == ("A", "B")


def test_record_cited_by_none_returns_nothing():
    claims = by_id(claim("A", "OPS-202"), claim("B"))
    assert dependency_graph.direct_dependents(claims, RECORD_ID) == ()
    assert dependency_graph.transitive_dependents(claims, RECORD_ID) == ()
    # A negative result is only meaningful if the same call can fire, so prove
    # the query shape matches something in the same mapping.
    assert dependency_graph.direct_dependents(claims, "OPS-202") == ("A",)


def test_claim_without_denormalized_dependencies_falls_back_to_evidence_rows():
    # `dependencies` is derived from `evidence` by the engine; a claim dict that
    # carries only the rows still has to answer, and must answer the same way.
    claims = {"A": {"id": "A", "evidence": [{"source_record_id": RECORD_ID}]}}
    assert dependency_graph.direct_dependents(claims, RECORD_ID) == ("A",)


# --- closure ----------------------------------------------------------------


def test_stored_claims_have_no_claim_to_claim_edge(db):
    """The premise of the collapse, read from the claims the engine produces."""
    records = store.list_records()
    engine = AssessmentEngine(clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    claims = {item["id"]: item for item in engine.investigate(records)}

    for item in claims.values():
        # `dependencies` is exactly the set of cited record ids (engine.py:539),
        # never another claim id: no field on `Claim` names a claim.
        assert item["dependencies"] == sorted({row["source_record_id"] for row in item["evidence"]})
        assert not set(item["dependencies"]) & set(claims)

    record_ids = {row["source_record_id"] for item in claims.values() for row in item["evidence"]}
    assert record_ids, "expected the fixture records to support at least one claim"
    for record_id in record_ids:
        assert dependency_graph.transitive_dependents(claims, record_id) == \
            dependency_graph.direct_dependents(claims, record_id)


def test_closure_terminates_on_a_claim_cycle():
    # A cycle through every node, plus a self-loop, plus an edge pointing at a
    # claim that does not exist. The guard is the visited set, so termination is
    # the assertion.
    claims = by_id(claim("A", RECORD_ID), claim("B"), claim("C"))
    edges = {"A": ["B"], "B": ["C"], "C": ["A", "C"], "B2": ["A"]}
    assert dependency_graph.transitive_dependents(claims, RECORD_ID, claim_edges=edges) == ("A", "B", "C")


def test_edges_to_unknown_claims_are_ignored():
    claims = by_id(claim("A", RECORD_ID))
    assert dependency_graph.transitive_dependents(claims, RECORD_ID, claim_edges={"A": ["MISSING"]}) == ("A",)


def test_closure_follows_supplied_claim_edges_and_stays_sorted():
    claims = by_id(claim("A", RECORD_ID), claim("Z"), claim("M"))
    edges = {"A": ["Z", "M"]}
    assert dependency_graph.transitive_dependents(claims, RECORD_ID, claim_edges=edges) == ("A", "M", "Z")


# --- determinism and purity -------------------------------------------------


def test_repeated_calls_return_equal_results():
    claims = by_id(claim("B", RECORD_ID), claim("A", RECORD_ID))
    edges = {"A": ["B"]}
    first = dependency_graph.transitive_dependents(claims, RECORD_ID, claim_edges=edges)
    second = dependency_graph.transitive_dependents(claims, RECORD_ID, claim_edges=edges)
    assert first == second == ("A", "B")
    assert dependency_graph.direct_dependents(claims, RECORD_ID) == ("A", "B")


def test_inputs_are_not_mutated():
    claims = {"B": claim("B", RECORD_ID), "A": claim("A")}
    edges = {"B": ["A", "A"]}
    before = repr((claims, edges))
    dependency_graph.direct_dependents(claims, RECORD_ID)
    dependency_graph.transitive_dependents(claims, RECORD_ID, claim_edges=edges)
    assert repr((claims, edges)) == before


# --- the binding: one notion of "affected" ---------------------------------


def test_module_matches_store_and_the_recomputed_set(db):
    """The graph's answer is the set the store recomputes and persists."""
    records = store.list_records()
    engine = AssessmentEngine(clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    created = store.create_investigation("Dependency graph binding", engine.investigate(records))

    snapshot = store.get_challenge_snapshot(created["id"], HYPOTHESIS, RECORD_ID)
    revised = {
        cid: engine.challenge(item, records, RECORD_ID, QUOTE)
        for cid, item in snapshot["claims"].items()
    }
    applied = store.apply_challenge(
        created["id"], HYPOTHESIS, "Dependency graph binding challenge.", RECORD_ID, QUOTE,
        expected_revision=snapshot["revision"], expected_claims=snapshot["claims"],
        revised_claims=revised,
    )

    # The graph over the pre-challenge claims equals the set the store read for
    # the challenge, and the set the store persisted as recomputed.
    assert dependency_graph.transitive_dependents(snapshot["claims"], RECORD_ID) == \
        tuple(snapshot["affected_claim_ids"])
    assert dependency_graph.transitive_dependents(snapshot["claims"], RECORD_ID) == \
        tuple(applied["recomputed_claim_ids"])

    # The challenged claim is in the set because its evidence cites the record,
    # not because it was named: the engine's guard requires that (engine.py:572).
    assert HYPOTHESIS in dependency_graph.direct_dependents(snapshot["claims"], RECORD_ID)

    # The claim set is not otherwise perturbed by the challenge, so the same
    # graph over the stored claims answers the same way.
    stored = {item["id"]: item for item in store.get_investigation(created["id"])["claims"]}
    assert dependency_graph.transitive_dependents(stored, RECORD_ID) == \
        tuple(applied["recomputed_claim_ids"])

    # The set is not "every claim": each member's own evidence cites the record.
    assert set(applied["recomputed_claim_ids"]) <= set(stored)
    assert all(RECORD_ID in item["dependencies"] for cid, item in stored.items()
               if cid in set(applied["recomputed_claim_ids"]))


def test_evaluate_reports_the_same_recomputed_set():
    """The evaluator's own check passes on the input the graph just answered for.

    `evaluate._evaluate_recomputation_history` asserts
    `sorted(applied["recomputed_claim_ids"]) == affected` for OPS-101 and
    CHECKLIST_UNAVAILABLE; `test_module_matches_store_and_the_recomputed_set`
    shows both of those equal the graph's output for the same claims. This test
    keeps the evaluator itself in the chain rather than a replica of it.
    """
    result = evaluate._evaluate_recomputation_history(guarded=True)
    assert result["checks"]["only_dependency_affected_claims_recomputed"] is True
    assert result["disposable_database_removed"] is True
