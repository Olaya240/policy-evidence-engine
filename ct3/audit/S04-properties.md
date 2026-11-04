# Slice 4 properties — `parse_provider_proposals` and provenance validation

Harness: `ct3/audit/slice4_properties.py`
Run: `cd /home/alex/policy-evidence-fix && PYTHONPATH=backend python ct3/audit/slice4_properties.py`

## What the source actually enforces (read, provider_safety.py:895-955)

| Condition | Code |
|---|---|
| body is not `bytes` | `malformed_response` |
| body is not valid UTF-8 | `malformed_response` |
| duplicate JSON object key | `malformed_response` |
| `NaN` / `Infinity` / malformed JSON | `malformed_response` |
| top level is not a list | `malformed_output` |
| item is not a dict, or its key set is not exactly the four required | `malformed_output` |
| `source_record_id` not a string, or not in the request envelope | `invalid_source` |
| `quote` not a string, shorter than 3 after strip, or not a substring of *that* record | `invalid_quote` |
| `stance` not exactly one of SUPPORTS / CONTRADICTS / NEUTRAL | `invalid_stance` |
| `rationale` not a non-blank string | `invalid_rationale` |
| request envelope itself unparseable | `invalid_request` |

## Properties and expected result

1. **Shape** — a valid array is accepted; `[]` returns `[]`; an object, `null`, or an array of non-objects is `malformed_output`; a non-bytes or invalid-UTF-8 body is `malformed_response`.
2. **Keys** — missing key and extra key are `malformed_output`; a non-string id is `invalid_source`; a duplicate JSON key is `malformed_response` (the `object_pairs_hook` fires before any validation).
3. **Vocabulary** — every case variant is `invalid_stance`; the three canonical values pass.
4. **Grounding** — an unknown id is `invalid_source`; a quote absent from the cited record, shorter than three characters, or whitespace-only is `invalid_quote`. A quote that belongs to a *different* record also yields `invalid_quote`, because the check is "substring of the cited record", not "belongs to exactly one record". A phrase present in two records is therefore accepted for either — recorded as a PASS with the reasoning, not a failure.
5. **Size** — the parser has **no item cap**: 129 valid proposals are accepted. The only bound is `MAX_REQUEST_BYTES` on the request, which limits how many citations can exist rather than how many the provider returns. A 100 KiB quote is refused by *grounding*, not by size.
6. **JSON strictness** — `NaN`, `Infinity`, a trailing comma and single-quoted strings are all `malformed_response`.

## Divergences to record, not fix here

- `parse_provider_proposals`' docstring says it "does not guess vendor envelopes or treat refusal/error objects as empty proposals". That is true for objects, but an **empty array is accepted and indistinguishable from "the provider had nothing to say"** — the refusal case a vendor would most likely send as `[]`. Bar 1 is honoured; nothing prevents a vendor adapter from mapping its refusal to `[]`.
- The parser validates each item against the request's records but imposes **no bound on the number of proposals**. An adapter that returns the same cited record 129 times is accepted. Whether that matters is a caller question, so it is reported rather than patched.

## Unrun

Nothing was executed: this worker has no terminal. The harness is written to fail loudly rather than silently pass, but its green state is the coordinator's to establish.

**Most likely to need adjustment:** property 3's "passes through" arm and property 4's shared-phrase case, because both assert on acceptance rather than on an error code — if either raises for a reason not visible from reading (for example an eligibility filter dropping a record), the coordinator will see a `FAIL` with the observed code and can decide whether the code or the expectation is wrong.
