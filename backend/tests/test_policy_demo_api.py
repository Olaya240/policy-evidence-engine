"""Tests for the Policy Demo API (port 8083).

Uses FastAPI TestClient for offline, isolated testing.
No real network calls — all data comes from policy_evidence_demo.py.
"""
from __future__ import annotations

import ast
import asyncio
import threading
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Import the FastAPI app from the demo module
from policy_demo_api import app

client = TestClient(app)


def _create_bound_session(scenario_id: str = "scheduling"):
    scenario_response = client.get(f"/demo-api/scenario?id={scenario_id}")
    assert scenario_response.status_code == 200
    proposal = scenario_response.json()
    session_response = client.post("/demo-api/session/new", json={
        "scenario_id": scenario_id, "proposal_id": proposal["proposal_id"],
    })
    assert session_response.status_code == 200
    return proposal, session_response.json()


def _challenge_payload(proposal: dict[str, Any], session: dict[str, Any], department_id: str):
    return {
        "scenario_id": proposal["scenario_id"],
        "proposal_id": proposal["proposal_id"],
        "session_id": session["session_id"],
        "department_id": department_id,
    }


def test_health_returns_offline_demo_status() -> None:
    """GET /demo-api/health should return 200 with mode == 'offline_demo'."""
    response = client.get("/demo-api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["mode"] == "offline_demo"


def test_scenario_returns_proposal_and_invariants() -> None:
    """GET /demo-api/scenario returns COMPATIBLE_CHANGE with required invariants."""
    response = client.get("/demo-api/scenario")
    assert response.status_code == 200
    result = response.json()
    assert result["proposed_relation"] == "COMPATIBLE_CHANGE"
    assert result["status"] == "PROPOSAL_ONLY"
    assert result["semantic_support"] == "NOT_VERIFIED"
    assert result["human_review_required"] is True
    assert result["official_policy_mutated"] is False


def test_scenario_has_two_provenance_details() -> None:
    """GET /demo-api/scenario returns exactly 2 provenance_details (OLDER + NEWER)."""
    response = client.get("/demo-api/scenario")
    assert response.status_code == 200
    result = response.json()
    assert len(result["provenance_details"]) == 2
    assert len(result["proposal_id"]) == 32
    assert result["proposal_id"].islower()


def test_challenge_returns_inconclusive_with_ungrounded_dept() -> None:
    """POST /demo-api/challenge with HOUSEKEEPING returns INCONCLUSIVE + UNGROUNDED."""
    proposal, session = _create_bound_session()
    response = client.post("/demo-api/challenge", json=_challenge_payload(proposal, session, "HOUSEKEEPING"))
    assert response.status_code == 200
    result = response.json()
    assert result["recomputed_proposal"]["proposed_relation"] == "INCONCLUSIVE"
    assert result["applicability_audit"]["applicability_status"] == "UNGROUNDED"
    assert result["contract_enforcement"]["one_sided_change_rejected"] is True


def test_challenge_uses_the_immutable_displayed_proposal_snapshot() -> None:
    proposal, session = _create_bound_session()
    displayed_relation = proposal["proposed_relation"]
    proposal["proposed_relation"] = "INCONCLUSIVE"  # local client copy is not authoritative

    response = client.post(
        "/demo-api/challenge",
        json=_challenge_payload(proposal, session, "HOUSEKEEPING"),
    )
    assert response.status_code == 200
    assert response.json()["proposal_id"] == session["proposal_id"]
    history = client.get(f"/demo-api/session/{session['session_id']}/history").json()
    assert history["events"][0]["initial_relation"] == displayed_relation
    assert history["events"][0]["proposal_id"] == session["proposal_id"]


def test_challenge_recomputed_differs_from_initial() -> None:
    """After challenge, recomputed proposed_relation differs from the initial COMPATIBLE_CHANGE."""
    proposal, session = _create_bound_session()
    response = client.post("/demo-api/challenge", json=_challenge_payload(proposal, session, "HOUSEKEEPING"))
    assert response.status_code == 200
    result = response.json()
    assert result["recomputed_proposal"]["proposed_relation"] != "COMPATIBLE_CHANGE"
    assert result["recomputed_proposal"]["proposed_relation"] == "INCONCLUSIVE"


def test_challenge_preserves_human_review_invariant() -> None:
    """After challenge, human_review_required and official_policy_mutated invariants hold."""
    proposal, session = _create_bound_session()
    response = client.post("/demo-api/challenge", json=_challenge_payload(proposal, session, "HOUSEKEEPING"))
    assert response.status_code == 200
    result = response.json()
    assert result["recomputed_proposal"]["human_review_required"] is True
    assert result["recomputed_core_result"]["official_policy_mutated"] is False


def test_unsupported_department_returns_error() -> None:
    """POST /demo-api/challenge with FINANCE should return 422 (validation error)."""
    proposal, session = _create_bound_session()
    response = client.post("/demo-api/challenge", json=_challenge_payload(proposal, session, "FINANCE"))
    assert response.status_code == 422


def test_get_scenarios_returns_all_three() -> None:
    """GET /demo-api/scenarios returns all 3 allowlisted synthetic scenarios."""
    response = client.get("/demo-api/scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert len(scenarios) == 3
    ids = [s["id"] for s in scenarios]
    assert ids == ["scheduling", "uniform_grooming", "lounge_access"]
    assert scenarios[0]["relation_type"] == "COMPATIBLE_CHANGE"
    assert scenarios[1]["relation_type"] == "CONTRADICTION"
    assert scenarios[2]["relation_type"] == "SCOPE_OR_TIME_DIFFERENCE"


def test_scenario_query_param_routing() -> None:
    """GET /demo-api/scenario with id query param routes to correct scenario."""
    # Scheduling (default)
    r1 = client.get("/demo-api/scenario")
    assert r1.status_code == 200
    assert r1.json()["proposed_relation"] == "COMPATIBLE_CHANGE"

    r1_explicit = client.get("/demo-api/scenario?id=scheduling")
    assert r1_explicit.status_code == 200
    assert r1_explicit.json()["proposed_relation"] == "COMPATIBLE_CHANGE"

    # Uniform
    r2 = client.get("/demo-api/scenario?id=uniform_grooming")
    assert r2.status_code == 200
    assert r2.json()["proposed_relation"] == "CONTRADICTION"
    assert r2.json()["core_classification"] == "INCONCLUSIVE"

    # Lounge
    r3 = client.get("/demo-api/scenario?id=lounge_access")
    assert r3.status_code == 200
    assert r3.json()["proposed_relation"] == "SCOPE_OR_TIME_DIFFERENCE"
    assert r3.json()["core_classification"] == "INCONCLUSIVE"


def test_unknown_scenario_id_returns_400() -> None:
    """GET /demo-api/scenario with invalid id returns 400."""
    response = client.get("/demo-api/scenario?id=unknown_fake_scenario")
    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["error"] == "unknown_scenario"


def test_scenario_specific_challenge_handling() -> None:
    """POST /demo-api/challenge operates on the selected scenario."""
    # Uniform challenge
    uniform_proposal, uniform_session = _create_bound_session("uniform_grooming")
    u_res = client.post(
        "/demo-api/challenge",
        json=_challenge_payload(uniform_proposal, uniform_session, "CONCIERGE"),
    )
    assert u_res.status_code == 200
    data = u_res.json()
    assert data["recomputed_proposal"]["proposed_relation"] == "INCONCLUSIVE"
    assert data["applicability_audit"]["applicability_status"] == "UNGROUNDED"
    assert data["scenario_id"] == "uniform_grooming"

    # Lounge challenge
    lounge_proposal, lounge_session = _create_bound_session("lounge_access")
    l_res = client.post(
        "/demo-api/challenge",
        json=_challenge_payload(lounge_proposal, lounge_session, "VALET"),
    )
    assert l_res.status_code == 200
    data = l_res.json()
    assert data["recomputed_proposal"]["proposed_relation"] == "INCONCLUSIVE"
    assert data["applicability_audit"]["applicability_status"] == "UNGROUNDED"
    assert data["scenario_id"] == "lounge_access"


def test_session_lifecycle_and_history() -> None:
    """Session creation, initial empty history, and valid session metadata."""
    proposal, create_data = _create_bound_session()
    assert "session_id" in create_data
    assert len(create_data["session_id"]) == 32
    assert create_data["scenario_id"] == "scheduling"
    assert create_data["proposal_id"] == proposal["proposal_id"]

    session_id = create_data["session_id"]

    # History starts empty
    hist_res = client.get(f"/demo-api/session/{session_id}/history")
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert hist_data["session_id"] == session_id
    assert hist_data["scenario_id"] == "scheduling"
    assert hist_data["proposal_id"] == proposal["proposal_id"]
    assert hist_data["event_count"] == 0
    assert hist_data["events"] == []


def test_session_creation_rejects_missing_stale_and_mismatched_proposal_references() -> None:
    missing = client.post("/demo-api/session/new", json={"scenario_id": "scheduling"})
    assert missing.status_code == 422

    proposal = client.get("/demo-api/scenario?id=scheduling").json()
    stale = client.post("/demo-api/session/new", json={
        "scenario_id": "scheduling", "proposal_id": "f" * 32,
    })
    assert stale.status_code == 404
    assert stale.json()["detail"]["error"] == "proposal_not_found"

    wrong_scenario = client.post("/demo-api/session/new", json={
        "scenario_id": "uniform_grooming", "proposal_id": proposal["proposal_id"],
    })
    assert wrong_scenario.status_code == 409
    assert wrong_scenario.json()["detail"]["error"] == "proposal_scenario_mismatch"

    consumed = client.post("/demo-api/session/new", json={
        "scenario_id": "scheduling", "proposal_id": proposal["proposal_id"],
    })
    assert consumed.status_code == 200
    replay = client.post("/demo-api/session/new", json={
        "scenario_id": "scheduling", "proposal_id": proposal["proposal_id"],
    })
    assert replay.status_code == 404
    assert replay.json()["detail"]["error"] == "proposal_not_found"


def test_challenge_rejects_missing_or_different_proposal_id_without_history_mutation() -> None:
    proposal, session = _create_bound_session()
    missing = client.post("/demo-api/challenge", json={
        "scenario_id": "scheduling", "department_id": "HOUSEKEEPING",
        "session_id": session["session_id"],
    })
    assert missing.status_code == 422

    different = client.post("/demo-api/challenge", json={
        **_challenge_payload(proposal, session, "HOUSEKEEPING"),
        "proposal_id": "e" * 32,
    })
    assert different.status_code == 409
    assert different.json()["detail"]["error"] == "proposal_mismatch"
    history = client.get(f"/demo-api/session/{session['session_id']}/history").json()
    assert history["events"] == []


def test_async_challenge_worker_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_demo_api

    proposal, session = _create_bound_session()

    def fail_in_worker(*_args, **_kwargs):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        raise RuntimeError("private provider response must not escape")

    monkeypatch.setattr(policy_demo_api, "_recompute_bound_challenge", fail_in_worker)
    response = client.post(
        "/demo-api/challenge",
        json=_challenge_payload(proposal, session, "HOUSEKEEPING"),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error": "demo_unavailable",
        "detail": "Demo scenario could not be computed.",
    }
    assert "private provider response" not in response.text
    assert client.get(f"/demo-api/session/{session['session_id']}/history").json()["events"] == []


def test_consecutive_challenges_append_ordered_history() -> None:
    """Multiple challenges within a session append ordered immutable events."""
    proposal, session = _create_bound_session()
    session_id = session["session_id"]

    # Challenge #1: HOUSEKEEPING
    c1_res = client.post(
        "/demo-api/challenge",
        json=_challenge_payload(proposal, session, "HOUSEKEEPING"),
    )
    assert c1_res.status_code == 200
    c1_data = c1_res.json()
    assert c1_data["sequence_number"] == 1
    assert c1_data["history_count"] == 1

    # Challenge #2: FRONT_DESK
    c2_res = client.post(
        "/demo-api/challenge",
        json=_challenge_payload(proposal, session, "FRONT_DESK"),
    )
    assert c2_res.status_code == 200
    c2_data = c2_res.json()
    assert c2_data["sequence_number"] == 2
    assert c2_data["history_count"] == 2

    # Verify history has 2 ordered events
    hist_res = client.get(f"/demo-api/session/{session_id}/history")
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert hist_data["event_count"] == 2
    assert len(hist_data["events"]) == 2

    evt1 = hist_data["events"][0]
    evt2 = hist_data["events"][1]

    assert evt1["sequence_number"] == 1
    assert evt1["proposal_id"] == proposal["proposal_id"]
    assert evt1["initial_relation"] == proposal["proposed_relation"]
    assert evt1["target_department"] == "HOUSEKEEPING"
    assert evt1["applicability_status"] == "UNGROUNDED"
    assert evt1["recomputed_relation"] == "INCONCLUSIVE"
    assert evt1["core_classification"] == "INCONCLUSIVE"
    assert "incomplete_comparison" in evt1["uncertainty_reasons"]

    assert evt2["sequence_number"] == 2
    assert evt2["proposal_id"] == proposal["proposal_id"]
    assert evt2["target_department"] == "FRONT_DESK"
    assert evt2["applicability_status"] == "UNGROUNDED"
    assert evt2["recomputed_relation"] == "INCONCLUSIVE"


def test_challenge_count_uses_locked_history_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Challenge counts history via a detached snapshot, never mutable session.events."""
    import policy_demo_api
    from policy_demo_session import default_session_manager

    proposal, bound_session = _create_bound_session()
    session_id = bound_session["session_id"]
    real_get_session = default_session_manager.get_session
    snapshots: list[int] = []

    class SessionView:
        def __init__(self, session):
            self.session_id = session.session_id
            self.scenario_id = session.scenario_id
            self.generation = session.generation

        @property
        def events(self):
            raise AssertionError("challenge read mutable session.events")

    class ManagerView:
        def get_session(self, sid):
            return SessionView(real_get_session(sid))

        def get_bound_proposal(self, sid, scenario_id, proposal_id):
            return default_session_manager.get_bound_proposal(sid, scenario_id, proposal_id)

        def record_challenge_event_snapshot(self, **kwargs):
            snapshot = default_session_manager.record_challenge_event_snapshot(**kwargs)
            snapshots.append(snapshot.metadata.history_count)
            return snapshot

    monkeypatch.setattr(policy_demo_api, "default_session_manager", ManagerView())
    response = client.post("/demo-api/challenge", json=_challenge_payload(proposal, bound_session, "HOUSEKEEPING"))
    assert response.status_code == 200
    assert snapshots == [1]
    assert response.json()["history_count"] == snapshots[0]


def test_request_body_limit_rejects_oversized_content_length() -> None:
    import policy_demo_api
    response = client.post("/demo-api/session/new", content=b" " * (policy_demo_api.MAX_REQUEST_BYTES + 1), headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"]["error"] == "body_too_large"
    assert "policy_demo_api" not in response.text


class _ASGIReceiveOverride:
    """Wrap the in-process ASGI app with controlled headers and receive chunks."""

    def __init__(self, app, chunks: list[bytes], *, content_length: str | None = None, chunked: bool = False) -> None:
        self.app = app
        self.chunks = chunks
        self.content_length = content_length
        self.chunked = chunked
        self.receive_calls = 0

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/demo-api/session/new":
            await self.app(scope, receive, send)
            return

        controlled_scope = dict(scope)
        headers = [
            (name, value)
            for name, value in scope["headers"]
            if name.lower() not in {b"content-length", b"transfer-encoding"}
        ]
        if self.content_length is not None:
            headers.append((b"content-length", self.content_length.encode("ascii")))
        if self.chunked:
            headers.append((b"transfer-encoding", b"chunked"))
        controlled_scope["headers"] = headers
        index = 0

        async def controlled_receive():
            nonlocal index
            self.receive_calls += 1
            if index >= len(self.chunks):
                return {"type": "http.request", "body": b"", "more_body": False}
            body = self.chunks[index]
            index += 1
            return {"type": "http.request", "body": body, "more_body": index < len(self.chunks)}

        await self.app(controlled_scope, controlled_receive, send)


def _post_via_controlled_asgi_receive(api_app, chunks: list[bytes], *, content_length: str | None = None, chunked: bool = False):
    from fastapi.testclient import TestClient

    controlled_app = _ASGIReceiveOverride(api_app, chunks, content_length=content_length, chunked=chunked)
    with TestClient(controlled_app) as asgi_client:
        response = asgi_client.post("/demo-api/session/new", content=b"", headers={"content-type": "application/json"})
    return response, controlled_app


def test_asgi_boundary_rejects_oversized_declared_length_before_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_demo_api
    from types import SimpleNamespace

    parsed = []
    original_loads = policy_demo_api.json.loads
    def observe_parse(*args, **kwargs):
        parsed.append(True)
        return original_loads(*args, **kwargs)
    monkeypatch.setattr(policy_demo_api, "json", SimpleNamespace(loads=observe_parse))

    response, controlled = _post_via_controlled_asgi_receive(
        policy_demo_api.app, [], content_length=str(policy_demo_api.MAX_REQUEST_BYTES + 1),
    )

    assert response.status_code == 413
    assert response.json()["detail"]["error"] == "body_too_large"
    assert not parsed
    assert controlled.receive_calls == 0
    assert "Traceback" not in response.text and "policy_demo_api.py" not in response.text


def test_asgi_boundary_rejects_malformed_content_length_before_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_demo_api
    from types import SimpleNamespace

    parsed = []
    original_loads = policy_demo_api.json.loads
    def observe_parse(*args, **kwargs):
        parsed.append(True)
        return original_loads(*args, **kwargs)
    monkeypatch.setattr(policy_demo_api, "json", SimpleNamespace(loads=observe_parse))

    response, controlled = _post_via_controlled_asgi_receive(
        policy_demo_api.app, [b'{"scenario_id":"scheduling"}'], content_length="+12",
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_content_length"
    assert not parsed
    assert controlled.receive_calls == 0
    assert "Traceback" not in response.text and "policy_demo_api.py" not in response.text


def test_asgi_boundary_missing_length_cannot_bypass_stream_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_demo_api
    from types import SimpleNamespace

    parsed = []
    original_loads = policy_demo_api.json.loads
    def observe_parse(*args, **kwargs):
        parsed.append(True)
        return original_loads(*args, **kwargs)
    monkeypatch.setattr(policy_demo_api, "json", SimpleNamespace(loads=observe_parse))

    response, controlled = _post_via_controlled_asgi_receive(
        policy_demo_api.app, [b" " * (policy_demo_api.MAX_REQUEST_BYTES + 1)],
    )

    assert response.status_code == 413
    assert response.json()["detail"]["error"] == "body_too_large"
    assert not parsed
    assert controlled.receive_calls == 1
    assert "Traceback" not in response.text and "policy_demo_api.py" not in response.text


def test_asgi_boundary_rejects_chunked_multiple_small_chunks_by_combined_size(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_demo_api
    from types import SimpleNamespace

    parsed = []
    original_loads = policy_demo_api.json.loads
    def observe_parse(*args, **kwargs):
        parsed.append(True)
        return original_loads(*args, **kwargs)
    monkeypatch.setattr(policy_demo_api, "json", SimpleNamespace(loads=observe_parse))
    chunks = [b" " * 2048 for _ in range(17)]

    response, controlled = _post_via_controlled_asgi_receive(
        policy_demo_api.app, chunks, chunked=True,
    )

    assert response.status_code == 413
    assert response.json()["detail"]["error"] == "body_too_large"
    assert not parsed
    assert controlled.receive_calls == 17
    assert "Traceback" not in response.text and "policy_demo_api.py" not in response.text


def test_request_parser_accepts_missing_content_length_and_bounds_stream() -> None:
    import policy_demo_api

    class RequestStub:
        def __init__(self, headers, chunks):
            self.headers = headers
            self.chunks = chunks
            self.stream_started = False
        async def stream(self):
            self.stream_started = True
            for chunk in self.chunks:
                yield chunk

    req = RequestStub({"content-type": "application/json"}, [b'{"scenario_id":"scheduling","proposal_id":"' + b"a" * 32 + b'"}'])
    parsed = asyncio.run(policy_demo_api._parse_request_model(req, policy_demo_api.CreateSessionRequest))
    assert parsed.scenario_id == "scheduling"
    assert req.stream_started

    invalid_length = RequestStub({"content-type": "application/json", "content-length": "+12"}, [])
    with pytest.raises(Exception) as malformed:
        asyncio.run(policy_demo_api._parse_request_model(invalid_length, policy_demo_api.CreateSessionRequest))
    assert getattr(malformed.value, "status_code", None) == 400
    assert not invalid_length.stream_started

    streamed = RequestStub({"content-type": "application/json"}, [b" " * policy_demo_api.MAX_REQUEST_BYTES, b" "])
    with pytest.raises(Exception) as too_large:
        asyncio.run(policy_demo_api._parse_request_model(streamed, policy_demo_api.CreateSessionRequest))
    assert getattr(too_large.value, "status_code", None) == 413

    optional_reset = RequestStub({}, [])
    assert asyncio.run(policy_demo_api._parse_request_model(optional_reset, policy_demo_api.ResetSessionRequest, allow_empty=True)) is None
    untyped_stream = RequestStub({}, [b" " * policy_demo_api.MAX_REQUEST_BYTES, b" "])
    with pytest.raises(Exception) as untyped_too_large:
        asyncio.run(policy_demo_api._parse_request_model(untyped_stream, policy_demo_api.ResetSessionRequest, allow_empty=True))
    assert getattr(untyped_too_large.value, "status_code", None) == 413


def _new_bound_session(scenario_id: str = "scheduling"):
    return _create_bound_session(scenario_id)


def _run_challenge_in_thread(proposal: dict[str, Any], session: dict[str, Any], output: list[Any]) -> threading.Thread:
    def worker():
        output.append(client.post("/demo-api/challenge", json=_challenge_payload(proposal, session, "HOUSEKEEPING")))
    thread = threading.Thread(target=worker)
    thread.start()
    return thread


def test_reset_between_challenge_validation_and_record_returns_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_demo_api
    proposal, session = _new_bound_session()
    session_id = session["session_id"]
    entered, release = threading.Event(), threading.Event()
    original = policy_demo_api.recompute_investigation_after_challenge
    def paused(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(policy_demo_api, "recompute_investigation_after_challenge", paused)
    responses = []
    thread = _run_challenge_in_thread(proposal, session, responses)
    try:
        assert entered.wait(5)
        reset = client.post(f"/demo-api/session/{session_id}/reset", json={"scenario_id": "scheduling"})
        assert reset.status_code == 200
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert responses[0].status_code == 409
    assert responses[0].json()["detail"]["error"] == "session_reset"
    assert client.get(f"/demo-api/session/{session_id}/history").json()["event_count"] == 0


def test_scenario_change_during_challenge_returns_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_demo_api
    proposal, session = _new_bound_session()
    session_id = session["session_id"]
    entered, release = threading.Event(), threading.Event()
    original = policy_demo_api.recompute_investigation_after_challenge
    def paused(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(policy_demo_api, "recompute_investigation_after_challenge", paused)
    responses = []
    thread = _run_challenge_in_thread(proposal, session, responses)
    try:
        assert entered.wait(5)
        reset = client.post(f"/demo-api/session/{session_id}/reset", json={"scenario_id": "uniform_grooming"})
        assert reset.status_code == 200
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert responses[0].status_code == 422
    assert responses[0].json()["detail"]["error"] == "scenario_mismatch"


def test_concurrent_challenges_return_atomic_event_and_count_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_demo_api
    proposal, session = _new_bound_session()
    session_id = session["session_id"]
    barrier = threading.Barrier(2)
    original = policy_demo_api._recompute_bound_challenge
    def synchronized(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(policy_demo_api, "_recompute_bound_challenge", synchronized)
    responses: list[Any] = []
    threads = [_run_challenge_in_thread(proposal, session, responses) for _ in range(2)]
    for thread in threads:
        thread.join(5)
    assert all(not thread.is_alive() for thread in threads)
    assert len(responses) == 2 and all(response.status_code == 200 for response in responses)
    pairs = sorted((response.json()["sequence_number"], response.json()["history_count"]) for response in responses)
    assert pairs == [(1, 1), (2, 2)]


def test_reset_after_atomic_record_does_not_change_challenge_response_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    import policy_demo_api
    from policy_demo_session import default_session_manager
    proposal, session = _new_bound_session()
    session_id = session["session_id"]
    recorded, release = threading.Event(), threading.Event()
    original = default_session_manager.record_challenge_event_snapshot
    def paused(**kwargs):
        snapshot = original(**kwargs)
        recorded.set()
        assert release.wait(5)
        return snapshot
    monkeypatch.setattr(default_session_manager, "record_challenge_event_snapshot", paused)
    responses = []
    thread = _run_challenge_in_thread(proposal, session, responses)
    try:
        assert recorded.wait(5)
        reset = client.post(f"/demo-api/session/{session_id}/reset", json={"scenario_id": "scheduling"})
        assert reset.status_code == 200
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    result = responses[0].json()
    assert (result["sequence_number"], result["history_count"]) == (1, 1)
    assert client.get(f"/demo-api/session/{session_id}/history").json()["event_count"] == 0


def test_session_reset_clears_history() -> None:
    """POST /demo-api/session/{session_id}/reset clears history events."""
    proposal, session = _create_bound_session("uniform_grooming")
    session_id = session["session_id"]

    # Run challenge
    client.post(
        "/demo-api/challenge",
        json=_challenge_payload(proposal, session, "CONCIERGE"),
    )

    # Verify 1 event
    h1 = client.get(f"/demo-api/session/{session_id}/history").json()
    assert h1["event_count"] == 1

    # Reset
    reset_res = client.post(
        f"/demo-api/session/{session_id}/reset",
        json={"scenario_id": "uniform_grooming"},
    )
    assert reset_res.status_code == 200
    assert reset_res.json()["event_count"] == 0

    # Verify history is now empty
    h2 = client.get(f"/demo-api/session/{session_id}/history").json()
    assert h2["event_count"] == 0
    assert h2["events"] == []


def test_invalid_reset_scenario_is_rejected_without_clearing_history() -> None:
    proposal, session = _new_bound_session()
    session_id = session["session_id"]
    challenge = client.post("/demo-api/challenge", json=_challenge_payload(proposal, session, "HOUSEKEEPING"))
    assert challenge.status_code == 200
    response = client.post(f"/demo-api/session/{session_id}/reset", json={"scenario_id": "unknown"})
    assert response.status_code == 422
    assert client.get(f"/demo-api/session/{session_id}/history").json()["event_count"] == 1


def test_session_isolation_rejects_scenario_mismatch() -> None:
    """A session created for uniform_grooming rejects scheduling challenges with 422."""
    uniform_proposal, uniform_session = _create_bound_session("uniform_grooming")
    scheduling_proposal = client.get("/demo-api/scenario?id=scheduling").json()

    mismatch_res = client.post(
        "/demo-api/challenge",
        json={
            **_challenge_payload(scheduling_proposal, uniform_session, "HOUSEKEEPING"),
            "scenario_id": "scheduling",
        },
    )
    assert mismatch_res.status_code == 422
    assert mismatch_res.json()["detail"]["error"] == "scenario_mismatch"


def test_session_invalid_id_returns_400() -> None:
    """Invalid session_id format returns 400."""
    res = client.get("/demo-api/session/short_id/history")
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "invalid_session_id"


def test_session_not_found_returns_404() -> None:
    """Non-existent 32-hex session_id returns 404."""
    res = client.get("/demo-api/session/0123456789abcdef0123456789abcdef/history")
    assert res.status_code == 404
    assert res.json()["detail"]["error"] == "session_not_found"


def test_bounded_history_eviction() -> None:
    """InMemoryDemoSessionManager evicts oldest events beyond max_events."""
    from policy_demo_session import InMemoryDemoSessionManager

    mgr = InMemoryDemoSessionManager(max_sessions=5, max_events=3)
    session = mgr.create_session("scheduling")
    sid = session.session_id

    for i in range(5):
        mgr.record_challenge_event(
            session_id=sid,
            scenario_id="scheduling",
            target_department=f"DEPT_{i}",
            target_side="OLDER",
            applicability_status="UNGROUNDED",
            initial_relation="COMPATIBLE_CHANGE",
            recomputed_relation="INCONCLUSIVE",
            core_classification="INCONCLUSIVE",
            uncertainty_reasons=["REASON_1"],
            contract_enforced=True,
            summary=f"Event {i}",
        )

    history = mgr.get_history_snapshot(sid)
    assert len(history) == 3
    # FIFO: first 2 evicted, remaining should have target_department DEPT_2, DEPT_3, DEPT_4
    assert [e.target_department for e in history] == ["DEPT_2", "DEPT_3", "DEPT_4"]
    assert [e.sequence_number for e in history] == [3, 4, 5]


def test_challenge_mismatched_department_returns_422() -> None:
    """POST /demo-api/challenge with mismatched department for scenario returns 422."""
    proposal, session = _create_bound_session("uniform_grooming")
    response = client.post(
        "/demo-api/challenge",
        json=_challenge_payload(proposal, session, "HOUSEKEEPING"),
    )
    assert response.status_code == 422
    assert "does not match expected challenge target" in str(response.json())


def test_challenge_unknown_scenario_returns_422() -> None:
    """POST /demo-api/challenge with unknown scenario returns 422 validation error."""
    response = client.post(
        "/demo-api/challenge",
        json={"scenario_id": "invalid_scenario_id", "department_id": "HOUSEKEEPING"},
    )
    assert response.status_code == 422


def test_demo_api_does_not_import_or_activate_active_policy_api() -> None:
    """AST inspection: policy_demo_api.py must not import policy_api module."""
    demo_api_path = Path(__file__).parent.parent / "policy_demo_api.py"
    source = demo_api_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_modules = {"policy_api"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_modules, (
                    f"policy_demo_api.py must not import '{alias.name}'"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module in forbidden_modules:
                pytest.fail(
                    f"policy_demo_api.py must not import from '{node.module}'"
                )
