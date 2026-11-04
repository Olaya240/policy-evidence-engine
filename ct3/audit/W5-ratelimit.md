# W5 — H8 rate limit: one bounded token bucket

Worker 5 of 10. Files written, and nothing else:

- `backend/app/rate_limit.py` (new)
- `backend/tests/test_rate_limit.py` (new)

`backend/app/main.py` was **not** edited — wiring is the coordinator's step, and the
contract for it is §2 below. Threat row H8 in `ct3/audit/THREAT-MODEL.md` is still
open until that wiring lands and a test in `test_api.py` exercises it; this worker
supplies the control and its proof, not the closure.

## 1. What the control is, and what it is not

A token bucket, keyed by whatever identity the caller passes, held in one dict in
this process:

| Property | Implementation | Anchor |
|---|---|---|
| Burst | `limit` tokens per key; each `check` spends one | `rate_limit.py:135` |
| Refill | `limit / window_seconds` tokens per second, continuous | `rate_limit.py:160` |
| Clock | `time.monotonic`, resolved at construction, injectable | `rate_limit.py:113` |
| Bounded keys | `max_keys` cap: prune full buckets, then evict least-recently-seen | `rate_limit.py:166` |
| Refusal | `RateLimitDecision(allowed=False, retry_after=<seconds to next token>)` | `rate_limit.py:150` |
| Registry | exactly one module-level limiter, `default_limiter` | `rate_limit.py:180` |
| Threads | none spawned; one `threading.Lock` guards the dict | `rate_limit.py:116` |
| Persistence | none — restart forgets every bucket, by design | — |

Defaults: 60 requests per 60 s per key, 1024 keys. A bucket that has refilled to
capacity holds no state, so pruning it loses nothing; the LRU pass is the only
path that can forget a client's consumption, and it exists so the map cannot grow.

**Not covered.** This is per-process and in-memory: two uvicorn workers would each
allow 60/min, and a restart resets the window. The key is the caller's string; with
no authentication (row H1) the honest key is the peer address, so a client behind a
proxy that rewrites the address is limited as the proxy, and `X-Forwarded-For` is
deliberately not trusted. It does not slow a flood from many addresses, and it is
not a substitute for ingress controls — none of which a local prototype can assert.

## 2. Integration contract

### Signature

```python
TokenBucketRateLimiter(*, limit: int = 60, window_seconds: float = 60.0,
                       max_keys: int = 1024, clock: Callable[[], float] | None = None)
    .check(key: object) -> RateLimitDecision   # allowed: bool; retry_after: float
    .key_count -> int                          # property, for a bounds assertion
    .reset() -> None                           # test setup only

rate_limit.default_limiter: TokenBucketRateLimiter   # the one registry
RateLimitDecision.retry_after_header -> str          # ceil(retry_after), never "0"
```

Invalid parameters (`limit < 1`, `window_seconds <= 0`, `max_keys < 1`, a
non-callable clock) raise `ValueError` in the constructor, so a typo cannot
silently disable the limit.

### Where to call it

In `main.py`, a middleware **added before** the CORS registration at
`backend/app/main.py:120`. That ordering is not cosmetic; see §2.1.

```python
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from app.rate_limit import default_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        decision = default_limiter.check(
            request.client.host if request.client is not None else "unknown")
        if decision.allowed:
            return await call_next(request)
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded."},
            headers={"Retry-After": decision.retry_after_header},
        )


# insert immediately before app.add_middleware(CORSMiddleware, ...) at main.py:120
app.add_middleware(RateLimitMiddleware)
```

The 429 body is a fixed string: it carries no record text, no path and no id, so it
adds nothing to the H4/H5 surfaces.

### 2.1 Why before CORS (observed, not assumed)

Two orderings, same request (`Origin: http://localhost:5174`, second call refused):

```
cors-first    -> 429 retry-after='60' acao=None
limiter-first -> 429 retry-after='60' acao='http://localhost:5174'
```

With the limiter added after CORS (the shape a `@app.middleware("http")` decorator
below line 120 produces), the refusal is missing `access-control-allow-origin`, so
the UI at `localhost:5174` sees an opaque network error and cannot read
`Retry-After`. Adding it first keeps CORS outermost and the 429 readable. Script:
`/tmp/w5_cors_order.py` (throwaway; not part of the repository).

### 2.2 Tests that will start seeing 429s

`default_limiter` is process-global, and `TestClient` presents one host
(`"testclient"`), so every request in a test module shares one bucket. If a module
issues more than 60 requests through the same client within 60 s of monotonic time,
it will now receive 429. Add to `test_api.py`:

```python
@pytest.fixture(autouse=True)
def _reset_rate_limit():
    default_limiter.reset()
```

A per-test reset also makes the limit's own behaviour testable there (row H8's
"test that fails when the control is removed"): a loop of 61 requests, assert the
61st is 429 with an integer `Retry-After`, and assert 429 for one client does not
refuse another.

## 3. Tests, verbatim

Command, from `/home/alex/policy-evidence-fix`:

```
cd backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_rate_limit.py
```

Output:

```
.........................                                                [100%]
25 passed in 0.15s
EXIT=0
```

The five required properties and the test that holds each:

| Requirement | Test |
|---|---|
| Bursts up to the limit pass, the next call is refused | `test_a_burst_up_to_the_limit_passes_and_the_next_call_is_refused` |
| The refusal's retry-after is right | same test (12.0 s for 5/60 s) and `test_retry_after_is_exactly_when_the_next_token_arrives` (allowed at `retry_after`, refused 10 ms earlier) |
| Refill restores capacity | `test_a_full_window_of_silence_restores_full_capacity`, `test_a_partial_window_restores_exactly_one_token` |
| The key map cannot grow without bound | `test_the_key_map_cannot_grow_past_its_cap` (500 keys, `key_count <= 8` at every step), `test_a_full_bucket_is_pruned_without_forgetting_anything`, `test_the_least_recently_seen_bucket_is_evicted_and_a_live_one_is_kept`, `test_a_flood_of_refusals_adds_neither_state_nor_credit` |
| Clock injection drives behaviour | every test above moves `FakeClock`; `test_reading_the_clock_does_not_itself_refill`, `test_a_clock_that_moves_backwards_never_grants_tokens`, and `test_the_default_clock_is_time_monotonic_and_moves_with_real_time` (60 ms of real time, the only sleep) |

Also pinned: independent keys, no shared state between limiters, exactly one
module-level limiter, `reset()`, parameter validation, and that the decision object
is immutable.

### 3.1 The tests fail when the control is removed

Each mutation applied to a throwaway copy (`/tmp/w5mut`) of the module, suite rerun
against it, original restored:

| Mutation | Result |
|---|---|
| `_evict` returns immediately (no cap) | 3 failed: `test_the_key_map_cannot_grow_past_its_cap`, `test_a_full_bucket_is_pruned_without_forgetting_anything`, `test_the_least_recently_seen_bucket_is_evicted_and_a_live_one_is_kept` |
| injected clock ignored (`self._clock = time.monotonic`) | 9 failed, incl. `test_retry_after_is_exactly_when_the_next_token_arrives`, `test_reading_the_clock_does_not_itself_refill` |
| refill disabled | 8 failed, incl. both refill tests |
| refusal spends half a token | 2 failed: `test_retry_after_is_exactly_when_the_next_token_arrives`, `test_reading_the_clock_does_not_itself_refill` |
| `retry_after` returns the whole window instead of the time to one token | 4 failed |
| `check` always allows | 14 failed |

## 4. Middleware smoke test, verbatim

The §2 snippet run against a `FastAPI` app under `TestClient`, 3 tokens per 6 s,
fake clock (`/tmp/w5_middleware_smoke.py`, throwaway):

```
burst: [200, 200, 200]
refused: 429 {'retry-after': '2', 'content-length': '33', 'content-type': 'application/json'} {'detail': 'Rate limit exceeded.'}
keys: 1
after 6s: 200
```

`retry-after: 2` is 6 s / 3 tokens, and the counter moved without real time
passing: the clock injection survives the middleware path.

## 5. Repository state

`git status --porcelain` shows `backend/app/main.py` modified — by another worker,
not by this one; my two files are the untracked additions listed at the top. The
full backend suite currently reports:

```
3 failed, 1756 passed, 1 warning in 24.90s
```

The three failures are `test_mock_provider_slice19.py::test_a_configured_override_is_echoed_verbatim_including_an_ungiven_record`
and two `test_semantic_guard_negation_corpus.py` rows (`TG-NOBODY-WALKED`,
`SC-NO-ONE-WAS`), in modules that do not import `app.rate_limit`; another worker is
editing `app/mock_provider.py` and `app/semantic_guard.py` concurrently. Nothing in
this worker's change touches them, and I did not investigate them further — they
are outside my ownership.

## 6. What would move the claim

The claim is "this bucket is a correct, bounded control and its tests discriminate".
It is backed by the run in §3, the mutation table in §3.1 and the middleware run in
§4, all on this machine against this copy of the file. It does **not** cover: a
real multi-worker deployment (the limit multiplies per process), a real client
behind a proxy (the key is the proxy), or whether 60/min is the right budget for
the UI's polling — that number is a policy choice the coordinator should confirm
before wiring, since it is the only tunable that changes user-visible behaviour.
