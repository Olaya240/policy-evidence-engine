"""Property harness for audit slice 2 — `app/provider_safety.py:292-497`.

Run:  cd /home/alex/policy-evidence-fix && PYTHONPATH=backend python ct3/audit/slice2_properties.py

Covers the response boundary (`_read_bounded_response`), the budget config and
gate (`ProviderBudgetConfig`, `_positive_decimal`, `ProviderCallGate`) and the
per-call dispatch capability (`_TransportDispatchAuthorization` and its
validate/consume helpers). Standard library only; every double is hand-written
so the properties are stated against the module's own constants.

Exit code is non-zero if any property fails. A property the code makes
impossible to state prints SKIP with the reason rather than inventing a pass.
"""

import asyncio
import sys
from decimal import Decimal

import app.provider_safety as ps

FAILURES = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append((name, detail))


def skip(name, reason):
    print(f"SKIP  {name}   [{reason}]")


def note(text):
    print(f"NOTE  {text}")


def expect_code(thunk, code):
    """Return (ok, observed). Distinguishes 'raised the wrong code' from 'did not raise'."""
    try:
        thunk()
    except ps.ProviderSafetyError as exc:
        return exc.code == code, exc.code
    except Exception as exc:  # noqa: BLE001 - the harness must report what actually happened
        return False, f"{type(exc).__name__}: {exc}"
    return False, "no error"


class FakeResponse:
    """A StreamingResponse double. `source` is a list of chunks or a callable n -> bytes."""

    def __init__(self, source, content_length=None, overshoot=0):
        self.source = source
        self.content_length = content_length
        self.overshoot = overshoot
        self.calls = 0
        self.closed = False

    async def read_chunk(self, n):
        self.calls += 1
        if callable(self.source):
            return self.source(n)
        if not self.source:
            return b""
        data = self.source.pop(0)
        return data[: n + self.overshoot]

    async def aclose(self):
        self.closed = True


def read(response):
    return asyncio.run(ps._read_bounded_response(response))


CAP = ps.MAX_RESPONSE_BYTES
CHUNK = ps.MAX_RESPONSE_READ_CHUNK_BYTES


# ---------------------------------------------------------------------------
# 1. The response byte cap
# ---------------------------------------------------------------------------

def property_response_cap():
    exact = [b"a" * CHUNK] * (CAP // CHUNK)
    response = FakeResponse(list(exact))
    body = read(response)
    check("1 cap: exactly at the limit is accepted", len(body) == CAP, f"{len(body)} != {CAP}")
    check("1 cap: response is closed on success", response.closed)

    response = FakeResponse([b"a" * CHUNK] * (CAP // CHUNK) + [b"x"])
    ok, observed = expect_code(lambda: read(response), "response_too_large")
    check("1 cap: one byte over raises response_too_large", ok, observed)
    check("1 cap: response is closed on failure", response.closed)

    for size in (1, 7, 1023, 1024):
        total = CAP
        chunks = []
        remaining = total
        while remaining:
            chunks.append(b"a" * min(size, remaining))
            remaining -= min(size, remaining)
        body = read(FakeResponse(chunks))
        check(f"1 cap: chunk size {size} fills exactly to the cap", len(body) == CAP, len(body))

    # A transport that hands back more than it was asked for is treated as an
    # oversize body, not trusted and trimmed.
    # The guard compares against the *requested window*, so the double has to
    # over-deliver past that window, not past a 4-byte list entry.
    response = FakeResponse([b"a" * (ps.MAX_RESPONSE_READ_CHUNK_BYTES + 1)], overshoot=1)
    ok, observed = expect_code(lambda: read(response), "response_too_large")
    check("1 cap: over-long chunk raises rather than being trimmed", ok, observed)

    # Declared length above the cap is refused before any read.
    response = FakeResponse([], content_length=str(CAP + 1))
    ok, observed = expect_code(lambda: read(response), "response_too_large")
    check("1 cap: declared length above cap is refused", ok, observed)
    check("1 cap: refused request performs no reads", response.calls == 0, response.calls)


# ---------------------------------------------------------------------------
# 2. Content-Length header validation
# ---------------------------------------------------------------------------

def property_header_validation():
    cases = {
        "non-str int": 5,
        "empty string": "",
        "non-decimal": "12.5",
        "non-ascii digits": "\uff11\uff12",
        "longer than the header cap": "1" * (ps.MAX_CONTENT_LENGTH_HEADER_CHARS + 1),
        "negative": "-1",
    }
    for label, value in cases.items():
        ok, observed = expect_code(
            lambda value=value: read(FakeResponse([], content_length=value)),
            "malformed_response_headers",
        )
        check(f"2 header: {label} -> malformed_response_headers", ok, observed)

    ok, observed = expect_code(
        lambda: read(FakeResponse([], content_length="1" * ps.MAX_CONTENT_LENGTH_HEADER_CHARS)),
        "response_too_large",
    )
    check("2 header: ten digits above the cap -> response_too_large", ok, observed)

    ok, observed = expect_code(
        lambda: read(FakeResponse([b"abc"], content_length="5")),
        "malformed_response",
    )
    check("2 header: body shorter than declared -> malformed_response", ok, observed)

    body = read(FakeResponse([b"abc"], content_length="3"))
    check("2 header: body matching declared length is accepted", body == b"abc", body)


# ---------------------------------------------------------------------------
# 3 and 4. Streams that make no progress, or make one byte of progress
# ---------------------------------------------------------------------------

def property_no_progress_and_slow_streams():
    response = FakeResponse(lambda n: b"")
    body = read(response)
    check("3 no-progress stream terminates", response.calls <= 2, f"{response.calls} reads")
    check("3 no-progress stream returns an empty body", body == b"", body)
    note("3 no-progress stream: terminates by returning b'' rather than raising; empty body is a valid response")

    def one_byte(_n):
        one_byte.total += 1
        if one_byte.total > CAP * 4:
            return b""
        return b"x"
    one_byte.total = 0
    response = FakeResponse(one_byte)
    ok, observed = expect_code(lambda: read(response), "response_too_large")
    check("4 one-byte stream stops at the cap", ok, observed)
    check("4 one-byte stream read no more than the cap plus a probe", response.calls <= CAP + 1,
          response.calls)


# ---------------------------------------------------------------------------
# 5. Budget config and call gate
# ---------------------------------------------------------------------------

def property_gate():
    disabled = ps.ProviderCallGate()
    ok, observed = expect_code(disabled.authorize_request, "provider_disabled")
    check("5 gate: disabled by default", ok, observed)
    check("5 gate: disabled gate has no ceiling", disabled.max_requests is None)

    def enabled(max_requests, ceiling, per_request):
        return ps.ProviderCallGate(ps.ProviderBudgetConfig(
            enabled=True,
            max_requests=max_requests,
            max_estimated_cost_usd=ceiling,
            conservative_cost_per_request_usd=per_request,
        ))

    gate = enabled(3, "0.30", "0.10")
    for _ in range(3):
        gate.authorize_request()
    check("5 gate: permitted calls are counted", gate.request_count == 3, gate.request_count)
    ok, observed = expect_code(gate.authorize_request, "request_limit")
    check("5 gate: the call past the limit is refused", ok, observed)
    check("5 gate: a refused call does not consume quota", gate.request_count == 3, gate.request_count)
    check("5 gate: reservations sum to the ceiling",
          gate.reserved_estimated_cost_usd == Decimal("0.30"), gate.reserved_estimated_cost_usd)

    for label, config in {
        "bool count": ps.ProviderBudgetConfig(enabled=True, max_requests=True,
                                              max_estimated_cost_usd="1", conservative_cost_per_request_usd="0.1"),
        "zero count": ps.ProviderBudgetConfig(enabled=True, max_requests=0,
                                              max_estimated_cost_usd="1", conservative_cost_per_request_usd="0.1"),
        "count above the experiment cap": ps.ProviderBudgetConfig(
            enabled=True, max_requests=ps.MAX_EXPERIMENT_REQUESTS + 1,
            max_estimated_cost_usd="5", conservative_cost_per_request_usd="0.1"),
        "ceiling above the configurable maximum": ps.ProviderBudgetConfig(
            enabled=True, max_requests=1,
            max_estimated_cost_usd=str(ps.MAX_CONFIGURABLE_ESTIMATED_BUDGET_USD + 1),
            conservative_cost_per_request_usd="0.1"),
        "per-request total above the ceiling": ps.ProviderBudgetConfig(
            enabled=True, max_requests=10, max_estimated_cost_usd="0.25",
            conservative_cost_per_request_usd="0.10"),
        "negative per-request": ps.ProviderBudgetConfig(
            enabled=True, max_requests=1, max_estimated_cost_usd="1",
            conservative_cost_per_request_usd="-0.10"),
        "non-finite per-request": ps.ProviderBudgetConfig(
            enabled=True, max_requests=1, max_estimated_cost_usd="1",
            conservative_cost_per_request_usd="NaN"),
    }.items():
        ok, observed = expect_code(lambda config=config: ps.ProviderCallGate(config), "invalid_budget")
        check(f"5 gate: {label} -> invalid_budget", ok, observed)

    ok, observed = expect_code(lambda: ps.ProviderCallGate(ps.ProviderBudgetConfig(enabled=True)), "invalid_budget")
    check("5 gate: enabled without limits -> invalid_budget", ok, observed)

    try:
        gate.request_count = 99
    except AttributeError:
        check("5 gate: is immutable after construction", True)
    except Exception as exc:  # noqa: BLE001
        check("5 gate: is immutable after construction", False, type(exc).__name__)
    else:
        check("5 gate: is immutable after construction", False, "assignment succeeded")

    # The construction-time rule `per_request * count <= ceiling` implies
    # `k * per_request <= ceiling` for every k <= count, so the runtime
    # `budget_exceeded` branch cannot be reached by any accepted configuration.
    reachable = False
    for count in range(1, ps.MAX_EXPERIMENT_REQUESTS + 1):
        per = Decimal("0.10")
        for ceiling in (per * count, ps.MAX_CONFIGURABLE_ESTIMATED_BUDGET_USD):
            try:
                g = enabled(count, str(ceiling), str(per))
            except ps.ProviderSafetyError:
                continue
            for _ in range(count):
                try:
                    g.authorize_request()
                except ps.ProviderSafetyError as exc:
                    reachable = reachable or exc.code == "budget_exceeded"
    check("5 gate: budget_exceeded is unreachable for accepted configs", not reachable,
          "an accepted config reached budget_exceeded")
    note("5 gate: budget_exceeded exists but is subsumed by the construction-time check; "
         "either drop it or allow a non-uniform per-request estimate")


# ---------------------------------------------------------------------------
# 6. Dispatch authorization
# ---------------------------------------------------------------------------

def property_dispatch_authorization():
    check("6 dispatch: arbitrary object is not a valid authorization",
          ps._valid_transport_dispatch_authorization(object(), object(), b"", 1.0) is False)
    check("6 dispatch: arbitrary object cannot be consumed",
          ps._consume_transport_dispatch_authorization(object(), object(), b"", 1.0) is False)

    ok, observed = expect_code(
        lambda: ps._TransportDispatchAuthorization(object(), object(), object(), b"", 1.0),
        "mandatory_boundary_required",
    )
    check("6 dispatch: minting without the seal is refused", ok, observed)


def main() -> int:
    properties = [
        ("1 response cap", property_response_cap),
        ("2 header validation", property_header_validation),
        ("3 no-progress and slow streams", property_no_progress_and_slow_streams),
        ("4 budget gate", property_gate),
        ("5 dispatch authorization", property_dispatch_authorization),
    ]
    note("6 dispatch single-use and identity binding are asserted in "
         "tests/test_provider_safety_slice2_contracts.py, which mints a real "
         "authorization without network; this harness does not duplicate it.")
    for label, function in properties:
        print(f"\n== {label} ==")
        try:
            function()
        except Exception as exc:  # noqa: BLE001
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
