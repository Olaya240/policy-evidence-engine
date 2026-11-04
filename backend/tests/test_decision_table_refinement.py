"""Refinement bridge: the table Coq computes vs the table Python ships.

`ct3/DecisionTable.v` proves properties of a *model* of the decision table. A
proved function is worth nothing if the shipped Python computes a different one,
so `ct3/refinement/generate_table.v` computes the model's decision over the whole
finite domain this repository tests (`s, c` in 0..6, `disputed_support,
disputed_contradiction` in 0..2: 441 rows) and writes it out. This module reads
that file and asserts, row by row, that `decide` returns what Coq computed.

Build the artifact (from `ct3/refinement/`):

    coqc -Q .. "" generate_table.v          # writes decision-table.out, legend.out

The two grids and the policy are the ones `test_confidence_reliability.py` names:
default policy only, `POLICY_SIGNED_MARGIN`, the rule `ct3/DecisionTable.v`
proves. The other two policies are explicitly unproved, so a row for them is a
row nobody has a theorem about.

What this checks, and what it does not
--------------------------------------
Checked: the status, the status rule id, and the score *as an exact rational*,
for every configuration in the grid, against `decide`. Every comparison is exact:
the rational is `Fraction(num, den)` in lowest-free form and the float is
compared with `==` against `float(Fraction(num, den))`, i.e. against the
correctly rounded image of the model's rational. There is no `approx` and no
tolerance anywhere in this file, and a change of one ulp fails.

Not checked (see `ct3/audit/REFINEMENT-PROOF.md`): anything outside the grid
(nothing is claimed about `s, c > 6`), `confidence_rule_id`, `contested`,
`disputed_groups`, and the step from raw evidence records to the group counts
(`_count_groups`, `group_key`) — this file starts at the counts, as the Coq model
does.

The status/rule *names* are the one hand-written bridge: Coq emits integers and
`STATUS_BY_CODE` / `RULE_BY_CODE` attach the Python names. `legend.out` carries
the same codes in constructor order, so a renumbering on the Coq side makes the
legend test fail instead of silently renaming a verdict.
"""

from __future__ import annotations

import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

import pytest

from app.decision_table import decide, score
from app.models import Status

REFINEMENT = Path(__file__).resolve().parents[2] / "ct3" / "refinement"
TABLE_PATH = REFINEMENT / "decision-table.out"
LEGEND_PATH = REFINEMENT / "legend.out"

# `emit_cell` in generate_table.v writes the numerator biased by 8, because the
# grid's numerators run -8..8 (s + ds <= 8) and Coq 8.18 core has no
# integer-to-string conversion, so every emitted number is a nat.
NUMERIC_BIAS = 8

# Column order of `emit_cell`: the four coordinates, the two counts the reported
# score is computed from, the rational, then the label and the rule.
COLUMNS = ("s", "c", "ds", "dc", "eff_s", "eff_c", "num", "den", "status", "rule")
INDEX = {name: position for position, name in enumerate(COLUMNS)}

STATUS_BY_CODE = {
    0: Status.SUPPORTED,
    1: Status.PARTIAL,
    2: Status.CONTRADICTED,
    3: Status.INSUFFICIENT,
}

RULE_BY_CODE = {
    0: "STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION",
    1: "STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT",
    2: "STATUS.V2_NO_DIRECTIONAL_EVIDENCE",
    3: "STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED",
    4: "STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT",
}

INSUFFICIENT_RULE = RULE_BY_CODE[2]
BALANCED_RULE = RULE_BY_CODE[3]
DISPUTED_RULE = RULE_BY_CODE[4]

EXPECTED_ROWS = 441


def _read(path: Path) -> str:
    if not path.exists():
        pytest.fail(
            f"{path} is missing. Build it with:\n"
            '    cd ct3/refinement && coqc -Q .. "" generate_table.v',
            pytrace=False,
        )
    return path.read_text()


def _integers(text: str) -> list[int]:
    """Every decimal in the term Coq printed, in order.

    `Eval vm_compute` prints `[[0%nat; 0%nat; ...]; [...]]`, so the payload is
    the text from the first `[` to the last `]`; the type annotation that follows
    it contributes no digits.
    """
    payload = text[text.index("[") : text.rindex("]") + 1]
    return [int(token) for token in re.findall(r"\d+", payload)]


def table() -> list[tuple[int, ...]]:
    values = _integers(_read(TABLE_PATH))
    width = len(COLUMNS)
    assert len(values) % width == 0, f"{len(values)} integers is not a whole number of rows"
    return [tuple(values[i : i + width]) for i in range(0, len(values), width)]


def legend() -> tuple[list[int], list[int]]:
    groups = re.findall(r"\[([^\[\]]*)\]", _read(LEGEND_PATH))
    assert len(groups) == 2, f"expected two code lists, found {len(groups)}"
    return (
        [int(token) for token in re.findall(r"\d+", groups[0])],
        [int(token) for token in re.findall(r"\d+", groups[1])],
    )


# ---------------------------------------------------------------------------
# 1. The artifact is the grid it claims to be
# ---------------------------------------------------------------------------

def test_the_table_is_the_full_grid_in_a_known_order():
    """441 rows, one per (s, c, ds, dc) in the documented nesting order.

    Exhaustive over the modelled domain, and pinned so a row that vanished,
    duplicated or moved cannot be absorbed by the row-by-row comparison below.
    """
    rows = table()
    expected = [
        (s, c, ds, dc)
        for s in range(7)
        for c in range(7)
        for ds in range(3)
        for dc in range(3)
    ]

    assert len(rows) == EXPECTED_ROWS
    assert [row[:4] for row in rows] == expected


def test_the_code_legend_is_the_one_coq_emitted():
    """Coq numbers the constructors; this test does not get to invent the numbers.

    `legend.out` is `status_codes` and `rule_codes` in declaration order, so the
    dictionaries above are pinned to Coq's numbering rather than assumed.
    """
    status_codes, rule_codes = legend()

    assert status_codes == list(STATUS_BY_CODE), status_codes
    assert rule_codes == list(RULE_BY_CODE), rule_codes
    assert status_codes == sorted(STATUS_BY_CODE)
    assert rule_codes == sorted(RULE_BY_CODE)


def test_the_table_reaches_every_status_and_every_rule():
    """A guard against the comparison passing because the table is degenerate.

    If every row were PARTIAL, or the dispute rule never fired, a mismatch in the
    four labels or the five rules could not show up at all.
    """
    rows = table()
    statuses = Counter(STATUS_BY_CODE[row[INDEX["status"]]] for row in rows)
    rules = Counter(RULE_BY_CODE[row[INDEX["rule"]]] for row in rows)

    assert set(statuses) == set(STATUS_BY_CODE.values()), statuses
    assert set(rules) == set(RULE_BY_CODE.values()), rules
    assert rules[DISPUTED_RULE] > 0
    # Exactly one row is INSUFFICIENT: the empty row with nothing challenged.
    # Every other (0, 0, ds, dc) row has a challenge that changes the label from
    # INSUFFICIENT to something else, so it is downgraded to PARTIAL.
    assert statuses[Status.INSUFFICIENT] == 1, statuses


# ---------------------------------------------------------------------------
# 2. Every row: Coq's decision == `decide`'s decision
# ---------------------------------------------------------------------------

def test_every_coq_row_equals_the_python_decision():
    """The refinement obligation, over the whole grid, exactly.

    Per row: the coordinates are the ones that were decided; the rational is the
    score of the counts it names; the status and the status rule id are the ones
    `decide` returns; and the float `decide` reports is the correctly rounded
    image of Coq's rational — compared with `==`, not `approx`.
    """
    mismatches: list[str] = []
    rows = table()

    for row in rows:
        s, c, ds, dc, eff_s, eff_c, biased_num, den, status_code, rule_code = row
        num = biased_num - NUMERIC_BIAS
        exact = Fraction(num, den)
        decision = decide(s, c, disputed_support=ds, disputed_contradiction=dc)
        model_status = STATUS_BY_CODE[status_code]
        model_rule = RULE_BY_CODE[rule_code]

        problems = []
        if num != eff_s - eff_c:
            problems.append(f"numerator {num} != eff_s - eff_c = {eff_s - eff_c}")
        if den != eff_s + eff_c + 1:
            problems.append(f"denominator {den} != eff_s + eff_c + 1 = {eff_s + eff_c + 1}")
        if exact != Fraction(eff_s - eff_c, eff_s + eff_c + 1):
            problems.append(f"rational {exact} is not (s-c)/(s+c+1) of {eff_s}, {eff_c}")
        if decision.status is not model_status:
            problems.append(f"status: coq {model_status.value} != python {decision.status.value}")
        if decision.status_rule_id != model_rule:
            problems.append(f"rule: coq {model_rule} != python {decision.status_rule_id}")
        if decision.score != float(exact):
            problems.append(
                f"score: coq {num}/{den} -> {float(exact)!r} != python {decision.score!r}"
            )
        if decision.score != score(eff_s, eff_c):
            problems.append(
                f"score(): app.decision_table.score({eff_s}, {eff_c}) "
                f"= {score(eff_s, eff_c)!r} != coq {exact}"
            )

        if problems:
            mismatches.append(
                f"  (s={s}, c={c}, ds={ds}, dc={dc}) -> {problems}"
            )

    if mismatches:
        shown = "\n".join(mismatches[:20])
        more = "" if len(mismatches) <= 20 else f"\n  ... and {len(mismatches) - 20} more"
        pytest.fail(
            f"{len(mismatches)} of {len(rows)} rows disagree between "
            f"ct3/refinement/generate_table.v and app.decision_table.decide:\n{shown}{more}",
            pytrace=False,
        )

    assert len(rows) == EXPECTED_ROWS


# ---------------------------------------------------------------------------
# 3. The rows the audit cites
# ---------------------------------------------------------------------------

def test_the_switch_point_rows_are_the_ones_the_audit_cites():
    """`(1,0,dc=1)` is 1/2 and `(2,0,dc=1)` is 1/4: more support, a lower number.

    Read out of Coq's table rather than from `decide`, so the two numbers in
    `ct3/audit/REFINEMENT-PROOF.md` are the model's, and the z3 query in
    `refinement/switch-point.smt2` is about the same pair.
    """
    by_row = {(row[0], row[1], row[2], row[3]): row for row in table()}

    def rational(row) -> Fraction:
        return Fraction(row[INDEX["num"]] - NUMERIC_BIAS, row[INDEX["den"]])

    def label(row) -> tuple[Status, str]:
        return STATUS_BY_CODE[row[INDEX["status"]]], RULE_BY_CODE[row[INDEX["rule"]]]

    low, high = by_row[(1, 0, 0, 1)], by_row[(2, 0, 0, 1)]

    assert label(low) == (Status.PARTIAL, BALANCED_RULE)
    assert rational(low) == Fraction(1, 2)

    assert label(high) == (Status.PARTIAL, DISPUTED_RULE)
    assert rational(high) == Fraction(1, 4)

    assert rational(high) < rational(low)


# The table in `decision-table.out` is produced by Coq and *read* by this test; the test
# does not run `coqc`. So without a freshness check the proof can drift from the table
# silently: edit `generate_table.v`, forget to regenerate, and the comparison keeps
# passing against a table that no longer describes the model. These digests are the
# handshake. When the Coq changes, regenerate and update them — the failure message says
# both commands.
GENERATED_FROM_DIGESTS = {'generate_table.v': '4f6348d5f0e3ee4e', 'DecisionTable.v': '456b2a663a9215ef'}


def test_the_emitted_table_was_generated_from_the_current_coq_sources():
    import hashlib
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[2]
    for name, expected in GENERATED_FROM_DIGESTS.items():
        path = root / "ct3" / "refinement" / name if name == "generate_table.v" else root / "ct3" / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        assert actual == expected, (
            f"{name} changed since decision-table.out was emitted ({expected} -> {actual}).\n"
            "Regenerate and re-record the digest:\n"
            "    cd ct3/refinement && coqc -Q .. \"\" generate_table.v\n"
            "    python -c \"import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('..)/generate_table.v').read_bytes()).hexdigest()[:16])\""
        )
