"""Slice 19-20 defect: the manifest must be bound to the run it describes.

Every assertion here fails on the pre-fix code:

* `AttemptMetadata.request_count` was fed the run-wide counter, so the attempt
  list read `1, 2, 3, ... len(eligible)` instead of a per-case count;
* `run_evaluation` serialised `code_revision=None` and never named the model,
  so two manifests from different code and different models were identical;
* `attempts` was a plain list, so attempts could be appended or replaced after
  the record was written, and a manifest with nothing recorded serialised as a
  complete run record.

The tests that pin the defect from the outside live in
`tests/test_manifest_and_routes.py`; this file pins the fixed contract.
"""
import json
import re

import pytest

from app import evaluate
from app.evaluate import DATASET_PATH, run_evaluation
from app.experiment_manifest import (
    UNKNOWN,
    AttemptMetadata,
    ExperimentRunManifest,
)

_DIGEST = "a" * 64


def _manifest(**overrides) -> ExperimentRunManifest:
    kwargs = dict(
        run_id="run-0001",
        dataset_sha256=_DIGEST,
        evaluator_version="3.16.0",
        prompt_version="local-instructions-v1",
        prompt_sha256="b" * 64,
        serializer_version="allowlist-json-v1",
        serializer_sha256="c" * 64,
        code_revision="rev-1",
        model_name="synthetic-model",
        model_version="2026-10-01",
        temperature=0.0,
        seed=7,
    )
    kwargs.update(overrides)
    return ExperimentRunManifest(**kwargs)


def _eligible_case_ids() -> list[str]:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]
    return [case["id"] for case in cases if not case.get("expected_rejection_code")]


@pytest.fixture(scope="module")
def evaluated() -> dict:
    return run_evaluation(guarded=False)


# --------------------------------------------------------------------------- #
# Per-attempt accounting
# --------------------------------------------------------------------------- #


def test_each_attempt_records_the_requests_spent_on_its_own_case(evaluated):
    eligible = _eligible_case_ids()
    attempts = evaluated["metrics"]["experiment_manifest"]["attempts"]

    assert [attempt["case_id"] for attempt in attempts] == eligible
    # One controlled request per served case. The run-wide counter reaches 17
    # by the last case, so a cumulative value cannot pass this.
    assert [attempt["request_count"] for attempt in attempts] == [1] * len(eligible)
    assert sum(attempt["request_count"] for attempt in attempts) == (
        evaluated["metrics"]["assessment_calls"]["numerator"]
    )


def test_attempt_metadata_accepts_a_refused_case_and_rejects_a_negative_count():
    # A case the controller refused before reserving anything spent nothing.
    refused = AttemptMetadata(case_id="refused-case", request_count=0)
    assert refused.to_dict()["request_count"] == 0

    with pytest.raises(ValueError):
        AttemptMetadata(case_id="impossible-case", request_count=-1)


# --------------------------------------------------------------------------- #
# Model, decoding and code identity
# --------------------------------------------------------------------------- #


def test_evaluated_manifest_names_the_model_and_code_that_produced_it(evaluated):
    manifest = evaluated["metrics"]["experiment_manifest"]

    assert manifest["model_name"] == "MockProvider"
    assert manifest["model_version"] == UNKNOWN
    assert manifest["code_revision"] is not None
    assert manifest["code_revision"] == UNKNOWN or re.fullmatch(
        r"[0-9a-f]{40}(?:[0-9a-f]{24})?(?:-dirty)?", manifest["code_revision"]
    )
    # The offline provider performs no sampling: both fields stay null instead
    # of being filled with a number nothing observed.
    assert manifest["decoding"] == {"temperature": None, "seed": None}


def test_code_revision_reports_head_and_the_observed_dirty_state(monkeypatch):
    head = "0123456789abcdef0123456789abcdef01234567"

    def clean(*args):
        if args[:2] == ("rev-parse", "--verify"):
            return head
        return ""

    monkeypatch.setattr(evaluate, "_git", clean)
    assert evaluate.code_revision() == head

    def dirty(*args):
        if args[:2] == ("rev-parse", "--verify"):
            return head
        return " M backend/app/evaluate.py"

    monkeypatch.setattr(evaluate, "_git", dirty)
    # An uncommitted tree is not that commit, and says so.
    assert evaluate.code_revision() == f"{head}-dirty"

    # Git unavailable, or a HEAD that is not a revision: explicit unknown.
    monkeypatch.setattr(evaluate, "_git", lambda *args: None)
    assert evaluate.code_revision() == UNKNOWN
    monkeypatch.setattr(evaluate, "_git", lambda *args: "not-a-revision")
    assert evaluate.code_revision() == UNKNOWN


# --------------------------------------------------------------------------- #
# Sealing: attempts can no longer arrive after the record is written
# --------------------------------------------------------------------------- #


def test_evaluation_seals_the_manifest_before_serialising(monkeypatch):
    sealed_at: list[list[str]] = []
    original_seal = ExperimentRunManifest.seal

    def recording_seal(self):
        sealed_at.append([attempt.case_id for attempt in self.attempts])
        original_seal(self)

    monkeypatch.setattr(ExperimentRunManifest, "seal", recording_seal)
    # The recomputation checks own a database; the manifest does not depend on them.
    monkeypatch.setattr(evaluate, "_evaluate_recomputation_history",
                        lambda guarded: {"passed": 1, "total": 1})

    result = run_evaluation(guarded=False)
    reported = [attempt["case_id"]
                for attempt in result["metrics"]["experiment_manifest"]["attempts"]]

    assert len(sealed_at) == 1
    assert sealed_at[0]
    assert sealed_at[0] == reported


def test_sealing_freezes_the_attempt_list():
    manifest = _manifest()
    manifest.add_attempt(AttemptMetadata(case_id="case-1", request_count=1))
    manifest.seal()

    with pytest.raises(ValueError):
        manifest.add_attempt(AttemptMetadata(case_id="added-after-seal", request_count=1))
    with pytest.raises(ValueError):
        manifest.seal()

    assert [attempt["case_id"] for attempt in manifest.to_dict()["attempts"]] == ["case-1"]


def test_manifest_refuses_attempts_that_bypassed_add_attempt():
    appended = _manifest()
    appended.add_attempt(AttemptMetadata(case_id="case-1", request_count=1))
    appended.attempts.append(AttemptMetadata(case_id="appended-later", request_count=1))
    with pytest.raises(ValueError):
        appended.to_dict()

    replaced = _manifest()
    replaced.add_attempt(AttemptMetadata(case_id="case-1", request_count=1))
    replaced.attempts = [AttemptMetadata(case_id="replaced", request_count=1)]
    with pytest.raises(ValueError):
        replaced.to_dict()

    sealed = _manifest()
    sealed.add_attempt(AttemptMetadata(case_id="case-1", request_count=1))
    sealed.seal()
    sealed.attempts.append(AttemptMetadata(case_id="appended-after-seal", request_count=1))
    with pytest.raises(ValueError):
        sealed.to_dict()


def test_sealing_refuses_a_record_with_nothing_recorded_or_no_identity():
    with pytest.raises(ValueError):
        _manifest().seal()  # zero attempts is not a run record

    for overrides in ({"code_revision": None}, {"model_name": None}):
        manifest = _manifest(**overrides)
        manifest.add_attempt(AttemptMetadata(case_id="case-1", request_count=1))
        with pytest.raises(ValueError):
            manifest.seal()

    # "Unknown" is an answer; silence is not.
    explicit = _manifest(code_revision=UNKNOWN, model_name=UNKNOWN, model_version=UNKNOWN)
    explicit.add_attempt(AttemptMetadata(case_id="case-1", request_count=1))
    explicit.seal()
    assert explicit.to_dict()["code_revision"] == UNKNOWN
