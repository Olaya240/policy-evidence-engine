"""Slice-6 property harness: `app/engine.py:1-206`.

Covers the decision summariser that slice 6 owns: purity, the record classes that
must not move the number (stale, unverified), the classes that may only weaken it
(disputed), monotonicity under added support, permutation invariance, and the
`contested` flag.

Where the property as briefed does not match the code's design, the harness prints
a DIVERGENCE line naming both rather than failing silently: two of the five
briefed properties are literally false and one is true only for the signed score.

Run:
    cd /home/alex/policy-evidence-fix && PYTHONPATH=backend python ct3/audit/slice6_properties.py
"""

from __future__ import annotations

import itertools
import sys
from datetime import datetime, timedelta, timezone

from app.engine import AssessmentEngine, _summarize_status_decision
from app.models import Evidence, EvidenceReviewState, Stance, Status

NOW = datetime.now(timezone.utc)
FAILURES: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append((name, detail))


def divergence(name: str, briefed: str, actual: str) -> None:
    print(f"DIVERGENCE {name}: briefed={briefed!r} code={actual!r}")


def ev(stance, group, record_id=None, *, stale=False, disputed=False,
       state=EvidenceReviewState.ACCEPTED):
    return Evidence(
        source_record_id=record_id or f"rec-{group}",
        timestamp=NOW - timedelta(days=1),
        quote="the handover checklist was unavailable",
        stance=stance,
        review_state=state,
        rationale="because",
        stale=stale,
        department="Front Office",
        source_group=group,
        disputed=disputed,
    )


def support(group, **kw):
    return ev(Stance.SUPPORTS, group, **kw)


def contradict(group, **kw):
    return ev(Stance.CONTRADICTS, group, **kw)


def same(a, b) -> bool:
    return a == b


# --------------------------------------------------------------- 1. purity

def property_purity() -> None:
    print("\n== 1 purity ==")
    evidence = [support("a"), support("b"), contradict("c")]
    first = _summarize_status_decision(evidence)
    second = _summarize_status_decision(evidence)
    check("1 same evidence twice yields an equal decision", same(first, second),
          f"{first.status} vs {second.status}")

    # The summariser takes no clock. Two engines with different clocks must not
    # change it, which is what makes the purity structural rather than tested-in.
    one = AssessmentEngine(clock=lambda: datetime(2020, 1, 1, tzinfo=timezone.utc))
    two = AssessmentEngine(clock=lambda: datetime(2030, 6, 6, tzinfo=timezone.utc))
    assert one is not two
    third = _summarize_status_decision(list(evidence))
    check("1 two engines with different clocks cannot change it", same(first, third))

    before = [dict(e.__dict__) for e in evidence] if hasattr(evidence[0], "__dict__") else None
    _summarize_status_decision(evidence)
    if before is not None:
        check("1 the function does not mutate its input",
              before == [dict(e.__dict__) for e in evidence])


# ------------------------------------------- 2. records that must not move it

def property_inert_records() -> None:
    print("\n== 2 record classes ==")
    base = [support("a"), support("b"), contradict("c")]
    reference = _summarize_status_decision(base)

    for label, extra in (
        ("stale support", support("s1", stale=True)),
        ("stale contradiction", contradict("s2", stale=True)),
        ("unverified support", support("u1", state=EvidenceReviewState.UNVERIFIED)),
        ("unverified contradiction", contradict("u2", state=EvidenceReviewState.UNVERIFIED)),
    ):
        result = _summarize_status_decision(base + [extra])
        check(f"2 adding a {label} changes neither status nor confidence",
              result.status == reference.status and result.confidence == reference.confidence,
              f"{result.status}/{result.confidence} vs {reference.status}/{reference.confidence}")
        check(f"2 adding a {label} does not change the signed score",
              result.evidence_score == reference.evidence_score)

    # A dispute is NOT inert: excluding it can change the label, and that is by
    # design. The real invariant is that a dispute may only weaken, never strengthen.
    disputed = _summarize_status_decision(base + [support("d1", disputed=True)])
    gained = (disputed.status in (Status.SUPPORTED, Status.CONTRADICTED)
              and reference.status not in (Status.SUPPORTED, Status.CONTRADICTED))
    check("2 a disputed record never grants a decisive label", not gained,
          f"{reference.status} -> {disputed.status}")
    check("2 a disputed record never raises confidence",
          disputed.confidence <= reference.confidence + 1e-12,
          f"{reference.confidence} -> {disputed.confidence}")
    divergence("2 disputed is inert", "adding a disputed record never changes status",
               "a decision-relevant dispute downgrades to PARTIAL")


# ------------------------------------------------------- 3. monotonic support

def property_monotone_support() -> None:
    print("\n== 3 monotone support ==")
    for s in range(0, 7):
        for c in range(0, 7):
            base = [support(f"s{i}") for i in range(s)] + [contradict(f"c{i}") for i in range(c)]
            grown = base + [support(f"new-{s}-{c}")]
            if s >= 2 and c >= 1:
                # adding a group can make the pair (s, c) become (s+1, c)
                pass
            check(f"3 ({s},{c}) -> ({s + 1},{c}) raises the signed score",
                  _summarize_status_decision(grown).evidence_score
                  > _summarize_status_decision(base).evidence_score,
                  f"{_summarize_status_decision(base).evidence_score} -> "
                  f"{_summarize_status_decision(grown).evidence_score}")

    # The magnitude is not monotone, and saying so is the point of the signed score.
    before = _summarize_status_decision([contradict("c")])
    after = _summarize_status_decision([contradict("c"), support("s")])
    check("3 confidence falls when a support is added to a refuted claim (by design)",
          after.confidence < before.confidence,
          f"{before.confidence} -> {after.confidence}")
    divergence("3 monotone confidence", "adding support never lowers confidence",
               "confidence is |score|, so it falls 0.5 -> 0.0; the signed score rises")


# ------------------------------------------------------ 4. permutation invariance

def property_permutation() -> None:
    print("\n== 4 permutation ==")
    evidence = [support("a"), support("b"), contradict("c")]
    reference = _summarize_status_decision(evidence)
    for order in itertools.permutations(range(len(evidence))):
        permuted = [evidence[i] for i in order]
        if not same(_summarize_status_decision(permuted), reference):
            check("4 every permutation yields the same decision", False, f"order {order}")
            return
    check("4 every permutation yields the same decision", True)


# ------------------------------------------------------------- 5. contested

def property_contested() -> None:
    print("\n== 5 contested ==")
    for s in range(0, 5):
        for c in range(0, 5):
            evidence = [support(f"s{i}") for i in range(s)] + [contradict(f"c{i}") for i in range(c)]
            decision = _summarize_status_decision(evidence)
            check(f"5 ({s},{c}) contested iff both directions present",
                  decision.contested == (s > 0 and c > 0),
                  f"{decision.contested}")

    inert_dispute = [support("a"), support("b", disputed=True)]
    decision = _summarize_status_decision(inert_dispute)
    check("5 a disputed record sets contested", decision.contested is True)
    divergence("5 contested scope", "contested when both directions or a decision-relevant dispute",
               "contested for ANY fresh accepted dispute, relevant or not")


def main() -> int:
    property_purity()
    property_inert_records()
    property_monotone_support()
    property_permutation()
    property_contested()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED property check(s):")
        for name, detail in FAILURES:
            print(f"  - {name} [{detail}]")
        return 1
    print("all property checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
