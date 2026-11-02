"""Regressions for the two defects that made `challenge` unsafe.

1. Impurity. The engine stamped wall-clock times into every trace, so two
   identical calls produced different bytes and the evaluator's own
   `same_input_same_recomputation` check scored 6/7. An injectable clock fixes
   the cause rather than the metric; the default clock is unchanged.

2. Caller mutation. `challenge` rebuilt `raw["evidence"]` and appended
   *references* for every evidence item it did not touch, then the semantic
   guard wrote `review_state` into those dicts. The API passes the caller's own
   claim objects as `expected_claims`, so the expected bytes changed before the
   compare in `store.apply_challenge` and a legacy investigation could never be
   challenged again.
"""

import copy
import json
from datetime import datetime, timedelta, timezone

from app.engine import AssessmentEngine
from app.models import Record

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
QUOTE = "checklist was unavailable"


def records():
    return [
        Record(
            id="R1",
            timestamp=NOW - timedelta(days=1),
            department="Front Office",
            text="The handover checklist was unavailable at shift change.",
            tags=[],
        ),
        Record(
            id="R2",
            timestamp=NOW - timedelta(days=2),
            department="Back Office",
            text="The handover checklist was unavailable again.",
            tags=[],
        ),
    ]


def fixed_engine():
    return AssessmentEngine(clock=lambda: NOW)


def legacy(claim):
    """Simulate a claim persisted before `review_state` existed on evidence."""
    for item in claim["evidence"]:
        item.pop("review_state", None)
    return claim


def test_two_challenges_with_one_clock_are_byte_identical():
    engine = fixed_engine()
    claim = json.loads(json.dumps(engine.assess_hypothesis(records(), HYPOTHESIS)))

    first = engine.challenge(claim, records(), "R1", QUOTE)
    second = engine.challenge(claim, records(), "R1", QUOTE)

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_the_clock_is_what_varies_when_it_is_not_injected():
    """Contrast case: the default clock reproduces the old impurity, which is
    why the fix is an injected clock and not a nulled field."""
    engine = AssessmentEngine()
    claim = json.loads(json.dumps(engine.assess_hypothesis(records(), HYPOTHESIS)))

    first = engine.challenge(claim, records(), "R1", QUOTE)
    second = engine.challenge(claim, records(), "R1", QUOTE)

    assert first["explanation_trace"]["generated_at"] != \
        second["explanation_trace"]["generated_at"]


def test_investigate_is_reproducible_under_a_fixed_clock():
    engine = fixed_engine()
    assert engine.assess_hypothesis(records(), HYPOTHESIS) == \
        engine.assess_hypothesis(records(), HYPOTHESIS)


def test_challenge_does_not_mutate_the_callers_claim():
    engine = fixed_engine()
    claim = json.loads(json.dumps(engine.assess_hypothesis(records(), HYPOTHESIS)))
    snapshot = copy.deepcopy(claim)

    engine.challenge(claim, records(), "R1", QUOTE)

    assert claim == snapshot


def test_challenge_does_not_rewrite_a_legacy_claim_it_was_handed():
    """The 409 case: legacy evidence has no `review_state`, and the guard used to
    add it to the caller's dict, so the later compare against stored bytes failed."""
    engine = fixed_engine()
    claim = legacy(json.loads(json.dumps(engine.assess_hypothesis(records(), HYPOTHESIS))))
    snapshot = copy.deepcopy(claim)

    revised = engine.challenge(claim, records(), "R1", QUOTE)

    assert claim == snapshot
    assert all("review_state" in item for item in revised["evidence"])
