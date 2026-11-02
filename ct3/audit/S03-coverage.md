# Slice 3 coverage map — `app/provider_safety.py` lines 498-703

Read by reading, not by running. No terminal in this session, so there is no coverage
number here: every "not reached" claim comes from reading the test bodies.

## Method and its boundary

Files read in full: `tests/test_provider_safety.py` (591 lines), `tests/test_baseten_adapter.py`,
`tests/provider_test_support.py`, `tests/test_session_concurrency.py` (confirmed unrelated).

Files I did **not** open: `test_engine.py`, `test_api.py`, `test_httpx_transport.py`,
`test_transport_hardening.py`, `test_provider_safety_slice1*.py`, `slice2_contracts`. A gap listed
below may still be covered there; I am reporting what I can see, not what exists.

`code_search` is rooted at a different repository in this session, so test names are cited by
name rather than line.

## What reaches what

| Definition (line) | Reached by | Branches no test reaches |
|---|---|---|
| `_valid_transport_dispatch_authorization` 498-511 | `test_dispatch_capability_rejects_mismatched_bindings_before_transport_construction`, `test_dispatch_capability_is_single_use_and_replay_stops_before_transport` | the `type(adapter) is not BasetenMuseSparkOpenAdapter` and `type(boundary) is not MandatoryProviderBoundary` arms — every negative case fails on transport/payload/timeout first |
| `_consume_transport_dispatch_authorization` 514-526 | `test_a_dispatch_authorization_is_consumable_exactly_once` (slice-2 file), `test_concurrent_cross_thread_reuse_of_one_capability_authorizes_one_send` | `type(authorization) is not _TransportDispatchAuthorization` arm |
| `BoundedTransportProvider.__init__` 536-545 | `test_bounded_provider_boundary_rejects_concurrent_transport_call_without_spending_quota`, `test_bounded_provider_rejects_custom_gate_objects_and_subclasses` | none: both reject arms covered |
| `__setattr__` 547-550 | `test_approved_adapter_is_immutable_and_protocol_shape_does_not_authorize_new_types` | none |
| `assess_serialized` 552-554 | `test_serialized_transport_dispatch_requires_mandatory_boundary` | none |
| `_bind_boundary` 556-560 | every construction path | **the second-bind arm (`self._boundary is not None`) — no test binds two boundaries to one provider** |
| `_assess_from_boundary` 562-589 | the engine's synchronous path (`test_engine_mandatorily_serializes_and_gates_transport_calls`) | **`async_context_unsupported` (the `asyncio.get_running_loop()` branch) is unreached: every test either calls `_assess_async` directly or calls this outside a loop**; the negative boundary/request/size arms are also unreached here because the engine always supplies a correct boundary |
| `_assess_async` 591-643 | `provider_test_support.bounded_transport_call`, `adapter._assess_async(...)` in the Baseten tests | **`concurrent_request` (single-flight refusal) is unreached — no test makes two simultaneous `_assess_async` calls**; boundary/request/size negative arms unreached for the same reason as above |
| `BasetenMuseSparkOpenAdapter.__init__` 665-673 | `test_baseten_adapter_is_exact_type_approved_and_bound_to_mandatory_boundary` | none |
| `_bind_boundary` 675-679 | same | **second-bind arm unreached** |
| `_wire_request` 682-703+ | every `_send_http` test in `test_baseten_adapter.py` | **the envelope-shape rejection (exact key sets) is unreachable through the public API**: a payload with the right seal but the wrong envelope cannot be produced by `serialize_provider_request`, and the forged-object test fails at `_is_serialized_request` before this check |

## Ranked gaps

1. **`concurrent_request` is never asserted.** The single-flight refusal at `_assess_async`
   (the `_TRANSPORT_SINGLE_FLIGHT.acquire(blocking=False)` branch) is the one mechanism that stops
   two in-process calls overlapping, and nothing exercises it.
   *Test that would pin it:* start one `_assess_async` against a transport that parks on an
   `asyncio.Event`, then call `_assess_async` again and assert `ProviderSafetyError("concurrent_request")`
   plus `gate.request_count == 1`.
2. **`async_context_unsupported` is never asserted.** If a future caller invokes the synchronous
   entry from inside a running loop, the guard is the only thing preventing a nested-loop escape,
   and it has no test.
   *Test:* `asyncio.run(wrap())` where `wrap` awaits nothing but calls
   `provider._assess_from_boundary(...)` directly, asserting the code.
3. **Double bind is untested on both `_bind_boundary` implementations.** A second
   `MandatoryProviderBoundary(provider)` must raise `mandatory_boundary_required`; nothing checks it.
   *Test:* construct the boundary twice and assert the code, and that the first binding still holds.
4. **The negative arms of the boundary/request/size checks in `_assess_from_boundary` and
   `_assess_async` are untested.** Both functions re-validate what the boundary already validated;
   no test passes a wrong boundary or a raw `bytes` to either.
5. **`_wire_request`'s envelope check is unreachable and therefore unverifiable.** Either it is
   defence-in-depth that no test can reach, or it is dead code. Decide which, and say so in the
   docstring; today it reads as active protection.

## Passes for the wrong reason

- `test_bounded_provider_boundary_rejects_concurrent_transport_call_without_spending_quota`
  asserts `unsupported_transport`. It is named for the concurrency refusal but exercises the
  transport-type rejection; if that check regressed it would fail, but the concurrency path it
  names is not tested by it. Rename it, or add the test from gap 1.

## Dead code found while mapping

- Inside `_assess_async` the timeout-validation block appears **twice, verbatim** (the second copy
  immediately follows the first, around lines 605-620). The two are indistinguishable, so the
  second cannot change behaviour; it is duplication that hides which copy is authoritative.
- `_assess_from_boundary` and `_assess_async` duplicate the boundary, request and size checks
  line for line. Any fix applied to one will silently diverge from the other.

## Not done

Nothing executed. `local_memory__memory_store` is not bound to this session — my tools are
`read_files`, `str_replace`, `write_file`, `code_search`, `glob`, `list_directory` — so I am not
claiming a memory write; the durable facts are in this file instead.
