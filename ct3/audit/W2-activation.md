# W2 — provider activation wiring

Worker 2 of 10. Files owned: `backend/app/provider_activation.py`, `backend/app/main.py`, new `backend/tests/test_activation_wiring.py`.

## What changed

- `main.py` now builds the process engine through `create_assessment_engine`, replacing `engine = AssessmentEngine()` (the direct constructor was the only engine construction in the module and the reason the factory had no caller).
- `build_engine_from_environment(environ)` is the explicit, default-off activation path: mock unless `ENABLE_BASETEN` names an affirmative literal AND `BASETEN_API_KEY` is present AND all three budget inputs are supplied. A refused or failed activation returns the mock and logs the reason; nothing escapes, so a half-built engine cannot be swapped in.
- A key present without the flag logs that it is being ignored instead of disappearing silently.
- `provider_activation.py` is unchanged. Its pins hold: exactly three keyword-only parameters, no environment or secret-store lookup in the module, one `BASETEN_API_KEY` literal. The environment read lives in the composition root, so the previously asserted "no environment path enables a provider" is now deliberately false at the app level — that is the defect being fixed.
- `MandatoryProviderBoundary` binding intact: both the mock default and the activated adapter come from the factory, so `engine.provider_boundary._provider` and `adapter._transport._boundary` are the same boundary object (asserted in the tests).

## Verbatim test output

```
$ cd backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q \
    tests/test_activation_wiring.py tests/test_provider_activation_slice20.py \
    tests/test_api.py tests/test_manifest_and_routes.py
........................................................................ [ 52%]
............F...................................................         [100%]
=================================== FAILURES ===================================
_ test_manifest_can_be_rewritten_after_construction_because_attempts_is_a_plain_list _

    def test_manifest_can_be_rewritten_after_construction_because_attempts_is_a_plain_list():
        manifest = ExperimentRunManifest(**_manifest_kwargs())
        manifest.add_attempt(AttemptMetadata(case_id="case-1", request_count=1))
    
        manifest.attempts = [AttemptMetadata(case_id="injected-after-the-fact", request_count=5)]
    
>       data = manifest.to_dict()
               ^^^^^^^^^^^^^^^^^^

tests/test_manifest_and_routes.py:210: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = ExperimentRunManifest(run_id='run-0001', dataset_sha256='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa...jected-after-the-fact', request_count=5, latency_ms=None, input_tokens=None, output_tokens=None, error_category=None)])

    def to_dict(self) -> dict[str, Any]:
        # Explicit fields prevent accidental inclusion of prompts, proposals, or record text.
        self._validate()
        if type(self.attempts) is not list or any(type(item) is not AttemptMetadata for item in self.attempts):
            raise ValueError("Invalid attempt metadata")
        for attempt in self.attempts:
            attempt._validate()
        if self._attempts_sha256 is None or self._fingerprint_attempts() != self._attempts_sha256:
>           raise ValueError("Manifest attempts were modified outside add_attempt")
E           ValueError: Manifest attempts were modified outside add_attempt

app/experiment_manifest.py:228: ValueError
=========================== short test summary info ============================
FAILED tests/test_manifest_and_routes.py::test_manifest_can_be_rewritten_after_construction_because_attempts_is_a_plain_list
1 failed, 135 passed in 7.64s
```

## Diff — backend/app/main.py (this worker's hunks only)

The working tree carried pre-existing edits to this file before this worker started; `git diff` includes them. Only the hunks below are from this worker. `provider_activation.py` has no diff.

```diff
diff --git a/backend/app/main.py b/backend/app/main.py
index e71b635..7dbbac5 100644
--- a/backend/app/main.py
+++ b/backend/app/main.py
@@ -1,4 +1,7 @@
 """FastAPI local API. Does not initialize the database or make network calls."""
+import logging
+import os
+from collections.abc import Mapping
 from copy import deepcopy
 
 from fastapi import FastAPI, HTTPException
@@ -11,13 +14,112 @@ from .models import (ChallengeCreate, HistoryEntry, Investigation,
                      InvestigationCreate, InvestigationPreset,
                      INVESTIGATION_PRESET_HYPOTHESES,
                      INVESTIGATION_PRESET_QUESTIONS, Record)
+from .provider_activation import (BASETEN_API_KEY_ENV_VAR,
+                                 ProviderActivationError,
+                                 create_assessment_engine)
+from .provider_safety import ProviderBudgetConfig
 from . import store
 
+logger = logging.getLogger(__name__)
+
+# Activation is opt-in through the environment and default-off. The flag is
+# necessary but never sufficient: the key and every budget input must also be
+# supplied, so no credential or misconfiguration can switch the network
+# provider on by itself.
+ACTIVATE_BASETEN_ENV_VAR = "ENABLE_BASETEN"
+BASETEN_MAX_REQUESTS_ENV_VAR = "BASETEN_MAX_REQUESTS"
+BASETEN_MAX_ESTIMATED_COST_ENV_VAR = "BASETEN_MAX_ESTIMATED_COST_USD"
+BASETEN_CONSERVATIVE_COST_ENV_VAR = "BASETEN_CONSERVATIVE_COST_PER_REQUEST_USD"
+_ACTIVATION_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})
+_ACTIVATION_DISABLED_VALUES = frozenset({"", "0", "false", "no", "off"})
+
+
+def _activation_requested(environ: Mapping[str, str]) -> bool:
+    """Read the flag as an explicit literal; an unrecognised value is off."""
+    raw = environ.get(ACTIVATE_BASETEN_ENV_VAR)
+    if raw is None:
+        return False
+    value = raw.strip().lower()
+    if value in _ACTIVATION_ENABLED_VALUES:
+        return True
+    if value in _ACTIVATION_DISABLED_VALUES:
+        return False
+    logger.warning(
+        "%s is not a recognised activation value; serving the mock provider. "
+        "Set it to one of %s to request Baseten activation.",
+        ACTIVATE_BASETEN_ENV_VAR, sorted(_ACTIVATION_ENABLED_VALUES))
+    return False
+
+
+def _budget_from_environment(environ: Mapping[str, str]) -> ProviderBudgetConfig | None:
+    """Return the explicit budget, or None when any of its inputs is absent or malformed."""
+    max_requests = environ.get(BASETEN_MAX_REQUESTS_ENV_VAR)
+    ceiling = environ.get(BASETEN_MAX_ESTIMATED_COST_ENV_VAR)
+    per_request = environ.get(BASETEN_CONSERVATIVE_COST_ENV_VAR)
+    if not max_requests or not ceiling or not per_request:
+        return None
+    try:
+        parsed_requests = int(max_requests)
+    except (TypeError, ValueError):
+        return None
+    return ProviderBudgetConfig(
+        enabled=True,
+        max_requests=parsed_requests,
+        max_estimated_cost_usd=ceiling,
+        conservative_cost_per_request_usd=per_request,
+    )
+
+
+def _environment_key_source(environ: Mapping[str, str]):
+    """Hand the factory a callable instead of the secret, read only after validation."""
+    def key_source():
+        return environ[BASETEN_API_KEY_ENV_VAR]
+
+    return key_source
+
+
+def build_engine_from_environment(environ: Mapping[str, str]) -> AssessmentEngine:
+    """Compose the process engine: mock by default, Baseten only on explicit request.
+
+    The mock provider is the only default that needs no credentials. Baseten is
+    activated only when the flag names an affirmative literal, a key is present
+    in `BASETEN_API_KEY`, and the three budget inputs are supplied. No refusal or
+    failure escapes this function: the mock provider is returned and the reason
+    is logged, so activation can never happen by accident.
+    """
+    if not _activation_requested(environ):
+        if environ.get(BASETEN_API_KEY_ENV_VAR):
+            logger.warning(
+                "%s is set but %s is not enabled; serving the mock provider and "
+                "ignoring the key. Set %s=1 to request Baseten activation.",
+                BASETEN_API_KEY_ENV_VAR, ACTIVATE_BASETEN_ENV_VAR,
+                ACTIVATE_BASETEN_ENV_VAR)
+        return create_assessment_engine()
+
+    key_source = None
+    if environ.get(BASETEN_API_KEY_ENV_VAR):
+        key_source = _environment_key_source(environ)
+    try:
+        return create_assessment_engine(
+            activate_baseten=True,
+            key_source=key_source,
+            budget_config=_budget_from_environment(environ),
+        )
+    except ProviderActivationError as error:
+        logger.warning(
+            "Baseten provider activation was refused (%s); serving the mock provider.",
+            error.code)
+    except Exception:  # the composition root must never fail to start
+        logger.warning(
+            "Baseten provider activation failed unexpectedly; serving the mock provider.")
+    return create_assessment_engine()
+
+
 app = FastAPI(title="Story Connect Handover Investigation Prototype", version="0.1.0",
               description="Synthetic local decision support. Findings require human review; this is not production software.")
 app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
                    allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
-engine = AssessmentEngine()
+engine = build_engine_from_environment(os.environ)
 
 
 @app.exception_handler(store.DatabaseUnavailable)
```

## Diff — backend/tests/test_activation_wiring.py (new file)

```diff
diff --git a/backend/tests/test_activation_wiring.py b/backend/tests/test_activation_wiring.py
new file mode 100644
index 0000000..65e160d
--- /dev/null
+++ b/backend/tests/test_activation_wiring.py
@@ -0,0 +1,203 @@
+"""Wiring tests: `app.main` builds its engine through the activation factory.
+
+The seam in `app.provider_activation` only matters if something calls it. These
+tests cover the composition root in `app.main`:
+
+1. The default is the mock provider, wrapped by the mandatory boundary, and no
+   configuration is required to keep it that way.
+2. A requested activation that is missing its key is refused — the process keeps
+   the mock and says why, instead of silently ignoring the request.
+3. Any activation failure leaves the mock provider in place.
+4. The explicit flag *and* a key *and* a budget do reach the live adapter, still
+   behind `MandatoryProviderBoundary`, so the wiring is a path and not a decoy.
+"""
+import logging
+import pathlib
+
+from app import main as main_module
+from app import provider_activation as activation
+from app.mock_provider import MockProvider
+from app.provider_activation import ProviderActivationError
+from app.provider_safety import (
+    BasetenMuseSparkOpenAdapter,
+    MandatoryProviderBoundary,
+    ProviderSafetyError,
+)
+
+_SYNTHETIC_KEY = "SYNTHETIC_WIRING_KEY_NEVER_REAL"
+_MAIN_SOURCE = pathlib.Path(main_module.__file__).read_text(encoding="utf-8")
+
+
+def _activated_environ(**overrides):
+    environ = {
+        main_module.ACTIVATE_BASETEN_ENV_VAR: "1",
+        main_module.BASETEN_API_KEY_ENV_VAR: _SYNTHETIC_KEY,
+        main_module.BASETEN_MAX_REQUESTS_ENV_VAR: "1",
+        main_module.BASETEN_MAX_ESTIMATED_COST_ENV_VAR: "0.10",
+        main_module.BASETEN_CONSERVATIVE_COST_ENV_VAR: "0.10",
+    }
+    environ.update(overrides)
+    return environ
+
+
+def _assert_bound_mock(engine) -> None:
+    assert type(engine.provider) is MockProvider
+    assert type(engine.provider_boundary) is MandatoryProviderBoundary
+    assert engine.provider_boundary._provider is engine.provider
+    assert not hasattr(engine.provider, "_transport")
+
+
+class _SealedKeyMapping(dict):
+    """A mapping whose key value cannot be fetched, so only presence is observable."""
+
+    def __getitem__(self, key):
+        if key == main_module.BASETEN_API_KEY_ENV_VAR:
+            raise AssertionError("the key value was read on the inactive path")
+        return super().__getitem__(key)
+
+
+def test_default_environment_builds_a_bound_mock_engine(caplog):
+    caplog.set_level(logging.DEBUG)
+
+    engine = main_module.build_engine_from_environment({})
+
+    _assert_bound_mock(engine)
+    assert [r for r in caplog.records if r.name == "app.main"] == []
+
+
+def test_process_engine_defaults_to_the_mock_reached_through_the_factory():
+    engine = main_module.engine
+    _assert_bound_mock(engine)
+    # The defect was a direct constructor call here: one caller of the factory
+    # replaces it, and nothing else in the module builds an engine by hand.
+    assert "engine = build_engine_from_environment(os.environ)" in _MAIN_SOURCE
+    assert "AssessmentEngine()" not in _MAIN_SOURCE
+
+
+def test_flag_without_key_is_refused_and_keeps_the_mock(monkeypatch, caplog):
+    seen = {}
+    real_factory = main_module.create_assessment_engine
+
+    def recording_factory(**kwargs):
+        seen.update(kwargs)
+        return real_factory(**kwargs)
+
+    monkeypatch.setattr(main_module, "create_assessment_engine", recording_factory)
+    caplog.set_level(logging.WARNING)
+    environ = _activated_environ()
+    del environ[main_module.BASETEN_API_KEY_ENV_VAR]
+
+    engine = main_module.build_engine_from_environment(environ)
+
+    _assert_bound_mock(engine)
+    # Activation was requested, so the refusal is the factory's, not a silently
+    # skipped branch.
+    assert seen["activate_baseten"] is True
+    assert seen["key_source"] is None
+    assert any("key_source_required" in r.getMessage() for r in caplog.records)
+
+
+def test_key_without_flag_is_reported_and_never_fetched(caplog):
+    caplog.set_level(logging.WARNING)
+    environ = _SealedKeyMapping(_activated_environ())
+    del environ[main_module.ACTIVATE_BASETEN_ENV_VAR]
+
+    engine = main_module.build_engine_from_environment(environ)
+
+    _assert_bound_mock(engine)
+    messages = [r.getMessage() for r in caplog.records]
+    assert any("ENABLE_BASETEN is not enabled" in message for message in messages)
+    assert all(_SYNTHETIC_KEY not in message for message in messages)
+
+
+def test_unrecognised_flag_value_stays_off(caplog):
+    caplog.set_level(logging.WARNING)
+    environ = _activated_environ(**{main_module.ACTIVATE_BASETEN_ENV_VAR: "maybe"})
+
+    engine = main_module.build_engine_from_environment(environ)
+
+    _assert_bound_mock(engine)
+    assert any(
+        "not a recognised activation value" in record.getMessage()
+        for record in caplog.records
+    )
+
+
+def test_incomplete_budget_refuses_and_keeps_the_mock(caplog):
+    caplog.set_level(logging.WARNING)
+    environ = _activated_environ()
+    del environ[main_module.BASETEN_CONSERVATIVE_COST_ENV_VAR]
+
+    engine = main_module.build_engine_from_environment(environ)
+
+    _assert_bound_mock(engine)
+    assert any("enabled_budget_required" in r.getMessage() for r in caplog.records)
+
+
+def test_failed_activation_leaves_the_mock_provider(monkeypatch, caplog):
+    def rejecting(key):
+        raise ProviderSafetyError("invalid_transport")
+
+    monkeypatch.setattr(activation, "BasetenMuseSparkOpenTransport", rejecting)
+    caplog.set_level(logging.WARNING)
+    original_engine = main_module.engine
+
+    engine = main_module.build_engine_from_environment(_activated_environ())
+
+    _assert_bound_mock(engine)
+    assert any("activation_failed" in r.getMessage() for r in caplog.records)
+    # The process engine is untouched, so a failed build cannot half-swap it.
+    assert main_module.engine is original_engine
+    _assert_bound_mock(main_module.engine)
+
+
+def test_unexpected_factory_failure_leaves_the_mock_provider(monkeypatch, caplog):
+    real_factory = main_module.create_assessment_engine
+
+    def exploding_factory(**kwargs):
+        if kwargs.get("activate_baseten"):
+            raise RuntimeError("synthetic wiring failure")
+        return real_factory(**kwargs)
+
+    monkeypatch.setattr(main_module, "create_assessment_engine", exploding_factory)
+    caplog.set_level(logging.WARNING)
+
+    engine = main_module.build_engine_from_environment(_activated_environ())
+
+    _assert_bound_mock(engine)
+    assert any(
+        "failed unexpectedly" in record.getMessage() for record in caplog.records
+    )
+    assert all(_SYNTHETIC_KEY not in record.getMessage() for record in caplog.records)
+
+
+def test_explicit_flag_key_and_budget_activate_behind_the_boundary():
+    engine = main_module.build_engine_from_environment(_activated_environ())
+
+    adapter = engine.provider
+    assert type(adapter) is BasetenMuseSparkOpenAdapter
+    assert type(engine.provider_boundary) is MandatoryProviderBoundary
+    assert engine.provider_boundary._provider is adapter
+    assert adapter._boundary is engine.provider_boundary
+    assert adapter._transport._boundary is engine.provider_boundary
+    assert adapter._gate.config.enabled is True
+    assert adapter._gate.config.max_requests == 1
+
+
+def test_refused_activation_does_not_echo_the_key(monkeypatch, caplog):
+    from app.provider_activation import create_assessment_engine
+
+    def refusing(**kwargs):
+        if kwargs.get("activate_baseten"):
+            raise ProviderActivationError("key_unavailable")
+        return create_assessment_engine(**kwargs)
+
+    monkeypatch.setattr(main_module, "create_assessment_engine", refusing)
+    caplog.set_level(logging.DEBUG)
+
+    engine = main_module.build_engine_from_environment(_activated_environ())
+
+    _assert_bound_mock(engine)
+    assert any("key_unavailable" in r.getMessage() for r in caplog.records)
+    assert all(_SYNTHETIC_KEY not in r.getMessage() for r in caplog.records)
+    assert all(_SYNTHETIC_KEY not in repr(r.args) for r in caplog.records)
```
