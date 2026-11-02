"""Suite-wide fixtures.

The rate limiter is a process-global token bucket (600 requests per minute) and the
suite makes thousands of API calls. Without a reset, whether a test sees a 429 depends
on how fast the machine ran that minute: two runs of identical code disagree, and the
test that fails is whichever one landed on the empty bucket. That is a defect in the
harness, not in the service, so the bucket is drained between cases and the suite's
verdict is a property of the code again.
"""

from __future__ import annotations

import pytest

from app import main as app_main


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    app_main.rate_limiter.reset()
    yield
    app_main.rate_limiter.reset()
