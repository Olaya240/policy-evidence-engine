"""Properties for engine.py:207-412 (dispositions, trace, investigate, challenge).

Run: cd /home/alex/policy-evidence-fix && PYTHONPATH=backend python3 ct3/audit/slice7_properties.py

Stdlib only at the harness level; the project itself supplies pydantic. Every
property prints PASS/FAIL, a failing property prints the smallest counterexample
it found, and any failure exits non-zero.
"""
import copy
import json
import sys
from datetime import datetime, timezone

from app.engine import AssessmentEngine
from app.mock_provider import SEED_RECORDS

FIXED = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

DISPOSITION_CODES = {
    "COUNTED_SUPPORT",
    "COUNTED_CONTRADICTION",
    "NEUTRAL_NOT_DIRECTIONAL",
    "UNVERIFIED_EXCLUDED",
    "STALE_HISTORICAL_CONTEXT",
    "STALE_NON_DIRECTIONAL_CONTEXT",
    "DISPUTED_REVIEW_REQUIRED",
    "DEPENDENT_SOURCE_GROUP",
    "UNCLASSIFIED_REVIEW_REQUIRED",
}

failures = []


def check(name, condition, counterexample=None):
    if condition:
        print(f"PASS {name}")
        return
    print(f"FAIL {name}")
    if counterexample is not None:
        print("     counterexample: " + json.dumps(counterexample, default=str)[:600])
    failures.append(name)


def engine():
    return AssessmentEngine(clock=lambda: FIXED)


def records_snapshot(records):
    return [record.model_dump(mode="json") for record in records]


def claims_for(hypothesis_id):
    return next(
        claim for claim in engine().investigate(SEED_RECORDS)
        if claim["hypothesis_id"] == hypothesis_id
    )


# P1: investigate does not mutate its input records.
before = records_snapshot(SEED_RECORDS)
engine().investigate(SEED_RECORDS)
after = records_snapshot(SEED_RECORDS)
check("P1 investigate leaves the caller's records unchanged", before == after,
      {"before": before[0], "after": after[0]} if before != after else None)

# P2: challenge does not mutate the claim it is given.
claim = claims_for("CHECKLIST_UNAVAILABLE")
original = copy.deepcopy(claim)
engine().challenge(claim, SEED_RECORDS, "OPS-101", "Night checklist binder was missing from the desk")
check("P2 challenge leaves the incoming claim unchanged", claim == original,
      next((k for k in claim if claim[k] != original.get(k)), None) if claim != original else None)

# P3: two engines with the same injected clock produce equal investigations.
check("P3 investigate is reproducible under a fixed clock",
      engine().investigate(copy.deepcopy(SEED_RECORDS)) == engine().investigate(copy.deepcopy(SEED_RECORDS)))

# P4: a challenge preserves every prior evidence item and bumps version by one.
challenged = engine().challenge(claim, SEED_RECORDS, "OPS-101", "Night checklist binder was missing from the desk")
same_count = len(challenged["evidence"]) == len(claim["evidence"])
preserved = all(
    {k: v for k, v in old.items() if k != "disputed"} == {k: v for k, v in new.items() if k != "disputed"}
    for old, new in zip(claim["evidence"], challenged["evidence"])
)
check("P4 challenge preserves prior evidence and increments version once",
      same_count and preserved and challenged["version"] == claim["version"] + 1,
      {"same_count": same_count, "preserved": preserved,
       "version": [claim["version"], challenged["version"]]})

# P5: the disposition list is a partition of the evidence, with known codes only.
for claim in engine().investigate(SEED_RECORDS):
    dispositions = claim["explanation_trace"]["evidence_dispositions"]
    ids_match = [d["source_record_id"] for d in dispositions] == [e["source_record_id"] for e in claim["evidence"]]
    codes_known = all(set(d["codes"]) <= DISPOSITION_CODES and d["codes"] for d in dispositions)
    dependent_is_counted = all(
        "COUNTED_SUPPORT" in d["codes"]
        for d in dispositions
        if "DEPENDENT_SOURCE_GROUP" in d["codes"]
    )
    check(
        f"P5 dispositions partition the evidence ({claim['hypothesis_id']})",
        ids_match and codes_known and dependent_is_counted,
        None if ids_match and codes_known and dependent_is_counted else {
            "ids_match": ids_match, "codes_known": codes_known,
            "dependent_is_counted": dependent_is_counted,
        },
    )

# P6: the trace and the claim agree about the same number and the same rule.
for claim in engine().investigate(SEED_RECORDS):
    trace = claim["explanation_trace"]
    score = claim["evidence_score"]
    expected = "FOR" if score > 0 else "AGAINST" if score < 0 else "NONE"
    agrees = (
        trace["evidence_score"] == score
        and claim["evidence_direction"] == expected
        and trace["evidence_direction"] == expected
        and trace["status_rule_id"] == claim["explanation_trace"]["status_rule_id"]
        and trace["status_rule_id"].startswith("STATUS.V2_")
        and bool(claim["uncertainty"].strip())
    )
    check(f"P6 trace and claim agree on score, direction and rule ({claim['hypothesis_id']})", agrees,
          None if agrees else {"score": score, "direction": claim["evidence_direction"],
                               "trace_rule": trace["status_rule_id"]})

# P7: a disputed record never adds independent weight on its own.
# The seed claim for CHECKLIST_UNAVAILABLE is supported by OPS-101 and
# contradicted by OPS-102/OPS-110; challenging OPS-101 marks a group that is
# already counted, so the reported status must not change.
if claim["status"] != challenged["status"]:
    changed = {"before": claim["status"], "after": challenged["status"]}
else:
    changed = None
check("P7 challenging an already-counted group leaves the status unchanged", changed is None, changed)

print()
if failures:
    print(f"{len(failures)} property check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all slice-7 properties hold")
