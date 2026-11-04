"""Offline, synthetic tests for attribution capture and persistence."""
import json
import sqlite3
import tempfile
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app import main, store
from app.engine import AssessmentEngine, ProviderError
from app.mock_provider import MockProvider, SEED_RECORDS
from app.models import Claim
from app.provider_activation import create_meta_assessment_engine
from app.provider_safety import (BasetenMuseSparkOpenAdapter, BoundedTransportProvider,
    MetaMuseSparkAdapter, ProviderBudgetConfig)


def test_mock_provider_identity_is_captured_from_invoked_instance():
    claim = AssessmentEngine(MockProvider()).assess_hypothesis(SEED_RECORDS, "TIME_PRESSURE")
    assert claim["provider_attribution"] == {"provider": "mock", "model": None,
        "request_id": None, "usage": None}


def test_unidentified_provider_identity_resolves_to_unknown():
    assert BoundedTransportProvider.PROVIDER_ID == "unknown"
    legacy = Claim.model_validate({
        "id": "TIME_PRESSURE", "hypothesis_id": "TIME_PRESSURE", "status": "INSUFFICIENT",
        "confidence": 0.0, "uncertainty": "legacy", "summary": "legacy", "evidence": [],
        "conflicts": [], "missing_evidence": [], "dependencies": [], "version": 1,
    })
    assert legacy.provider_attribution.provider == "unknown"


def test_meta_provider_identity_is_captured_after_offline_success(monkeypatch):
    record = SEED_RECORDS[0]
    proposal = {"source_record_id": record.id, "quote": record.text[:40],
                "stance": "NEUTRAL", "rationale": "Synthetic attribution test."}
    body = json.dumps({"id": "synthetic-request", "object": "chat.completion", "created": 1,
        "model": MetaMuseSparkAdapter.MODEL_ID, "choices": [{"index": 0,
        "message": {"role": "assistant", "content": json.dumps([proposal])}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield body
        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(
        lambda request: httpx.Response(200, stream=Stream())))
    engine = create_meta_assessment_engine(
        key_source=lambda: "SYNTHETIC_TEST_KEY",
        budget_config=ProviderBudgetConfig(enabled=True, max_requests=1,
            max_estimated_cost_usd=Decimal("0.10"),
            conservative_cost_per_request_usd=Decimal("0.10")),
    )
    claim = engine.assess_hypothesis([record], "TIME_PRESSURE")
    assert claim["provider_attribution"] == {"provider": "meta", "model": "muse-spark-1.3",
        "request_id": "synthetic-request", "usage": {"prompt_tokens": 1,
        "completion_tokens": 1, "total_tokens": 2}}
    assert "SYNTHETIC_TEST_KEY" not in json.dumps(claim)


def test_baseten_identity_is_stable_and_conflicting_activation_stays_mock():
    assert BasetenMuseSparkOpenAdapter.PROVIDER_ID == "baseten"
    env = {"ENABLE_META": "1", "MODEL_API_KEY": "SYNTHETIC_TEST_KEY",
        "META_MAX_REQUESTS": "1", "META_MAX_ESTIMATED_COST_USD": "0.10",
        "META_CONSERVATIVE_COST_PER_REQUEST_USD": "0.10", "ENABLE_BASETEN": "1"}
    assert type(main.build_engine_from_environment(env).provider) is MockProvider


def test_provider_failure_does_not_return_successful_assessment(monkeypatch):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{}"
        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(
        lambda request: httpx.Response(500, stream=Stream())))
    engine = create_meta_assessment_engine(
        key_source=lambda: "SYNTHETIC_TEST_KEY",
        budget_config=ProviderBudgetConfig(enabled=True, max_requests=1,
            max_estimated_cost_usd=Decimal("0.10"),
            conservative_cost_per_request_usd=Decimal("0.10")),
    )
    with pytest.raises(ProviderError):
        engine.assess_hypothesis([SEED_RECORDS[0]], "TIME_PRESSURE")


def test_attribution_is_persisted_and_legacy_snapshot_stays_unknown(monkeypatch):
    with tempfile.TemporaryDirectory(prefix=".tmp-provider-attribution-", dir=Path.cwd()) as temporary:
        data_dir = Path(temporary)
        monkeypatch.setattr(store, "DATA_DIR", data_dir)
        db_path = data_dir / "attribution-test.sqlite3"
        monkeypatch.setenv("HACKATHON_DB_PATH", str(db_path))
        store.initialize_database()
        claim = AssessmentEngine(MockProvider()).assess_hypothesis(SEED_RECORDS, "TIME_PRESSURE")
        created = store.create_investigation("Synthetic provider attribution test", [claim])
        loaded = store.get_investigation(created["id"])
        assert loaded["claims"][0]["provider_attribution"]["provider"] == "mock"

        db = sqlite3.connect(db_path)
        try:
            row = db.execute("SELECT claim_json FROM claim_versions").fetchone()
        finally:
            db.close()
        stored = json.loads(row[0])
        stored.pop("provider_attribution")
        assert Claim.model_validate(stored).provider_attribution.provider == "unknown"
