"""Latency benchmark for the claim decision path.

Runs against whichever `app` is on PYTHONPATH, so the same script measures the
v1 branch and the v2 worktree:

    cd ~/policy-evidence-new/backend && PYTHONPATH=. <venv>/python ../ct3/bench.py
    cd ~/policy-evidence-fix/backend && PYTHONPATH=. <venv>/python ../ct3/bench.py

Prints JSON. The two numbers that matter are `summarize_us` (the decision table
itself) and `investigate_ms` (the end-to-end call the API serves).
"""

import json
import statistics
import time
from datetime import datetime, timedelta, timezone

from app.engine import AssessmentEngine, _summarize_status_decision
from app.models import Evidence, EvidenceReviewState, Stance

NOW = datetime.now(timezone.utc)


def evidence(n_support: int, n_contra: int) -> list[Evidence]:
    items = []
    for i in range(n_support):
        items.append(Evidence(
            source_record_id=f"S{i}", timestamp=NOW - timedelta(days=1), quote="q",
            stance=Stance.SUPPORTS, review_state=EvidenceReviewState.ACCEPTED,
            rationale="r", stale=False, department=f"D{i}", source_group=f"G{i}",
        ))
    for i in range(n_contra):
        items.append(Evidence(
            source_record_id=f"C{i}", timestamp=NOW - timedelta(days=1), quote="q",
            stance=Stance.CONTRADICTS, review_state=EvidenceReviewState.ACCEPTED,
            rationale="r", stale=False, department=f"E{i}", source_group=f"H{i}",
        ))
    return items


def timed(fn, iterations: int) -> dict:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1e6)
    samples.sort()
    return {
        "p50_us": round(statistics.median(samples), 2),
        "p95_us": round(samples[int(len(samples) * 0.95) - 1], 2),
        "n": iterations,
    }


def main() -> None:
    shapes = {
        "single_support": evidence(1, 0),
        "two_groups": evidence(2, 0),
        "mixed_2_1": evidence(2, 1),
        "ten_items": evidence(6, 4),
        "empty": [],
    }
    out = {"summarize": {}, "decide": {}, "investigate_ms": None}

    for name, items in shapes.items():
        out["summarize"][name] = timed(lambda items=items: _summarize_status_decision(items), 2000)

    try:
        from app.decision_table import decide_evidence
        out["decide"]["ten_items"] = timed(lambda: decide_evidence(shapes["ten_items"]), 2000)
    except ImportError:
        out["decide"]["ten_items"] = "absent (v1 branch)"

    from app.models import Record

    engine = AssessmentEngine()
    records = [
        Record(
            id=f"R{i}",
            timestamp=NOW - timedelta(days=1),
            department=f"Dept{i % 3}",
            text=t,
            tags=[],
        )
        for i, t in enumerate([
            "The handover checklist was unavailable at shift change.",
            "The binder was missing during the handover.",
            "Handover notes were not signed by the outgoing nurse.",
            "The checklist was unavailable again on the night shift.",
            "A desk lamp was replaced before dinner.",
            "The fire door was propped open during the inspection.",
            "The binder was missing and the checklist was unavailable.",
            "Handover was completed but the checklist was not signed.",
            "The medication fridge temperature was not logged.",
            "The binder was missing at the start of the shift.",
        ])
    ]

    out["investigate_ms"] = {
        "p50_ms": round(timed(lambda: engine.investigate(records), 200)["p50_us"] / 1000, 3),
        "n": 200,
    }

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
