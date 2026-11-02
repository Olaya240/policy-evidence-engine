# Slice 2 — threat audit, `provider_safety.py:292-497`

Read range: `_read_bounded_response` (292-323), `ProviderBudgetConfig` (326-334),
`_positive_decimal` (336-346), `ProviderCallGate` (348-424),
`_TransportDispatchAuthorization` (426-468), `_valid_transport_dispatch_authorization` (470-491),
`_consume_transport_dispatch_authorization` (493-505). The slice boundary cuts the last function;
I read 493-505 to close it, and 498-522 to see `BoundedTransportProvider`'s constructor, which the
gate's isolation question depends on. Nothing executed.

Ratings: **A** exploitable now, **B** latent trap for the next caller, **C** documentation drift.

## 1. Response path

### Terminates, and the bound is real — A0 (no finding)

Infinite stream with `content_length=None`: `requested` shrinks as the body grows
(`min(CHUNK, MAX_RESPONSE_BYTES - len(body) + 1)`, line 315). Once the body reaches the cap,
`requested` is 1; the next one-byte chunk makes `len(body) + len(chunk) > MAX_RESPONSE_BYTES` and
line 323 raises `response_too_large`. Worst-case buffering is `MAX_RESPONSE_BYTES + 1` bytes,
then it stops. This is the one place the module's sizing discipline is airtight.

Declared-small-then-more and declared-`"0"`-then-data behave the same way: the byte cap bounds the
read regardless of what was declared, and the length mismatch is only reported at EOF (line 319).
A liar can therefore push the buffer to the cap, never past it.

### B1 — an empty chunk is treated as EOF, so a partial body can be accepted whole

Line 317: `if not chunk: ... return bytes(body)`. If the transport ever yields `b""` to mean *"no
data yet"* rather than *"stream finished"*, the body is truncated silently and returned as complete
when `declared_size is None`. Nothing downstream can tell a truncated payload from a short one; the
next component fails on malformed JSON, so the operator sees a JSON error where the truth was a
transport that stopped early. Either the transport contract must state that `b""` is final, or the
reader needs a sentinel.

### B2 — a non-`bytes` chunk is reported as `response_too_large`

Line 321 raises `response_too_large` when `not isinstance(chunk, bytes)`. A `bytearray` or
`memoryview` from a protocol-conforming transport is not oversized; it is a type violation, and
the operator-facing code says the wrong thing. This is the same defect class slice 1 fixed for
`serialization_accounting_mismatch`: an internal fault wearing a size error's message.

### B3 — no read timeout inside the loop

`await response.read_chunk(requested)` (line 316) has no per-read bound. The dispatch guard proves
`0 < timeout_seconds <= MAX_REQUEST_TIMEOUT_SECONDS` at mint time (426-468), but that value is never
consulted here. A transport that stalls mid-body holds the coroutine indefinitely; the size cap
bounds bytes, not wall time.

### B4 — an exception in `aclose` masks the real failure

`finally:` awaits `close()` (325-327). If closing raises, it replaces the in-flight
`response_too_large` / `malformed_response` error with the close error, so the audit trail names
the wrong fault. Worth a `try/except` that logs and re-raises the original.

## 2. Header parsing — A0 (no finding)

I tried to make each of these pass and could not:

| input | `isinstance(str)` | `isascii()` | `isdecimal()` | result |
|---|---|---|---|---|
| `b"42"` | no | — | — | `malformed_response_headers` |
| `"+42"` | yes | yes | **no** | rejected |
| `" 42"` | yes | yes | **no** | rejected |
| `"4_2"` | yes | yes | **no** | rejected |
| `"٤٢"` (Arabic-Indic) | yes | **no** | — | rejected |
| `""` | yes | yes | **no** | rejected |
| `"0042"` | yes | yes | yes | accepted, `int` = 42 |

The `len(...) > MAX_CONTENT_LENGTH_HEADER_CHARS` guard at line 300 runs *before* `int()`, so a
million-digit header is rejected without paying the quadratic parse. The `isascii()` +
`isdecimal()` pair is the correct combination here: `isdecimal()` alone would accept `"٤٢"`.

## 3. Budget — one real bypass

### A1 — the budget is per-gate, not per-process

`ProviderCallGate.__slots__` holds `_request_count` per instance (348-424), and
`BoundedTransportProvider.__init__` (511-522) does `ProviderCallGate() if gate is None else gate` —
a fresh, independent gate whenever a provider is built without one. Two providers, two budgets:
`max_requests × number_of_providers` calls, each gate reporting a truthful count. Nothing in this
range makes the gate a singleton, and nothing ties it to a boundary that would be single.

Whether this is reachable depends on who constructs `BoundedTransportProvider` — outside this slice.
Flagging it as a real bypass rather than a latent trap because the constructor's default path
creates the weaker configuration.

### B5 — `object.__setattr__` resets the counters

`authorize_request` deliberately increments with `object.__setattr__` (417-419) to bypass the
sealing `__setattr__`. Any in-process code can use the same call to zero `_request_count`. The
authorization docstring is honest that the seal is not a boundary against in-process code; the gate
carries no such statement, so a reader will assume it is one.

### A0 — counting itself is correct

`authorize_request` reserves *before* dispatch and never refunds (comment at 416), so failures and
retries consume quota. `_lock` is held only across non-awaiting arithmetic — no `await` inside the
`with` — so it cannot deadlock an event loop. Two gates are the problem, not the counter.

## 4. Dispatch authorization — bound, and replay-proof

Verified by reading:

- **Payload identity, not equality** (line 483: `authorization._payload is not payload`). Two equal
  `bytes` objects are different objects, so an authorization minted for one payload cannot be
  redeemed with a copy of the same bytes. This is the strongest binding available in-process.
- **Transport, adapter, boundary and gate are all identity-bound** (474-476, 487-492), and the
  adapter/boundary/gate triple is cross-checked for mutual identity, so a minted capability cannot
  be transplanted onto a second adapter.
- **Replay is atomic**: `_consume_...` takes `_consume_lock`, re-runs the full validation *inside*
  the lock, then sets `_consumed = True` before returning `True` (501-505). `_valid_...` returns
  `False` once `_consumed` is set (473). Two threads racing the same authorization get exactly one
  `True`.
- **Timeout is compared by equality** (481); `math.isfinite` at mint (443-448) keeps NaN out, and
  `NaN != NaN` would fail closed anyway.

### B6 — a non-consuming `_valid_...` sits next to the consuming one

`_valid_transport_dispatch_authorization` returns `True` without consuming. A caller that validates
and then dispatches on the strength of that answer has a replayable capability, and the two names
differ by four characters. The consuming function is the only correct entry point; the other should
be private-to-the-module or renamed to say it does not consume. This is exactly the trap the slice-1
audit found in `request_too_large`.

## 5. Ordering of what to fix

1. **A1** per-gate budget (does the default constructor create one gate per provider?).
2. **B2** error code for a non-bytes chunk — cheap, and it is the same defect class already fixed once.
3. **B1** empty-chunk contract — state it, or the truncation is invisible.
4. **B3/B4** read timeout and close-error masking.
5. **B6/B5** naming and the immutability claim on the gate.

`_TRANSPORT_SINGLE_FLIGHT` is not in this range; the lock question belongs to slice 3 (508+), which I
did not read past 522.
