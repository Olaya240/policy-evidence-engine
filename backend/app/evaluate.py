"""Deterministic, offline evaluation against the checked-in synthetic gold set."""
import json
import os
import inspect
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from unittest.mock import patch

from . import store
from .engine import AssessmentEngine, ProviderError
from .mock_provider import MockProvider
from .models import Record
from .provider_safety import SYSTEM_INSTRUCTIONS, serialize_provider_request
from .experiment_control import ExperimentControlError, ExperimentRunController
from .experiment_manifest import UNKNOWN, AttemptMetadata, ExperimentRunManifest, sha256_hex

DATASET_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "gold_cases.json"
EVALUATION_AS_OF = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Only the code this harness executes: the package under test and the checked-in
# gold set. A change anywhere here means the working copy is not HEAD.
_REVISION_SUBJECTS = ("backend/app", "backend/evaluation")
_REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

# The offline harness answers with `MockProvider` only, so that class is the
# model of record. It is read from the class that is actually constructed rather
# than asserted. The provider defines no version of its own and performs no
# sampling, so version is the explicit unknown and the decoding fields stay null
# (null meaning "not applicable here", never a plausible-looking number).
MODEL_NAME = MockProvider.__name__
MODEL_VERSION = UNKNOWN


def _git(*args: str) -> str | None:
    """Read one fact from the checkout's git metadata, or None if unreadable."""
    try:
        completed = subprocess.run(
            ["git", *args], cwd=_REPO_ROOT, capture_output=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", "replace").strip()


def code_revision() -> str:
    """The revision the evaluated code came from, or the explicit `"unknown"`.

    HEAD alone is not the answer when tracked or untracked files under the
    evaluated paths differ from it, so an uncommitted tree is reported as
    `<sha>-dirty`: the commit this copy is based on plus the observed fact that
    it is not that commit. Git being absent, the directory not being a checkout,
    or a HEAD that is not a revision all yield `"unknown"` rather than a value
    that merely looks like one.
    """
    head = _git("rev-parse", "--verify", "HEAD")
    if head is None or _REVISION.fullmatch(head) is None:
        return UNKNOWN
    status = _git("status", "--porcelain", "--untracked-files=all", "--", *_REVISION_SUBJECTS)
    if status is None:
        return UNKNOWN
    return f"{head}-dirty" if status else head


class EvaluationDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return EVALUATION_AS_OF.replace(tzinfo=None)
        return EVALUATION_AS_OF.astimezone(tz)


def _fixture_provider(case_id: str, hypothesis_id: str, provider_mode: str, fixture_output: Any) -> MockProvider:
    """Use immutable JSON fixtures while preserving the exact local mock type."""
    if provider_mode == "mock":
        return MockProvider()
    return MockProvider(assessment_overrides={hypothesis_id: fixture_output})


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
    }


def _evaluate_recomputation_history(guarded: bool) -> dict[str, Any]:
    db_path = store.validate_database_path(store.DATA_DIR / f".phase37-eval-{uuid4().hex}.sqlite3")
    if db_path.exists():
        raise RuntimeError("Refusing to overwrite an existing evaluation database")
    previous_db_path = os.environ.get("HACKATHON_DB_PATH")
    os.environ["HACKATHON_DB_PATH"] = str(db_path)
    checks: dict[str, bool] = {}
    try:
        store.initialize_database()
        records = store.list_records()
        # The clock is injected for the whole run, not just around `investigate`:
        # patching `app.engine.datetime` only inside the first call left the
        # challenge recomputations on the real clock, which is why
        # `same_input_same_recomputation` failed on a deterministic engine.
        engine = AssessmentEngine(semantic_guard=guarded, clock=lambda: EVALUATION_AS_OF)
        with patch("app.engine.datetime", EvaluationDateTime):
            initial_claims = engine.investigate(records)
        # The run is evaluated as of a frozen instant, so the rows it writes must
        # carry that instant rather than the wall clock at the moment of writing.
        created = store.create_investigation("Phase 3.6 deterministic history evaluation", initial_claims,
                                             clock=lambda: EVALUATION_AS_OF)
        initial = store.get_investigation(created["id"])
        source_id = "OPS-101"
        source = next(record for record in records if record.id == source_id)
        target_id = "CHECKLIST_UNAVAILABLE"
        snapshot = store.get_challenge_snapshot(created["id"], target_id, source_id)
        target = snapshot["claims"][target_id]
        affected = snapshot["affected_claim_ids"]
        pure_first = engine.challenge(target, records, source_id, "binder was missing")
        pure_second = engine.challenge(target, records, source_id, "binder was missing")
        checks["same_input_same_recomputation"] = pure_first == pure_second

        revised = {
            cid: engine.challenge(claim, records, source_id, "binder was missing")
            for cid, claim in snapshot["claims"].items()
        }
        applied = store.apply_challenge(
            created["id"], target_id, "Evaluation fixture challenge.", source_id,
            "binder was missing", expected_revision=snapshot["revision"],
            expected_claims=snapshot["claims"], revised_claims=revised,
            clock=lambda: EVALUATION_AS_OF,
        )
        current = store.get_investigation(created["id"])
        history = store.get_history(created["id"])
        current_by_id = {claim["id"]: claim for claim in current["claims"]}
        checks["only_dependency_affected_claims_recomputed"] = sorted(applied["recomputed_claim_ids"]) == affected
        checks["history_versions_appended"] = [event["version"] for event in history] == [1, 2]
        checks["before_snapshot_preserved"] = history[1]["before"] == {cid: next(c for c in initial["claims"] if c["id"] == cid) for cid in affected}
        checks["unaffected_claims_unchanged"] = all(
            current_by_id[claim["id"]] == claim for claim in initial["claims"] if claim["id"] not in affected
        )
        checks["history_after_matches_current"] = history[1]["after"] == {
            cid: current_by_id[cid] for cid in affected
        }
        checks["stored_investigation_revision_advanced_once"] = current["version"] == 2 and applied["version"] == 2
    finally:
        if previous_db_path is None:
            os.environ.pop("HACKATHON_DB_PATH", None)
        else:
            os.environ["HACKATHON_DB_PATH"] = previous_db_path
        for suffix in ("", "-journal", "-wal", "-shm"):
            candidate = Path(str(db_path) + suffix)
            if candidate.exists():
                candidate.unlink()
    passed = sum(checks.values())
    return {"passed": passed, "total": len(checks), "checks": checks, "disposable_database_removed": not db_path.exists()}


def run_evaluation(*, guarded: bool = True, failure_injector=None) -> dict[str, Any]:
    raw_dataset = DATASET_PATH.read_bytes()
    dataset = json.loads(raw_dataset.decode("utf-8"))
    cases = dataset["cases"]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Gold case IDs must be unique")

    # Freeze all gold denominators before invoking any assessor. Contract cases
    # are local validator checks and are deliberately outside model metrics.
    eligible_cases = [case for case in cases if not case.get("expected_rejection_code")]
    stance_denominator = sum(len(case["expected_stances"]) for case in eligible_cases)
    status_denominator = len(eligible_cases)
    false_support_denominator = sum(
        stance != "SUPPORTS" for case in eligible_cases for stance in case["expected_stances"]
    )
    false_abstention_denominator = sum(
        stance in {"SUPPORTS", "CONTRADICTS"} for case in eligible_cases for stance in case["expected_stances"]
    )
    # This is a case-level metric: all semantic-review assessment cases are
    # frozen here, before provider work. A failed attempt or valid abstention is
    # a distinct outcome, not a semantic mismatch and never a denominator drop.
    semantic_case_ids = [case["id"] for case in eligible_cases if case.get("semantic_review")]
    semantic_case_id_set = set(semantic_case_ids)
    expected_stances_by_mode = {
        mode: sum(len(case["expected_stances"]) for case in eligible_cases if case["provider_mode"] == mode)
        for mode in sorted({case["provider_mode"] for case in eligible_cases})
    }

    stance_correct = status_correct = insufficient_count = valid_abstentions = 0
    exact_quote_valid = 0
    rejection_results: dict[str, list[bool]] = {}
    rejection_by_case: dict[str, bool] = {}
    semantic_mismatch_case_ids: list[str] = []
    semantic_error_case_ids: list[str] = []
    semantic_abstention_case_ids: list[str] = []
    semantic_match_case_ids: list[str] = []
    unverified_proposal_case_ids: list[str] = []
    false_support: list[str] = []
    false_contradiction: list[str] = []
    false_abstention: list[str] = []
    provider_errors: list[str] = []
    case_results = []
    run_controller = ExperimentRunController(max_requests=len(eligible_cases), single_flight=True)
    prompt_digest = sha256_hex(SYSTEM_INSTRUCTIONS.encode("utf-8"))
    serializer_digest = sha256_hex(inspect.getsource(serialize_provider_request).encode("utf-8"))
    manifest = ExperimentRunManifest(
        run_id=run_controller.run_id,
        dataset_sha256=sha256_hex(raw_dataset),
        code_revision=code_revision(),
        prompt_version="local-instructions-v1",
        prompt_sha256=prompt_digest,
        serializer_version="allowlist-json-v1",
        serializer_sha256=serializer_digest,
        evaluator_version="3.16.0",
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        temperature=None,
        seed=None,
    )
    contract_cases = [case for case in cases if case.get("expected_rejection_code")]

    for case in cases:
        records = [Record.model_validate(item) for item in case["records"]]
        provider = _fixture_provider(case["id"], case["hypothesis_id"], case["provider_mode"], case.get("fixture_output"))
        engine = AssessmentEngine(provider, semantic_guard=guarded)
        expected_rejection = case.get("expected_rejection_code")
        started = time.perf_counter()
        requests_before = run_controller.request_count
        claim = None
        observed_rejection = None
        if expected_rejection:
            # These four cases exercise only the local proposal validator.
            try:
                with patch("app.engine.datetime", EvaluationDateTime):
                    claim = engine.assess_hypothesis(records, case["hypothesis_id"])
            except ProviderError as exc:
                observed_rejection = exc.code
            except Exception:
                observed_rejection = "unexpected_exception"
            matched = observed_rejection == expected_rejection
            rejection_results.setdefault(expected_rejection, []).append(matched)
            rejection_by_case[case["id"]] = matched
            case_results.append({
                "id": case["id"], "observed": "rejected" if observed_rejection else "accepted",
                "rejection_code": observed_rejection, "expected_rejection_code": expected_rejection,
                "assessment_calls": 1,
            })
            continue

        try:
            def assess_target():
                if failure_injector is not None:
                    injected = failure_injector(case)
                    if injected is not None:
                        raise injected
                with patch("app.engine.datetime", EvaluationDateTime):
                    return engine.assess_hypothesis(records, case["hypothesis_id"])
            claim = run_controller.execute(case["id"], assess_target)
            error_category = None
        except ProviderError as exc:
            error_category = exc.code
        except ExperimentControlError as exc:
            error_category = exc.code
        except TimeoutError:
            error_category = "timeout"
        except Exception:
            # Never retain exception text: it could contain record or prompt data.
            error_category = "unexpected_exception"
        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        # Per-case accounting: the run-wide counter says nothing about what this
        # attempt cost, and a refused case reserves nothing at all.
        requests_used = run_controller.request_count - requests_before
        if error_category:
            provider_errors.append(error_category)
            if case["id"] in semantic_case_id_set:
                semantic_error_case_ids.append(case["id"])
            manifest.add_attempt(AttemptMetadata(
                case_id=case["id"], request_count=requests_used,
                latency_ms=latency_ms, error_category=(error_category if error_category in {
                    "timeout", "provider_failure", "malformed_response", "malformed_output",
                    "invalid_source", "invalid_quote", "invalid_stance", "invalid_rationale",
                    "request_limit", "single_flight_limit", "estimated_budget_exceeded",
                } else "unexpected_exception"),
            ))
            case_results.append({"id": case["id"], "observed": "provider_error", "error_category": error_category,
                                 "expected_stances": case["expected_stances"], "expected_status": case["expected_status"],
                                 "assessment_calls": 1})
            continue

        manifest.add_attempt(AttemptMetadata(case_id=case["id"], request_count=requests_used, latency_ms=latency_ms))
        observed_proposals = [item.get("proposed_stance") or item["stance"] for item in claim["evidence"]]
        # Only locally accepted stances count as semantic assessment output.
        # Unverified proposals remain visible for review and score as missing.
        actual_stances = [item["stance"] if item.get("review_state", "ACCEPTED") == "ACCEPTED" else None
                          for item in claim["evidence"]]
        unverified_case = any(item.get("review_state") == "UNVERIFIED" for item in claim["evidence"])
        if unverified_case:
            unverified_proposal_case_ids.append(case["id"])
        expected_stances = case["expected_stances"]
        correct = sum(index < len(actual_stances) and actual_stances[index] == expected
                      for index, expected in enumerate(expected_stances))
        stance_correct += correct
        if case.get("semantic_review"):
            if not claim["evidence"]:
                semantic_abstention_case_ids.append(case["id"])
            else:
                mismatch = (len(actual_stances) != len(expected_stances)
                            or any(actual_stances[index] != expected
                                   for index, expected in enumerate(expected_stances)
                                   if index < len(actual_stances)))
                if mismatch:
                    semantic_mismatch_case_ids.append(case["id"])
                else:
                    semantic_match_case_ids.append(case["id"])
            for actual, expected in zip(actual_stances, expected_stances):
                if actual == "CONTRADICTS" and expected == "NEUTRAL":
                    false_contradiction.append(case["id"])
        for index, expected in enumerate(expected_stances):
            actual = actual_stances[index] if index < len(actual_stances) else None
            if expected != "SUPPORTS" and actual == "SUPPORTS":
                false_support.append(case["id"])
            if expected in {"SUPPORTS", "CONTRADICTS"} and actual in {None, "NEUTRAL"}:
                false_abstention.append(case["id"])
        status_correct += claim["status"] == case["expected_status"]
        insufficient_count += claim["status"] == "INSUFFICIENT"
        valid_abstentions += not claim["evidence"]
        record_by_id = {record.id: record for record in records}
        for index in range(len(expected_stances)):
            if index < len(claim["evidence"]):
                evidence = claim["evidence"][index]
                source = record_by_id.get(evidence["source_record_id"])
                exact_quote_valid += bool(source and evidence["quote"] in source.text)
        case_results.append({
            "id": case["id"], "observed_stances": actual_stances,
            "observed_proposals": observed_proposals,
            "expected_stances": expected_stances, "observed_status": claim["status"],
            "expected_status": case["expected_status"], "assessment_calls": 1,
            "guard_audit": [
                {"proposed_stance": e.get("proposed_stance"), "semantic_relation": e.get("semantic_relation"),
                 "final_stance": e["stance"], "review_state": e.get("review_state", "ACCEPTED"),
                 "rationale": e["rationale"]} for e in claim["evidence"]
            ],
        })

    # Unexpected/injected provider errors occupy their gold slots as incorrect;
    # they are reported separately and never counted as valid abstentions.
    recomputation = _evaluate_recomputation_history(guarded)
    mode_metrics = {}
    for mode, denominator in expected_stances_by_mode.items():
        mode_correct = 0
        for case in eligible_cases:
            if case["provider_mode"] != mode:
                continue
            result = next((r for r in case_results if r["id"] == case["id"]), {})
            actual = result.get("observed_stances", [])
            mode_correct += sum(i < len(actual) and actual[i] == expected
                                for i, expected in enumerate(case["expected_stances"]))
        mode_metrics[mode] = _ratio(mode_correct, denominator)
    metrics = {
        "expected_denominators": {
            "eligible_cases": status_denominator, "stance_labels": stance_denominator,
            "status_labels": status_denominator, "exact_quote_slots": stance_denominator,
            "false_support_labels": false_support_denominator,
            "false_neutral_labels": false_abstention_denominator,
            "local_contract_cases": len(contract_cases),
        },
        "assessment_calls": {"numerator": run_controller.request_count, "denominator": len(eligible_cases),
                             "exactly_one_per_eligible_case": run_controller.request_count == len(eligible_cases)},
        "provider_error_rate": {**_ratio(len(provider_errors), status_denominator), "categories": provider_errors,
                                 "case_ids": [r["id"] for r in case_results if r.get("observed") == "provider_error"],
                                 "note": "Failures count as incorrect in stance/status accuracy and are not valid abstentions."},
        "valid_abstention_rate": {**_ratio(valid_abstentions, status_denominator),
                                  "case_ids": [r["id"] for r in case_results if r.get("observed_status") == "INSUFFICIENT" and not r.get("guard_audit") and r.get("observed_stances") == []],
                                  "note": "Numerator counts successful eligible assessments with no accepted evidence; infrastructure failures are excluded."},
        "stance_accuracy": {**_ratio(stance_correct, stance_denominator), "by_provider_mode": mode_metrics},
        "status_accuracy": _ratio(status_correct, status_denominator),
        "insufficient_evidence_rate": {
            **_ratio(insufficient_count, status_denominator),
            "gold_insufficient_cases": sum(c["expected_status"] == "INSUFFICIENT" for c in eligible_cases),
            "gold_status_cases": status_denominator,
        },
        "exact_quote_validity": _ratio(exact_quote_valid, stance_denominator),
        "invalid_source_rejection": _ratio(
            sum(rejection_results.get("invalid_source", [])), len(rejection_results.get("invalid_source", []))
        ),
        "invalid_quote_rejection": _ratio(
            sum(rejection_results.get("invalid_quote", [])), len(rejection_results.get("invalid_quote", []))
        ),
        "malformed_provider_output_rejection": _ratio(
            sum(rejection_results.get("malformed_output", [])), len(rejection_results.get("malformed_output", []))
        ),
        "unsupported_causation_rejection": _ratio(
            int(rejection_by_case.get("unsupported-causation-overclaim", False)), 1
        ),
        "invalid_proposal_rejection": _ratio(
            sum(rejection_by_case.values()), len(rejection_by_case)
        ),
        "false_support_rate": {
            **_ratio(len(false_support), false_support_denominator),
            "case_ids": sorted(set(false_support)),
            "false_support_stance_count": len(false_support),
            "note": "Denominator is every gold NEUTRAL or CONTRADICTS stance label; numerator is an observed SUPPORTS stance.",
        },
        "false_abstention_false_neutral_rate": {
            **_ratio(len(false_abstention), false_abstention_denominator),
            "case_ids": sorted(set(false_abstention)),
            "false_neutral_stance_count": len(false_abstention),
            "note": "Denominator is every gold SUPPORTS or CONTRADICTS stance label; numerator is observed NEUTRAL or a missing stance.",
        },
        "semantic_mismatch_case_rate": {
            **_ratio(len(semantic_mismatch_case_ids), len(semantic_case_ids)),
            "case_ids": sorted(semantic_mismatch_case_ids),
            "eligible_case_ids": semantic_case_ids,
            "provider_error_case_ids": sorted(semantic_error_case_ids),
            "valid_abstention_case_ids": sorted(semantic_abstention_case_ids),
            "matched_case_ids": sorted(semantic_match_case_ids),
            "false_support_case_ids": false_support,
            "false_contradiction_case_ids": false_contradiction,
            "note": "Case-level metric: numerator is semantic-review cases with at least one mismatched stance; denominator is every semantic-review eligible case fixed before assessment. Provider errors and valid abstentions remain in the denominator and are reported separately, not as mismatches.",
        },
        "unverified_proposal_case_rate": {
            **_ratio(len(unverified_proposal_case_ids), status_denominator),
            "case_ids": sorted(unverified_proposal_case_ids),
            "note": "Successful eligible cases containing at least one unverified proposal; proposals are retained for review and are not accepted stance labels.",
        },
        "causal_rationale_sanitization": {
            "sanitized": bool(guarded and "caused" not in next(
                e["rationale"] for case in case_results if case["id"] == "causal-rationale-sanitized"
                for e in case.get("guard_audit", [])
            ).casefold()),
            "applicable": guarded,
            "note": "The guard replaces provider rationale with fixed text; it does not infer causality from arbitrary language.",
        },
        "deterministic_recomputation_history_consistency": recomputation,
    }
    # Seal before serialising: the record cannot be extended afterwards, and a
    # run that recorded no attempt cannot be published as a run record.
    manifest.seal()
    metrics["experiment_manifest"] = manifest.to_dict()
    return {
        "evaluation": dataset["title"],
        "semantic_guard": guarded,
        "dataset": str(DATASET_PATH),
        "case_count": len(cases),
        "labeling_note": dataset["labeling_note"],
        "metrics": metrics,
        "cases": case_results,
    }


def main() -> None:
    baseline = run_evaluation(guarded=False)
    guarded = run_evaluation(guarded=True)
    print(json.dumps({"baseline": baseline, "guarded": guarded}, indent=2))


if __name__ == "__main__":
    main()
