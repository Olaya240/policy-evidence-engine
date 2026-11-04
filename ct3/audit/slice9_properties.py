#!/usr/bin/env python3
"""Slice 9 properties over ``app/decision_table.py`` (score, _label, decide).

Stdlib only. Every property runs over the small integer grids
``support, contradiction, disputed_support, disputed_contradiction in 0..6``
(49 points for the two scored counts, 2401 for the four-count grid) and, where
the policy is an input, over all three module policies
(``POLICY_SIGNED_MARGIN``, ``POLICY_CONTEST_BLOCKS``, ``POLICY_TWO_TO_ONE``).

The six properties:

  P1  score in [-1, 1]                     score(s, c) and the score decice reports
  P2  antisymmetry                         score(s, c) == -score(c, s)
  P3  monotone in support                  score(s + 1, c) > score(s, c)
  P4  status is a function of (s, c)       for one fixed policy
  P5  confidence is the magnitude          decision.confidence == abs(decision.score)
  P6  disputed_total == the as-if sum      decide() is unchanged by passing it

A failure prints a minimal counterexample (the first point in ascending grid
order, up to three of them, plus the number of violating points) and the process
exits non-zero.

Run:
    PYTHONPATH=backend <venv>/bin/python ct3/audit/slice9_properties.py
"""

from __future__ import annotations

import math
import sys
from dataclasses import fields

import app.decision_table as dt
from app.decision_table import (
    POLICY_CONTEST_BLOCKS,
    POLICY_SIGNED_MARGIN,
    POLICY_TWO_TO_ONE,
    decide,
    score,
)

# 0..6 inclusive for every integer input, as the brief specifies.
COUNTS = range(0, 7)
# The three named policies, including the two whose consequences are not
# machine-checked (their docstring says so; that is why they are checked here).
POLICIES = (POLICY_SIGNED_MARGIN, POLICY_CONTEST_BLOCKS, POLICY_TWO_TO_ONE)

CHECKED: list[tuple[str, bool, str]] = []


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def report(name: str, cases: str, failures: list[str]) -> None:
    ok = not failures
    CHECKED.append((name, ok, failures[0] if failures else ""))
    print(f"{name:<60s} {'PASS' if ok else 'FAIL'}   ({cases})")
    for failure in failures:
        for line in failure.splitlines():
            print(f"    {line}")


def bounded(value: float) -> bool:
    return math.isfinite(value) and -1.0 <= value <= 1.0


def field_diff(left, right) -> list[str]:
    """Field-by-field difference between two ``Decision`` instances."""
    out = []
    for field in fields(type(left)):
        lhs, rhs = getattr(left, field.name), getattr(right, field.name)
        if lhs != rhs:
            out.append(f"{field.name}: {lhs!r} != {rhs!r}")
    return out


def keep(failures: list[str], message: str) -> None:
    """Record at most three counterexamples; the violation count is reported."""
    if len(failures) < 3:
        failures.append(message)


# --------------------------------------------------------------------------- #
# P1 — the score is bounded by [-1, 1]
# --------------------------------------------------------------------------- #


def p1_score_bounded() -> tuple[str, list[str]]:
    failures: list[str] = []
    violations = 0

    for s in COUNTS:
        for c in COUNTS:
            value = score(s, c)
            if not bounded(value):
                violations += 1
                keep(failures, f"score({s}, {c}) = {value!r} is outside [-1, 1]")

    points = 0
    for policy in POLICIES:
        for s in COUNTS:
            for c in COUNTS:
                for ds in COUNTS:
                    for dc in COUNTS:
                        points += 1
                        decision = decide(
                            s,
                            c,
                            disputed_support=ds,
                            disputed_contradiction=dc,
                            policy=policy,
                        )
                        if not bounded(decision.score):
                            violations += 1
                            keep(
                                failures,
                                f"decide(s={s}, c={c}, ds={ds}, dc={dc}, "
                                f"{policy.policy_id}).score = {decision.score!r} "
                                "is outside [-1, 1]",
                            )

    if violations:
        failures.append(f"{violations} violating point(s)")
    return f"score: {len(COUNTS) ** 2}, decide: {points}", failures


# --------------------------------------------------------------------------- #
# P2 — antisymmetry
# --------------------------------------------------------------------------- #


def p2_antisymmetric() -> tuple[str, list[str]]:
    failures: list[str] = []
    violations = 0

    for s in COUNTS:
        for c in COUNTS:
            # Exact float equality: the two calls differ only by the sign of the
            # numerator over an identical denominator, so no tolerance applies.
            if score(s, c) + score(c, s) != 0.0:
                violations += 1
                keep(
                    failures,
                    f"score({s}, {c}) = {score(s, c)!r} but "
                    f"score({c}, {s}) = {score(c, s)!r}; sum is not 0.0",
                )

    points = 0
    for policy in POLICIES:
        for s in COUNTS:
            for c in COUNTS:
                for ds in COUNTS:
                    for dc in COUNTS:
                        points += 1
                        forward = decide(
                            s,
                            c,
                            disputed_support=ds,
                            disputed_contradiction=dc,
                            policy=policy,
                        )
                        mirrored = decide(
                            c,
                            s,
                            disputed_support=dc,
                            disputed_contradiction=ds,
                            policy=policy,
                        )
                        if forward.score + mirrored.score != 0.0:
                            violations += 1
                            keep(
                                failures,
                                f"decide(s={s}, c={c}, ds={ds}, dc={dc}, "
                                f"{policy.policy_id}): {forward.score!r} + "
                                f"{mirrored.score!r} != 0.0",
                            )

    if violations:
        failures.append(f"{violations} violating point(s)")
    return f"score: {len(COUNTS) ** 2}, decide: {points}", failures


# --------------------------------------------------------------------------- #
# P3 — one more support group strictly raises the score
# --------------------------------------------------------------------------- #


def p3_monotone_in_support() -> tuple[str, list[str]]:
    failures: list[str] = []
    violations = 0

    for s in range(max(COUNTS)):  # 0..5, so s + 1 stays inside the grid
        for c in COUNTS:
            lower, higher = score(s, c), score(s + 1, c)
            if not higher > lower:
                violations += 1
                keep(
                    failures,
                    f"score({s + 1}, {c}) = {higher!r} is not > "
                    f"score({s}, {c}) = {lower!r}",
                )

    points = 0
    for policy in POLICIES:
        for s in range(max(COUNTS)):
            for c in COUNTS:
                points += 1
                lower = decide(s, c, policy=policy)
                higher = decide(s + 1, c, policy=policy)
                if not higher.score > lower.score:
                    violations += 1
                    keep(
                        failures,
                        f"decide({s + 1}, {c}, {policy.policy_id}).score = "
                        f"{higher.score!r} is not > decide({s}, {c}).score = "
                        f"{lower.score!r}",
                    )

    if violations:
        failures.append(f"{violations} violating point(s)")
    return f"score: {len(COUNTS) * (len(COUNTS) - 1)}, decide: {points}", failures


# --------------------------------------------------------------------------- #
# P4 — with a fixed policy, the status depends on (s, c) and nothing else
# --------------------------------------------------------------------------- #


def p4_status_function_of_counts() -> tuple[str, list[str]]:
    """``disputed_total`` is bookkeeping: it reports how many groups were

    challenged, it does not enter the as-if arithmetic. So for a fixed policy
    every value of it must leave the status (and the status rule id) alone, and
    two calls with the same (s, c, policy) must never disagree.
    """
    failures: list[str] = []
    violations = 0
    coverage: list[str] = []

    for policy in POLICIES:
        seen: dict[str, int] = {}
        for s in COUNTS:
            for c in COUNTS:
                answers = set()
                for disputed_total in (None, 0, s + c, 7):
                    decision = decide(
                        s, c, disputed_total=disputed_total, policy=policy
                    )
                    answers.add((decision.status.value, decision.status_rule_id))
                if len(answers) > 1:
                    violations += 1
                    keep(
                        failures,
                        f"{policy.policy_id}: (s={s}, c={c}) is labelled "
                        f"{sorted(answers)} depending only on disputed_total",
                    )
                status = next(iter(answers))[0]
                seen[status] = seen.get(status, 0) + 1
        coverage.append(
            f"{policy.policy_id}: "
            + " ".join(f"{name}={count}" for name, count in sorted(seen.items()))
        )
        if len(seen) < 2:
            violations += 1
            keep(
                failures,
                f"{policy.policy_id}: the 0..6 grid produces only {sorted(seen)}, "
                "so the status check is vacuous",
            )

    if violations:
        failures.append(f"{violations} violating point(s)")
    print("    coverage (status counts over the 49 points, per policy):")
    for line in coverage:
        print(f"      {line}")
    return f"{len(POLICIES)} policies x {len(COUNTS) ** 2} points x 4 disputed_total", failures


# --------------------------------------------------------------------------- #
# P5 — confidence is the magnitude of the score
# --------------------------------------------------------------------------- #


def p5_confidence_is_magnitude() -> tuple[str, list[str]]:
    failures: list[str] = []
    violations = 0
    points = 0

    for policy in POLICIES:
        for s in COUNTS:
            for c in COUNTS:
                for ds in COUNTS:
                    for dc in COUNTS:
                        points += 1
                        decision = decide(
                            s,
                            c,
                            disputed_support=ds,
                            disputed_contradiction=dc,
                            policy=policy,
                        )
                        if (
                            decision.confidence != abs(decision.score)
                            or not bounded(decision.confidence)
                            or decision.confidence < 0.0
                        ):
                            violations += 1
                            keep(
                                failures,
                                f"decide(s={s}, c={c}, ds={ds}, dc={dc}, "
                                f"{policy.policy_id}): confidence = "
                                f"{decision.confidence!r}, score = "
                                f"{decision.score!r}, abs(score) = "
                                f"{abs(decision.score)!r}",
                            )

    if violations:
        failures.append(f"{violations} violating point(s)")
    return f"decide: {points}", failures


# --------------------------------------------------------------------------- #
# P6 — passing disputed_total equal to the as-if sum changes nothing
# --------------------------------------------------------------------------- #


def p6_disputed_total_is_bookkeeping() -> tuple[str, list[str]]:
    """``decide`` computes ``disputed = disputed_support + disputed_contradiction``

    and reports ``disputed_total`` when given, so passing the as-if sum must
    return an identical ``Decision`` object — every field, not just status.
    """
    failures: list[str] = []
    violations = 0
    points = 0

    for policy in POLICIES:
        for s in COUNTS:
            for c in COUNTS:
                for ds in COUNTS:
                    for dc in COUNTS:
                        points += 1
                        without = decide(
                            s,
                            c,
                            disputed_support=ds,
                            disputed_contradiction=dc,
                            policy=policy,
                        )
                        with_total = decide(
                            s,
                            c,
                            disputed_support=ds,
                            disputed_contradiction=dc,
                            disputed_total=ds + dc,
                            policy=policy,
                        )
                        if without != with_total:
                            violations += 1
                            diff = "; ".join(field_diff(without, with_total))
                            keep(
                                failures,
                                f"decide(s={s}, c={c}, ds={ds}, dc={dc}, "
                                f"disputed_total={ds + dc}, {policy.policy_id}) "
                                f"differs from decide(...) without it: {diff}",
                            )

    if violations:
        failures.append(f"{violations} violating point(s)")
    return f"decide: {points}", failures


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    print("slice 9 properties -- app/decision_table.py")
    print(f"  module: {dt.__file__}")
    print(
        "  grid: support, contradiction, disputed_support, disputed_contradiction "
        f"in {min(COUNTS)}..{max(COUNTS)}"
    )
    print(f"  policies: {', '.join(p.policy_id for p in POLICIES)}")
    print()

    for name, check in (
        ("P1 score in [-1, 1]", p1_score_bounded),
        ("P2 antisymmetry score(s, c) == -score(c, s)", p2_antisymmetric),
        ("P3 one more support group strictly raises score", p3_monotone_in_support),
        ("P4 status is a function of (s, c) for a fixed policy", p4_status_function_of_counts),
        ("P5 confidence == abs(score)", p5_confidence_is_magnitude),
        ("P6 disputed_total == as-if sum leaves decide unchanged", p6_disputed_total_is_bookkeeping),
    ):
        cases, failures = check()
        report(name, cases, failures)

    failed = [name for name, ok, _ in CHECKED if not ok]
    print()
    print(f"{len(CHECKED) - len(failed)} passed, {len(failed)} failed, {len(CHECKED)} properties")
    if failed:
        for name in failed:
            print(f"  FAILED: {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
