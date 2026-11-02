# Slice 4b — second harness (envelope, model pin, cap, refusal, usage, grounding)

File: `ct3/audit/slice4b_properties.py`
Run: `cd /home/alex/policy-evidence-fix && PYTHONPATH=backend python ct3/audit/slice4b_properties.py`

Unrun: this worker session has no terminal. Every "expected" below comes from
reading `app/provider_safety.py`, not from executing it.

## What it covers, and what the code says should happen

| # | Property | Expected | Where the code enforces it |
|---|---|---|---|
| 1 | bodies nested 10 / 100 / 1k / 10k / 100k deep never raise `RecursionError` | `malformed_response` once `json.loads` recurses too far; a shape error (`malformed_output`) below that | `parse_provider_proposals` except tuple now includes `RecursionError` (≈929) |
| 2 | response `model` must equal `MODEL_SLUG` | exact match accepted; suffix, prefix, case variant, empty → `unsupported_response` | `_parse_response`, the pin added after the non-empty-string check (≈782) |
| 3 | proposal cap | 127 and 128 accepted, 129 → `malformed_output` | `_validate_provider_proposals` + `MAX_PROPOSALS = 128` (≈19) |
| 4 | refusal field | a real string → `provider_refusal`; empty or whitespace → `unsupported_response` | `_parse_response` refusal branch (≈810-815) |
| 5 | usage arithmetic | negative, float, bool, string → `unsupported_response`; valid triple accepted | usage block (≈790-797) |
| 6 | grounding precision | suffix quote accepted; homoglyph, null byte, quote from another record → `invalid_quote` | `quote not in records[source_id]` (≈945) |

## Divergence the harness records rather than passes

**Zero-width refusal.** The refusal branch is `type(refusal) is str and refusal.strip()`.
`str.strip()` does not remove U+200B, so a refusal of `"\u200b"` is treated as a real
refusal and returns `provider_refusal`. The harness asserts `provider_refusal` for that
case on purpose: if the code ever starts normalising zero-width characters the property
fails and the behaviour change is visible. A refusal that is *only* invisible characters
is arguably a refusal, so this is a documented judgement call rather than a defect.

## Finding for the coordinator (not patched here — outside this worker's files)

`_assess_async` in `BasetenMuseSparkOpenAdapter` awaits

    response = await self._transport._send_from_adapter(...)      # provider_safety.py:878
    return await _read_bounded_response(response)                 # :883

with no `try/finally`. `BoundedTransportProvider.exchange` gained exactly that
`finally: await _close_quietly(response)` earlier in this audit, for the cancellation
window between `send` returning and the bounded read starting. The adapter path has the
same window and no close, so the leak was fixed on one of the two dispatch paths only.
One three-line change closes it symmetrically.

## Most likely to fail on first run

Property 1 at depth 100,000: CPython's `json.loads` raises `RecursionError`, which the
parser now converts, but building the body with `"[" * depth` is itself cheap while the
decoder may raise at a much lower depth (~1000). The harness accepts any controlled
outcome, so it should pass; the case I am least sure of is 2's empty-model row, if an
empty string is caught earlier by the `not result["model"]` check and reported as
`malformed_response` rather than `unsupported_response`.

## Memory

No `local_memory__*` tool is bound to this worker session, so nothing was stored rather
than claiming a write. Durable fact for the coordinator:

- `policy-evidence-engine adapter dispatch` · `MISSES_CLOSE` · `_assess_async awaits
  _send_from_adapter at provider_safety.py:878 and reads the body at :883 with no
  try/finally, so cancellation before the bounded read drops the response unclosed;
  BoundedTransportProvider.exchange has the close, the adapter path does not`
