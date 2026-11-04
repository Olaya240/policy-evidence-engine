# Slice 4 — adversarial security pass (`provider_safety.py:704-965`)

Scope read: `_parse_response` (755-844), `parse_provider_proposals` (899-935),
`_validate_provider_proposals` (937-980), `_reject_duplicate_object_keys`,
`_reject_nonstandard_json_constant`, `_reject_surrogate_text`, and the adapter's
`content.encode` hop at 823-827. Line numbers are from the 1002-line file as read
just now; the module has grown twice during this audit, so they may drift again.

**Verdict: nothing exploitable found in this range.** Four latent traps and three
drift items, ranked below. What I attacked and what held is listed first, so the
absence of an exploit is a result rather than a blank.

## What held (each Read with the line that holds)

| Attack | Outcome | Line |
|---|---|---|
| Body of 1000+ `[` (4096 bytes, inside `MAX_RESPONSE_BYTES`) | `RecursionError` is now caught in **both** parsers → `malformed_response` | 768, 931 |
| Deep nesting that survives `json.loads` but recurses in `_reject_surrogate_text` | the walk runs inside the same `try` | 764 (inside 757-769) |
| Surrogate pair split across escapes (`"\ud83d\ude00"`) | decodes to U+1F600, accepted | 762 |
| Duplicate key at any depth | `object_pairs_hook` fires on every object, not just the top | 897-905 |
| `10**5000` integer in `usage` | CPython's int-digit limit raises `ValueError` → `malformed_response` | 767 |
| `1e999` → `inf` in `usage` | `type(value) is not int` → `unsupported_response` | 789-793 |
| `choices` with two entries | `len(choices) != 1` → `unsupported_response` | 796 |
| `content` as a JSON array | `type(...) is not str` → `unsupported_response` | 818-820 |
| `refusal` containing only a zero-width space | `strip()` does not remove ZWSP, so it is truthy → `provider_refusal` (fail-closed) | 811-816 |
| Refusal mapped to `[]` through the adapter | `if not proposals: raise empty_output` | 828-829 |
| 129 proposals | `MAX_PROPOSALS` cap → `malformed_output` | 948-951 |
| Hugely long `quote` | grounding substring test against a ≤16 KiB record, and the body is ≤4 KiB | 965 |

## Latent traps

### L1 — `parse_provider_proposals` accepts lone surrogates in `rationale` (Read 962-964)
The public parser decodes strict UTF-8, but a JSON escape `"\ud800"` survives
decoding as a lone surrogate. `_validate_provider_proposals` checks only that
`rationale` is a non-empty `str`; it never calls `_reject_surrogate_text`.

Through the adapter this is unreachable: `message["content"].encode("utf-8",
errors="strict")` at 823-827 raises `UnicodeEncodeError` first, and that is mapped
to `malformed_response`. But the function's docstring invites direct use by
"a documented vendor adapter", and any such caller that hands over already-decoded
bytes bypasses the encode hop. The value is accepted here and fails later, at
persistence or JSON serialisation, as an unclassified error far from the boundary.

Cheapest fix: call `BasetenMuseSparkOpenAdapter._reject_surrogate_text(result)` at
the top of `_validate_provider_proposals`, before the shape loop.

### L2 — empty array is two different answers depending on the caller (Read 828, 940)
`parse_provider_proposals` returns `[]` for `[]`; `_parse_response` turns the same
value into `empty_output`. The docstring says refusal/error objects are not treated
as empty proposals — true for objects, but nothing stops an adapter mapping a
vendor refusal onto an empty array. A direct caller cannot distinguish "the model
returned nothing" from "the model refused". Decision, not patch: either the parser
raises `empty_output` itself, or the docstring states that an empty array is a
valid answer and the caller decides.

### L3 — the request re-parse swallows everything (Read 938-942)
`_validate_provider_proposals` rebuilds the record map with
`except Exception: raise ProviderSafetyError("invalid_request")`. That also catches
`ProviderSafetyError` raised by the JSON hooks, so a duplicate-key fault in the
request would be reported as a caller error. Unreachable today because the request
bytes come from the serializer and carry the seal, but the catch is wider than the
contract it implements.

### L4 — records are keyed by `id`, later duplicates silently win (Read 939-940)
`{item["id"]: item["text"] for item in ...}` keeps the last text for a repeated id.
The serializer does not deduplicate ids either. If two records ever share an id,
grounding is checked against the *last* text while the first is invisible, so a
quote could ground against text the provider never saw. Latent constraint worth an
explicit assertion in `serialize_provider_request` rather than here.

## Drift / decisions

### D1 — the model pin is one-way no longer, and that has an operational cost (Read 777-781)
`result["model"]` must now equal `MODEL_SLUG` exactly. Correct for trust, but if
the vendor echoes a dated snapshot (`…-2026-01-01`) every live call fails closed
with `unsupported_response`. No test exercises a live or recorded real response,
so this cannot be settled by the suite. Needs either an allowlist of accepted
echoes or a recorded fixture from a real call before it ships.

### D2 — `usage` accepts only three keys (Read 787-793)
A vendor adding `prompt_tokens_details` is rejected as `unsupported_response`.
Strictness is defensible for an audit tool, but it is a compatibility landmine
that no test names.

### D3 — the count cap is undocumented in the parser's contract (Read 946-951)
`MAX_PROPOSALS` is enforced; the docstring still describes the shape only. A
reader cannot learn the limit from the function they are calling.

## Memory

`local_memory__memory_store` is not bound to this worker session (my tools are
read/search/write only), so I am not claiming a write. The one durable fact:

```
s: policy-evidence-engine parse_provider_proposals
p: ACCEPTS_LONE_SURROGATES
o: rationale is checked only for non-empty str; the adapter's strict UTF-8 encode
   blocks the production path, so this is latent, not exploitable
source: project:verification
```
