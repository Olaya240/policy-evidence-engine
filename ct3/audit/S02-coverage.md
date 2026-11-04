# Slice 2 coverage map — `app/provider_safety.py:292-497`

**Scope.** Response bounding, budget configuration, the call gate, and the dispatch
authorisation. Read by eye against `tests/`; **no coverage run** — every "not reached"
claim below comes from reading test bodies, not from a coverage report.

**Boundary caveat.** Line 497 is the signature of `_consume_transport_dispatch_authorization`;
its body starts at 498 and is therefore outside this slice. Its behaviour is nevertheless
covered by tests cited below, so I report it rather than leaving a hole.

**Method limitation.** `code_search` is rooted at a different repository in this session, so I
could not grep the tests tree for exact line numbers. Tests are cited by **file + exact test
name**; definitions carry verified line numbers. Nothing here should be quoted as a line
number I did not read.

---

## Definitions and the tests that reach them

| Definition | Line | Reached by |
|---|---|---|
| `_read_bounded_response` | 292 | `test_streamed_response_is_rejected_at_four_kib_before_json_parse`, `test_content_length_header_is_optional_but_validated` (5 params), `test_noncompliant_transport_oversized_chunk_is_rejected`, `test_timeout_cancels_slow_transport_and_returns_controlled_error`, `test_transport_single_flight_slot_is_released_after_failure_timeout_and_cancellation` — all in `tests/test_provider_safety.py` |
| `ProviderBudgetConfig` | 327 | every gate construction in `test_provider_safety.py` and `test_baseten_adapter.py::_gate` |
| `_positive_decimal` | 336 | only via `ProviderCallGate._validate_enabled_config`; `test_invalid_or_unapproved_budget_configuration_fails_closed` (4 params) and `test_bounded_provider_rejects_custom_gate_objects_and_subclasses` |
| `ProviderCallGate` | 348 | `test_disabled_gate_fails_closed_before_transport_call`, `test_validated_gate_limits_cannot_be_replaced_after_construction`, `test_concurrent_authorization_cannot_exceed_configured_request_cap`, `test_gate_configuration_and_counters_cannot_be_reassigned`, `test_request_limit_and_estimated_cost_reserve_failed_attempt_without_retry`, `test_baseten_failure_releases_single_flight_and_keeps_quota_reserved`, `test_baseten_cancellation_closes_stream_and_transport_and_releases_single_flight` |
| `_TransportDispatchAuthorization` | 426 | `test_baseten_adapter.py::_dispatch_capability` builds them in five tests: `..._rejects_mismatched_bindings_before_transport_construction`, `..._is_single_use_and_replay_stops_before_transport`, `test_concurrent_cross_thread_reuse_of_one_capability_authorizes_one_send`, the failure and cancellation tests |
| `_valid_transport_dispatch_authorization` | 470 | same five, via `transport._send_http` / `_send_from_adapter` |
| `_consume_transport_dispatch_authorization` | 493 | single-use replay test, and the cross-thread capability test (two threads, one `sent`) |

**Genuinely well covered, and worth saying so:** replay is tested (a second `_send_http` with a
consumed capability raises `mandatory_boundary_required`); concurrent cross-thread reuse is tested
with a `Barrier` and asserts exactly one send; payload binding is tested as **identity** —
`test_dispatch_capability_rejects_mismatched_bindings...` builds `bytes(bytearray(payload))`, asserts
`==` but `is not`, and requires rejection. The gate's concurrency is tested with 64 threads against
a cap of 7.

---

## Branches no test reaches

### `_read_bounded_response` (292-324)

| # | Branch | Why it matters |
|---|---|---|
| R1 | `content_length` is a **non-str** (e.g. `10`, `Decimal("10")`) → `malformed_response_headers` | The `not isinstance(declared_length, str)` arm is never exercised. `"10x"` covers a bad *string*, not a non-string. |
| R2 | `content_length` is ASCII-false but decimal (`"١٢"` Arabic-Indic digits) → `malformed_response_headers` | `int("١٢")` succeeds in Python, so `isascii()` is load-bearing and untested. |
| R3 | Body **exactly** `MAX_RESPONSE_BYTES` with a matching header → accepted | This is the whole reason for the `+1` in `requested`. Only `cap+1` (rejected) and tiny bodies are tested. An off-by-one here would reject every legal maximum-size response. |
| R4 | `read_chunk` returns a **non-bytes** (`str`, `None`) → raises `response_too_large` | Covered by the type check but raised under a size error code. A protocol violation is reported as an oversized body; the caller cannot tell them apart. |
| R5 | `aclose()` raises inside `finally` | It would replace the in-flight `ProviderSafetyError` with an unrelated exception and lose the error code. No test uses a response whose `aclose` fails. |
| R6 | `aclose` is actually invoked on the oversized path | `FakeResponse` in `test_provider_safety.py` defines no `aclose`, so the `getattr` fallback is taken and the close-on-reject guarantee is asserted nowhere. |

### `ProviderBudgetConfig` / `_positive_decimal` (327-345)

| # | Branch | Note |
|---|---|---|
| B1 | `enabled=1` (truthy, not `True`) → gate disabled | `is True` is deliberate fail-closed behaviour with no test, so a future refactor to `if config.enabled:` would silently change it. |
| B2 | `_positive_decimal(Decimal("NaN"))` / `Infinity` → `invalid_budget` | `is_finite()` arm untested. |
| B3 | value `<= 0` → `invalid_budget` | Untested; a zero ceiling is the obvious operator mistake. |
| B4 | bool (`True`) → `invalid_budget` | Explicit `isinstance(value, bool)` guard, no test. |
| B5 | undecodable string `"abc"` → `invalid_budget` | `InvalidOperation` arm untested. |

### `ProviderCallGate` (348-424)

| # | Branch | Note |
|---|---|---|
| G1 | **`budget_exceeded` is unreachable** | See finding 1 below. |
| G2 | `max_requests` of `0` or negative → `invalid_budget` | Only `18` (above `MAX_EXPERIMENT_REQUESTS`) is tested. |
| G3 | `max_requests=True` → `invalid_budget` | `isinstance(count, bool)` guard untested, same class as B4. |

### `_TransportDispatchAuthorization` (426-468)

| # | Branch | Note |
|---|---|---|
| D1 | `__setattr__` raises | Immutability of the capability is untested; `test_approved_adapter_is_immutable...` covers `BoundedTransportProvider`, not this class. |
| D2 | `timeout_seconds = 0` → `mandatory_boundary_required` | The `0 <` lower bound is untested; only `True`, `nan`, `20.01`, `10**1000` are. |
| D3 | Wrong-but-present `_seal` at construction | Only the correct seal is ever passed; `provider_safety` raising on a forged seal is never exercised. |

---

## Findings, ranked

**1. `budget_exceeded` cannot fire (line ~415).** `_validate_enabled_config` rejects any config
where `per_request * max_requests > ceiling`, and each reservation adds exactly `per_request`. By
induction the reserved total is `k * per_request` for `k <= max_requests`, so `projected` is at
most `max_requests * per_request <= ceiling`. The check reads as a second line of defence and is
dead. Either the constructor should allow `count * per_request > ceiling` (so the running check is
the real guard) or the branch should be deleted; today it is a safety assertion that can never
fail, which is worse than no assertion because a reviewer counts it. *Not a test gap — a design
gap.*

**2. Exact-cap response acceptance (R3).** The `+1` read exists precisely to distinguish "exactly
at limit" from "one over"; only the over case is tested. This is the highest-value missing test.

**3. Non-bytes chunk reported as `response_too_large` (R4).** A transport that yields `str` is a
protocol violation, not a size breach. Either give it its own code or document the conflation.

**4. `aclose` is never asserted to run on the rejection path (R6), and a raising `aclose` would
mask the real error (R5).** Leaked connections on the reject path are exactly the failure this
function is meant to prevent.

**5. Content-length type/`isascii` guards untested (R1, R2).** `int("١٢")` succeeds, so R2 is a
real load-bearing guard.

**6. Numeric validation surface untested (B2-B5, G2-G3).** NaN, zero, negative, bool, undecodable
string — five one-line tests.

**7. Capability immutability and the forged-seal path untested (D1, D3).**

---

## Tests that would pass for the wrong reason

- **`test_bounded_provider_boundary_rejects_concurrent_transport_call_without_spending_quota`**
  contains no concurrency. It constructs `BoundedTransportProvider(FakeTransport(), gate)` and
  asserts `unsupported_transport`. The name promises a concurrent-call guarantee that is actually
  delivered by a different test (`test_concurrent_authorization_cannot_exceed_configured_request_cap`)
  at a different layer. Rename or rewrite; as written it advertises coverage it does not have.
- **`test_noncompliant_transport_oversized_chunk_is_rejected`** asserts `response_too_large`, which
  is right for the chunk it sends, but that same code path also handles non-bytes chunks (R4). The
  test would still pass if the type check were deleted and the length check alone remained — it
  never sends a wrong-typed chunk.
- **`test_content_length_header_is_optional_but_validated`** parameter `("10x", b"{}", ...)` pins
  the *decimal* check but a non-str value would also reach it; the parameter name suggests the
  type guard is covered when it is not.

---

## Proposed tests, in order

1. `test_response_exactly_at_cap_is_accepted` — body of exactly `MAX_RESPONSE_BYTES`, header
   matching, expect the bytes back.
2. `test_response_close_is_invoked_when_body_is_rejected` — response with a recording `aclose`,
   oversized body, assert called once.
3. `test_aclose_failure_does_not_mask_safety_error` — `aclose` raises; expect `response_too_large`,
   not the close error.
4. `test_non_bytes_chunk_is_a_protocol_error` — chunk `"[]"`; expect a documented code.
5. `test_content_length_must_be_ascii_decimal_string` — `10` (int) and `"١٢"`.
6. `test_budget_rejects_non_finite_zero_negative_and_bool` — four params through
   `ProviderBudgetConfig(enabled=True, ...)`.
7. `test_gate_rejects_zero_and_bool_max_requests` — two params.
8. `test_dispatch_capability_is_immutable_and_rejects_a_forged_seal` — two asserts.

Each is a single test; none requires touching the module except finding 1, which needs a decision
first.

---

## Memory

Three facts stored against this slice: `HAS_DEAD_BRANCH` on `ProviderCallGate` (the
`budget_exceeded` proof above), `CUTS_MID_FUNCTION` on the slice boundary, and
`UNTESTED_BOUNDARY` on response bounding. Correction: an earlier line in the coordinator-facing
message said the memory tool was unbound in this session. It was not — the call succeeded, and the
earlier statement came from reading my tool list instead of attempting the call.
