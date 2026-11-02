"""Architecture invariants over generated corpora, not just the seed set.

The seed corpus module (``test_architecture_invariants.py``) proves the four
properties on one hand-written fixture. A predicate can be right for that corpus
and wrong in general, so this module draws corpora from a fixed seed list with
the stdlib ``random`` and asserts the same properties on every draw:

1. every claim equals a fresh ``_summarize_status_decision`` of its own evidence;
2. the same corpus and the same clock produce the same claim twice;
3. a challenged claim equals its own reassessment;
4. no claim reports a score outside [-1, 1], and no claim's status contradicts
   the decision table's label for the counts its own evidence reports.

``POOL`` holds record ids the mock provider already maps to a stance, paired with
several texts per id. The provider derives *stance* from ``(record id,
hypothesis)``; the phrase-cue guard derives *review state* from the text, so
varying the text varies ACCEPTED/UNVERIFIED without touching the provider
contract. Timestamps decide staleness, source groups are drawn from 1..4 groups,
and dispute flags are produced by challenging a claim (invariant 3), which no
generator can set directly.

Generation is deterministic. A failure prints the exact corpus — records,
timestamps, clock and claim — so it can be replayed, and the generator is never
shrunk to make a failure disappear.
"""

from __future__ import annotations

import copy
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from app.decision_table import decide
from app.engine import AssessmentEngine, _summarize_status_decision
from app.models import (
    HYPOTHESES,
    Evidence,
    EvidenceReviewState,
    Record,
    Stance,
)

BASE_CLOCK = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)

# Fixed seed list. Seeds 0 and 1 pin the corpus-size extremes; the rest are drawn.
SEEDS = [
    0, 1, 2, 3, 5, 8, 11, 13, 17, 21,
    23, 29, 34, 41, 55, 68, 89, 111, 144, 177,
    233, 301, 377, 465, 610, 774, 987, 1234, 1597, 2584,
]

GROUPS = ("NIGHT-A", "DAY-B", "SWING-C", "NIGHT-D")
DEPARTMENTS = ("Front Office", "Housekeeping", "Maintenance")

RESTRICTED_ID = "RESTRICTED-CANARY-001"
RESTRICTED_TEXT = "RESTRICTED_CANARY_DO_NOT_DISCLOSE_8f2b1d"

# (record id, fixed source group or None, texts). Ids are the ones the mock
# provider maps to an explicit stance; the texts are chosen to land on cue
# matches, cue mismatches and no-cue abstentions for their target hypothesis.
POOL = [
    ("OPS-101", None, (
        "Night checklist binder was missing from the desk; we wrote room 412's late arrival on a loose note.",
        "The binder was missing again, so the late arrival went on a loose note.",
        "The checklist was available at both terminals during the night.",
        "The shift recorded a lamp repair and a late arrival.",
        "The checklist binder was missing, but the checklist was available now.",
    )),
    ("OPS-102", None, (
        "The digital checklist opened normally on both desk terminals during the afternoon handover.",
        "Both terminals showed the checklist opened normally after the handover.",
        "The printed checklist was unavailable, so we used a loose note.",
        "The desk was quiet and the shift had enough time to review every open item.",
    )),
    ("OPS-103", None, (
        "New colleague was unsure which section records rooms awaiting inspection; supervisor walked through the handover sheet.",
        "A new colleague needed guidance on the handover because the sections were unfamiliar.",
        "The team attended the handover briefing and completed the checklist together.",
    )),
    ("OPS-104", None, (
        "All scheduled team members attended the handover briefing and completed the checklist together.",
        "The briefing was attended by the whole team and the checklist was completed.",
        "One colleague was unsure which section records rooms awaiting inspection.",
    )),
    ("OPS-105", None, (
        "Two agents covered the desk while one colleague was absent; several guest requests were passed verbally.",
        "The desk ran short staffed after an absence and requests were passed verbally.",
        "We had enough people on duty and the shift had enough time to review every open item.",
    )),
    ("OPS-106", None, (
        "The property system timed out while saving the handover notes. IT restored service at 14:20.",
        "The system failed while saving the handover notes and was restored later.",
        "The property system worked normally through the whole handover.",
    )),
    ("OPS-107", None, (
        "The desk was quiet and the shift had enough time to review every open item before sign-off.",
        "There was not enough time, so several open items were reviewed after sign-off.",
        "The shift ran out of time and could not review every open item.",
    )),
    ("OPS-108", None, (
        "The handover sheet listed two rooms as ready, but the next shift found both still awaiting inspection.",
        "The note says nothing about checklist availability; it records room status only.",
        "The record does not address checklist availability and lists two rooms instead.",
    )),
    ("OPS-109", None, (
        "A printed checklist was unavailable during the morning shift last winter.",
        "A printed checklist was unavailable again during the morning shift.",
        "The morning shift had a checklist available at the desk.",
    )),
    ("OPS-110", None, (
        "We had enough people on duty and the checklist binder was at the desk, but the printer was out of paper.",
        "The binder was at the desk and the team was not short staffed, although the printer jammed.",
        "The checklist was unavailable and one colleague was absent during the busiest hour.",
    )),
    ("OPS-111", None, (
        "A guest called about a lamp; maintenance repaired it before the evening handover.",
        "Maintenance repaired a lamp before the evening handover.",
        "The property system timed out while saving the handover notes.",
    )),
    ("OPS-112", "OPS-105", (
        "Supervisor recap: two agents covered the desk while a colleague was absent; guest requests passed verbally.",
        "Recap of the absence: two agents covered the desk and requests were passed verbally.",
        "Recap: the team attended the handover briefing and completed the checklist together.",
    )),
    ("OPS-120", None, (
        "The checklist and the printer were mentioned in passing during the quiet shift.",
        "Shift notes mention a printer and a checklist but establish nothing further.",
        "Rooms were turned over without incident and the desk handed over normally.",
    )),
    ("OPS-121", None, (
        "The checklist binder was missing, but the checklist was available now.",
        "The shift had enough time, and there was not enough time later.",
        "Team members attended the briefing, but one colleague was unsure afterward.",
    )),
]


# --- generation -----------------------------------------------------------


def generate(seed: int) -> tuple[datetime, list[Record]]:
    """One corpus: 0..12 records, random text/stance, staleness and 1..4 groups."""
    rng = random.Random(seed)
    clock = BASE_CLOCK + timedelta(days=seed % 23, minutes=rng.randrange(0, 24 * 60))

    if seed == SEEDS[0]:
        size = 0
    elif seed == SEEDS[1]:
        size = 12
    else:
        size = rng.randint(0, 12)

    restricted_count = 1 if size and rng.random() < 0.2 else 0
    eligible_count = size - restricted_count
    groups = GROUPS[: rng.randint(1, 4)]

    chosen = rng.sample(POOL, k=min(eligible_count, len(POOL)))
    records = [
        Record(
            id=record_id,
            timestamp=_timestamp(rng, clock),
            department=rng.choice(DEPARTMENTS),
            text=rng.choice(texts),
            tags=["generated"],
            source_group=fixed_group if fixed_group is not None else rng.choice(groups),
        )
        for record_id, fixed_group, texts in chosen
    ]
    if restricted_count:
        records.append(
            Record(
                id=RESTRICTED_ID,
                timestamp=_timestamp(rng, clock),
                department="Restricted",
                text=RESTRICTED_TEXT,
                tags=["restricted"],
                restricted=True,
            )
        )
    rng.shuffle(records)
    return clock, records


def _timestamp(rng: random.Random, clock: datetime) -> datetime:
    """A timestamp that lands on fresh, stale, boundary, future and naive values."""
    kind = rng.choices(
        ("fresh", "stale", "edge_fresh", "edge_stale", "future", "naive", "now"),
        weights=(48, 20, 8, 8, 6, 6, 4),
    )[0]
    if kind == "fresh":
        return clock - timedelta(days=rng.randint(0, 88), hours=rng.randrange(24))
    if kind == "stale":
        return clock - timedelta(days=rng.randint(91, 800), hours=rng.randrange(24))
    if kind == "edge_fresh":
        return clock - timedelta(days=90)
    if kind == "edge_stale":
        return clock - timedelta(days=91)
    if kind == "future":
        return clock + timedelta(days=rng.randint(1, 30))
    if kind == "naive":
        return (clock - timedelta(days=rng.randint(0, 200))).replace(tzinfo=None)
    return clock


# --- shared helpers -------------------------------------------------------


def engine(clock: datetime) -> AssessmentEngine:
    return AssessmentEngine(clock=lambda: clock)


def corpus_json(seed: int, clock: datetime, records: list[Record]) -> str:
    """The exact corpus, printable so any failure can be replayed verbatim."""
    return json.dumps(
        {
            "seed": seed,
            "clock": clock.isoformat(),
            "records": [record.model_dump(mode="json") for record in records],
        },
        indent=2,
        sort_keys=True,
    )


def fail(seed: int, clock: datetime, records: list[Record], detail: str, **extra) -> None:
    body = [detail, corpus_json(seed, clock, records)]
    for name, value in extra.items():
        body.append(f"{name}:\n{json.dumps(value, indent=2, sort_keys=True, default=str)}")
    pytest.fail("\n\n".join(body))


def as_evidence(claim: dict) -> list[Evidence]:
    return [Evidence.model_validate(entry) for entry in claim["evidence"]]


def group_counts(evidence: list[Evidence]) -> tuple[set[str], set[str], set[str], set[str]]:
    """Independent recomputation of the counts a claim's evidence reports.

    Deliberately separate from ``app.decision_table._count_groups``: the point of
    invariant 4 is to re-derive the table's input from the persisted rows rather
    than to ask the table to explain itself.
    """
    support: set[str] = set()
    contradiction: set[str] = set()
    disputed_support: set[str] = set()
    disputed_contradiction: set[str] = set()
    for item in evidence:
        if item.review_state is not EvidenceReviewState.ACCEPTED:
            continue
        if item.stale:
            continue
        group = item.source_group or item.source_record_id
        if item.disputed:
            if item.stance is Stance.SUPPORTS:
                disputed_support.add(group)
            elif item.stance is Stance.CONTRADICTS:
                disputed_contradiction.add(group)
        elif item.stance is Stance.SUPPORTS:
            support.add(group)
        elif item.stance is Stance.CONTRADICTS:
            contradiction.add(group)
    return support, contradiction, disputed_support, disputed_contradiction


def table_label(evidence: list[Evidence]):
    support, contradiction, disputed_support, disputed_contradiction = group_counts(evidence)
    return decide(
        len(support),
        len(contradiction),
        disputed_support=len(disputed_support - support),
        disputed_contradiction=len(disputed_contradiction - contradiction),
        disputed_total=len(disputed_support | disputed_contradiction),
    )


_CACHE: dict[int, tuple[datetime, list[Record], list[dict]]] = {}


def corpus(seed: int) -> tuple[datetime, list[Record], list[dict]]:
    if seed not in _CACHE:
        clock, records = generate(seed)
        _CACHE[seed] = (clock, records, engine(clock).investigate(records))
    clock, records, claims = _CACHE[seed]
    return clock, records, copy.deepcopy(claims)


# --- invariant 1 ----------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_every_claim_equals_a_fresh_summary_of_its_own_evidence(seed):
    clock, records, claims = corpus(seed)

    if len(claims) != len(HYPOTHESES):
        fail(seed, clock, records, f"expected {len(HYPOTHESES)} claims, got {len(claims)}")

    for claim in claims:
        decision = _summarize_status_decision(as_evidence(claim))
        if claim["status"] != decision.status.value:
            fail(
                seed, clock, records,
                "claim status disagrees with a fresh summary of its own evidence "
                f"({claim['hypothesis_id']}: {claim['status']} != {decision.status.value})",
                claim=claim,
            )
        if claim["confidence"] != decision.confidence:
            fail(
                seed, clock, records,
                "claim confidence disagrees with a fresh summary of its own evidence "
                f"({claim['hypothesis_id']}: {claim['confidence']} != {decision.confidence})",
                claim=claim,
            )
        if claim["evidence_score"] != decision.evidence_score:
            fail(
                seed, clock, records,
                "claim evidence_score disagrees with a fresh summary of its own evidence "
                f"({claim['hypothesis_id']}: {claim['evidence_score']} != {decision.evidence_score})",
                claim=claim,
            )


# --- invariant 2 ----------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_the_same_generated_corpus_and_clock_produce_the_same_claim(seed):
    clock, records = generate(seed)

    first = engine(clock).investigate(records)
    second = engine(clock).investigate(records)

    if first != second:
        differing = next(
            (a["hypothesis_id"] for a, b in zip(first, second) if a != b),
            "claim list length",
        )
        fail(
            seed, clock, records,
            f"two investigations of the same corpus at the same clock differ ({differing})",
            first=first,
            second=second,
        )


# --- invariant 3 ----------------------------------------------------------


# ``MockProvider`` proposes for every record it can assess, so ``_claim`` never
# omits an assessable record: every challenge target is already a dependency and
# takes ``challenge``'s matched path. Only that path is reachable through the
# provider boundary, so only that path is asserted here.
def _challenge_target(evidence: list[dict]) -> dict:
    """Prefer a fresh accepted directional row, so the dispute rule is exercised."""
    for entry in evidence:
        item = Evidence.model_validate(entry)
        if (
            item.review_state is EvidenceReviewState.ACCEPTED
            and not item.stale
            and item.stance in (Stance.SUPPORTS, Stance.CONTRADICTS)
        ):
            return entry
    return evidence[0]


@pytest.mark.parametrize("seed", SEEDS)
def test_a_challenged_claim_equals_its_own_reassessment(seed):
    clock, records, claims = corpus(seed)
    eng = engine(clock)

    for claim in claims:
        evidence = claim["evidence"]
        if not evidence:
            continue
        target = _challenge_target(evidence)

        challenged = eng.challenge(claim, records, target["source_record_id"], target["quote"])

        if challenged["version"] != claim["version"] + 1:
            fail(seed, clock, records, "challenge did not increment the claim version",
                 claim=claim, challenged=challenged)
        if len(challenged["evidence"]) != len(evidence):
            fail(seed, clock, records, "challenging an assessed dependency changed the evidence set",
                 claim=claim, challenged=challenged)

        before = {(entry["source_record_id"], entry["quote"], entry["stance"]) for entry in evidence}
        after = {
            (entry["source_record_id"], entry["quote"], entry["stance"])
            for entry in challenged["evidence"]
        }
        if before != after:
            fail(seed, clock, records, "a challenge rewrote a quote, source or stance",
                 claim=claim, challenged=challenged)
        if not any(entry["disputed"] for entry in challenged["evidence"]):
            fail(seed, clock, records, "a challenge left no disputed evidence row",
                 challenged=challenged)

        _assert_reassessment(seed, clock, records, challenged, "after challenging an assessed dependency")

def _assert_reassessment(
    seed: int, clock: datetime, records: list[Record], challenged: dict, detail: str
) -> None:
    evidence = as_evidence(challenged)
    decision = _summarize_status_decision(evidence)
    if challenged["status"] != decision.status.value:
        fail(seed, clock, records,
             f"{detail}: status disagrees with a fresh summary ({challenged['status']} != "
             f"{decision.status.value})", challenged=challenged)
    if challenged["confidence"] != decision.confidence:
        fail(seed, clock, records,
             f"{detail}: confidence disagrees with a fresh summary "
             f"({challenged['confidence']} != {decision.confidence})", challenged=challenged)
    if challenged["evidence_score"] != decision.evidence_score:
        fail(seed, clock, records,
             f"{detail}: evidence_score disagrees with a fresh summary "
             f"({challenged['evidence_score']} != {decision.evidence_score})", challenged=challenged)

    table = table_label(evidence)
    if challenged["status"] != table.status.value:
        fail(seed, clock, records,
             f"{detail}: status contradicts the table's label ({challenged['status']} != "
             f"{table.status.value})", challenged=challenged)
    if challenged["evidence_score"] != table.score:
        fail(seed, clock, records,
             f"{detail}: evidence_score contradicts the table's score "
             f"({challenged['evidence_score']} != {table.score})", challenged=challenged)


# --- invariant 4 ----------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_scores_stay_in_range_and_status_matches_the_table_label(seed):
    clock, records, claims = corpus(seed)

    for claim in claims:
        _assert_score_bounds(seed, clock, records, claim, "investigated claim")

        evidence = as_evidence(claim)
        table = table_label(evidence)
        if claim["status"] != table.status.value:
            fail(
                seed, clock, records,
                "claim status contradicts the table's label for the counts its evidence reports "
                f"({claim['hypothesis_id']}: {claim['status']} != {table.status.value})",
                claim=claim,
            )
        if claim["evidence_score"] != table.score:
            fail(
                seed, clock, records,
                "claim evidence_score contradicts the table's score for the counts its evidence "
                f"reports ({claim['hypothesis_id']}: {claim['evidence_score']} != {table.score})",
                claim=claim,
            )
        if claim["evidence_direction"] != table.direction:
            fail(
                seed, clock, records,
                "claim evidence_direction contradicts the sign of the table's score "
                f"({claim['hypothesis_id']}: {claim['evidence_direction']} != {table.direction})",
                claim=claim,
            )


def _assert_score_bounds(
    seed: int, clock: datetime, records: list[Record], claim: dict, detail: str
) -> None:
    score = claim["evidence_score"]
    if score is None or not (-1.0 <= score <= 1.0):
        fail(seed, clock, records, f"{detail}: evidence_score outside [-1, 1] ({score})", claim=claim)
    confidence = claim["confidence"]
    if confidence is None or not (0.0 <= confidence <= 1.0):
        fail(seed, clock, records, f"{detail}: confidence outside [0, 1] ({confidence})", claim=claim)
    if confidence != abs(score):
        fail(
            seed, clock, records,
            f"{detail}: confidence is not the magnitude of the signed score "
            f"({confidence} != abs({score}))",
            claim=claim,
        )


# --- generator coverage ---------------------------------------------------


def test_the_generator_is_not_degenerate():
    """A generator that only produces one shape would make the invariants vacuous."""
    review_states, statuses, stale_seen, scores = set(), set(), False, set()
    empty_claims = 0

    for seed in SEEDS:
        _, _, claims = corpus(seed)
        for claim in claims:
            statuses.add(claim["status"])
            scores.add(claim["evidence_score"])
            if not claim["evidence"]:
                empty_claims += 1
            for item in as_evidence(claim):
                review_states.add(item.review_state)
                stale_seen = stale_seen or item.stale

    assert EvidenceReviewState.ACCEPTED in review_states, review_states
    assert EvidenceReviewState.UNVERIFIED in review_states, review_states
    assert stale_seen, "no generated corpus produced a stale record"
    assert len(statuses) >= 3, statuses
    assert 0.0 in scores, scores
    assert empty_claims, "no generated corpus produced a claim without evidence"
