# Slice 4 — over-strictness review (worker 9 of 10)

Scope: `backend/app/provider_safety.py` lines 704-1002 — `BasetenMuseSparkOpenAdapter._wire_request`,
`_reject_surrogate_text`, `_parse_response`, `parse_provider_proposals`,
`_validate_provider_proposals`.

Method: read only, nothing executed. **Line numbers in this file shifted twice during the audit**
(the module went 883 → 1002 lines), so each check is cited by its condition text and an approximate
line. Treat `~NNN` as "within a few lines of".

The question this report answers: the parser was hardened against hostile input, so where does that
hardening now reject output a correct provider would legitimately send?

---

## 1. Every rejection, and whether a correct provider can trigger it

### Envelope (`_parse_response`, ~777-830)

| Check | Condition | What a correct provider may send | Risk | Verdict |
|---|---|---|---|---|
| top-level allowlist | keys ⊆ `{id, object, created, model, choices, usage}` | OpenAI-compatible hosts add `system_fingerprint`, `service_tier`, sometimes `prompt_filter_results` | **High** | relax: ignore unknown top-level keys |
| model non-empty str | `type(...) is not str or not ...` | fine | Low | keep |
| **model must equal `MODEL_SLUG`** | `result["model"] != MODEL_SLUG` | a versioned echo, e.g. `…/muse-spark-8b-instruct-2026-01`, or the slug plus a date suffix | **High** | keep as a pin, but give it its own code and decide the suffix rule against a recorded response |
| id type | `type(result["id"]) is not str` | fine | Low | keep |
| object must be `chat.completion` | equality | streaming would be `chat.completion.chunk` — we do not request streaming | Low | keep |
| created int (not bool) | type check | epoch seconds | Low | keep |
| usage allowlist | keys ⊆ `{prompt_tokens, completion_tokens, total_tokens}` | `prompt_tokens_details`, `completion_tokens_details`, `prompt_cache_hit_tokens` are standard on OpenAI-compatible APIs | **High** | relax: ignore unknown usage keys (nothing reads them) |
| choices exactly one | `len(choices) != 1` | a provider configured with `n>1` returns several; we never set `n` in the wire body (~735-745) | Medium | keep the rejection, distinct code |
| choice allowlist | keys == `{index, message, finish_reason}` | `logprobs: null` is emitted by default on OpenAI-compatible APIs | **High** | relax: require the three, ignore the rest |
| index must be 0 | equality | fine | Low | keep |
| finish_reason must be `"stop"` | equality | `"length"` on a truncated call | Medium | keep rejection, code `truncated_output` |
| message allowlist | keys == `{role, content}` | `tool_calls`, `annotations`, `audio`, and `refusal` (the last is handled deliberately at ~818) | **High** | relax: require role/content and types, keep the `refusal` semantic check, ignore the rest |
| role must be `assistant` | equality | fine | Low | keep |
| content non-empty str | type + `.strip()` | newer APIs can return an array of content parts | Medium | keep, distinct code |
| surrogate rejection | any lone surrogate in the tree | UTF-8 strict decode already forbids this on the wire | Low | keep (defence in depth) |
| duplicate JSON keys | `object_pairs_hook` | no correct provider emits duplicates | Low | keep |
| `NaN` / `Infinity` | `parse_constant` | no | Low | keep |
| empty proposals | `_parse_response` raises `empty_output` on `[]` | a legitimate "nothing to report" answer | Medium | keep rejecting, but see §4 |

### Proposals (`_validate_provider_proposals`, ~946-966)

| Check | What a correct provider may send | Risk | Verdict |
|---|---|---|---|
| top-level must be a list, count ≤ `MAX_PROPOSALS` (128) | ≤128 items; our request caps at 128 records, so the bound matches | Low | keep |
| item keys exactly `{source_record_id, quote, stance, rationale}` | our own output instruction asks for exactly that; extras are a model error | Low | keep |
| `source_record_id` must be in the request | fine | Low | keep |
| `quote` length ≥ 3 and substring of **that** record's text | typographic quote substitution (`’` for `'`), reflowed whitespace, or elided ellipses | Medium | keep (retryable), distinct code from fabrication |
| `stance` in our vocabulary | fine | Low | keep |
| `rationale` non-empty | fine | Low | keep |

---

## 2. Ranked by likelihood of breaking a real integration

1. **`choice` key allowlist** — `logprobs` is present by default on OpenAI-compatible responses.
   This is the one most likely to fail on the first live call.
2. **top-level key allowlist** — `system_fingerprint` is emitted by OpenAI and by gateways that
   mimic it.
3. **`usage` key allowlist** — token-detail sub-objects are standard.
4. **exact `model` equality** — a versioned echo is common; our own wire body sends a slug the
   provider may normalise.
5. **`message` key allowlist** — `tool_calls` / `annotations` appear only if the provider is
   configured for tools or citations, but nothing in the request forbids them.
6. **`content` as an array of parts** — depends on the vendor's default content format.
7. **`choices` length > 1** — only under provider-side configuration drift.
8. **`finish_reason == "length"`** — occasional, and the body would fail proposal parsing anyway.

---

## 3. Minimal relaxations (sketch only — no code changed)

- Replace the four key-set equalities with a shared helper that asserts the *required* keys are
  present with the right types and ignores unknown ones. Top level, `usage`, `choice`, `message`
  all currently read as "hostile field" what is usually "vendor field we do not use".
- Keep the `refusal` branch **before** that helper, or a response with `refusal: null` and
  `tool_calls` would be read as a schema error rather than as content.
- Give the model pin its own code (`model_mismatch`) so an operator can tell a versioned echo from
  a schema breach; decide separately whether to accept `MODEL_SLUG` as a prefix.
- Give `finish_reason == "length"` its own code (`truncated_output`); today it is indistinguishable
  from a malformed envelope.
- If array-shaped `content` is plausible for this vendor, map it to a distinct
  `unsupported_content_shape` rather than the generic envelope code.

---

## 4. Where strictness must stay

Types and required-key presence (that is what stops a `dict` where a `str` belongs), the `refusal`
handling, the stance vocabulary, quote grounding against the cited record, `source_record_id`
membership, duplicate-key rejection, non-standard-constant rejection, the 4 KiB body cap, the
128-proposal cap, single-flight, and the budget gate. Relaxing the *allowlists* costs nothing
because unknown fields are never read; relaxing the *type* checks or grounding would.

`empty_output` is worth a separate decision rather than a relaxation: the adapter converts a valid
"no findings" answer into an error, so a model that correctly reports nothing looks like a broken
provider. That is a semantic choice, not over-strict parsing, and it belongs to the caller.

---

## 5. What I could not settle

No recorded real provider response exists in the repository, so the two facts that would convert
§2 from a ranking into a measurement — the exact `model` echo string, and whether this vendor
emits `logprobs` by default — cannot be established by reading. One captured response body (or the
vendor's documented schema) answers both.

---

## 6. Memory

No `local_memory__*` tool is bound to this worker session; the tools available here are file reads,
edits and searches. Storable form, for the coordinator:

```
s: policy-evidence-engine proposal parser
p: REJECTS_VENDOR_FIELDS
o: key-set equalities on the envelope, usage, choice and message reject logprobs,
   system_fingerprint, token details and tool_calls, all standard on OpenAI-compatible APIs
source: project:verification

s: policy-evidence-engine model pin
p: IS_EXACT_MATCH
o: result["model"] must equal MODEL_SLUG, so a versioned echo is refused as unsupported_response
source: project:verification
```
