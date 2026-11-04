# Threat model and control trace

Counts, as written: 26 rows — **23 proven**, 1 partial (B5), 1 declared and not
defended (H1), 1 open (B6).

Scope: the local prototype API and everything it calls. One row per abuse the system has
to survive, the control that stops it, and the test that fails when the control is
removed. A row with no test is marked **open** — a control nobody exercises is a claim,
not a defence.

The posture the code declares is a single-user, synthetic-data, local prototype with **no
authentication**. That is a product decision, not an oversight; row H1 records it as a
declaration and no row below asserts a protection that does not exist.

## HTTP surface (`app/main.py`)

| # | Abuse | Control | Test | Status |
|---|---|---|---|---|
| H1 | An unauthenticated caller reads everything | None — declared posture (`authentication: false`, `synthetic_data_only: true` in `/api/health`) | `test_the_health_endpoint_declares_the_posture_it_has` | declared, not defended |
| H2 | A hostile page reads the API from the user's browser | CORS allowlist pinned to `http://localhost:5174` / `127.0.0.1:5174`, credentials off | `test_cors_admits_the_local_ui_and_refuses_any_other_origin` | proven |
| H3 | Restricted record text leaves through `/api/records` | `store.list_records` filter + `access.visible_records` | `test_no_restricted_text_leaves_through_the_records_endpoint` | proven |
| H4 | The API tells an attacker which restricted ids exist | One 404 with identical body for restricted and absent ids | `test_a_restricted_record_is_indistinguishable_from_an_absent_one` | proven |
| H5 | A provider fault echoes record text into the response | `ProviderError` handler returns a fixed 503 body | `test_a_provider_fault_never_echoes_record_text` | proven |
| H6 | An uninitialised or corrupt database produces a 500 with a traceback | `require_database`, `DatabaseUnavailable` handler, `PRAGMA schema_version` probe in `/api/health` | `test_an_uninitialised_database_is_a_503_not_a_500` | proven |
| H7 | A malformed or oversized body reaches the engine | Pydantic models with `extra="forbid"` and bounded strings | `test_a_malformed_request_is_refused_before_the_engine_sees_it` | proven |
| H9 | A malformed body makes the *error handler* crash | `RequestValidationError` handler renders with `ensure_ascii=True` and drops non-JSON-safe values | `tests/test_attack_surfaces.py::test_a_lone_surrogate_in_the_question_is_refused_not_a_500`, `::test_non_finite_numbers_are_refused` | proven (found and fixed 2026-11-02) |
| H8 | Request flooding | `TokenBucketRateLimiter` wired as `rate_limit_middleware` in `main.py`: 600 requests/minute per client host, bounded key map, `Retry-After` on refusal, `/api/health` exempt so a flood cannot suppress the probe | `tests/test_rate_limit_wiring.py` — the second call in a window is 429 with `Retry-After`, a refusal never reaches the route, the bucket is per client not global, and health answers with an empty bucket | proven |

## Engine (`app/engine.py`)

| # | Abuse | Control | Test | Status |
|---|---|---|---|---|
| E1 | A claim carries a verdict its own evidence cannot produce | `_summarize_status_decision` is the only authority; claims are summaries of evidence | `test_architecture_invariants.py::test_every_claim_equals_a_fresh_summary_of_its_own_evidence` | proven |
| E2 | Stale evidence counts as current proof | `_is_stale`, applied at validation and again at every challenge | `test_a_future_dated_record_is_not_current_evidence`, `test_challenge_re_evaluates_staleness_at_its_own_clock` | proven |
| E3 | A citation that is not in its own source record | Quote must be an exact substring of that record's text | `tests/test_provider_safety.py` grounding cases | proven |
| E4 | A challenge rewrites the stored snapshot it was given | Challenge copies; the route passes the same dict to `apply_challenge` as `expected_claims` | `test_engine_slice8_challenge.py` purity case | proven |
| E5 | One source is counted as two independent groups | Group keys, plus the as-if dispute dedupe | `test_a_group_with_a_challenged_and_a_clean_record_is_one_source` | proven |

## Provider boundary (`app/provider_safety.py`)

| # | Abuse | Control | Test | Status |
|---|---|---|---|---|
| B1 | Restricted text reaches the provider | Projection inside `MandatoryProviderBoundary` | `test_no_restricted_record_reaches_the_provider_request` | proven |
| B2 | An unknown provider is swapped in | Exact type check in the boundary constructor | slice-5 tests | proven |
| B3 | A hostile response body | Byte cap, strict UTF-8, duplicate-key rejection, `RecursionError` mapped, closed key allowlist | slice-4 contract tests | proven |
| B4 | Too many proposals per response | `MAX_PROPOSALS = 43`, set to the measured ceiling (43 assessable, 44 refused) | `test_the_proposal_cap_binds_before_the_byte_cap_can` | proven |
| B5 | The vendor answers with a different model | Exact `MODEL_SLUG` pin | slice-4/5 tests | proven as a *rejection*; the live echo format is unknown → decision 7 open |
| B6 | A legitimate vendor response is rejected (availability) | None | — | **open** — needs one recorded live response |

## Transport (`app/httpx_transport.py`)

| # | Abuse | Control | Test | Status |
|---|---|---|---|---|
| T1 | A hanging provider holds the request open | `httpx.Timeout` plus `asyncio.wait_for` around the exchange | `test_slow_provider_control.py` — a real loopback server that reads the POST and never answers, and one that sends headers plus a partial body | proven, measured: 0.3 s timeout returned at **304 ms / 303 ms**, peer saw EOF, parser never called; the discriminator is the same server with a 20 s timeout still pending after 1.5 s |
| T2 | Cancellation leaves the response unclosed on the adapter path | `try/finally: await _close_quietly(response)` around the bounded read in `_assess_async` (`provider_safety.py:878-889`) | `test_baseten_cancellation_closes_stream_and_transport_and_releases_single_flight` (`tests/test_baseten_adapter.py:479`) | proven — the slice-4 audit reported this open against an earlier copy; the current file closes in a `finally`, and the test cancels mid-flight and asserts both the stream and the transport are closed |

## Store (`app/store.py`)

| # | Abuse | Control | Test | Status |
|---|---|---|---|---|
| S1 | The protected e2e database is opened, via `..` or a symlink | `validate_database_path`: lexical check before any filesystem touch, then resolve, then containment in `data/` | `test_store_path_safety.py` | proven |
| S2 | A challenge commits over a changed revision | `BEGIN IMMEDIATE` + revision and claim comparison inside the write transaction | `test_a_stale_revision_writes_nothing`, `test_changed_claims_behind_the_revision_are_stale` | proven |
| S3 | A client error is reported as a database outage | `connect()` scopes its `ValueError` handler to path validation | `test_a_recomputed_set_that_does_not_match_the_affected_claims_is_refused` | proven (found and fixed today) |
| S4 | Restricted rows are read directly from SQLite | `get_record` filters `restricted=0`; `list_records` filters by default | `test_restricted_records_are_hidden_from_reads` | proven |

## What this trace does not cover

- **B6 (false rejection)** is open and cannot be closed from this repository alone: it
  needs one recorded response from the live vendor.
- ~~T2~~ was reported open by the slice-4 audit against an earlier copy of the file; the
  current `_assess_async` closes in a `finally` and the cancellation test at
  `test_baseten_adapter.py:479` proves it. Recorded as a correction, not a fix.
- No row covers the *host*: process isolation, file permissions on the SQLite file, or who
  can reach port 8000. Those are deployment controls and the code cannot assert them.
