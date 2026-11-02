# Slice 01 — test pass (worker 4 of 5)

Slice: `app/provider_safety.py:1-208`. Files created, nothing edited.

## File collision, stated first

The assigned path `backend/tests/test_provider_safety_slice1.py` **already contained
another worker's file** (154 lines, header "Slice 1 audit tests") when I went to write.
I did not overwrite it. My tests are in
`backend/tests/test_provider_safety_slice1_contracts.py` instead, and the two files are
deliberately disjoint — I read theirs first and skipped every contract it already pins.

**The coordinator must decide which survives.** Two files with near-identical names in one
directory will confuse the next reader.

Also worth flagging: `app/provider_safety.py` was **883 lines when the ledger was built and
920 lines when I read it later in this turn**. The slice is being mutated while it is being
audited, so any line numbers in the five slice-01 reports may disagree with each other. The
ledger should be rebuilt from the final file before slice 02.

## What the existing suite already covered (so these do not repeat it)

`tests/test_provider_safety.py` covers the allowlist end to end, the restricted canary,
prompt-injection text, dict rejection, one oversized string, the four original sensitive
patterns, and a forged payload through `bytes.__new__`.

The sibling `..._slice1.py` adds: the size model against `json.dumps` across 22 code points,
lone-surrogate rejection, the 129-record ceiling, immutability, the module-level seal, the
eligibility type check, the projection shim, and the six keyword-less credential patterns.

## What my file adds

| Test | Contract |
|---|---|
| `test_constructing_a_payload_without_the_seal_is_refused` | direct construction raises `invalid_request`, and so does a wrong seal object |
| `test_failed_assignment_does_not_strip_the_seal` | immutability is not a route to de-trusting an existing payload |
| `test_trust_check_rejects_every_way_of_forging_a_bytes_lookalike` | plain bytes, concatenation, a bytes subclass, `memoryview`, `bytearray` and `None` are all untrusted |
| `test_envelope_keys_are_exactly_the_documented_set` | nested key sets are exact, not merely present |
| `test_record_order_is_preserved_and_nothing_else_leaks` | order across three records |
| `test_empty_record_list_is_a_valid_request` | `records: []` is valid, distinct from a missing input |
| `test_unknown_hypothesis_is_refused_before_encoding` | `invalid_context`, not a KeyError |
| `test_byte_cap_is_inclusive_at_exactly_the_limit` | equality at `MAX_REQUEST_BYTES` is admitted; +1 byte is refused |
| `test_eligibility_preserves_input_order` | the filter is a filter, not a reorder |
| `test_projection_carries_exactly_two_frozen_fields` | field set is exactly `id`, `text` and assignment raises |
| `test_near_misses_are_not_redacted` (5 cases) | short phone, nine digits, separator with no value, benign prose |
| `test_positive_cases_the_other_file_leaves_to_the_keyword_rule` | the three keyword/phone/SSN positives |

## Two things the read turned up that a test cannot fix

1. **The phone pattern over-matches ordinary numeric text.** `(?<!\w)(?:\+?\d[\d(). -]{8,}\d)(?!\w)`
   matches an ISO timestamp (`2026-01-01 12:34:56`) and any 10+ digit identifier, so such a
   record is silently dropped from provider context. Over-redaction deletes evidence; this
   deserves an explicit decision rather than a test that locks it in.
2. **`_is_serialized_request` is a type-and-seal check, not an isolation boundary.**
   `_SERIALIZATION_SEAL` is module-level, so in-process code can construct a trusted payload.
   The sibling file documents this; it is worth repeating in the module docstring, which
   currently reads as a stronger guarantee than the code provides.

## Unrun

No terminal in this session: none of these tests has been executed, and I have not
typechecked them. The two most likely to fail for a reason I cannot see:

- `test_byte_cap_is_inclusive_at_exactly_the_limit` — depends on the envelope size being
  exactly `base + spare` for ASCII text, which holds only if no field length crosses a
  digit boundary in the size model.
- `test_trust_check_rejects_every_way_of_forging_a_bytes_lookalike` — `bytearray(genuine)`
  and `memoryview(...).tobytes()` assume the check is `type(...) is`, not `isinstance`;
  the source says `type(...) is`, so this should hold, but it is the assertion most
  sensitive to a future edit.
