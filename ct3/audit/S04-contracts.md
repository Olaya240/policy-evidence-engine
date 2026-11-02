# Slice 4 contract audit — `provider_safety.py:704-909`

Read 704-957 so that `parse_provider_proposals` and `_validate_provider_proposals` are
closed rather than cut mid-function. `MandatoryProviderBoundary` begins at 958 and belongs
to slice 5.

Nothing executed (no terminal in this session). Every line reference below was re-read; every
consequence is tagged.

## Definitions

| Definition | Line | Stated contract | Enforced | Accepted but undescribed |
|---|---|---|---|---|
| `_wire_request` (tail) | ..738 | envelope must carry exactly the serialised keys | `set(raw) == required` before rebuild; `user_content` rebuilt from validated parts only | a record whose `text` is control-character-only passes; no such guard exists |
| `_reject_surrogate_text` | 742 | reject lone surrogates anywhere in the tree | walks `str`, `list`, `dict` keys and values | recursion depth is unbounded (see F1) |
| `_parse_response` | 754 | strict vendor-envelope parse | top-level keys exactly `{model, choices, usage}`; `choices` a 1-element list; `message` exactly `{role, content}`; `finish_reason == "stop"`; non-empty content; `usage` values ints ≥ 0 | `model` only checked as a non-empty string (see F2) |
| `_assess_from_boundary` | 820 | sync entry, refuses under a running loop | four-way identity chain, timeout validation, then `async_context_unsupported` | — |
| `_assess_async` | 843 | the only live dispatch path | identity chain, timeout, single-flight lock, gate reserved inside the lock, `wait_for` around network + read | parsing happens outside `wait_for`, so it is bounded by bytes, not by time |
| `bounded_provider_call` | 881 | legacy helper fails closed | raises `unsupported_transport`, then `mandatory_boundary_required` | — |
| `_reject_duplicate_object_keys` | 888 | duplicate keys are fatal | `object_pairs_hook` on every object, nested included | — |
| `_reject_nonstandard_json_constant` | 897 | `NaN`/`Infinity` are fatal | `parse_constant` hook | — |
| `parse_provider_proposals` | 901 | parse the neutral proposal JSON | bytes type, strict UTF-8, duplicate keys, constants, then shape/provenance | returns `[]` for `[]` (see Q4) |
| `_validate_provider_proposals` | 929 | provenance and shape | exact 4 keys per item; `source_record_id` must be a serialised record; `quote` a substring of that record; stance vocabulary; rationale non-empty string | no limit on item count (F3) |

## The five questions

**1. What `parse_provider_proposals` accepts.** In order: `type(body) is bytes` (902);
`body.decode("utf-8", errors="strict")` (905); `json.loads` with `object_pairs_hook=
_reject_duplicate_object_keys` and `parse_constant=_reject_nonstandard_json_constant`
(907-911); then `_validate_provider_proposals` (918): `type(result) is list` (931); each item
`type is dict` and `set(item) == {"source_record_id","quote","stance","rationale"}` (934);
`source_record_id` a `str` and present in the request's record map (938-940); `quote` a `str`,
stripped length ≥ 3, and `quote in records[source_id]` (941-943); `stance` in `Stance` values
(944-946); `rationale` a non-empty `str` (952-953).

**2. Quote binding.** `quote not in records[source_id]` is a **substring membership test
against the record named by `source_record_id`** (941-943). A quote drawn from a *different*
record cannot pass, because the map is keyed by id and only that record's text is searched.
The floor is three characters after stripping, so a generic fragment such as `"the"` can
satisfy it.

**3. Duplicate keys.** Handled by `object_pairs_hook` (761, 906), which applies to every
object at every depth, so `{"a":1,"a":2}` raises `malformed_response` rather than silently
keeping the last. Whether any test exercises a duplicate is **Unknown** — I did not read the
test bodies in this session.

**4. Degenerate shapes.** Empty array → `parse_provider_proposals` returns `[]` with no
error, while `_parse_response` raises `empty_output` at 816-817: the two entry points
disagree. 129 items → accepted; there is no count cap. A 1 MiB item → bounded only by
`MAX_RESPONSE_BYTES` upstream. Empty quote → `invalid_quote` via the length floor.

**5. Adapter re-validation.** `_parse_response` validates the vendor envelope and then hands
`proposal_bytes` to `parse_provider_proposals`, so proposals are validated once, by the
parser. Nothing is validated twice. A missing or extra field in either layer is
`malformed_response`; a non-`stop` finish reason is `unsupported_response`. Content type is
never seen at this layer — the transport returns a body — so a provider answering with the
wrong media type is indistinguishable here.

## Top three findings

**F1 — `RecursionError` escapes both parsers. (Inferred; one probe settles it.)**
At 762 and 912 the `except` tuple is `(UnicodeDecodeError, json.JSONDecodeError, TypeError,
ValueError)`. `json.loads` raises `RecursionError` on deeply nested input, and
`_reject_surrogate_text` (742-752) recurses once per nesting level. A hostile or malformed
body therefore produces an unclassified 500 instead of `malformed_response` — the same
"internal fault wearing the wrong clothes" pattern the slice-1 and slice-2 fixes removed.

**F2 — the response's `model` is never compared to `MODEL_SLUG`. (Read.)**
The request pins the model; the response's echoed `model` is only checked as a non-empty
string. A response from any other model passes the provenance gate, so the pin is one-way.

**F3 — no cap on proposal count. (Read; consequence inferred.)**
`_validate_provider_proposals` iterates without a limit (929-955). At roughly 80 bytes per
item the 1 MiB response cap admits on the order of thirteen thousand proposals, each of which
becomes claim evidence downstream.

## Lower-severity notes

- `_validate_provider_proposals` wraps request re-parsing in `except Exception` and reports
  `invalid_request` (929-934), attributing an internal fault to the client.
- The three-character quote floor (941) is weak provenance: a fabricated fragment can match.
- Parsing sits outside `asyncio.wait_for` (843-878), so time is bounded by bytes only.
