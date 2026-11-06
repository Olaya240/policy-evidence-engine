"""Direct, offline tests for the non-initializing provider status route."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import policy_demo_api


def _request(peer="127.0.0.1", headers=()):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/demo-api/provider-status",
        "raw_path": b"/demo-api/provider-status",
        "query_string": b"",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
        "client": (peer, 43210),
        "server": ("127.0.0.1", 8083),
    }
    return Request(scope)


def _reset_provider_state(monkeypatch, *, initialized=False, provider=None, failure=None):
    monkeypatch.setattr(policy_demo_api, "_policy_provider_initialized", initialized)
    monkeypatch.setattr(policy_demo_api, "_policy_provider", provider)
    monkeypatch.setattr(policy_demo_api, "_policy_provider_failure_code", failure)


def _fail_if_built(*_args, **_kwargs):
    raise AssertionError("provider status must not construct a provider")


def test_meta_configured_but_uninitialized_reports_pinned_model_and_zero_attempts(monkeypatch):
    _reset_provider_state(monkeypatch)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")
    monkeypatch.setattr(policy_demo_api, "build_policy_provider_from_environment", _fail_if_built)

    status = policy_demo_api.provider_status(_request())

    assert status == {
        "configured_provider": "meta",
        "provider_id": None,
        "model_id": "muse-spark-1.3",
        "provider_state": "not_initialized",
        "authorized_request_attempts": 0,
        "counter_semantics": "budget reservations before transport; not confirmed HTTP deliveries",
    }
    assert policy_demo_api._policy_provider_initialized is False


def test_synthetic_is_reported_as_default_without_provider_initialization(monkeypatch):
    _reset_provider_state(monkeypatch)
    monkeypatch.delenv("POLICY_DEMO_PROVIDER", raising=False)
    monkeypatch.setattr(policy_demo_api, "build_policy_provider_from_environment", _fail_if_built)

    status = policy_demo_api.provider_status(_request())

    assert status["configured_provider"] == "synthetic"
    assert status["provider_id"] is None
    assert status["model_id"] is None
    assert status["provider_state"] == "not_initialized"
    assert status["authorized_request_attempts"] == 0
    assert policy_demo_api._policy_provider_initialized is False


def test_initialized_mock_meta_provider_reports_identity_and_gate_attempts(monkeypatch):
    provider = SimpleNamespace(
        provider_id="meta",
        model_id="muse-spark-1.3",
        _gate=SimpleNamespace(request_count=2),
    )
    _reset_provider_state(monkeypatch, initialized=True, provider=provider)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")
    monkeypatch.setattr(policy_demo_api, "build_policy_provider_from_environment", _fail_if_built)

    status = policy_demo_api.provider_status(_request())

    assert status["provider_id"] == "meta"
    assert status["model_id"] == "muse-spark-1.3"
    assert status["provider_state"] == "ready"
    assert status["authorized_request_attempts"] == 2


@pytest.mark.parametrize("provider", [
    SimpleNamespace(provider_id="unexpected", model_id="muse-spark-1.3",
                    _gate=SimpleNamespace(request_count=0)),
    SimpleNamespace(provider_id="meta", model_id="unexpected-model",
                    _gate=SimpleNamespace(request_count=0)),
    SimpleNamespace(provider_id="meta", model_id="muse-spark-1.3", _gate=SimpleNamespace()),
    SimpleNamespace(provider_id="meta", model_id="muse-spark-1.3",
                    _gate=SimpleNamespace(request_count=-1)),
])
def test_unexpected_identity_model_or_counter_never_reports_ready(monkeypatch, provider):
    _reset_provider_state(monkeypatch, initialized=True, provider=provider)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")
    monkeypatch.setattr(policy_demo_api, "build_policy_provider_from_environment", _fail_if_built)

    status = policy_demo_api.provider_status(_request())

    assert status["provider_state"] == "unknown"
    assert status["provider_state"] != "ready"


def test_forwarded_headers_cannot_change_loopback_peer_decision(monkeypatch):
    _reset_provider_state(monkeypatch)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")
    monkeypatch.setattr(policy_demo_api, "build_policy_provider_from_environment", _fail_if_built)

    # An external forwarded address does not invalidate a direct loopback peer.
    status = policy_demo_api.provider_status(_request(
        "127.0.0.1", headers=(("x-forwarded-for", "203.0.113.9"),),
    ))
    assert status["provider_state"] == "not_initialized"

    # A forwarded loopback value cannot make a non-loopback peer pass.
    with pytest.raises(HTTPException) as caught:
        policy_demo_api.provider_status(_request(
            "203.0.113.9", headers=(("x-forwarded-for", "127.0.0.1"),),
        ))
    assert caught.value.status_code == 403


def test_backend_startup_disables_proxy_header_rewriting_and_stays_loopback(monkeypatch):
    calls = []
    monkeypatch.setattr(policy_demo_api.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    policy_demo_api.main()

    assert len(calls) == 1
    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 8083
    assert calls[0][1]["proxy_headers"] is False
    assert calls[0][1]["reload"] is False


def test_initialization_failure_is_sanitized(monkeypatch):
    _reset_provider_state(monkeypatch, initialized=True, failure="provider_unavailable")
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")

    status = policy_demo_api.provider_status(_request())

    assert status["configured_provider"] == "meta"
    assert status["provider_id"] is None
    assert status["model_id"] == "muse-spark-1.3"
    assert status["provider_state"] == "unavailable"
    assert status["authorized_request_attempts"] == 0
    assert "provider_unavailable" not in repr(status)


def test_repeated_status_calls_do_not_initialize_or_mutate_provider_state(monkeypatch):
    _reset_provider_state(monkeypatch)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")
    monkeypatch.setattr(policy_demo_api, "build_policy_provider_from_environment", _fail_if_built)

    first = policy_demo_api.provider_status(_request())
    second = policy_demo_api.provider_status(_request())

    assert first == second
    assert policy_demo_api._policy_provider_initialized is False
    assert policy_demo_api._policy_provider is None


def test_non_loopback_peer_is_rejected_without_provider_work(monkeypatch):
    _reset_provider_state(monkeypatch)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")
    monkeypatch.setattr(policy_demo_api, "build_policy_provider_from_environment", _fail_if_built)

    with pytest.raises(HTTPException) as caught:
        policy_demo_api.provider_status(_request("192.0.2.44"))

    assert caught.value.status_code == 403
    assert caught.value.detail == {"error": "loopback_only"}
    assert policy_demo_api._policy_provider_initialized is False


def test_response_never_contains_secret_or_request_policy_content(monkeypatch):
    _reset_provider_state(monkeypatch)
    monkeypatch.setenv("POLICY_DEMO_PROVIDER", "meta")
    monkeypatch.setenv("MODEL_API_KEY", "test-only-secret-sentinel")
    monkeypatch.setenv("POLICY_TEXT_SENTINEL", "fictional policy request content")
    monkeypatch.setattr(policy_demo_api, "build_policy_provider_from_environment", _fail_if_built)

    status = policy_demo_api.provider_status(_request())
    serialized = repr(status)

    assert "test-only-secret-sentinel" not in serialized
    assert "fictional policy request content" not in serialized
    assert "MODEL_API_KEY" not in serialized
    assert policy_demo_api._policy_provider_initialized is False

