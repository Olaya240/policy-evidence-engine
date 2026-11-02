"""Semantic re-check of the strict xfails: is each one still owed, for the reason it states?

A strict xfail is a debt with a reason string attached. The reason is the only
thing that tells a later reader *why* the guard is wrong, so it has to name the
mechanism that actually fails. This module re-runs each marked row and decides
which of four things is true:

``a``  still the stated defect: the row fails, and a counterfactual that removes
       the stated cause makes the guard behave differently.
``b``  fixed but the mark is stale: the row passes, so the reason string now
       describes a defect that no longer exists (pytest reports it as a strict
       XPASS failure before this module runs).
``c``  wrong for a different reason than stated: the row fails, but the
       counterfactual implied by the reason string does not change the reading,
       so the cause named there is not the cause.
``d``  the label looks wrong: the benchmark row's expected answer, not the guard,
       is the thing to fix. Recorded by hand; no row in the ledger is ``d``.

Classes ``c`` and ``d`` are failures of *this* test, by design: a reason string
that names the wrong mechanism is an audit trail that has become fiction. Class
``b`` is a skip, because the strict mark itself already fails the suite for it,
and this module only reports which cleanup is owed.

The evidence column in ``ct3/audit/XFAIL-INVENTORY.md`` records the reading and
reason code seen at audit time; the tests below do not pin those, they recompute
them, so a fix landing during the same turn changes this module's verdict rather
than its expectations.

Run::

    cd backend && python -m pytest tests/test_xfail_inventory.py -q -rs
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from app.models import Stance
from app.semantic_guard import reviewed_relation_details

ABSTAIN = "ABSTAIN"

CU = "CHECKLIST_UNAVAILABLE"
SC = "STAFFING_CONSTRAINTS"
TP = "TIME_PRESSURE"
PMS = "PMS_SYSTEM_ISSUE"

HERE = Path(__file__).resolve().parent
RIG = HERE / "test_semantic_benchmark.py"
CORPUS = HERE / "test_semantic_guard_negation_corpus.py"
HOLDOUT_V2 = HERE / "test_semantic_holdout_v2.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their annotations through sys.modules during class creation
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_BENCHMARK = _load("_xfail_inventory_benchmark", RIG)
_NEGATION = _load("_xfail_inventory_negation", CORPUS)


def _reading(sentence: str, hypothesis: str) -> tuple[str, str | None]:
    """The guard's direction for one sentence, with ``NEUTRAL`` folded into ABSTAIN."""
    detail = reviewed_relation_details(sentence, hypothesis)
    relation = detail["relation"]
    if relation is None or relation is Stance.NEUTRAL:
        return ABSTAIN, detail["reason_code"]
    return relation.value, detail["reason_code"]


@dataclass(frozen=True)
class Counterfactual:
    """The test the reason string implies: if it says X causes the failure,
    removing X must change the reading."""

    sentence: str
    hypothesis: str
    expect: str
    why: str


@dataclass(frozen=True)
class Audit:
    """One marked row, its reason as written, and the check the reason implies."""

    rid: str
    line: int
    sentence: str
    hypothesis: str
    label: str
    reason: str
    observed_at_audit: str
    reason_code_at_audit: str | None
    klass: str
    counterfactual: Counterfactual


AUDIT: dict[str, Audit] = {
    "quant-d3": Audit(
        rid="quant-d3", line=651,
        sentence="Nobody saw that the binder was missing.",
        hypothesis=CU, label=ABSTAIN,
        reason="'that' disables the quantifier rule, so a denied sighting certifies SUPPORTS",
        observed_at_audit="SUPPORTS", reason_code_at_audit=None, klass="a",
        counterfactual=Counterfactual(
            "Nobody saw the binder was missing.", CU, ABSTAIN,
            "same sentence without the complementiser 'that' should abstain",
        ),
    ),
    "temp-d1": Audit(
        rid="temp-d1", line=654,
        sentence="The checklist was unavailable this morning, but it is available now.",
        hypothesis=CU, label="CONTRADICTS",
        reason="safe abstention: 'available now' supersedes the cue",
        observed_at_audit=ABSTAIN,
        reason_code_at_audit="CONTRAST_CHANGED_CURRENT_STATE", klass="a",
        counterfactual=Counterfactual(
            "The checklist was unavailable this morning.", CU, "SUPPORTS",
            "the first clause alone should certify, so the contrast clause is what suppresses it",
        ),
    ),
    "temp-d2": Audit(
        rid="temp-d2", line=655,
        sentence="The ward was short staffed last week, but it is not short staffed any more.",
        hypothesis=SC, label="CONTRADICTS",
        reason="safe abstention: a present-tense denial in the contrary clause abstains where the label expects CONTRADICTS",
        observed_at_audit=ABSTAIN, reason_code_at_audit="ALL_MATCHED_CUES_REJECTED", klass="a",
        counterfactual=Counterfactual(
            "The ward was short staffed last week, but it is not short staffed anymore.",
            SC, ABSTAIN,
            "both spellings now abstain: the contrast reader accepts a subject and 'any more' "
            "as well as 'anymore', so the token spelling is no longer the cause; the residue "
            "is the abstention policy itself, which refuses to emit CONTRADICTS from a negated "
            "support cue",
        ),
    ),
    "temp-d3": Audit(
        rid="temp-d3", line=656,
        sentence="The binder was missing at 8am, but it is at the desk now.",
        hypothesis=CU, label="CONTRADICTS",
        reason="safe abstention: 'at the desk now' supersedes the cue",
        observed_at_audit=ABSTAIN,
        reason_code_at_audit="CONTRAST_CHANGED_CURRENT_STATE", klass="a",
        counterfactual=Counterfactual(
            "The binder was missing at 8am.", CU, "SUPPORTS",
            "the first clause alone should certify, so the contrast clause is what suppresses it",
        ),
    ),
    "temp-h1": Audit(
        rid="temp-h1", line=657,
        sentence="The system was unavailable yesterday, but it is working normally today.",
        hypothesis=PMS, label="CONTRADICTS",
        reason="safe abstention: 'working normally today' supersedes the cue",
        observed_at_audit=ABSTAIN,
        reason_code_at_audit="CONTRAST_CHANGED_CURRENT_STATE", klass="a",
        counterfactual=Counterfactual(
            "The system was unavailable yesterday.", PMS, "SUPPORTS",
            "the first clause alone should certify, so the contrast clause is what suppresses it",
        ),
    ),
    "temp-h2": Audit(
        rid="temp-h2", line=658,
        sentence="The shift had enough time yesterday; today it does not have enough time.",
        hypothesis=TP, label="SUPPORTS",
        reason="unsafe: supersession across a semicolon is invisible, so yesterday's state certifies",
        observed_at_audit="CONTRADICTS", reason_code_at_audit=None, klass="a",
        counterfactual=Counterfactual(
            "The shift had enough time yesterday, but today it does not have enough time.",
            TP, ABSTAIN,
            "the same clauses joined by ', but' should abstain, so the semicolon is what hides it",
        ),
    ),
    "rept-d1": Audit(
        rid="rept-d1", line=664,
        sentence="The auditor did not say the checklist was unavailable.",
        hypothesis=CU, label=ABSTAIN,
        reason="unsafe, pinned by the negation corpus: a negated report certifies the complement",
        observed_at_audit=ABSTAIN, reason_code_at_audit="ATTRIBUTED_DENIAL", klass="b",
        counterfactual=Counterfactual(
            "The auditor did not say the checklist was unavailable.", CU, ABSTAIN,
            "a row that now passes has no failure left for the reason to describe",
        ),
    ),
    "rept-d2": Audit(
        rid="rept-d2", line=665,
        sentence="The clerk never claimed the binder was missing.",
        hypothesis=CU, label=ABSTAIN,
        reason="unsafe, pinned by the negation corpus: a denied claim certifies the complement",
        observed_at_audit=ABSTAIN, reason_code_at_audit="ATTRIBUTED_DENIAL", klass="b",
        counterfactual=Counterfactual(
            "The clerk never claimed the binder was missing.", CU, ABSTAIN,
            "a row that now passes has no failure left for the reason to describe",
        ),
    ),
    "rept-d3": Audit(
        rid="rept-d3", line=666,
        sentence="The supervisor did not mention that the shift ran out of time.",
        hypothesis=TP, label=ABSTAIN,
        reason="unsafe, pinned by the negation corpus: a denied mention certifies the complement",
        observed_at_audit=ABSTAIN, reason_code_at_audit="ATTRIBUTED_DENIAL", klass="b",
        counterfactual=Counterfactual(
            "The supervisor did not mention that the shift ran out of time.", TP, ABSTAIN,
            "a row that now passes has no failure left for the reason to describe",
        ),
    ),
    "rept-h1": Audit(
        rid="rept-h1", line=667,
        sentence="No one reported that the ward was short staffed.",
        hypothesis=SC, label=ABSTAIN,
        reason="unsafe, pinned by the negation corpus: a denied report certifies the complement",
        observed_at_audit=ABSTAIN, reason_code_at_audit="ATTRIBUTED_DENIAL", klass="b",
        counterfactual=Counterfactual(
            "No one reported that the ward was short staffed.", SC, ABSTAIN,
            "a row that now passes has no failure left for the reason to describe",
        ),
    ),
    "rept-h2": Audit(
        rid="rept-h2", line=668,
        sentence="The technician did not note that the system timed out.",
        hypothesis=PMS, label=ABSTAIN,
        reason="unsafe, pinned by the negation corpus: a missing note certifies the complement",
        observed_at_audit=ABSTAIN, reason_code_at_audit="ATTRIBUTED_DENIAL", klass="b",
        counterfactual=Counterfactual(
            "The technician did not note that the system timed out.", PMS, ABSTAIN,
            "a row that now passes has no failure left for the reason to describe",
        ),
    ),
    "cond-h2": Audit(
        rid="cond-h2", line=671,
        sentence="Were the ward short staffed, agency staff would cover the shift.",
        hypothesis=SC, label=ABSTAIN,
        reason="unsafe: an inverted subjunctive is certified as if asserted",
        observed_at_audit="SUPPORTS", reason_code_at_audit=None, klass="a",
        counterfactual=Counterfactual(
            "If the ward was short staffed, agency staff would cover the shift.",
            SC, ABSTAIN,
            "the same antecedent under 'if' should abstain, so the inversion is what escapes",
        ),
    ),
    "bound-h2": Audit(
        rid="bound-h2", line=673,
        sentence="No one had seen the binder before, yet the checklist was unavailable.",
        hypothesis=CU, label="SUPPORTS",
        reason="safe abstention: the quantifier rule reaches across a clause boundary",
        observed_at_audit=ABSTAIN, reason_code_at_audit="NEGATED_CUE", klass="a",
        counterfactual=Counterfactual(
            "The clerk had seen the binder before, yet the checklist was unavailable.",
            CU, "SUPPORTS",
            "with a plain subject in the first clause the cue should certify, so the "
            "quantifier is what reaches across the comma",
        ),
    ),
}


def _live_marks() -> dict[str, str]:
    """Every strict xfail id still marked, with its reason, from the two files that mark rows."""
    live = dict(_BENCHMARK.KNOWN_MISREADS)
    live.update(_NEGATION._KNOWN_UNFIXED)
    return live


def _rows_by_id() -> dict[str, object]:
    return {row.id: row for row in _BENCHMARK.ROWS}


def _live_class(entry: Audit) -> tuple[str, str]:
    """The class the live guard supports, with the evidence that decided it."""
    row = _rows_by_id()[entry.rid]
    seen, code = _reading(row.sentence, row.hypothesis)
    if seen == row.expected:
        return "b", f"the row now reads {seen} and its label is {row.expected}"
    got, cf_code = _reading(entry.counterfactual.sentence, entry.counterfactual.hypothesis)
    evidence = (
        f"row reads {seen} (reason {code}) against label {row.expected}; "
        f"counterfactual {entry.counterfactual.sentence!r} reads {got} "
        f"(reason {cf_code}), expected {entry.counterfactual.expect}"
    )
    return ("a" if got == entry.counterfactual.expect else "c"), evidence


def test_every_live_mark_has_an_audit_record() -> None:
    """A new strict xfail without a recorded reason check is debt nobody is tracking."""
    unknown = sorted(set(_live_marks()) - set(AUDIT))
    assert not unknown, (
        "strict xfails with no record in this inventory: "
        f"{unknown}. Add each one to tests/test_xfail_inventory.py and "
        "ct3/audit/XFAIL-INVENTORY.md, or remove the mark."
    )


def test_a_removed_mark_does_not_hide_a_live_defect() -> None:
    """Deleting a mark without a fix would hide the debt the reason recorded."""
    live = _live_marks()
    hidden: list[str] = []
    for rid, entry in AUDIT.items():
        if rid in live:
            continue
        row = _rows_by_id()[rid]
        seen, code = _reading(row.sentence, row.hypothesis)
        if seen != row.expected:
            hidden.append(
                f"{rid} (was line {entry.line}): mark removed, row still reads {seen} "
                f"(reason {code}) against label {row.expected}"
            )
    assert not hidden, (
        "marks disappeared while their defect is still live: " + "; ".join(hidden)
    )


def test_recorded_reason_matches_what_the_mark_says() -> None:
    """The inventory must quote the mark, so a rewritten reason cannot drift from it."""
    live = _live_marks()
    wrong = {
        rid: (entry.reason, live[rid])
        for rid, entry in AUDIT.items()
        if rid in live and live[rid] != entry.reason
    }
    assert not wrong, (
        "reason strings changed since the audit; re-run the check and update the "
        f"inventory: {wrong}"
    )


def test_holdout_v2_carries_no_xfails() -> None:
    """The holdout v2 file is cited as a source of xfails; it has none."""
    source = HOLDOUT_V2.read_text(encoding="utf-8")
    assert "xfail" not in source, (
        "test_semantic_holdout_v2.py grew an xfail mark; inventory it before it lands"
    )


def test_no_row_is_class_d() -> None:
    """Class d (the label, not the guard, is wrong) is recorded by hand; none is open."""
    disputed = {rid: entry.label for rid, entry in AUDIT.items() if entry.klass == "d"}
    assert not disputed, f"rows whose label is disputed: {disputed}"


@pytest.mark.parametrize("rid", sorted(AUDIT))
def test_marked_row_is_still_owed_for_the_stated_reason(rid: str) -> None:
    """The audit itself, one case per mark: a stale or misdescribed reason is a failure."""
    entry = AUDIT[rid]
    if rid not in _live_marks():
        pytest.skip(
            f"{rid}: no longer marked; the inventory entry is historical. "
            "Delete it if the defect was fixed and the mark removed."
        )

    klass, evidence = _live_class(entry)

    if klass == "b":
        # pytest already fails the suite on the strict XPASS; this module only
        # records that the reason string now describes a closed defect.
        pytest.skip(
            f"{rid}: defect fixed, mark is stale — delete the entry and this row. {evidence}"
        )

    if klass in ("c", "d"):
        pytest.fail(
            f"{rid} (line {entry.line}): reason {entry.reason!r} names the wrong cause. "
            f"{evidence}. The row still fails, but for a different reason than the "
            "reason string states; rewrite the reason to the measured cause (or fix it, "
            "and delete the mark).",
            pytrace=False,
        )

    assert klass == entry.klass, (
        f"{rid} (line {entry.line}): recorded class {entry.klass!r}, live class "
        f"{klass!r}. {evidence}"
    )
