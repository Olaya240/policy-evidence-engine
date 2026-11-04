# Certification — what the gate now proves, and what it still does not

2026-11-02, after the certification wave. **`scripts/quality_gate.py` → 7 PASS, 0
FAIL, 0 SKIPPED, exit 0.** Suite **5 202 passed, 0 failed, 15 xfailed, 6 skipped**.

Two consecutive full runs agree, which is itself new: the previous suite was
intermittently red (details in §1), so "5202 passed" had been a coin flip that
happened to land green the times it was quoted.

## 1. The suite was flaky, and the cause was the harness

`app/main.py:172` builds a **process-global** token bucket (600 requests/minute).
The suite makes thousands of API calls in ~85 seconds, so whether a given test saw a
429 depended on how fast the machine ran that minute. Two runs of identical code
disagreed, and the failing test was whichever one happened to land on the empty
bucket — observed on two different tests in two runs (`test_ingest`,
`test_api_reason_codes`).

Fixed with `TokenBucketRateLimiter.reset()` and an autouse fixture in
`backend/tests/conftest.py`. The service is unchanged; the suite's verdict is a
property of the code again. This is the kind of defect that makes every previous
green number worth less than it looked.

## 2. The mutation floor now runs

`ct3/audit/measure_mutations.py --fast`: seven mutants, one per control family, each
against only the tests that are supposed to kill it. **7/7 killed in 47 s**, and the
harness prints that **15 of 22 controls are outside the sample** — a sample, not a
score. `SURVIVED`, `NOT_APPLIED` and `HUNG` all count as failure; `NOT_APPLIED`
because a stale substring means the measurement describes code that no longer exists
(three mutations were stale when this ran, and were repaired).

## 3. Two gate holes closed, one left

| Hole | Was | Now |
|---|---|---|
| refinement freshness | compared two digests living in the same commit, so re-recording both certified an unregenerated table | **rebuilds `decision-table.out` with `coqc` in a copy and compares bytes**; the digests remain as a readable first line |
| assertion-free tests | a test body of `pass` counted as a pass | check 4 rejects any test function whose body is only `pass` or only `assert <literal true>` |
| 5xx allowlist | any 503 whose detail quotes a documented sentence is accepted, whatever route produced it | **still open**, recorded as a strict xfail in `tests/test_gate_integrity.py` |

The third is a real hole: a route that fabricates a documented detail passes check 6.
Closing it needs a route allowlist (which routes may legitimately produce which 503),
which is a service decision rather than a gate tweak.

## 4. What "certified" means here, exactly

It means: the proofs compile with no unproved steps; the decision table rebuilds from
Coq and matches the shipped code byte-for-byte; the suite passes on a tree whose rate
limiter cannot make it flaky; every strict xfail names a defect and a reason; hostile
input produces no unexpected 5xx; and every sampled control is killed by a test.

It does **not** mean the reader is right. The measured semantic numbers are in
`REVIEW-final.md`, the falsification corpus is saturated at 0 and therefore no longer
evidence, and no human has labelled a single row.

## 5. Why a Baseten key would matter, and why nothing here needs one

`app/provider_activation.py` and `app/main.py:74-90`: when `BASETEN_API_KEY` is set,
the service builds a real assessment provider; when it is not, the deterministic
mock is used. The key is required for exactly two claims that cannot be made without
it:

1. **the live provider path has executed at all** — it never has, in any run in this
   repository, so every provider statement is a statement about the mock;
2. **the reader's readings transfer** — whether a model's proposals pass
   `provider_safety` and grounding is an empirical question about that model, and a
   recorded response would answer it offline through `provider_replay.py`.

Everything certified above is independent of it: the proofs, the refinement, the
suite, the hostile-input checks and the mutation sample all run against the mock. So
the key is not a blocker for certification — it is a blocker for the *provider*
claim, and quoting a live-provider number without it would be the fabrication this
gate exists to prevent.
