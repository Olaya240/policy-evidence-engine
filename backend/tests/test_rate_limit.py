"""Contract of the bounded token bucket in `app.rate_limit` (threat row H8).

`backend/app/main.py` is not wired to this module yet; the coordinator wires it.
What is pinned here is the control itself:

* a burst up to `limit` passes, the next call is refused, and the refusal's
  `retry_after` is exactly the time until the next token;
* a refusal consumes nothing, and a flood of refusals adds neither state nor
  credit;
* refill is driven only by the injected clock, in full and in part;
* the key map cannot grow past `max_keys`: full buckets are pruned (lossless),
  then the least-recently-seen bucket is evicted;
* instances share no state, the module has exactly one registry, and the
  constructor refuses parameters that would make a limit meaningless.

No test here sleeps except the one that pins the default clock, which needs real
time to move; every other refill is a value change on `FakeClock`.
"""

from __future__ import annotations

import time

import pytest

from app import rate_limit
from app.rate_limit import RateLimitDecision, TokenBucketRateLimiter


class FakeClock:
    """A monotonic clock whose value only moves when a test moves it."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make(clock: FakeClock, **overrides) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(clock=clock, **overrides)


# --- burst, refusal, and the retry-after it carries -------------------------


def test_a_burst_up_to_the_limit_passes_and_the_next_call_is_refused():
    clock = FakeClock()
    bucket = make(clock, limit=5, window_seconds=60.0)

    allowed = [bucket.check("10.0.0.1") for _ in range(5)]
    assert [decision.allowed for decision in allowed] == [True] * 5
    assert [decision.retry_after for decision in allowed] == [0.0] * 5

    refused = bucket.check("10.0.0.1")
    assert refused.allowed is False
    # 60 s / 5 tokens = 12 s per token, from the bucket rather than the window.
    assert refused.retry_after == pytest.approx(12.0)
    assert refused.retry_after_header == "12"

    # The refused call consumed nothing: asking again at the same instant
    # returns the same wait, not a longer one and not an allowance.
    again = bucket.check("10.0.0.1")
    assert again.allowed is False
    assert again.retry_after == pytest.approx(refused.retry_after)
    # Nothing above depended on real elapsed time.
    assert clock.now == 1000.0


def test_retry_after_is_exactly_when_the_next_token_arrives():
    clock = FakeClock()
    bucket = make(clock, limit=5, window_seconds=60.0)
    for _ in range(5):
        assert bucket.check("k").allowed is True
    wait = bucket.check("k").retry_after
    assert wait == pytest.approx(12.0)

    clock.advance(wait - 0.01)
    assert bucket.check("k").allowed is False
    clock.advance(0.02)
    assert bucket.check("k").allowed is True


def test_retry_after_header_never_rounds_down_to_zero():
    clock = FakeClock()
    bucket = make(clock, limit=1, window_seconds=0.5)
    assert bucket.check("k").allowed is True
    refused = bucket.check("k")
    assert refused.allowed is False
    assert 0 < refused.retry_after <= 0.5
    assert refused.retry_after_header == "1"


# --- refill is a function of the injected clock only ------------------------


def test_a_full_window_of_silence_restores_full_capacity():
    clock = FakeClock()
    bucket = make(clock, limit=4, window_seconds=60.0)
    for _ in range(4):
        assert bucket.check("k").allowed is True
    assert bucket.check("k").allowed is False

    clock.advance(60.0)
    assert [bucket.check("k").allowed for _ in range(4)] == [True] * 4
    assert bucket.check("k").allowed is False


def test_a_partial_window_restores_exactly_one_token():
    clock = FakeClock()
    bucket = make(clock, limit=2, window_seconds=10.0)
    assert bucket.check("k").allowed is True
    assert bucket.check("k").allowed is True
    assert bucket.check("k").allowed is False

    clock.advance(5.0)  # 5 s at 0.2 tokens/s is exactly one token
    assert bucket.check("k").allowed is True
    refused = bucket.check("k")
    assert refused.allowed is False
    assert refused.retry_after == pytest.approx(5.0)


def test_reading_the_clock_does_not_itself_refill():
    clock = FakeClock()
    bucket = make(clock, limit=1, window_seconds=1000.0)
    assert bucket.check("k").allowed is True

    # Repeated calls at a frozen clock must not accumulate fractions of a token
    # into a grant, and must report a shrinking -- not growing -- wait.
    waits = [bucket.check("k").retry_after for _ in range(100)]
    assert all(decision == pytest.approx(1000.0) for decision in waits)

    clock.advance(500.0)  # half a token
    half = bucket.check("k")
    assert half.allowed is False
    assert half.retry_after == pytest.approx(500.0)

    clock.advance(500.0)
    assert bucket.check("k").allowed is True


def test_a_clock_that_moves_backwards_never_grants_tokens():
    clock = FakeClock()
    bucket = make(clock, limit=2, window_seconds=10.0)
    assert bucket.check("k").allowed is True
    assert bucket.check("k").allowed is True
    before = bucket.check("k").retry_after

    clock.advance(-3600.0)
    after = bucket.check("k")
    assert after.allowed is False
    assert after.retry_after == pytest.approx(before)


def test_the_default_clock_is_time_monotonic_and_moves_with_real_time():
    # The only sleeping test: it proves the shipped default is a live monotonic
    # clock rather than a frozen value. 60 ms, not a rate-limit window.
    bucket = TokenBucketRateLimiter(limit=1, window_seconds=0.05)
    assert bucket.check("k").allowed is True
    assert bucket.check("k").allowed is False
    time.sleep(0.06)
    assert bucket.check("k").allowed is True


# --- the key map is bounded -------------------------------------------------


def test_the_key_map_cannot_grow_past_its_cap():
    clock = FakeClock()
    bucket = make(clock, limit=5, window_seconds=60.0, max_keys=8)
    for index in range(8):
        clock.advance(1.0)  # distinct last-seen stamps; no bucket is full
        assert bucket.check(f"c{index}").allowed is True
    assert bucket.key_count == 8

    for index in range(8, 500):
        clock.advance(1.0)
        bucket.check(f"c{index}")
        assert bucket.key_count <= 8
    assert bucket.key_count == 8


def test_a_flood_of_refusals_adds_neither_state_nor_credit():
    clock = FakeClock()
    bucket = make(clock, limit=3, window_seconds=60.0)
    for _ in range(3):
        assert bucket.check("flooder").allowed is True

    for _ in range(10_000):
        assert bucket.check("flooder").allowed is False
    assert bucket.key_count == 1
    assert bucket.check("flooder").allowed is False

    clock.advance(20.0)  # one token, not ten thousand
    assert bucket.check("flooder").allowed is True
    assert bucket.check("flooder").allowed is False


def test_a_full_bucket_is_pruned_without_forgetting_anything():
    clock = FakeClock()
    bucket = make(clock, limit=2, window_seconds=10.0, max_keys=2)
    for key in ("a", "b"):
        assert bucket.check(key).allowed is True
        assert bucket.check(key).allowed is True
        assert bucket.check(key).allowed is False

    clock.advance(10.0)  # both buckets are full again: they hold no state
    assert bucket.check("c").allowed is True
    assert bucket.key_count == 1

    # The dropped buckets were full, so a is indistinguishable from a new client.
    assert [bucket.check("a").allowed for _ in range(2)] == [True, True]
    assert bucket.check("a").allowed is False


def test_the_least_recently_seen_bucket_is_evicted_and_a_live_one_is_kept():
    clock = FakeClock()
    bucket = make(clock, limit=4, window_seconds=40.0, max_keys=2)

    for _ in range(4):  # a: empty, last seen at t=0
        assert bucket.check("a").allowed is True
    clock.advance(10.0)
    for _ in range(4):  # b: empty, last seen at t=10
        assert bucket.check("b").allowed is True

    clock.advance(10.0)  # t=20; neither bucket is full (a holds 2, b holds 1)
    assert bucket.check("c").allowed is True
    assert bucket.key_count == 2

    # b was seen more recently than a, so b kept its history: one token only.
    assert bucket.check("b").allowed is True
    assert bucket.check("b").allowed is False

    # a was evicted, so it restarts with a full burst. Adding it back evicts one
    # of the two live keys: that is the cap working, not a leak.
    assert [bucket.check("a").allowed for _ in range(4)] == [True] * 4
    assert bucket.key_count <= 2


# --- independence, registry, parameters ------------------------------------


def test_clients_have_independent_buckets():
    clock = FakeClock()
    bucket = make(clock, limit=2, window_seconds=10.0)
    assert bucket.check("a").allowed is True
    assert bucket.check("a").allowed is True
    assert bucket.check("a").allowed is False

    assert bucket.check("b").allowed is True
    assert bucket.check("b").allowed is True
    assert bucket.check("b").allowed is False


def test_limiters_share_no_state():
    clock = FakeClock()
    first = make(clock, limit=1, window_seconds=10.0)
    second = make(clock, limit=1, window_seconds=10.0)
    assert first.check("k").allowed is True
    assert first.check("k").allowed is False
    assert second.check("k").allowed is True


def test_the_module_exposes_exactly_one_shared_registry():
    shared = [value for value in vars(rate_limit).values()
              if isinstance(value, TokenBucketRateLimiter)]
    assert shared == [rate_limit.default_limiter]
    # The registry is a limiter like any other, so integration can reset it.
    assert isinstance(rate_limit.default_limiter, TokenBucketRateLimiter)


def test_reset_forgets_every_bucket():
    clock = FakeClock()
    bucket = make(clock, limit=1, window_seconds=10.0)
    assert bucket.check("a").allowed is True
    assert bucket.check("b").allowed is True
    assert bucket.key_count == 2

    bucket.reset()
    assert bucket.key_count == 0
    assert bucket.check("a").allowed is True
    assert bucket.check("a").allowed is False


@pytest.mark.parametrize("overrides", [
    {"limit": 0},
    {"limit": -1},
    {"limit": 2.5},
    {"window_seconds": 0},
    {"window_seconds": -1.0},
    {"max_keys": 0},
    {"max_keys": -4},
])
def test_parameters_that_would_remove_the_limit_are_refused(overrides):
    with pytest.raises(ValueError):
        make(FakeClock(), **overrides)


def test_a_non_callable_clock_is_refused():
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(limit=1, window_seconds=1.0, clock=1000.0)


def test_the_decision_is_immutable():
    decision = RateLimitDecision(allowed=True)
    with pytest.raises(Exception):
        decision.allowed = False  # type: ignore[misc]
