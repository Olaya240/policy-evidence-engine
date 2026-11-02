# Slice 3 — `app/provider_safety.py:498-703`

Scope read in full: the tail of `_consume_transport_dispatch_authorization`,
`BoundedTransportProvider` (constructor, `assess_serialized`, `_bind_boundary`,
`_assess_from_boundary`, `_assess_async`), and the first half of
`BasetenMuseSparkOpenAdapter`. I read on to 907 and 987 to close the adapter and
`MandatoryProviderBoundary`, because the dispatch path cannot be understood
without the boundary that binds it.

## The harness

`ct3/audit/slice3_properties.py` — five properties, executed against the real
classes. The only replacement is `BasetenMuseSparkOpenTransport._send_from_adapter`:
both dispatch guards are `type(x) is ...`, so a test double is impossible by
design, and patching the one network hop keeps every guard in force.

| # | Property | Expected |
|---|---|---|
| 1 | quota per attempt | first dispatch fails at the transport → `provider_failure`, `request_count == 1`; second → `request_limit`, count stays 1 |
| 2 | single flight | 5 concurrent dispatches with a gate of 5 → exactly 1 `provider_failure`, 4 `concurrent_request`, lock free afterwards |
| 3 | cancellation | cancelling mid-dispatch spends the reservation and releases the lock; task ends `CancelledError` |
| 4 | boundary wiring | arbitrary provider → `unsupported_provider`; unbound boundary → `mandatory_boundary_required`; second boundary for one adapter refused |
| 5 | legacy paths | `bounded_provider_call(object(), ...)` → `unsupported_transport`; `assess_serialized` → `mandatory_boundary_required` |

**Unrun.** No terminal in this session, so every row is an expectation, not a
result. Most likely to need adjustment: property 2, because `gather` schedules the
five coroutines in order and the first one to reach the lock wins deterministically
only if the event loop runs them in creation order — the assertion counts one
success and four refusals, which holds either way, but the *codes* list order is
not asserted. Second most likely: property 3, if cancellation lands before the
gate reservation (the `await asyncio.sleep(0.05)` should be sufficient, but that is
a timing assumption).

## Findings from reading (not properties)

1. **A duplicated validation block.** In `BoundedTransportProvider._assess_async`,
   immediately before `_TRANSPORT_SINGLE_FLIGHT.acquire`, the same five-line
   timeout check (`not isinstance(timeout_seconds, bool)` … `raise invalid_timeout`)
   appears twice verbatim. The second copy is unreachable in effect and dead in
   fact: it re-tests a value the first copy already accepted. It should be deleted;
   keeping it invites a future edit to change one copy only.

2. **Parsing sits outside the timeout.** In both `_assess_async` implementations,
   `asyncio.wait_for` wraps only `exchange()` (the network hop plus body read), and
   `_parse_response` / `parse_provider_proposals` run after it returns. A large but
   in-cap body is parsed with no deadline. Low severity — `MAX_RESPONSE_BYTES`
   bounds the work — but the timeout's contract reads broader than it is.

3. **`concurrent_request` is a rejection, not a queue.** The single-flight lock is
   acquired non-blocking, so the second concurrent caller fails fast instead of
   awaiting its turn. That is a defensible design (bounded latency, no queue to
   starve), but it means a burst of legitimate requests loses all but one. Worth
   recording as intentional in the module docstring, since `_TRANSPORT_SINGLE_FLIGHT`
   reads like mutual exclusion rather than admission control.

4. **The same triple guard is duplicated** across `_assess_from_boundary` and
   `_assess_async` (boundary identity, transport type, gate type), four lines each.
   Not a defect; a drift risk, since the two copies must stay in step.

## Memory

No memory tool is bound to this session (my available tools are file reads, edits
and searches), so I am not claiming a write. The durable fact, in storable form:

```
s: policy-evidence-engine BoundedTransportProvider._assess_async
p: DUPLICATES_TIMEOUT_CHECK
o: the five-line timeout validation is repeated twice verbatim before the
   single-flight acquire; the second copy is dead
source: project:verification
```
