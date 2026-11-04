# Slice 4 / worker 2 — `_parse_response` and `_reject_surrogate_text`

Range read: `app/provider_safety.py:750-840` (the numbering shifted by the coordinator's
`MAX_PROPOSALS` and model-pin edits, so line numbers below are from the file as it stands
now and each is paired with the quoted code so they stay checkable).

Nothing executed — no terminal in this session. Every verdict is Read or Inferred.

## Branch table

| # | Line | Check | Attack it blocks | Input that still passes |
|---|---|---|---|---|
| 1 | 757 | `type(body) is not bytes` | str/bytearray smuggling | a `bytes` subclass is rejected too (exact type) — correct, but it also rejects `memoryview(...).tobytes()`? No: that is plain `bytes`. OK |
| 2 | 760-764 | strict UTF-8 decode + `json.loads` with duplicate-key and constant hooks | invalid encoding, `NaN`/`Infinity`, duplicate keys at any depth | a 4 KiB body with ~900 levels of nesting parses, then #3 recurses |
| 3 | 764 | `_reject_surrogate_text(result)` | lone surrogates (`"\ud800"`) that survive `json.loads` and would later fail `.encode("utf-8")` | nothing: str, list and dict (keys included) are all walked |
| 4 | 767-770 | `except (UnicodeDecodeError, JSONDecodeError, TypeError, ValueError, RecursionError)` | a hostile body becoming a 500 | — `RecursionError` was added by the coordinator this session; before that a deep body escaped unclassified (see finding 3) |
| 5 | 772-775 | top-level allowlist `{id,object,created,model,choices,usage}` | vendor envelope smuggling (markdown, tool calls, error objects) | a legitimate response carrying `system_fingerprint` — rejected as `unsupported_response` (finding 1) |
| 6 | 776-777 | `model` is a non-empty str | null/missing model | — |
| 7 | 778-781 | `model == MODEL_SLUG` | a response from a model nobody approved | — new in this session; it is the only two-way pin in the file |
| 8 | 782-783 | `id` optional, must be str | type confusion in the optional field | any string, including one that looks like a UUID — not validated, not used |
| 9 | 784-785 | `object` must be `"chat.completion"` | streaming/chunk envelopes | — |
| 10 | 786-787 | `created` int, not bool | bool-as-int confusion | negative or absurd timestamps pass; not used downstream |
| 11 | 788-795 | `usage` ⊆ {prompt,completion,total}, ints ≥ 0, no bools | negative/float/bool accounting | `{}` passes (all keys optional); `{"total_tokens": 1}` passes |
| 12 | 797-799 | exactly one choice, dict | multi-choice or chunked streaming | — |
| 13 | 800-801 | choice keys exactly {index,message,finish_reason} | `logprobs`, `tool_calls`, vendor extras | — fail-closed, documented |
| 14 | 802-803 | index is int 0 (not bool) | off-by-one choice selection | — |
| 15 | 804-805 | `finish_reason == "stop"` | truncated (`length`) or filtered output being read as a complete answer | — |
| 16 | 808-813 | `refusal` present and non-blank → `provider_refusal`; present and blank/None → `unsupported_response` | a model refusal being parsed as an empty success | — |
| 17 | 814-816 | message keys exactly {role,content}, role `"assistant"`, content non-blank str | role spoofing, empty content | whitespace-only is rejected by `.strip()` |
| 18 | 817-821 | `content.encode("utf-8", strict)` | unencodable text | unreachable in practice: #3 already rejected surrogates. Belt-and-braces, harmless |
| 19 | 822-824 | `parse_provider_proposals` then `if not proposals: empty_output` | an empty array counting as a successful assessment | `[]` from the *parser* is fine; only the adapter rejects it — the asymmetry is deliberate but undocumented |

## Over-strictness: can a legitimate response fail?

Yes, in one place that matters. The top-level allowlist (#5) and the choice allowlist (#13)
reject any key they do not know. A real OpenAI-compatible completion may carry
`system_fingerprint` (common), `service_tier`, or per-choice `logprobs`. Any of them turns a
good answer into `unsupported_response`.

That is consistent with the class docstring ("additional response fields or variants fail
closed"), so it is not a contract violation — it is a **deployment risk**, and it is the one
thing on this list that a live call would hit on day one. Mitigation, if wanted: ignore a
fixed set of known-benign extra keys rather than dropping the allowlist.

The model pin (#7) is the other one to watch. It is correct in principle, but it is new and
unexercised against the real vendor; if Baseten echoes a versioned slug
(`meta-models/muse-spark-open-0815`) every live call now fails closed. Failing closed is the
right direction; the value of `MODEL_SLUG` still has to be checked against a real response.

## Cost of `_reject_surrogate_text`

It is recursive over list and dict, and it visits every node once, so a 4 KiB body is at most
~4096 nodes — microseconds, no allocation. Depth equals JSON nesting depth; at roughly 900+
levels both `json.loads` and this walk approach the interpreter recursion limit, and either
can raise `RecursionError`. Both are now inside the `except` tuple, so the outcome is
`malformed_response` rather than a 500. Before that change, a deeply nested body escaped as an
unclassified error — the fix is what makes this function safe to be recursive.

## Ranked findings

1. **(deployment, medium)** A legitimate response with `system_fingerprint` / `service_tier` /
   `logprobs` is rejected as `unsupported_response`. Fail-closed by design, but it will surface
   as a total provider outage the first time the vendor adds a field, and the error will look
   like a malformed response rather than an allowlist decision. Consider a named error code for
   "unrecognised but well-formed envelope".
2. **(security, low, now closed)** `RecursionError` was outside the `except` tuple; a deeply
   nested body produced an unclassified error. Adding it to the tuple (this session) is the fix.
   Worth a regression test with ~1200 levels of nesting.
3. **(correctness, low)** `usage` accepts `{}` and `{"total_tokens": 1}` because it uses
   `issubset`. Harmless today (nothing reads usage), but a future cost-accounting caller would
   silently under-count. Name it in the docstring or require all three keys.

## Worth checking by the coordinator

- The model pin has no test and no recorded live echo. One captured vendor response would settle
  both #7 and finding 1.
- The `[]`-vs-`empty_output` asymmetry is deliberate but unstated in either docstring.

## Memory

Two facts stored (`inserted: 2`): `policy-evidence-engine model pin` · `LACKS_LIVE_ECHO` and
`policy-evidence-engine response allowlist` · `REJECTS_VENDOR_EXTRAS`.

**Correction to this report as first written:** it said `local_memory__memory_store` was not
bound to this session. That was wrong. The tool was available; I inferred "absent" from the
tool list in my brief instead of attempting the call, which is the same false negative several
siblings hit today. A call that was never tried is not evidence of a missing tool.
