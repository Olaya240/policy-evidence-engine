# Slice 4 — coverage map (worker 6 of 10)

Slice: `app/provider_safety.py` lines 704–965 — `BasetenMuseSparkOpenAdapter`
(`_wire_request`, `_reject_surrogate_text`, `_parse_response`,
`_assess_from_boundary`, `_assess_async`, `bounded_provider_call`) and
`parse_provider_proposals` / `_validate_provider_proposals`, plus the JSON hooks
`_reject_duplicate_object_keys`, `_reject_nonstandard_json_constant`.

Method: read the slice, then every test in `backend/tests` that names these entry
points — `test_baseten_adapter.py` (556 lines, read through line 400),
`test_provider_safety.py` (591 lines, read the proposal-parser region),
`test_provider_activation.py`, `test_provider_safety_slice2_contracts.py`, and
targeted searches for each error code. **Nothing executed** — every "reached"
claim is from reading the test body, not a coverage run.

## 1. What is covered

| Branch (function) | Test that reaches it |
|---|---|
| `_parse_response` non-bytes / invalid UTF-8 | `test_provider_safety.py::test_strict_proposal_parser_rejects_ambiguous_or_empty_json` (`\xff`, `b''`) — via the legacy helper, not the adapter |
| JSON decode error, truncated body | `test_baseten_adapter.py::test_baseten_response_parser_fails_closed_on_unsupported_or_empty_shapes` (`{"model":"m","choices":[]`) |
| duplicate key at depth | same, `{"model":"m","model":"other",...}`; and `test_baseten_strict_inner_proposal_parser_rejects_duplicate_keys_and_nonstandard_constants` |
| non-standard constant (`NaN`) | same two tests |
| surrogate text | same param list, `{"model":"m","choices":[],"id":"\xed\xa0\x80"}` |
| top-level key subset (`unexpected`) | same param list |
| `choices` length 0 | same param list, `"choices":[]` |
| `refusal` present and non-empty | same param list, `_response("[]", extra_message={"refusal": ...})` |
| `message` key superset (`tool_calls`) | same param list |
| `empty_output` (empty content) | same param list, `_response("")` |
| item key set exact (engine-owned fields) | `test_baseten_response_parser_rejects_proposals_with_engine_control_fields` (5 params, asserts `malformed_output`), and `test_provider_safety.py::test_provider_proposals_cannot_assign_engine_owned_fields` |
| `invalid_source` | `test_provider_safety.py:431` |
| constructor overrides (endpoint/model) | `test_baseten_constructor_has_no_endpoint_or_model_override_and_gate_is_disabled_by_default` |
| gate disabled → `provider_disabled` | same test |
| transport/adapter subclass rejection, boundary identity | `test_dispatch_capability_rejects_mismatched_bindings_before_transport_construction` |
| dispatch capability single-use / replay | `test_dispatch_capability_is_single_use_and_replay_stops_before_transport` |
| cross-thread single authorization | `test_concurrent_cross_thread_reuse_of_one_capability_authorizes_one_send` |

## 2. Branches added in the last hour with no test at all

These were added while this audit was running, and a grep for `MAX_PROPOSALS`,
`RecursionError`, `deeply`, `nested` and `MODEL_SLUG` under `backend/tests`
finds **no test** for any of them:

1. `RecursionError` → `malformed_response` in `parse_provider_proposals` and in
   `_parse_response`. A deeply nested body escapes `json.loads` as
   `RecursionError`; the except tuple now catches it. Untested.
2. `result["model"] != MODEL_SLUG` → `unsupported_response` in `_parse_response`.
   The only existing `MODEL_SLUG` assertion is
   `test_provider_activation.py:137`, which checks the constant's value, not the
   comparison. Untested, and it changes what the `{"model":"m",...}` params above
   actually exercise — `"m"` is not the slug, so those cases now raise at the pin
   rather than at the shape check, without any test saying so.
3. `len(proposals) > MAX_PROPOSALS` → `malformed_output` in
   `_validate_provider_proposals`. Untested; no test builds more than a handful of
   proposals.

## 3. Ranked untested branches (one-line test each)

1. **model pin** — `_parse_response(_response(valid_content, model="meta-models/other"), request)` → `unsupported_response`; and the positive twin with `MODEL_SLUG` → parses.
2. **RecursionError** — `parse_provider_proposals(b"[" * 10000 + b"]" * 10000, request)` → `malformed_response`, not `RecursionError`.
3. **MAX_PROPOSALS** — 128 valid proposals parse; 129 → `malformed_output`.
4. **`usage` negative / bool** — `{"prompt_tokens": -1}` and `{"prompt_tokens": true}` → `unsupported_response` (only `NaN` is tested today).
5. **`created` bool or non-int** — `{"created": true}` → `malformed_response`.
6. **`object` field** — `{"object": "text.completion"}` → `unsupported_response`.
7. **choice `index`** — `{"index": 1}` and `{"index": true}` → `unsupported_response`.
8. **`finish_reason`** — `"length"` → `unsupported_response` (only `"stop"` is exercised, implicitly).
9. **`message.role`** — `"user"` → `unsupported_response`.
10. **`refusal` empty or whitespace** — present but `""` / `"   "` → `unsupported_response`, distinct from the non-empty `provider_refusal` that is tested.
11. **content not a str / whitespace-only** — `{"content": "   "}` → `unsupported_response`.
12. **`invalid_quote` floor** — quote of two characters that *is* a substring → `invalid_quote` (the `< 3` strip rule), and quote from a different record than the one cited → `invalid_quote`.
13. **`invalid_stance`** — `"supports"` (case variant) → `invalid_stance`.
14. **`invalid_rationale`** — `"   "` → `invalid_rationale`.
15. **adapter's own `request_too_large`** — `_wire_request` caps at `MAX_REQUEST_BYTES`; slice-1 tests cover `serialize_provider_request`'s cap, not this one.
16. **non-bytes body to `_parse_response` directly** — `_parse_response("{}", request)` → `malformed_response` (the param list only passes bytes).
17. **`_reject_surrogate_text` non-container types** — ints/bools/None pass through; nothing asserts they are ignored rather than rejected.

## 4. Tests that pass for the wrong reason

- `test_baseten_response_parser_fails_closed_on_unsupported_or_empty_shapes`
  (lines 189–211) asserts only `pytest.raises(ProviderSafetyError)`, never
  `error.value.code`. Any of ten different checks can fire and it stays green —
  which is exactly how the model pin changed its meaning silently. It also
  cannot distinguish `malformed_response` from `unsupported_response`, and those
  two codes imply opposite things about the provider.
- `test_empty_proposal_array_remains_distinct_from_empty_response_body` pins
  `== []` through `_bounded_transport_call`, the legacy helper that production
  dispatch refuses (`mandatory_boundary_required`). It documents a path no
  boundary caller can take.
- `test_baseten_adapter.py:226` (engine-owned fields) does assert the code, but
  every case collides on the same `malformed_output`, so it cannot tell the
  item key-set check from the count cap added today.

## 5. Left undone

- Read only to line 400 of 556 in `test_baseten_adapter.py`; the remaining
  tests (requests/counters, gate refunds) may reach additional branches.
- No coverage run, so "reached" is by reading test bodies; a branch could be
  reached indirectly by a fixture and missed here.
- Did not read `test_protocol_v1.py` in full; it contains `invalid_source` /
  `invalid_quote` for a different contract (`normalize_proposal_response`) and
  those do not cover this slice.

## 6. Memory candidates (no memory tool in this worker session)

```
s: policy-evidence-engine adapter parser
p: LACKS_TESTS
o: RecursionError handling, the MODEL_SLUG pin and MAX_PROPOSALS were added with no test; grep under backend/tests finds none
source: project:verification
--
s: policy-evidence-engine response shape test
p: OMITS_CODE
o: test_baseten_response_parser_fails_closed_on_unsupported_or_empty_shapes asserts only that some ProviderSafetyError was raised, so a change of which check fires stays green
source: project:verification
```
