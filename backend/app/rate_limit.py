"""A bounded in-memory token bucket, for a single-user local prototype.

Threat-model row H8 (`ct3/audit/THREAT-MODEL.md`): the API bounds each *request*
but not the *rate* of requests. This is the smallest control that changes that,
and nothing more.

* **Token bucket, not a sliding window.** A client holds at most ``limit``
  tokens, one per call, and one token returns every
  ``window_seconds / limit`` seconds. A burst up to ``limit`` is allowed by
  design; a client that stays under one token per refill interval is never
  refused. No per-request timestamp list is kept.
* **Monotonic clock only, resolved when the limiter is built.** ``clock``
  defaults to ``time.monotonic``; a test drives refill by moving a value rather
  than sleeping. Nothing here reads wall-clock time, so an NTP step can neither
  refill nor freeze a bucket.
* **State in memory, in this process.** No database, no file, no network, no
  thread spawned. Restarting the process forgets every bucket, and two worker
  processes would each hold their own limit. The prototype runs one uvicorn
  process; if that changes, this control weakens proportionally.
* **Bounded keys.** ``max_keys`` caps the map. A bucket that has refilled to
  capacity holds no state, so those are dropped first, and dropping one cannot
  loosen the limit. Only when that frees nothing is the least-recently-seen
  bucket evicted, which does forget that client's consumption: a bounded,
  documented bias toward whichever client arrives next, in exchange for a map
  that cannot grow without bound.
* **A refusal carries its own retry-after.** ``RateLimitDecision.retry_after``
  is the time until the next token, computed from the bucket rather than guessed
  from the window.

What this is *not*: authentication (row H1 is declared open), an ingress
control, or a defence against many source addresses. The key is whatever the
caller passes; without authentication the honest key is the peer address, and a
client whose address a proxy rewrites is limited as that proxy.

Integration — one registry, ``default_limiter``, so the application has one place
to call. A middleware is expected to do:

    decision = default_limiter.check(
        request.client.host if request.client is not None else "unknown")
    if not decision.allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded."},
            headers={"Retry-After": decision.retry_after_header},
        )
    return await call_next(request)

Placement matters: see ``ct3/audit/W5-ratelimit.md``.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

DEFAULT_LIMIT = 60
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_MAX_KEYS = 1024

# Floating-point slack so a bucket that has refilled exactly one token is not
# refused by a rounding error, and so "full" means full when pruning.
_TOLERANCE = 1e-9


@dataclass(frozen=True)
class RateLimitDecision:
    """The outcome of one :meth:`TokenBucketRateLimiter.check` call.

    ``retry_after`` is seconds until the next token is available and is ``0.0``
    when the call was allowed. ``retry_after_header`` is the integer form a
    ``Retry-After`` response header needs; it never rounds down to zero.
    """

    allowed: bool
    retry_after: float = 0.0

    @property
    def retry_after_header(self) -> str:
        return str(max(1, math.ceil(self.retry_after)))


@dataclass
class _Bucket:
    tokens: float
    seen: float


class TokenBucketRateLimiter:
    """A keyed token bucket whose memory and key count are both bounded."""

    def __init__(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        max_keys: int = DEFAULT_MAX_KEYS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be an integer >= 1")
        if not window_seconds > 0:
            raise ValueError("window_seconds must be > 0")
        if not isinstance(max_keys, int) or max_keys < 1:
            raise ValueError("max_keys must be an integer >= 1")
        if clock is not None and not callable(clock):
            raise ValueError("clock must be callable returning seconds")

        self._limit = limit
        self._window_seconds = float(window_seconds)
        self._max_keys = max_keys
        self._rate = limit / self._window_seconds
        self._clock = clock if clock is not None else time.monotonic
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    @property
    def max_keys(self) -> int:
        return self._max_keys

    @property
    def key_count(self) -> int:
        with self._lock:
            return len(self._buckets)

    def check(self, key: object) -> RateLimitDecision:
        """Consume one token for ``key`` or report how long until one exists."""
        bucket_key = str(key)
        now = self._clock()
        with self._lock:
            if bucket_key not in self._buckets and len(self._buckets) >= self._max_keys:
                self._evict(now)
            bucket = self._buckets.get(bucket_key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self._limit), seen=now)
                self._buckets[bucket_key] = bucket
            else:
                bucket.tokens = self._tokens_at(bucket, now)
            bucket.seen = now
            if bucket.tokens >= 1.0 - _TOLERANCE:
                bucket.tokens = max(0.0, bucket.tokens - 1.0)
                return RateLimitDecision(allowed=True)
            return RateLimitDecision(allowed=False,
                                     retry_after=(1.0 - bucket.tokens) / self._rate)

    def reset(self) -> None:
        """Forget every bucket. For test setup, not for production use."""
        with self._lock:
            self._buckets.clear()

    def _tokens_at(self, bucket: _Bucket, now: float) -> float:
        elapsed = now - bucket.seen
        if elapsed <= 0:  # a clock that moves backwards never removes tokens
            return bucket.tokens
        return min(float(self._limit), bucket.tokens + elapsed * self._rate)

    def _evict(self, now: float) -> None:
        """Free at least one slot, called only when a new key needs one."""
        # Lossless pass: a bucket that is full right now is indistinguishable
        # from an absent one, so dropping it cannot make the limit weaker.
        for key, bucket in list(self._buckets.items()):
            if self._tokens_at(bucket, now) >= self._limit - _TOLERANCE:
                del self._buckets[key]
        # Bounded pass: something must go, so the client seen longest ago goes.
        while len(self._buckets) >= self._max_keys and self._buckets:
            oldest = min(self._buckets, key=lambda candidate: self._buckets[candidate].seen)
            del self._buckets[oldest]


# The one registry. Nothing else in this module is mutable module state.
default_limiter = TokenBucketRateLimiter()

__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_MAX_KEYS",
    "DEFAULT_WINDOW_SECONDS",
    "RateLimitDecision",
    "TokenBucketRateLimiter",
    "default_limiter",
]
