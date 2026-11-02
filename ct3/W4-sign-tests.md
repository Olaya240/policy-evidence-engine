# W4 — claim signing contract tests

**File created:** `backend/tests/test_claim_signing.py` (7 tests). No source file edited.

## What each test pins

| Test | Pins |
|---|---|
| `test_single_support_signs_positive` | one fresh accepted support ⇒ `FOR`, score = (1−0)/(1+0+1), confidence = \|score\| |
| `test_single_contradiction_signs_negative_with_the_same_magnitude` | one fresh contradiction ⇒ `AGAINST`, score = (0−1)/(0+1+1); confidences equal, scores not |
| `test_confidence_is_always_the_magnitude_of_the_signed_score` | `confidence == abs(evidence_score)` and the direction agrees with the sign, over three shapes including the no-evidence case |
| `test_json_round_trip_preserves_the_sign` | `Claim.model_dump_json()` → `json.loads` keeps a negative float; no magnitude coercion in serialisation |
| `test_serialized_trace_and_claim_carry_the_same_signed_score` | the claim-level fields agree with `explanation_trace.evidence_score` / `.evidence_direction` |
| `test_a_legacy_claim_without_the_signed_fields_still_validates` | a claim dict without either field validates and leaves both `None`, with `confidence` untouched |

Expected scores are computed from `(s - c) / (s + c + 1)` in the test rather than
hardcoded, so a table change surfaces as a formula mismatch.

## Unrun, and what will break first

No terminal, so **none of these has been executed**.

The two most likely to need adjusting:

1. `test_serialized_trace_and_claim_carry_the_same_signed_score` — it assumes the
   claim-level fields are populated from the same `Decision` the trace is built
   from. If the sibling worker populates the claim before the trace is attached,
   or attaches the trace from a separate computation, this will disagree.
2. `test_a_legacy_claim_without_the_signed_fields_still_validates` — assumes both
   new fields are `Optional` with a `None` default. If they were added as required
   with a numeric default, `evidence_score` will read `0.0` and the `is None`
   assertions fail.

Not covered here: the HTTP response surface. Asserting through the API would
duplicate the `client` fixture in `tests/test_api.py`; the model round-trip above
covers the serialisation step, and the coordinator can add one API assertion if
the route layer is suspected of dropping a field.
