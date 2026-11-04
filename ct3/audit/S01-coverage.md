# Slice 01 coverage map — `app/provider_safety.py:1-208`

Scope: lines 1-208 (through the end of `serialize_provider_request`, line 208).
Read: the slice in full, and `tests/test_provider_safety.py` in full (591 lines), plus a
name search across `backend/tests` for the slice's public symbols.

Everything below is **Read** unless marked Inferred. Nothing was executed: no pytest, no
import check. Line numbers are from the files as read.

## 1. Definition-by-definition

| Slice symbol | Exercised by | Branches NOT reached |
|---|---|---|
| `MAX_REQUEST_TIMEOUT_SECONDS` (16) | `test_oversized_request_and_invalid_timeout_are_rejected_before_transport` :232 (`20.01` → `invalid_timeout`); `FakeTransport.send` asserts the range on every bounded call | the accepted boundary `== 20.0` is never asserted on its own |
| `MAX_REQUEST_BYTES` (17) | :122 oversized text; :232 oversized payload; :551 | `len(payload) == MAX_REQUEST_BYTES` exactly (off-by-one both directions) untested |
| `MAX_RESPONSE_BYTES` (18) | :249 | boundary exactly 4096 accepted |
| `MAX_RESPONSE_READ_CHUNK_BYTES` (19) | **indirect only** — :247 asserts `largest_read_request <= 1024` as a literal | no test references the constant, so changing it leaves that assertion passing-but-stale |
| `MAX_CONTENT_LENGTH_HEADER_CHARS` (20) | :265 (`"0"*10000` → `malformed_response_headers`) | exactly-10-digit value; 11 digits with a small number (rejected by length, not size) |
| `MAX_EXPERIMENT_REQUESTS` (21) | **indirect only** — :162 passes `max_requests=18` and expects `invalid_budget` | nothing names the constant; the 17/18 boundary is inferred from one case |
| `MAX_CONFIGURABLE_ESTIMATED_BUDGET_USD` (22) | :162 (`"5.01"` → `invalid_budget`); `_enabled_gate` uses `"5.00"` | exact equality at 5.00 is exercised only through the helper, never asserted |
| `SYSTEM_INSTRUCTIONS` (27) | :106 asserts `startswith("Assess only whether")` and `!= attack` | **content is not pinned.** Any rewrite that keeps that prefix passes every test. No test asserts the text cannot be attacker-influenced beyond prefix identity |
| `SerializedProviderRequest.__new__` (35) | :567 forged `bytes.__new__` path | a *wrong but non-None* seal is never passed; only the absent-seal path is reached |
| `SerializedProviderRequest.__setattr__` (42) | **none** | immutability untested (the only `__setattr__` hits in `tests/` are `test_policy_challenge_propagation.py:621-623`, unrelated) |
| `_is_serialized_request` (47) | :567 (plain `bytes`), :551 | a *subclass* of `SerializedProviderRequest` (the `type(value) is ...` arm) never exercised |
| `AssessmentContextRecord` (52) | **none** | `.restricted` always returning `False` (56-57) is untested and semantically load-bearing |
| `LocalAssessmentProvider.assess` (65) | `test_engine.py:890` subclasses it, but overrides `assess` | the `NotImplementedError` body is never reached |
| `_SENSITIVE_TEXT_PATTERNS` / `contains_sensitive_text` (70-80) | :135 (all four patterns, via the serializer), :142 (id field) | no **negative** case: one string per pattern that must classify as safe; no overlap/adjacency case (e.g. digits inside an allowed id) |
| `eligible_provider_records` (83) | :116 (dict element → `invalid_context`), :86 (restricted), :135/:142 (sensitive) | the outer sequence check (85-86): tuple accepted, generator/`deque`/`None` rejected — all untested |
| `ProviderSafetyError` (97) | :475 sanitized `str`, plus `.code` assertions throughout | — |
| `StreamingResponse` / `StreamingTransport` / `ApprovedProviderAdapter` (109-146) | :389 (protocol-shaped adapter → `unsupported_provider`) | — |
| `_json_string_size` (150) | :122 early length raise; normal ASCII path everywhere | **all escape branches**: `"`, `\`, `\b`, `\f`, `\n`, `\r`, `\t` (159-160); other control chars `< 0x20` → 6 (161-162); the `UnicodeEncodeError` path (165-169) |
| `_encode_json_string` (177) | normal path only | `TypeError` / `UnicodeEncodeError` → `invalid_context` (180-182) |
| `serialize_provider_request` (183) | :86, :106, :116, :122, :135, :142 | unknown hypothesis → `invalid_context` (186-187); the 129-record cap (192-193); aggregate-over-cap with many small records; the `len(payload) != predicted_size` guard (207) |

## 2. Ranked gaps, with the test each needs

1. **`_json_string_size` escape arithmetic (high).** The predicted size must equal
   `json.dumps(..., ensure_ascii=False)` byte-for-byte, because a mismatch raises
   `request_too_large` on *valid* input (line 207). No test contains a quote, backslash,
   newline or other control character in a record, so six of the model's eight branches are
   unexercised. Test: one record per character class, asserting the serialized payload parses
   back to the same text and that a payload sized just under the cap still serializes.
2. **`SerializedProviderRequest.__setattr__` immutability (high).** The whole boundary rests on
   "a sealed request cannot be edited"; nothing asserts it. Test: `pytest.raises(AttributeError)`
   on setting `_seal`, `payload`, and an arbitrary attribute.
3. **`serialize_provider_request` record cap (medium).** 129 tiny records raise
   `request_too_large` while 129 large-but-legal payloads would fit the byte budget. Pinning it
   records the intent (a record-count limit, not only a size limit). Test: 128 accept, 129 reject.
4. **`eligible_provider_records` outer sequence check (medium).** A generator or `deque` raises
   `invalid_context` while a tuple is accepted; the type hint says `Sequence`, so the contract is
   narrower than it reads. Test: tuple accepted, `iter([...])` rejected with `invalid_context`.
5. **`_is_serialized_request` exact-type arm (medium).** A subclass carrying a seal is rejected
   only because of `type(value) is ...`. Untested, and it is the only thing preventing a
   monkeypatched subclass from passing as sealed.
6. **`AssessmentContextRecord.restricted` (medium, semantic).** It returns `False`
   unconditionally. Today it is only built from already-filtered records, but any future caller
   that projects a restricted record gets a silently false flag. Test: construct one and assert
   the documented intent, or (better) remove the property in favour of the filter staying the
   only gate.
7. **`LocalAssessmentProvider.assess` (low).** `NotImplementedError` is the contract for
   "documentation only"; untested.
8. **`contains_sensitive_text` negatives (low).** Four positives are covered indirectly; no test
   asserts a clean sentence stays eligible, so an over-broad pattern would only surface as a
   mysteriously empty payload.
9. **`SYSTEM_INSTRUCTIONS` content (low but security-relevant).** Only a prefix is pinned.
10. **`MAX_*` constants referenced by literal (low).** `1024` at :247 and `18` at :162 duplicate
    constants; renaming a constant would not fail either test.

## 3. One ambiguity worth recording

`test_engine_rejects_unsupported_provider_bypass_and_raw_payload` (:567) builds a forged request
with `bytes.__new__(SerializedProviderRequest, ...)`. That call bypasses the Python-level
`__new__`, so the instance carries no `_seal`; the test then sees `invalid_request` from
`_is_serialized_request`, not from `SerializedProviderRequest.__new__`'s seal check. The boundary
holds either way, but the test cannot distinguish the two defences — a regression in the seal
check at line 36 alone would leave it green. Inferred from reading; not executed.

## 4. What this map does not cover

- I did not read lines 209+ of the module, so anything `_read_bounded_response` shares with this
  slice (it calls `ProviderSafetyError` only) is out of scope.
- No execution: every "not reached" claim is a read of the test bodies, not a coverage run.
- I did not enumerate tests outside `tests/` (e.g. `evaluate.py` paths) that might reach these
  helpers indirectly.
