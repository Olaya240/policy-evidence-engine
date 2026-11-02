#!/usr/bin/env python3
"""Slice 8 properties over ``AssessmentEngine.challenge`` (backend/app/engine.py:538).

Stdlib only. Each property is checked over a set of scenarios that reach the
distinct branches of ``challenge``: an existing evidence item matched by its
full quote, the same item matched by a shorter substring, evidence appended for
a dependency the claim did not carry, and repeated challenges against one item.
A failure prints a minimal counterexample (first differing JSON paths, or the
competing scalars) and the process exits non-zero.

Run:
    PYTHONPATH=backend <venv>/bin/python ct3/audit/slice8_properties.py
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import timedelta

from app.engine import AssessmentEngine, _summarize_status_decision
from app.mock_provider import SEED_RECORDS
from app.models import Evidence

# One hour after the newest seed record, so the assessed evidence is fresh and
# the decision table produces a non-trivial status/signed score.
NOW = max(r.timestamp for r in SEED_RECORDS) + timedelta(hours=1)
HYPOTHESIS = "CHECKLIST_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

CHECKED: list[tuple[str, bool, str]] = []


def report(name: str, cases: str, failures: list[str]) -> None:
    ok = not failures
    CHECKED.append((name, ok, failures[0] if failures else ""))
    print(f"{name:<62s} {'PASS' if ok else 'FAIL'}   ({cases})")
    for failure in failures:
        for line in failure.splitlines():
            print(f"    {line}")


def diff_paths(before, after, path="$", out=None, limit=6):
    """Return up to ``limit`` dotted paths whose values differ."""
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if type(before) is not type(after) and not (
        isinstance(before, (int, float)) and isinstance(after, (int, float))
    ):
        out.append(f"{path}: {before!r} != {after!r}")
        return out
    if isinstance(before, dict):
        for key in sorted(set(before) | set(after), key=str):
            if key not in before:
                out.append(f"{path}.{key}: added {after[key]!r}")
            elif key not in after:
                out.append(f"{path}.{key}: removed (was {before[key]!r})")
            else:
                diff_paths(before[key], after[key], f"{path}.{key}", out, limit)
            if len(out) >= limit:
                return out
    elif isinstance(before, list):
        if len(before) != len(after):
            out.append(f"{path}: len {len(before)} != {len(after)}")
        for index in range(min(len(before), len(after))):
            diff_paths(before[index], after[index], f"{path}[{index}]", out, limit)
            if len(out) >= limit:
                return out
    elif before != after:
        out.append(f"{path}: {before!r} != {after!r}")
    return out


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

def engine() -> AssessmentEngine:
    return AssessmentEngine(clock=lambda: NOW)


def base_claim(eng: AssessmentEngine, hypothesis: str = HYPOTHESIS) -> dict:
    """A claim in exactly the persisted shape (JSON round trip, as tests do)."""
    return json.loads(json.dumps(eng.assess_hypothesis(SEED_RECORDS, hypothesis)))


def item(claim: dict, record_id: str) -> dict:
    return next(e for e in claim["evidence"] if e["source_record_id"] == record_id)


def without(claim: dict, record_id: str) -> dict:
    """A claim that does not carry a dependency it could still be challenged on."""
    trimmed = copy.deepcopy(claim)
    trimmed["evidence"] = [
        e for e in trimmed["evidence"] if e["source_record_id"] != record_id
    ]
    trimmed["version"] = claim["version"]
    return trimmed


def record(record_id: str):
    return next(r for r in SEED_RECORDS if r.id == record_id)


def scenarios(eng: AssessmentEngine) -> list[tuple[str, dict, str, str]]:
    """(name, claim, record_id, quote) for every reachable branch of challenge."""
    claim = base_claim(eng)
    ops101 = item(claim, "OPS-101")
    ops109 = item(claim, "OPS-109")
    ops110 = item(claim, "OPS-110")

    # A substring of the assessed quote, still an exact substring of the record.
    substring = ops109["quote"][:32]
    assert substring in record("OPS-109").text and substring in ops109["quote"]

    appended = eng.challenge(without(claim, "OPS-110"), SEED_RECORDS, "OPS-110", ops110["quote"])

    # A second hypothesis, so the properties are exercised on a different
    # status (CONTRADICTED) rather than only on INSUFFICIENT/PARTIAL.
    time_pressure = base_claim(eng, "TIME_PRESSURE")
    ops107 = item(time_pressure, "OPS-107")

    return [
        ("existing-item/full-quote/OPS-101", claim, "OPS-101", ops101["quote"]),
        ("existing-item/substring-quote/OPS-109", claim, "OPS-109", substring),
        ("append-missing-dependency/OPS-110", without(claim, "OPS-110"), "OPS-110", ops110["quote"]),
        ("repeat-after-append/OPS-101", appended, "OPS-101", ops101["quote"]),
        ("other-hypothesis/full-quote/OPS-107", time_pressure, "OPS-107", ops107["quote"]),
    ]


# --------------------------------------------------------------------------- #
# P1 — challenge is pure with respect to the dict it is given
# --------------------------------------------------------------------------- #

def property_purity(eng: AssessmentEngine) -> None:
    failures: list[str] = []
    cases = scenarios(eng)
    for name, claim, record_id, quote in cases:
        before = copy.deepcopy(claim)
        before_bytes = json.dumps(claim, sort_keys=True, default=str)
        eng.challenge(claim, SEED_RECORDS, record_id, quote)
        if claim != before or json.dumps(claim, sort_keys=True, default=str) != before_bytes:
            failures.append(
                f"{name}: the caller's dict changed\n      "
                + "\n      ".join(diff_paths(before, claim) or ["(bytes differ)"])
            )
    report("P1 purity: challenge does not mutate its input dict", f"n={len(cases)}", failures)


# --------------------------------------------------------------------------- #
# P2 — returned status/confidence equal a fresh summary over its own evidence
# --------------------------------------------------------------------------- #

def property_recomputed_summary(eng: AssessmentEngine) -> None:
    failures: list[str] = []
    cases = scenarios(eng)
    for name, claim, record_id, quote in cases:
        result = eng.challenge(copy.deepcopy(claim), SEED_RECORDS, record_id, quote)
        try:
            models = [Evidence.model_validate(e) for e in result["evidence"]]
        except Exception as exc:  # pragma: no cover - reported, not hidden
            failures.append(f"{name}: returned evidence does not validate: {exc}")
            continue
        decision = _summarize_status_decision(models)
        pairs = [
            ("status", result["status"], decision.status.value),
            ("confidence", result["confidence"], decision.confidence),
            ("evidence_score", result["evidence_score"], decision.evidence_score),
            ("uncertainty", result["uncertainty"], decision.uncertainty),
            ("conflicts", result["conflicts"], decision.conflicts),
        ]
        for field, got, want in pairs:
            if got != want:
                failures.append(f"{name}: {field} {got!r} != {want!r} from a fresh summary")
    report("P2 returned status/confidence == fresh summary of its evidence",
           f"n={len(cases)}", failures)


# --------------------------------------------------------------------------- #
# P3 / P4 — version +1 per challenge; evidence never shrinks
# --------------------------------------------------------------------------- #

CHAIN = ["OPS-101", "OPS-102", "OPS-103", "OPS-104"]


def property_version_and_growth(eng: AssessmentEngine) -> tuple[list[str], list[str], dict]:
    version_failures: list[str] = []
    growth_failures: list[str] = []
    claim = base_claim(eng)
    for step, record_id in enumerate(CHAIN, start=1):
        before = copy.deepcopy(claim)
        quote = item(claim, record_id)["quote"]
        claim = eng.challenge(claim, SEED_RECORDS, record_id, quote)
        if claim["version"] != before["version"] + 1:
            version_failures.append(
                f"step {step} ({record_id}): version {before['version']} -> {claim['version']}"
            )
        if len(claim["evidence"]) < len(before["evidence"]):
            growth_failures.append(
                f"step {step} ({record_id}): evidence {len(before['evidence'])} -> {len(claim['evidence'])}"
            )
    return version_failures, growth_failures, claim


def property_repeat_matched(eng: AssessmentEngine) -> dict:
    """Two successful challenges against the same item (the P5 counterexample)."""
    claim = base_claim(eng)
    quote = item(claim, "OPS-101")["quote"]
    claim = eng.challenge(claim, SEED_RECORDS, "OPS-101", quote)
    first = len([e for e in claim["evidence"] if e["disputed"]])
    claim = eng.challenge(claim, SEED_RECORDS, "OPS-101", quote)
    second = len([e for e in claim["evidence"] if e["disputed"]])
    return {"matched_challenges": 2, "disputed_after_first": first, "disputed_after_second": second}


# --------------------------------------------------------------------------- #
# P5 — disputed count equals successful challenges that matched evidence
# --------------------------------------------------------------------------- #

def count_disputed(claim: dict) -> int:
    return len([e for e in claim["evidence"] if e["disputed"]])


def main() -> int:
    eng = engine()

    property_purity(eng)
    property_recomputed_summary(eng)

    version_failures, growth_failures, chained = property_version_and_growth(eng)
    report("P3 version increments by exactly one per challenge",
           f"n={len(CHAIN)}", version_failures)
    report("P4 evidence never shrinks across a challenge chain",
           f"n={len(CHAIN)}, evidence={len(chained['evidence'])}", growth_failures)

    # P5, literal statement, over distinct matched dependencies in one chain.
    distinct = base_claim(eng)
    matched = 0
    for record_id in CHAIN:
        quote = item(distinct, record_id)["quote"]
        distinct = eng.challenge(distinct, SEED_RECORDS, record_id, quote)
        matched += 1
        if count_disputed(distinct) != matched:
            report(
                "P5 disputed count == successful challenges that matched",
                f"n={matched}",
                [f"after {record_id}: {count_disputed(distinct)} disputed, {matched} matched challenges"],
            )
            break
    else:
        report("P5 disputed count == successful challenges that matched",
               f"n={matched}, disputed={count_disputed(distinct)}", [])

    # P5, same item challenged twice: the literal equality is what is checked.
    repeat = property_repeat_matched(eng)
    repeat_failures = []
    if repeat["disputed_after_second"] != repeat["matched_challenges"]:
        repeat_failures.append(
            "same item challenged twice: 2 successful challenges matched evidence, "
            f"but disputed evidence count is {repeat['disputed_after_second']} "
            f"(was {repeat['disputed_after_first']} after one challenge); "
            "`disputed` is a boolean flag, so the count saturates"
        )
    report("P5b disputed count == matched challenges (same item repeated)",
           "n=2", repeat_failures)

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
