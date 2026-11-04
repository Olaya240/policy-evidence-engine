# W4 — override fixtures must cite evidence the provider was given

Worker 4 of 10. Owned paths (only these were written):

- `/home/alex/policy-evidence-fix/backend/app/mock_provider.py` (modified)
- `/home/alex/policy-evidence-fix/backend/tests/test_mock_overrides_grounding.py` (new)

Nothing else was edited. `backend/tests/test_mock_provider_slice19.py` was run but
**not** touched, and it now fails — see §4.

## 1. The defect as it stood

`MockProvider.assess` returned the configured fixture verbatim:

```python
        has_fixture, fixture_output = self._fixture_output(hypothesis_id)
        if has_fixture:
            return fixture_output
```

`_fixture_output` only `json.loads`es the encoded override/sequence, so a fixture
such as

```python
{"source_record_id": "INVENTED", "quote": "a fabricated quote", "stance": "SUPPORTS", "rationale": "fixture"}
```

came back out of the *provider* as a proposal citing a record that was never in
the call. The only rejection was `engine._provider_assess` →
`MandatoryProviderBoundary` → `_validate_provider_proposals`, one layer later. The
provider therefore manufactured fabricated evidence and depended on its caller to
notice.

## 2. The fix

`backend/app/mock_provider.py`: new module-level `validate_fixture_output(output,
records)`, called on the fixture branch of `assess` (so it covers
`assessment_overrides` and `assessment_sequences`, which share that branch).
It refuses, with the boundary's own `ProviderSafetyError` codes:

| condition | code |
|---|---|
| output is not a list; item is not a dict or its key set is not exactly `{source_record_id, quote, stance, rationale}` | `malformed_output` |
| `source_record_id` is not a string, or not an `id` of a record passed to *this* call | `invalid_source` |
| `quote` is not a string, is blank, or is not a substring of the cited record's text | `invalid_quote` |

Nothing is silently dropped: a bad proposal aborts the call. Codes are chosen to
match `provider_safety._validate_provider_proposals`, so `engine._provider_assess`
still surfaces the same code (`invalid_source`, `invalid_quote`,
`malformed_output`) instead of collapsing into `provider_failure`. Stance/rationale
domain validity stays with the boundary — it sees the same list afterwards, and
this change is about provenance, not domain fields.

Both record shapes work: `Record` (direct calls) and `AssessmentContextRecord`
(the boundary's projection) are read via `.id` / `.text`.

```diff
diff --git a/backend/app/mock_provider.py b/backend/app/mock_provider.py
index 77c8ac8..21fc5ec 100644
--- a/backend/app/mock_provider.py
+++ b/backend/app/mock_provider.py
@@ -5,7 +5,7 @@ from threading import Lock
 from datetime import datetime, timezone
 
 from .models import HYPOTHESES, Record, Stance
-from .provider_safety import AssessmentContextRecord, LocalAssessmentProvider
+from .provider_safety import AssessmentContextRecord, LocalAssessmentProvider, ProviderSafetyError
 
 # Deliberately small synthetic fixture set. Provider output remains untrusted and
 # is checked again by engine.py before it can become a persisted assessment.
@@ -63,6 +63,40 @@ def assess_pair(record: Record | AssessmentContextRecord, hypothesis_id: str) ->
     return {"source_record_id": record.id, "quote": record.text, "stance": stance.value, "rationale": rationale}
 
 
+_PROPOSAL_KEYS = frozenset({"source_record_id", "quote", "stance", "rationale"})
+
+
+def validate_fixture_output(output, records):
+    """Refuse a configured fixture that cites evidence this call did not supply.
+
+    A fixture is provider output, so it is held to the provenance rule the
+    provider itself must obey: every ``source_record_id`` must be one of the
+    records handed to *this* call, and every ``quote`` must appear in that
+    record's own text. A fixture naming any other record is fabricated evidence
+    even before the engine sees it, so it is refused here rather than echoed.
+
+    Shape and provenance only; stance/rationale domain validity stays with the
+    engine's boundary, which sees the same proposal list afterwards.
+    """
+    texts = {}
+    for record in records:
+        record_id, text = getattr(record, "id", None), getattr(record, "text", None)
+        if type(record_id) is str and type(text) is str:
+            texts[record_id] = text
+    if type(output) is not list:
+        raise ProviderSafetyError("malformed_output")
+    for item in output:
+        if type(item) is not dict or set(item) != _PROPOSAL_KEYS:
+            raise ProviderSafetyError("malformed_output")
+        source_id = item["source_record_id"]
+        if type(source_id) is not str or source_id not in texts:
+            raise ProviderSafetyError("invalid_source")
+        quote = item["quote"]
+        if type(quote) is not str or len(quote.strip()) < 3 or quote not in texts[source_id]:
+            raise ProviderSafetyError("invalid_quote")
+    return output
+
+
 class MockProvider(LocalAssessmentProvider):
     """Offline provider interface. Its assessments are always independently validated."""
 
@@ -159,7 +193,9 @@ class MockProvider(LocalAssessmentProvider):
             raise ValueError("Unknown hypothesis")
         has_fixture, fixture_output = self._fixture_output(hypothesis_id)
         if has_fixture:
-            return fixture_output
+            # Fixtures (overrides and sequences) are held to the same provenance
+            # rule as generated output: cite only records this call was given.
+            return validate_fixture_output(fixture_output, records)
         result = []
         for record in records:
             if record.restricted:
```

## 3. New tests — `backend/tests/test_mock_overrides_grounding.py`

Seven tests, one assertion each and a control beside every refusal:

1. `test_an_override_naming_a_record_this_call_was_not_given_is_refused` — override
   cites `INVENTED`; `assess([T1], ...)` raises `ProviderSafetyError("invalid_source")`.
   **The defect**: the fabricated citation never leaves the provider.
2. `test_a_quote_absent_from_the_cited_record_is_refused` — legitimate id, quote
   taken from a *different* given record → `invalid_quote`.
3. `test_a_record_supplied_to_an_earlier_call_is_not_citable_in_a_later_one` — the
   same fixture is accepted while `T1` is in the call's input, then refused once
   `T1` is not. Pins "this call's input", not "known to the provider".
4. `test_a_sequence_fixture_naming_an_unreceived_record_is_refused_too` — the
   `assessment_sequences` path shares the branch.
5. `test_the_engine_reports_the_provider_refusal_with_its_own_code` — through
   `AssessmentEngine.assess_hypothesis` the caller sees `ProviderError("invalid_source")`,
   not `provider_failure`.
6. `test_a_legitimate_override_still_produces_the_claim_evidence` — control: a real
   seed record with a genuine substring quote still becomes the claim's evidence.
7. `test_an_empty_override_list_is_still_accepted` — `[]` fixtures (used widely by
   `test_engine.py`) still return `[]`.

## 4. Runs — verbatim

Command (all runs): `cd backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q <file>`

### `tests/test_mock_overrides_grounding.py` — exit 0

```
.......                                                                  [100%]
7 passed in 0.16s
```

### `tests/test_engine.py` — exit 0

```
........................................................................ [ 63%]
.........................................                                [100%]
113 passed in 0.61s
```

### `tests/test_mock_provider_slice19.py` — exit 1

```
.........................F                                               [100%]
=================================== FAILURES ===================================
__ test_a_configured_override_is_echoed_verbatim_including_an_ungiven_record ___

    def test_a_configured_override_is_echoed_verbatim_including_an_ungiven_record():
        """Scope of the guarantee above: fixtures are returned untrusted.
    
        The provider never *invents* a citation, but a fixture may name anything, so
        "cite only what you were given" is a property of the default path only.
        Rejection is the boundary's, not this provider's.
        """
        bogus = {"source_record_id": "INVENTED", "quote": "a fabricated quote", "stance": "SUPPORTS", "rationale": "fixture"}
        provider = MockProvider(assessment_overrides={"CHECKLIST_UNAVAILABLE": [bogus]})
    
>       assert provider.assess([by_id("OPS-101")], "CHECKLIST_UNAVAILABLE") == [bogus]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_mock_provider_slice19.py:268: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
app/mock_provider.py:198: in assess
    return validate_fixture_output(fixture_output, records)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

output = [{'quote': 'a fabricated quote', 'rationale': 'fixture', 'source_record_id': 'INVENTED', 'stance': 'SUPPORTS'}]
records = [Record(id='OPS-101', timestamp=datetime.datetime(2026, 10, 20, 6, 5, tzinfo=datetime.timezone.utc), department='Front...te room 412's late arrival on a loose note.", tags=['checklist', 'late-arrival'], restricted=False, source_group=None)]

    def validate_fixture_output(output, records):
        """Refuse a configured fixture that cites evidence this call did not supply.
    
        A fixture is provider output, so it is held to the provenance rule the
        provider itself must obey: every ``source_record_id`` must be one of the
        records handed to *this* call, and every ``quote`` must appear in that
        record's own text. A fixture naming any other record is fabricated evidence
        even before the engine sees it, so it is refused here rather than echoed.
    
        Shape and provenance only; stance/rationale domain validity stays with the
        engine's boundary, which sees the same proposal list afterwards.
        """
        texts = {}
        for record in records:
            record_id, text = getattr(record, "id", None), getattr(record, "text", None)
            if type(record_id) is str and type(text) is str:
                texts[record_id] = text
        if type(output) is not list:
            raise ProviderSafetyError("malformed_output")
        for item in output:
            if type(item) is not dict or set(item) != _PROPOSAL_KEYS:
                raise ProviderSafetyError("malformed_output")
            source_id = item["source_record_id"]
            if type(source_id) is not str or source_id not in texts:
>               raise ProviderSafetyError("invalid_source")
E               app.provider_safety.ProviderSafetyError: Provider request could not be safely completed

app/mock_provider.py:93: ProviderSafetyError
=========================== short test summary info ============================
FAILED tests/test_mock_provider_slice19.py::test_a_configured_override_is_echoed_verbatim_including_an_ungiven_record
1 failed, 25 passed in 0.18s
```

**This failure is the point, not a regression I can fix within my ownership.** The
test (`backend/tests/test_mock_provider_slice19.py:258-268`) asserts the exact
behaviour my brief calls the defect: that an override naming `"INVENTED"` is echoed
verbatim and "rejection is the boundary's, not this provider's". No provider-side
provenance check can coexist with that assertion, so the two cannot both be true.
The file is not mine to edit; the coordinator needs to decide whether to flip this
test to expect `ProviderSafetyError("invalid_source")` (mirroring the slice-8
`test_proposal_naming_a_restricted_record_is_refused_and_the_code_is_recorded`
shape) or to reject the fix.

### Whole suite — `pytest -q`, exit 1

```
FAILED tests/test_mock_provider_slice19.py::test_a_configured_override_is_echoed_verbatim_including_an_ungiven_record
1 failed, 1676 passed, 1 warning in 31.30s
PYTEST_EXIT=1
```

The only failure in 1677 tests is the S19 test above, which is why 1676 legacy
call sites (including the heavy `assessment_overrides` users in `test_engine.py`,
`test_api.py`, `test_explanation_trace.py`, `test_claim_signing.py`,
`test_semantic_guard_slice18.py`) still pass: all of them cite records they were
given and quote their text.

## 5. Second half of the change — one behavioural tightening to know about

`engine.py:570` (challenge path, when a claim has no matching evidence) calls the
provider with **one** record:

```python
candidates = [a for a in self._provider_assess([record], current["hypothesis_id"]) ...]
```

Before, a multi-record fixture survived that single-record call because it was
echoed; now a fixture citing a record outside `[record]` raises `invalid_source`
there instead of being filtered. No test in the suite exercises that combination
(the challenge tests either match existing evidence, so the provider is not
re-asked, or configure single-record fixtures), so nothing fails — but a future
multi-record fixture plus a challenge on a non-evidence source would surface
`ProviderError("invalid_source")` rather than
`AssessmentError("This source is not an assessed dependency for the selected claim")`.
That is a property of the engine's ask, not of this check; at the provider, citing
a record absent from the call is never sound.

## 6. What I could not check

- **Not mine to edit**: `test_mock_provider_slice19.py` (§4) — the conflict is
  reported, unmodified.
- **Network / real provider**: not exercised; `MockProvider` makes no outbound call
  and this change adds none.
- **Parallel-worker surface**: the working tree already carried modifications to
  `engine.py`, `provider_safety.py`, `test_engine.py`, `test_api.py` etc. from the
  other workers, so the "1676 passed" figure is the suite as of this run, not of a
  clean baseline. My `git diff` for `mock_provider.py` contains only my two hunks.
- **`assessment_sequences` callers**: only `test_api.py` (3 sites) uses sequences;
  all pass. I did not audit whether sequence fixtures elsewhere in future work
  intentionally serve ungrounded output.
