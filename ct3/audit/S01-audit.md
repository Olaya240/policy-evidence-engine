# Slice 01 — `app/provider_safety.py:1-208`

Status: **AUDITED. Three findings closed in code; verification blocked.** The property harness is
written but unexecuted because the terminal was unavailable, so this slice is not yet signed off.
See the Closure section at the end for what changed and what is still owed.

## What was actually read

- `provider_safety.py:1-206` in full, plus `200-225` to reach the end of
  `serialize_provider_request` (the slice boundary cuts a function; the range was extended to 208).
- `52-84` re-read after the file grew from 883 to 920 lines mid-audit.
- `models.py:1-60` and `136-144` for `Hypothesis`, `HYPOTHESES`, `Record`.
- `mock_provider.py:30-49` and the single `AssessmentContextRecord(**item)` construction site.
- `ct3/audit/S01-threats.md` (sibling threat audit) for corroboration, not as evidence.

## Verified by reading

1. **The serializer emits only `id` and `text`.** `eligible_provider_records` (≈95) filters on
   `record.restricted` and `contains_sensitive_text` of id and text; the payload then carries those
   two fields alone. Department, timestamp, tags and `source_group` never cross the boundary. So the
   redaction claim for this path holds.
2. **The `AssessmentContextRecord.restricted` constant is sound where it is used and nowhere else.**
   The only construction is `AssessmentContextRecord(**item)` from the already-filtered envelope, so
   `False` is true there. A sibling worker has since documented it as a compatibility shim and named
   the precondition in the docstring (lines 68-84), which is the right resolution: the alternative
   (deleting it) breaks `mock_provider.py:165`, and a stored field would be `False` anyway because
   the envelope has no such key.
3. **The 128-record bound is off-by-one-safe.** `if len(permitted) > 128` runs after the append, so
   the 129th record raises and 128 is the maximum accepted.
4. **Three different failures share one error code.** Payload over `MAX_REQUEST_BYTES`, more than 128
   records, and `len(payload) != predicted_size` all raise `request_too_large`. The third is an
   internal model mismatch reported as a client error, which is the finding I would fix first because
   it hides a bug class behind a plausible message.

## Inferred, not verified (needs a run)

- **Copy semantics of the sealed request.** `copy.copy`, `copy.deepcopy` and slicing a
  `bytes` subclass: CPython returns a plain `bytes` for a slice, but `copy` may re-enter
  `__reduce_ex__` and either produce an unsealed object or raise. Either outcome is acceptable; what
  must not happen is a forged object that passes `_is_serialized_request`. `slice1_properties.py`
  property 4 decides it.
- **Size-model equality.** The per-character model looks right for short escapes (2), other C0
  controls (6) and everything else (UTF-8 length), but "looks right" is not a check; property 1 runs
  it across 12,288 codepoints.
- **Sensitive-text recall.** Four patterns; the sibling report claims three concrete false negatives
  and two false positives. Property 6 measures recall over 200 generated forms and prints misses
  rather than asserting perfection.

## Blocking facts

- `provider_safety.py` is **being edited by another process during this audit** (883 → 920 lines).
  Any line number in this note may be stale by one edit, and the slice cannot be declared solid
  while it is a moving target. It needs a re-snapshot before sign-off.
- No terminal this turn: `slice1_properties.py` has never executed, so every property above is a
  hypothesis about the code, not a result.

## To close this slice

1. Run `PYTHONPATH=backend python3 ct3/audit/slice1_properties.py`; fix what fails.
2. Split the `request_too_large` code so an internal size-model mismatch cannot masquerade as a
   client error.
3. Give `eligible_provider_records` a reason channel, or document that a filtered corpus is
   indistinguishable from an empty one.
4. Re-snapshot the file, re-read the changed regions, and only then mark the ledger entry complete.

## Closure (this turn)

- **2 — closed.** The combined check is now two: `serialization_accounting_mismatch` when the encoder
  and the size model disagree, `request_too_large` only for genuine client limits. The mismatch code
  is internal and unreachable from a well-formed request, so no existing expectation changes.
- **3 — closed.** `partition_provider_records(records) -> (eligible, [(record_id, reason)])` with a
  closed reason set (`restricted`, `sensitive_text`). `eligible_provider_records` delegates to it, so
  every existing caller keeps its shape and the reason is now recoverable.
- **4 — done to the limit of reading.** The file was re-read at its new line numbers: the seal
  docstring, the sensitive-text patterns and the narrowed annotation are intact at 35-60, 97-114 and
  119-147; the serializer ends at 249. Line numbers in the body of this note above refer to the
  pre-edit snapshot and are superseded by the closure section.
- **1 — still blocked.** No terminal this turn: `slice1_properties.py` and the suite remain unrun.
  The slice cannot be called solid on reading alone, and the ledger entry says so.
- Two findings from the contract pass are recorded in `S01-contracts.md`: the seal docstring claimed
  a boundary the type cannot provide, and the sensitive-text filter missed credentials with no
  keyword (`Bearer`, JWT, `sk-`, `ghp_`, `xoxb-`, `AKIA`). Both were fixed in the same edits.
