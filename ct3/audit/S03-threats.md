# Slice 3 — threat audit of the dispatch path

**Range audited:** `backend/app/provider_safety.py:498-703` at the revision where the
file is 987 lines. Line numbers below are from that read; the file has moved during
earlier slices, so they are indicative, not stable.

**Read:** `_valid_transport_dispatch_authorization` (498-513),
`_consume_transport_dispatch_authorization` (516-529), `BoundedTransportProvider`
(532-636) including `assess_serialized`, `_bind_boundary`, `_assess_from_boundary`,
`_assess_async`, and the head of `BasetenMuseSparkOpenAdapter` (638-703).

**Not executed.** No terminal in this session, so every statement below is Read
(line) or Inferred from the code path. The two probes that would upgrade the two
main findings to Observed are named at the end.

---

## What holds under attack

- **Boundary cannot be bypassed from the provider side.** `BoundedTransportProvider.__init__`
  requires `type(transport) is HttpxAsyncTransport` (537) and exact-type gate (539);
  `assess_serialized` always raises `mandatory_boundary_required` (553-555), so the old
  public dispatch path is closed. `_assess_from_boundary` re-checks boundary identity,
  `boundary._provider is self`, transport type and gate type at call time (566-570), so a
  provider bound to a different boundary cannot be driven.
- **Exact-type checks beat `isinstance`.** `type(adapter) is BasetenMuseSparkOpenAdapter`
  and `type(boundary) is MandatoryProviderBoundary` (504-512) mean a subclass cannot
  inherit trust.
- **The single-flight lock does not block the event loop.** `acquire(blocking=False)`
  (616) fails fast with `concurrent_request` instead of waiting, so an async caller can
  never park the loop on a `threading.Lock`. Release is in `finally` (634-635), so it
  holds across exceptions, `ProviderSafetyError`, and task cancellation.
- **The gate is reserved inside the lock**, so two coroutines cannot both reserve the last
  permitted call: the second never reaches `authorize_request` (618).

---

## F1 — a response can leak its connection on cancellation (latent, highest real risk)

**Mechanism.** `exchange()` (620-623) does `response = await self._transport.send(...)`
and then `return await _read_bounded_response(response)`. Closing lives *inside*
`_read_bounded_response` (`finally: await aclose()`), so it only runs once that
coroutine has started. `asyncio.wait_for(exchange(), ...)` (625) cancels at an await
point; if cancellation lands after `send` returned and before `_read_bounded_response`
is entered — or during the `await` inside it, before its `try` is set up — the response
object is dropped without `aclose()`. The lock is released (634), so the next request
proceeds against a transport whose connection was never returned.

**Consequence.** On a busy provider path with client timeouts, response objects and
HTTPX connections accumulate until the pool is exhausted; the visible symptom is
`provider_failure`/`timeout` on *unrelated* requests, far from the cause.

**Cheapest mitigation.** Hold the response in a local and close it in a `finally` that
wraps both awaits, or make `exchange` itself:

```python
response = await self._transport.send(...)
try:
    return await _read_bounded_response(response)
finally:
    await response.aclose()
```

and have `_read_bounded_response` tolerate a double close (it already may).

**Discriminating check.** Cancel a task at the await between `send` and read (a double
whose `read_chunk` awaits `asyncio.sleep(0)` and a transport that records `aclose`), then
assert `transport.aclose_calls == 1`. Under the current code it is 0.

---

## F2 — `_assess_async` validates the timeout twice in a row (drift)

**Mechanism.** Lines 604-619 contain the same `valid_timeout` expression and the same
`raise ProviderSafetyError("invalid_timeout")` twice, back to back. The second block is
unreachable-in-effect: it recomputes an identical predicate and cannot differ.

**Consequence.** No behavioural risk today, but the function no longer has the same shape
as `_assess_from_boundary`, which validates once (573-581). A future edit to one copy
leaves the other stale, and the duplicated block already makes the guards harder to
review — which is how the `request_too_large` overload in slice 1 survived.

**Cheapest mitigation.** Delete the second block; assert in a test that
`invalid_timeout` is raised exactly once for `timeout_seconds=0`, `float("nan")`,
`True`, and `MAX+1`.

---

## F3 — the transport's real exception is discarded (diagnosability)

**Mechanism.** `except Exception: raise ProviderSafetyError("provider_failure") from None`
(630-631). `from None` suppresses the chain, and nothing in this range logs.

**Consequence.** An audit product that cannot say *why* a provider call failed. The
failure is indistinguishable between DNS, TLS, a 500, and a marshalling bug — and the
gate quota has already been spent.

**Cheapest mitigation.** Keep the code stable but attach a cause: log the exception at
`warning` on a dedicated logger, or carry a stable `error_class` field on the raised
`ProviderSafetyError` derived from `type(exc).__name__` (not the message, which may echo
provider content).

---

## F4 — the gate is consulted after the single-flight lock, so the reported cause can be wrong

**Mechanism.** Order is: acquire single-flight (616) → `authorize_request()` (618). When
the provider is disabled or over budget *and* another call is in flight, the caller that
arrives second sees `concurrent_request`, not `provider_disabled`/`request_limit`.

**Consequence.** An operator reading error codes sees contention when the truth is
"budget exhausted", which is the code that should page someone. Low severity, but it
inverts the priority of two very different operational states.

**Cheapest mitigation.** Check the gate's configuration before taking the lock
(`if not self._gate.enabled: raise provider_disabled`) and leave the reservation inside
the lock.

---

## F5 — replay is bounded by quota, not by request identity (by design, worth stating)

**Mechanism.** `SerializedProviderRequest` is an immutable sealed value; nothing in this
range records that a given request object was already dispatched. `_TransportDispatchAuthorization`
exists and is single-use (slice 2), but it is minted and consumed by the transport, not
here — so at *this* layer the same request can be sent again.

**Consequence.** Bounded: every dispatch reserves one unit of the gate (618), and a gate
without an enabled config refuses outright (`provider_disabled`). Without a budget this
would be unbounded; with the fail-closed default it is not.

**Cheapest mitigation.** None required; document the bound where the class is described,
so a future reader does not assume request-level idempotence.

---

## F6 — cancellation spends quota and never refunds

**Mechanism.** `authorize_request()` reserves before `exchange()` (618), and nothing
refunds on cancellation or timeout.

**Consequence.** Consistent with the documented "attempts, not successes" policy, and it
is the safe direction (a cancelled call still cost money). Worth naming because a client
that retries on timeout burns the budget faster than its success rate suggests.

**Cheapest mitigation.** None; state it in the budget docstring, which already says
retries consume quota.

---

## Cross-slice note — the lock and the budget are per process

`_TRANSPORT_SINGLE_FLIGHT` is a module global, so single-flight is per interpreter. Under
a multi-worker deployment, N workers allow N concurrent provider calls, and a per-instance
`ProviderCallGate` gives N × `max_requests`. Neither is a defect in this slice — the gate
is only active when a caller passes an enabled config — but the guarantee "one call at a
time" is process-local and should be described that way wherever it is relied upon.

---

## Ranked

| # | Finding | Class |
|---|---|---|
| F1 | response/connection leak on cancellation between send and read | latent, real |
| F3 | transport cause discarded, no trace | diagnosability |
| F2 | duplicated timeout validation in `_assess_async` | drift |
| F4 | gate checked after the lock, wrong error code under contention | minor |
| F5 | replay bounded only by quota | by design, document |
| F6 | cancellation burns quota | by design, document |

## Unrun — the two probes that would settle F1 and F4

1. `asyncio` cancellation between `send` and read, asserting `aclose` was called exactly
   once. Current expectation: zero calls, so F1 fails.
2. A disabled gate plus a held single-flight lock, asserting which code is raised.
   Current expectation: `concurrent_request`, which is F4.
