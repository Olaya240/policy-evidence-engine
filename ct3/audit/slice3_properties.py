"""Slice-3 property harness: dispatch, quota and single-flight.

Run from the worktree root:

    cd /home/alex/policy-evidence-fix && PYTHONPATH=backend python ct3/audit/slice3_properties.py

Every property is exercised against the real classes. The only thing replaced is
`BasetenMuseSparkOpenTransport._send_from_adapter`, because the type guards in
`BoundedTransportProvider` and `BasetenMuseSparkOpenAdapter` are identity checks
(`type(x) is ...`) and forbid a test double. Patching that one method on the real
class keeps every guard in force and confines the fake to the network hop.

Nothing here touches the network: the patched hop raises, sleeps, or returns a
response double. `BasetenMuseSparkOpenTransport(api_key=...)` constructs without
I/O, as slice 2 established.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from app import provider_safety as ps
from app.httpx_transport import BasetenMuseSparkOpenTransport
from app.models import Record

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
NOW = datetime.now(timezone.utc)

FAILURES: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}   [{detail}]")
        FAILURES.append((name, detail))


def note(text: str) -> None:
    print(f"NOTE  {text}")


def expect_error(call, code: str) -> tuple[bool, str]:
    try:
        call()
    except ps.ProviderSafetyError as exc:
        return exc.code == code, f"code={exc.code}"
    except BaseException as exc:  # noqa: BLE001 - the point is to see what escapes
        return False, f"{type(exc).__name__}: {exc}"
    return False, "no error raised"


def record(index: int = 0) -> Record:
    return Record(
        id=f"REC-{index}",
        timestamp=NOW - timedelta(days=1),
        department="Front Office",
        text=f"The checklist was unavailable during the night handover {index}.",
        tags=[],
    )


def budget_gate(max_requests: int) -> ps.ProviderCallGate:
    return ps.ProviderCallGate(ps.ProviderBudgetConfig(
        enabled=True,
        max_requests=max_requests,
        max_estimated_cost_usd="1.00",
        conservative_cost_per_request_usd="0.10",
    ))


def graph(max_requests: int = 1):
    transport = BasetenMuseSparkOpenTransport(api_key="test-key-not-used")
    gate = budget_gate(max_requests)
    adapter = ps.BasetenMuseSparkOpenAdapter(transport, gate)
    boundary = ps.MandatoryProviderBoundary(adapter)
    request = ps.serialize_provider_request(
        ps.eligible_provider_records([record()]), HYPOTHESIS,
    )
    return transport, gate, adapter, boundary, request


class FakeResponse:
    content_length = None

    def __init__(self, delay: float = 0.0):
        self._delay = delay
        self.closed = False

    async def read_chunk(self, _n: int) -> bytes:
        if self._delay:
            await asyncio.sleep(self._delay)
        return b""

    async def aclose(self) -> None:
        self.closed = True


class patched_send:
    """Replace the single network hop on the real transport class."""

    def __init__(self, behaviour):
        self._behaviour = behaviour
        self._original = None

    def __enter__(self):
        self._original = BasetenMuseSparkOpenTransport._send_from_adapter

        async def replacement(_self, *_args, **_kwargs):
            result = self._behaviour()
            if asyncio.iscoroutine(result):
                return await result
            return result

        BasetenMuseSparkOpenTransport._send_from_adapter = replacement
        return self

    def __exit__(self, *_exc):
        BasetenMuseSparkOpenTransport._send_from_adapter = self._original
        return False


# ---------------------------------------------------------------------------
# 1. Quota is spent once per attempt, and an attempt counts even when the
#    transport fails after the reservation.
# ---------------------------------------------------------------------------
def property_quota_per_attempt() -> None:
    def boom():
        raise RuntimeError("transport down")

    with patched_send(boom):
        _transport, gate, adapter, boundary, request = graph(1)

        async def attempt():
            return await adapter._assess_async(request, boundary, timeout_seconds=5.0)

        ok, detail = expect_error(lambda: asyncio.run(attempt()), "provider_failure")
        check("1 quota: a failed dispatch still spends quota", ok, detail)
        check("1 quota: attempt counted once", gate.request_count == 1,
              f"count={gate.request_count}")

        ok, detail = expect_error(lambda: asyncio.run(attempt()), "request_limit")
        check("1 quota: the second attempt is refused by the gate", ok, detail)
        check("1 quota: a refused attempt does not consume more",
              gate.request_count == 1, f"count={gate.request_count}")


# ---------------------------------------------------------------------------
# 2. Concurrent dispatches: exactly one enters, the rest are refused with a
#    classified error, and the single-flight lock is released afterwards.
# ---------------------------------------------------------------------------
def property_concurrent_single_flight() -> None:
    async def slow_failure():
        await asyncio.sleep(0.05)
        raise RuntimeError("slow transport")

    with patched_send(lambda: slow_failure()):
        _transport, gate, adapter, boundary, request = graph(5)

        async def all_five():
            return await asyncio.gather(
                *[adapter._assess_async(request, boundary, timeout_seconds=5.0) for _ in range(5)],
                return_exceptions=True,
            )

        results = asyncio.run(all_five())

    codes = [getattr(item, "code", type(item).__name__) for item in results]
    check("2 concurrency: exactly one dispatch entered",
          codes.count("provider_failure") == 1, f"codes={codes}")
    check("2 concurrency: the others are refused as concurrent_request",
          codes.count("concurrent_request") == 4, f"codes={codes}")
    check("2 concurrency: no unclassified exception escaped",
          all(code in {"provider_failure", "concurrent_request"} for code in codes),
          f"codes={codes}")

    acquired = ps._TRANSPORT_SINGLE_FLIGHT.acquire(blocking=False)
    check("2 concurrency: the lock is released after the burst", acquired, "lock still held")
    if acquired:
        ps._TRANSPORT_SINGLE_FLIGHT.release()


# ---------------------------------------------------------------------------
# 3. Cancellation: the quota is already spent and the lock must be released.
# ---------------------------------------------------------------------------
def property_cancellation() -> None:
    async def never_finishes():
        await asyncio.sleep(30)
        raise RuntimeError("unreachable")

    with patched_send(lambda: never_finishes()):
        _transport, gate, adapter, boundary, request = graph(3)

        async def cancel_midway():
            task = asyncio.ensure_future(
                adapter._assess_async(request, boundary, timeout_seconds=5.0))
            await asyncio.sleep(0.05)
            task.cancel()
            return await asyncio.gather(task, return_exceptions=True)

        results = asyncio.run(cancel_midway())

    check("3 cancellation: the task ends cancelled, not crashed",
          isinstance(results[0], asyncio.CancelledError), f"{type(results[0]).__name__}")
    note(f"3 cancellation: quota after cancel = {gate.request_count} "
         "(reserved before dispatch, never refunded)")
    check("3 cancellation: the reservation is spent", gate.request_count == 1,
          f"count={gate.request_count}")
    acquired = ps._TRANSPORT_SINGLE_FLIGHT.acquire(blocking=False)
    check("3 cancellation: the lock is released", acquired, "lock still held")
    if acquired:
        ps._TRANSPORT_SINGLE_FLIGHT.release()


# ---------------------------------------------------------------------------
# 4. Boundary wiring: only an approved provider may hold a boundary, and a
#    dispatch must present the boundary it was bound to.
# ---------------------------------------------------------------------------
def property_boundary_wiring() -> None:
    ok, detail = expect_error(lambda: ps.MandatoryProviderBoundary(object()),
                              "unsupported_provider")
    check("4 wiring: an arbitrary provider cannot get a boundary", ok, detail)

    with patched_send(FakeResponse):
        _transport, _gate, adapter, boundary, request = graph(2)

        async def wrong_boundary():
            return await adapter._assess_async(request, object(), timeout_seconds=5.0)

        ok, detail = expect_error(lambda: asyncio.run(wrong_boundary()),
                                  "mandatory_boundary_required")
        check("4 wiring: an unbound boundary is refused", ok, detail)

        ok, detail = expect_error(lambda: ps.MandatoryProviderBoundary(adapter),
                                  "mandatory_boundary_required")
        check("4 wiring: a second boundary for the same adapter is refused", ok, detail)


# ---------------------------------------------------------------------------
# 5. The former public dispatch helpers stay closed.
# ---------------------------------------------------------------------------
def property_legacy_paths_closed() -> None:
    _transport, _gate, _adapter, _boundary, request = graph(2)

    ok, detail = expect_error(
        lambda: asyncio.run(ps.bounded_provider_call(object(), request)), "unsupported_provider")
    check("5 legacy: bounded_provider_call rejects an arbitrary provider", ok, detail)

    provider = object.__new__(ps.BoundedTransportProvider)
    object.__setattr__(provider, "_sealed", True)
    ok, detail = expect_error(
        lambda: provider.assess_serialized(request), "mandatory_boundary_required")
    check("5 legacy: assess_serialized stays closed", ok, detail)


def main() -> int:
    properties = [
        ("1 quota per attempt", property_quota_per_attempt),
        ("2 concurrent single flight", property_concurrent_single_flight),
        ("3 cancellation", property_cancellation),
        ("4 boundary wiring", property_boundary_wiring),
        ("5 legacy paths", property_legacy_paths_closed),
    ]
    for label, function in properties:
        print(f"\n== {label} ==")
        try:
            function()
        except Exception as exc:  # noqa: BLE001 - a harness crash is a finding
            check(f"{label}: harness raised", False, f"{type(exc).__name__}: {exc}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED property check(s):")
        for name, detail in FAILURES:
            print(f"  - {name} [{detail}]")
        return 1
    print("all property checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
