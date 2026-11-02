# Slice 02 — contract audit: `app/provider_safety.py:292-505`

Scope note: the assigned range ended at 497, mid-body of
`_consume_transport_dispatch_authorization`. I read to 505 to include the end of that
function — a truncated read is not a read. Everything below is from the file as it stands
now (964 lines; slice 1's edits moved the boundaries). Nothing was executed.

Definitions in range:

| # | Definition | Line |
|---|---|---|
| 1 | `_read_bounded_response` | 292 |
| 2 | `ProviderBudgetConfig` | 322 |
| 3 | `_positive_decimal` | 331 |
| 4 | `ProviderCallGate` | 343 |
| 5 | `_TransportDispatchAuthorization` | 426 |
| 6 | `_valid_transport_dispatch_authorization` | 465 |
| 7 | `_consume_transport_dispatch_authorization` | 490 |

---

## 1. `_read_bounded_response` (292-317)

Contract: read the streaming body, never buffer more than `MAX_RESPONSE_BYTES` (4096),
reject a declared length that disagrees with the received body, always close.

Enforced by: the `+1` probe at 307, the `len(chunk) > requested` check at 309, the
`len(body) + len(chunk) > MAX_RESPONSE_BYTES` check at 314, the terminal
`len(body) != declared_size` check at 312, and `aclose` in `finally` at 316-317.

Answers to the specific questions:

- **Can it read more than the cap?** No. When `len(body) == MAX_RESPONSE_BYTES`, `requested`
  is `min(1024, 0 + 1) == 1` (307); a one-byte chunk then trips 314 before extending. The
  probe costs at most one byte of over-read from the socket, which is the point of 305-306.
- **`"0"` and `"0000000000"`**: both `isdecimal()` (305), both `int → 0`, both accepted; the
  first read returns `b""`, `len(body) == declared_size == 0`, returns empty (312-313).
  Leading zeros are therefore legal — harmless, because the overflow check does not depend
  on the declared value.
- **Header validation order.** 11+ digits → `malformed_response_headers` (306-308) before
  any integer conversion; a 10-digit value above the cap → `response_too_large` (310). The
  two errors are distinguishable to the peer, but neither reveals anything secret, and the
  length cap (10 chars) is redundant with the byte cap (4096 needs 4 digits) rather than
  protective.
- **Absent header**: `declared_size is None`, so the early-exit equality check at 312 is
  skipped and only the byte cap bounds the body. Correct.

Findings:

- **`aclose()` inside `finally` can replace the safety error** (316-317). If the transport's
  `aclose` raises, Python discards the in-flight `ProviderSafetyError` and propagates the
  close error instead, so a `response_too_large` becomes an unclassified exception. Fail-closed
  but off-taxonomy: it would surface as a 500 rather than the intended controlled error.
- **A non-`bytes` chunk is classified as `response_too_large`** (309). A `bytearray` or
  `memoryview` from an adapter is a type fault, not a size fault. This is the same defect
  class that slice 1 fixed for `request_too_large`: a mislabel hides a bug class behind a
  plausible client-facing code.
- `MAX_CONTENT_LENGTH_HEADER_CHARS` is used before the value is range-checked, so the
  constant protects nothing that 310 does not already cover. Documentation drift, not a bug.

## 2. `ProviderBudgetConfig` (322-329)

Contract: "explicit opt-in budget"; per-request cost must be a conservative estimate.

Enforced by: nothing at construction. It is a frozen dataclass with no `__post_init__`, so
`ProviderBudgetConfig(enabled=False, max_requests=-5, max_estimated_cost_usd=Decimal("NaN"))`
builds successfully. Validation happens only in `ProviderCallGate._validate_enabled_config`
(384-395) and only when `enabled` is true. Because the gate captures `_enabled` at
construction and is immutable, the invalid values cannot be activated later — so this is a
latent trap for the next caller (constructing a config, validating it by hand, then enabling
it elsewhere), not a live bypass.

## 3. `_positive_decimal` (331-341)

- `Decimal("0")`, negative, `NaN`, `sNaN`, `Infinity` → all rejected by 340 (`is_finite()`
  and `<= 0`); `sNaN` comparison would raise `InvalidOperation`, and `is_finite()` short-circuits
  first, so it is caught by the same line. Correct.
- `bool` → rejected at 333 before `Decimal` is ever consulted, so `True` cannot become 1.
- Leading/trailing whitespace **is** accepted: `Decimal(" 1 ")` parses to 1, and `1_0`
  becomes 10. Neither is a safety problem; both are undocumented liberality.
- `float` input is accepted (`Decimal(0.1)`), which imports binary float error into a money
  ceiling. A caller passing `0.1` gets `0.1000000000000000055511151231257827`. Since the
  ceiling check is `>` and the reservation is a sum of the same value, it stays consistent —
  but the type hint says `Decimal | str | None` and a float slips through with no error.

## 4. `ProviderCallGate` (343-424)

Contract: disabled by default; "reserve each attempt so retries consume quota too"; immutable.

Enforced by: `_enabled = config.enabled is True` (355), the reserve-before-send at 419-422,
and `__setattr__` (363-366).

Answers:

- **Does a failed call count?** Yes, by design: 419-422 increments and accrues before any
  send, and the comment says failures do not refund. `request_count` therefore measures
  *attempts*, while the property name says requests. Naming drift with a real consequence for
  anyone reading the counter as a success count.
- **Can a caller reserve and never call?** Yes. `authorize_request()` alone burns one request
  and one per-request cost; if the caller then raises before dispatch, the quota is gone.
  That is the safe direction (over-counting), but it means one buggy caller can exhaust the
  budget without a single provider call, and nothing reconciles reservations against
  completions.

## 5. `_TransportDispatchAuthorization` (426-463)

Contract: a per-call capability minted only after adapter validation and gate reservation; it
explicitly disclaims being an isolation boundary.

Enforced by: the sentinel check at 434, the identity-chain check at 441-451 (transport type,
adapter type, `adapter._transport is transport`, `adapter._boundary is boundary`, boundary
type and back-pointer, gate type), the payload type and cap, and the timeout validation in a
`try/except` that also catches `OverflowError` from `math.isfinite` on a huge int.

The disclaimer at 430-433 is accurate and is the right thing to have written down.

Finding: **payload identity is brittle.** 468 compares `authorization._payload is not payload`.
Any wrapper that normalises the payload (`bytes(payload)`, a concatenation, a re-encode) makes
a legitimate authorization fail validation, and the failure is reported as a misuse rather
than as "the transport copied the payload". It fails closed, so it is not a vulnerability;
it is a trap, and there is no test that exercises a copied-but-equal payload.

## 6-7. `_valid_…` (465-486) and `_consume_…` (488-505)

Contract: validate and consume atomically; single-use.

Enforced by: 496 `with authorization._consume_lock:`, the re-validation inside the lock at
497-499, and `_consumed = True` at 500. Two threads racing: both may pass the unlocked
`_valid_…` read of `_consumed`, but only one wins the lock and the loser's re-validation sees
`_consumed` true and returns False. Correct.

Note: `_consume_…` returns `False` rather than raising, so single-use enforcement depends
entirely on the caller (`BoundedTransportProvider`, slice 3) treating `False` as "do not
send". That is a contract the next slice must check; nothing in this range guarantees it.

---

## Ranked findings

1. **`budget_exceeded` is unreachable when the configuration validates.** (Inferred from
   390 and 418.) `_validate_enabled_config` rejects any config where
   `per_request * count > ceiling`, so after `k < count` reservations
   `(k+1) * per_request <= count * per_request <= ceiling` always holds and 418 can never fire;
   `request_limit` at 416 is the only reachable guard. Either the ceiling check is meant for a
   per-request cost that can change (it cannot; it is frozen) or it is dead defence. A dead
   branch in a budget gate is a branch no test can reach, which is exactly how it will rot.
2. **`aclose()` in `finally` can mask a `ProviderSafetyError`** (316-317). Converts a
   controlled rejection into an unclassified exception on any adapter whose close fails.
3. **A non-`bytes` chunk is reported as `response_too_large`** (309) — mislabelled, same
   family as the `request_too_large` overload fixed in slice 1.

Lower: `assert` used as a guard in security code (414-415, vanishes under `python -O`);
`ProviderBudgetConfig` unvalidated unless enabled; float cost accepted where the hint says
`Decimal | str`; `request_count` counts attempts.

## Not verified

No terminal, so nothing was executed: the unreachability of 418, the `aclose` masking, and the
payload-copy trap are all read-derived. One test each would settle them:
`ProviderCallGate(enabled=True, max_requests=1, conservative_cost_per_request_usd="1",
max_estimated_cost_usd="1").authorize_request()` twice (expect `request_limit`, not
`budget_exceeded`); an adapter whose `aclose` raises; and `_valid_…` with `bytes(payload)`.

Memory: this session exposes no local-memory tool, so no fact could be stored from here. The
one worth keeping: **`ProviderCallGate.authorize_request` reserves quota before dispatch and
never refunds, so `request_count` counts attempts, not calls** — a distinction the next slice
needs when it reads the counter.
