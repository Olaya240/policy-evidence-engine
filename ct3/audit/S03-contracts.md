# Slice 3 contract audit — `provider_safety.py:498-703`

Read at the on-disk state of `/home/alex/policy-evidence-fix/backend/app/provider_safety.py`
(987 lines at the time of reading; the file grew during the previous slices, so line numbers are
from this read only).

No file under `app/` or `tests/` was modified. Nothing was executed: no terminal in this session,
so every claim below is **Read** (with a line) or **Inferred** (with the step it depends on).

| Definition | Line | Contract stated | Enforced? | Input it accepts that the contract does not describe |
|---|---|---|---|---|
| `_valid_transport_dispatch_authorization` | 478–514 | "Validate … authorization" | Yes — type, seal, `_consumed`, transport identity, payload identity, timeout equality, then the adapter/boundary/gate triple by identity | A **consumed** authorization is rejected (good), but a *valid* one is returned `True` without being consumed — the name suggests a gate, the function is only a predicate |
| `_consume_transport_dispatch_authorization` | 517–529 | "Validate and consume … atomically" | Yes — re-validates under `authorization._consume_lock`, then sets `_consumed` | Nothing; the lock is per-authorization, so two different authorizations can be consumed independently (correct) |
| `BoundedTransportProvider.__init__` | 532–548 | "Exact approved remote adapter" | Yes — `type(transport) is HttpxAsyncTransport`, optional gate type-checked, object sealed | `gate=None` silently installs a **fresh disabled** gate; the class docstring does not say the provider then refuses every call |
| `assess_serialized` | 556–558 | "Reject the former public dispatch path" | Yes — always raises `mandatory_boundary_required` | Nothing; it is a deliberate tombstone |
| `_bind_boundary` | 560–563 | Bind once | Yes — type-checked and refuses a second bind | Nothing |
| `_assess_from_boundary` | 566–591 | Synchronous dispatch only | Yes — full guard, size check, timeout validation, then `asyncio.run` when no loop is running | When a loop **is** running it raises `async_context_unsupported`, so from a FastAPI handler this entry point can never succeed (see finding 5) |
| `_assess_async` | 593–644 | Bounded single dispatch | Mostly — see findings 1–3 | The timeout is validated **twice** (607–614 and again at 615–622) |
| `BasetenMuseSparkOpenAdapter.__init__` | 652–669 | Approved adapter, disabled by default | Yes — exact type of transport, gate type, seals, back-binds the transport | `gate=None` has the same fail-closed implication as above |

## Findings, ranked

### 1. The timeout validation block is duplicated verbatim — 607–614 and 615–622
Two identical `try: valid_timeout = … except (OverflowError, TypeError, ValueError)` blocks, eight
lines each, back to back. The second can never change the outcome. This is a merge artifact: the
same guard preamble is also duplicated between `_assess_from_boundary` (577–586) and `_assess_async`
(596–606). Low severity, high signal — two copies of a security predicate are one edit away from
diverging, and the divergence would be silent because both currently agree.

### 2. The single-flight lock is process-wide and held across the network call — 623, 643
`_TRANSPORT_SINGLE_FLIGHT.acquire(blocking=False)` is non-blocking, so it cannot stall the event
loop — the earlier concern about a `threading.Lock` in async code does not apply to *this* use.
What it does instead is cap the whole process at one in-flight provider call, held across
`send`, the bounded read, and `parse_provider_proposals` (641). Under concurrent claims the loser
receives `concurrent_request` rather than queueing, so contention becomes user-visible errors.
Fail-closed is the right direction, but the ceiling and the error mode are undocumented.
Second-order: because the lock is released in `finally` while `asyncio.wait_for` cancels `exchange`,
a timeout that lands inside `self._transport.send` can abandon a response that was never returned to
`_read_bounded_response`, so nothing closes it. **Inferred** from 628–643; the transport's own
close-on-cancel behaviour lives in `httpx_transport.py`, outside this slice.

### 3. Every transport failure collapses into `provider_failure` with the cause discarded — 639–640
`except Exception: raise ProviderSafetyError("provider_failure") from None` loses the original
exception and the traceback, and there is no logging in this path. A recurring transport fault is
therefore indistinguishable from a malformed response, and impossible to diagnose from production
without reproducing. `ProviderSafetyError` itself is re-raised correctly (636–637), and
`CancelledError` is not caught because it derives from `BaseException` — both good.

### 4. `_valid_…` is a predicate that looks like a check-and-consume — 478–514
Returning `True` without consuming is defensible if `_consume_…` is the only caller. That cannot be
confirmed inside this slice: the call sites are transport-side (out of range), and `code_search` is
rooted at a different repository here, so I could not enumerate them. **Inferred**: a second caller
doing `if _valid(...): dispatch()` would be racy in exactly the way the lock exists to prevent.

### 5. The synchronous entry point cannot be used from the async server — 588–590
`asyncio.get_running_loop()` succeeds under FastAPI, and the code then raises
`async_context_unsupported` by design ("Never create an unmanaged loop or thread to escape the
mandatory boundary"). That is a coherent policy, but it means the bound provider is only reachable
from synchronous code; if any future handler is `async def`, the provider is unreachable there. The
docstring says "Application dispatch is synchronous", which states the assumption without stating
the consequence.

## What held under reading

- The boundary check is a genuine two-way identity chain: provider ↔ boundary ↔ adapter ↔ transport,
  each by `is`, plus `type(...) is`, plus the dispatch gate type (571–575, 596–601).
- Requests are re-checked at both entry points for seal and size (`_is_serialized_request`,
  `len(request) > MAX_REQUEST_BYTES`), so a payload cannot arrive unsealed even if the boundary is
  bypassed by constructing one directly.
- The gate is authorised **inside** the lock, so attempt counting cannot interleave.
- `assess_serialized` hard-fails rather than delegating, closing the old public path by construction.

## Not verified

- Call sites of `_valid_…`/`_consume_…` and whether the transport mints an authorization per
  dispatch (outside 498–703).
- Whether the transport closes its response on cancellation.
- Any runtime behaviour at all: this slice has no executed evidence from me.
