"""Offline tests for the dedicated database-free policy API."""
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import policy_api
from policy_candidate_adapter import FakePolicyCandidateAdapter
from policy_orchestration import orchestrate_policy_comparison


def _version(version_id: str, text: str) -> dict:
    from hashlib import sha256

    first = text.split("\n\n")[0]
    passage_id = f"p000001-{sha256(first.encode('utf-8')).hexdigest()[:16]}"
    return {
        "document_id": "syn-policy-handover",
        "version_id": version_id,
        "original_text": text,
        "effective_from": "2026-01-01",
        "effective_to_exclusive": "2027-01-01",
        "scope": {
            "departments": {"state": "KNOWN", "ids": ["FRONT_OFFICE"]},
            "procedures": {"state": "UNKNOWN", "ids": []},
            "property_id": None,
            "evidence_passage_ids": [passage_id],
        },
        "text_coverage": "EXCERPT",
        "impact_dependencies": [],
    }


def _pair() -> dict:
    return {
        "schema_version": 1,
        "comparison_id": "cmp-syn-api-001",
        "older": _version("v1", "Record requests before shift end.\n\nKeep the log complete."),
        "newer": _version("v2", "Record requests at shift start.\n\nKeep the log complete."),
    }


@pytest.fixture
def client():
    return TestClient(policy_api.app)


def test_health_has_no_policy_or_database_work(monkeypatch, client):
    def forbidden(*_args, **_kwargs):
        pytest.fail("health must not invoke policy comparison")

    monkeypatch.setattr(policy_api, "validate_policy_pair", forbidden)
    monkeypatch.setattr(policy_api, "orchestrate_policy_comparison", forbidden)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "mode": "offline_fixture"}


def test_valid_synthetic_pair_uses_real_orchestration_and_fixture_adapter(monkeypatch, client):
    calls = []

    def observe(pair_input, adapter):
        calls.append((pair_input["comparison_id"], type(adapter)))
        assert type(adapter) is FakePolicyCandidateAdapter
        return orchestrate_policy_comparison(pair_input, adapter)

    monkeypatch.setattr(policy_api, "orchestrate_policy_comparison", observe)
    response = client.post("/policy-comparisons", json=_pair())
    assert response.status_code == 200
    assert calls == [("cmp-syn-api-001", FakePolicyCandidateAdapter)]
    body = response.json()
    assert body["comparison_id"] == "cmp-syn-api-001"
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["classification"] == "INCONCLUSIVE"
    assert result["proposed_classification"] == "INCONCLUSIVE"
    assert result["human_review_required"] is True
    assert result["official_policy_mutated"] is False
    assert result["proposal_status"] == "PROPOSAL_ONLY"
    assert result["proposal_semantic_support"] == "NOT_VERIFIED"
    assert {item["role"] for item in result["citations"]} == {"OLDER", "NEWER"}


@pytest.mark.parametrize("body", [b"{broken", b'{"schema_version":1,"schema_version":1}'])
def test_malformed_or_duplicate_key_json_is_rejected(client, body):
    response = client.post(
        "/policy-comparisons", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": "malformed_json",
        "detail": "Request body is not valid JSON.",
    }


def test_oversized_body_is_rejected(client):
    body = b" " * (policy_api.MAX_REQUEST_BYTES + 1)
    response = client.post(
        "/policy-comparisons", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"] == "body_too_large"


def test_oversized_stream_without_content_length_is_rejected(client):
    def body_chunks():
        yield b" " * (policy_api.MAX_REQUEST_BYTES // 2)
        yield b" " * (policy_api.MAX_REQUEST_BYTES // 2 + 1)

    response = client.post(
        "/policy-comparisons",
        content=body_chunks(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"] == "body_too_large"


def test_invalid_policy_and_unsupported_fields_are_sanitized(client):
    invalid = _pair()
    invalid["schema_version"] = True
    response = client.post("/policy-comparisons", json=invalid)
    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_input",
        "detail": "Policy comparison input is invalid.",
    }

    unsupported = _pair()
    unsupported["provider"] = {"mode": "real", "key": "synthetic-canary"}
    response = client.post("/policy-comparisons", json=unsupported)
    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_input",
        "detail": "Policy comparison input is invalid.",
    }
    assert "synthetic-canary" not in response.text


def test_unexpected_orchestration_error_has_fixed_response(monkeypatch, client):
    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic-private-exception-detail")

    monkeypatch.setattr(policy_api, "orchestrate_policy_comparison", fail)
    response = client.post("/policy-comparisons", json=_pair())
    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "detail": "Policy comparison could not be completed.",
    }
    assert "synthetic-private-exception-detail" not in response.text


def test_module_imports_no_handover_database_or_provider_code():
    source = Path(policy_api.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    forbidden = ("app", "sqlite3", "store", "mock_provider", "provider_safety", "httpx", "requests")
    assert not any(name == prefix or name.startswith(prefix + ".") for name in imported for prefix in forbidden)
    forbidden_calls = {"open", "connect", "execute", "commit", "write_text", "write_bytes"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func.id if isinstance(node.func, ast.Name) else (
            node.func.attr if isinstance(node.func, ast.Attribute) else ""
        )
        assert called not in forbidden_calls


def test_server_entrypoint_uses_fixed_loopback_and_port(monkeypatch):
    observed = {}

    def run(app, **kwargs):
        observed["app"] = app
        observed.update(kwargs)

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))
    policy_api.main()
    assert observed == {
        "app": policy_api.app,
        "host": "127.0.0.1",
        "port": 8082,
        "reload": False,
    }


def test_cors_allows_only_the_exact_vite_origin_without_credentials(client):
    allowed = client.options(
        "/policy-comparisons",
        headers={
            "origin": "http://127.0.0.1:5174",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"
    assert "access-control-allow-credentials" not in allowed.headers
    assert "*" not in allowed.headers["access-control-allow-origin"]

    denied = client.get("/health", headers={"origin": "http://localhost:5174"})
    assert denied.status_code == 200
    assert "access-control-allow-origin" not in denied.headers


def test_non_json_content_type_is_rejected(client):
    response = client.post("/policy-comparisons", content="{}", headers={"content-type": "text/plain"})
    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_media_type"
