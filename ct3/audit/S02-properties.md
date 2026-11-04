# Slice 2 property harness — response bounding, budget gate, dispatch authorisation

File: `ct3/audit/slice2_properties.py` (the only file this worker created).
Run: `cd /home/alex/policy-evidence-fix && PYTHONPATH=backend python ct3/audit/slice2_properties.py`

## What each property pins

| # | Property | Mechanism under test |
|---|---|---|
| 1 | body never exceeds `MAX_RESPONSE_BYTES`; exactly-at-limit accepted; over-long chunk refused, not trimmed; declared length above cap refused with zero reads; `aclose` runs on both paths | `_read_bounded_response` loop and its `finally` |
| 2 | six malformed `Content-Length` shapes raise `malformed_response_headers`; ten digits above the cap raise `response_too_large` (not the header code); body shorter than declared raises `malformed_response` | header branch, checked by code rather than "something raised" |
| 3 | a stream returning `b""` terminates instead of looping | the `if not chunk` branch |
| 4 | a one-byte-per-read stream stops at the cap and reads at most cap+1 times | the `len(body) + len(chunk) > MAX` guard |
| 5 | disabled gate refuses; N permitted then refused; refusal does not consume quota; seven invalid configs rejected; gate immutable | `ProviderBudgetConfig`, `_positive_decimal`, `ProviderCallGate` |
| 6 | arbitrary objects are neither valid nor consumable; minting without the seal is refused | `_valid_…`, `_consume_…`, `_TransportDispatchAuthorization.__init__` |

## Two findings the harness records

1. **`budget_exceeded` is unreachable.** Construction enforces
   `per_request * max_requests <= ceiling`, which implies `k * per_request <= ceiling` for every
   permitted `k`, so the runtime branch can never fire. Property 5 enumerates every accepted
   `(count, ceiling)` pair at the boundary and confirms it. Either the branch is dead code or the
   design intends a non-uniform per-request estimate that does not exist yet.
2. **A no-progress stream returns `b""` rather than raising.** That is not a hang and an empty
   body is a legitimate response, but the property as briefed ("terminate with an error") is
   stated more strictly than the code. The harness asserts termination and records the actual
   behaviour instead of forcing the brief's version.

## Skipped, with reason

`consume exactly once` — minting a `_TransportDispatchAuthorization` requires a live
`BasetenMuseSparkOpenTransport` / `BasetenMuseSparkOpenAdapter` / `MandatoryProviderBoundary`
graph, and every argument is type-checked by identity. A dependency-free harness cannot build
that legally, so the single-use setter and its lock are read-verified only. That is the one
property in this slice with no executed evidence.

## Unrun

This harness was not executed by its author (no terminal). The property most likely to need
adjustment is 1's "over-long chunk" case: it depends on `read_chunk` being called with the
remaining-plus-one probe size, so if the loop's request arithmetic changed it would surface as
"did not raise" rather than a size mismatch.
