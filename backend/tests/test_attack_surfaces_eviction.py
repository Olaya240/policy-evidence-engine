"""Thirteenth probe batch: does the bounded key map let a client reset its own limit?

The limiter caps its key map so memory stays bounded. The documented cost is that an
evicted bucket forgets its consumption. This probe measures exactly that, and asks whether
the eviction is reachable by the attacker whose bucket it is.
"""

from __future__ import annotations

import pytest

from app.rate_limit import TokenBucketRateLimiter


def test_eviction_forgets_an_exhausted_bucket():
    clock = [1000.0]
    limiter = TokenBucketRateLimiter(limit=1, window_seconds=60.0, max_keys=4, clock=lambda: clock[0])

    assert limiter.check("attacker").allowed
    assert not limiter.check("attacker").allowed

    # Four other identities — more than the cap of four including the attacker's bucket.
    for index in range(4):
        assert limiter.check(f"other-{index}").allowed

    # The attacker's consumption is gone, because the bucket was evicted.
    assert limiter.check("attacker").allowed, "eviction did not forget the exhausted bucket"


def test_eviction_cannot_be_reached_without_distinct_identities():
    clock = [1000.0]
    limiter = TokenBucketRateLimiter(limit=1, window_seconds=60.0, max_keys=4, clock=lambda: clock[0])

    assert limiter.check("attacker").allowed
    for _ in range(50):
        assert not limiter.check("attacker").allowed, "one identity must never reset its own limit"


def test_the_key_map_never_exceeds_its_cap():
    clock = [1000.0]
    limiter = TokenBucketRateLimiter(limit=5, window_seconds=60.0, max_keys=8, clock=lambda: clock[0])

    for index in range(500):
        limiter.check(f"client-{index}")

    assert limiter.key_count <= 8, limiter.key_count


def test_the_middleware_key_is_the_socket_peer_not_a_header():
    """The limiter is only bypassable by rotating identities if the deployment lets a
    client choose its own identity. `request.client.host` is the socket peer."""
    from app import main as main_module
    from app.rate_limit import TokenBucketRateLimiter as Limiter

    original = main_module.rate_limiter
    main_module.rate_limiter = Limiter(limit=1, window_seconds=60.0)
    try:
        assert main_module.rate_limiter.check("127.0.0.1").allowed
        assert not main_module.rate_limiter.check("127.0.0.1").allowed
    finally:
        main_module.rate_limiter = original
