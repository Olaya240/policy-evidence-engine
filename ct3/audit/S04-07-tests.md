# Slice 4 — worker 7 of 10: test file

## File created

`backend/tests/test_provider_safety_slice4_contracts.py` — 12 test cases (10 functions, two of them
parametrised), covering the seven branches the slice-4 audits flagged.

| # | Test | Pins |
|---|---|---|
| 1 | `test_deeply_nested_body_is_a_controlled_malformed_response` | 2000-deep nested array → `malformed_response`, not `RecursionError` |
| 2 | `test_a_response_from_an_unapproved_model_is_refused` / `...approved_model_is_accepted` | the model pin is two-way; both arms asserted |
| 3 | `test_the_proposal_cap_is_inclusive_and_guarded_one_past_it` | `MAX_PROPOSALS` accepted, `+1` refused with `malformed_output` |
| 4 | duplicate key at item level / at top level | `object_pairs_hook` fires at every depth → `malformed_response` |
| 5 | `test_impossible_usage_accounting_is_refused` (parametrised) | `usage` with a bool or a negative → `unsupported_response` |
| 6 | ZWSP refusal / empty refusal | `provider_refusal` for a non-empty-after-strip refusal; `unsupported_response` for `""` |
| 7 | `test_a_three_character_quote_from_another_record_is_invalid` | a 3-char quote that clears the length floor still fails grounding |

## What I read rather than assumed

- `parse_provider_proposals` catches `RecursionError` (added this slice) at the `json.loads` call.
- The model comparison is `result["model"] != BasetenMuseSparkOpenAdapter.MODEL_SLUG` → `unsupported_response`.
- The cap is `len(proposals) > MAX_PROPOSALS` → `malformed_output`, checked before the per-item loop.
- The refusal arm is `if type(refusal) is str and refusal.strip(): provider_refusal`, otherwise
  `unsupported_response`. `"\u200b".strip()` is unchanged in Python, which is why test 6 expects
  `provider_refusal` and not the fall-through.
- The quote arm is `len(quote.strip()) < 3 or quote not in records[source_id]` → `invalid_quote`, so a
  three-character quote reaches the membership test.

Expectations are derived from `ps.MAX_PROPOSALS`, `Stance.SUPPORTS.value` and `MODEL_SLUG`, not from
literals, except the token counts in test 5, which are the test's own inputs.

## Unrun and unverified

No terminal in this session: the file has never been imported or executed. The two I would expect to
need adjusting:

1. **Test 2's accepted arm** compares the parsed proposals to `[proposal()]` exactly; if the parser
   ever normalises key order or adds a field, the equality fails for the wrong reason.
2. **Test 1's nesting depth** (2000) is above CPython's default recursion limit but the exact
   threshold where `json.loads` raises rather than the C scanner truncating is interpreter-specific.

## Memory

No `local_memory_*` tool is bound to this worker session (my tools are file read/edit/search only), so
I am not claiming a write. The durable fact belongs to the coordinator:

```
s: policy-evidence-engine parse_provider_proposals
p: GUARDS_RECURSION
o: RecursionError from json.loads is converted to malformed_response; a 2000-deep body is a controlled
   rejection rather than an unclassified 500
source: project:verification
```

## Left undone

I did not touch `app/` or any other test file. I did not run anything, so none of the twelve cases is
evidence yet — the coordinator runs them with the rest of slice 4.
