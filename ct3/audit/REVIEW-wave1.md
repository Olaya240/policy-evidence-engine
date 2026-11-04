# REVIEW — wave 1 change set

Reviewer turn: `decide` (findings only, nothing fixed). Reviewed 2026-11-02
03:40–03:53 +01:00.

**The tree under review moved while it was being reviewed.** One tree fingerprint is
used for every number below, so they are all comparable (first 16 hex characters of
`sha256sum`; the tree value is the hash of the sorted per-file hash list):

```
cd backend && find app tests -name '*.py' | sort | xargs sha256sum | sha256sum
579c5298f2bdb102   # app/ + tests/, all *.py  -> every measurement and both runs
f638390d7c9dbdc6   # backend/app/semantic_guard.py
f28734676f222ad9   # backend/tests/test_semantic_benchmark.py
e6fa5b315a0d8b6e   # backend/app/store.py
11a2fc05c442cd28   # backend/app/models.py
ae6f10ed586c6944   # ct3/audit/SEMANTIC-BENCHMARK.md
```

Two test modules and one audit document (`test_semantic_holdout_v2.py`,
`test_semantic_guard_mood.py`, `SEMANTIC-HOLDOUT-V2.md`) appeared **during** this
review, and `semantic_guard.py` gained two rules at 03:44:42 — after the wave-1
benchmark document was written (02:17:39). Finding **C1** is a direct consequence.

The brief listed `app/ingest.py` and `app/dependency_graph.py` as changed. They are
not in the change set; `git diff --name-only` returns only `decision_table.py`,
`models.py`, `semantic_guard.py`, `store.py` and two test files.

---

## Per-file verdicts

| File | Verdict |
|---|---|
| `backend/app/store.py` | **Sound.** Localisation is real: one unreadable row now fails closed by row (`CorruptStoredRow` carrying table/row/column) or is skipped with a report, never a whole-endpoint 500. Verified by probe, not by test (see §4). One gap: the skip is visible only in-process — see F1. |
| `backend/app/models.py` | **Sound for the three fields it covers, incomplete for the request body.** The `Cc` filter is by Unicode category, runs before `str.strip()` (`models.py:230` precedes `:234`), and leaves `Cf`/`Zl`/`Zp`/emoji alone — verified by probe. But `tags` and `source_group` on the same endpoint take a NUL and store it: **F5**. Minor: `department` errors are labelled "Ingested text and department" (`models.py:230`), so a caller with a bad department is told the wrong field. |
| `backend/app/semantic_guard.py` | **Behaviour unobjectionable, but no longer the file the wave-1 audit describes.** Two further rules (`CUE_IN_QUESTION`, `CONDITIONAL_CUE`) landed at 03:44. See **C1**. |
| `backend/app/decision_table.py` | **Sound.** Comment-only change; every number in the new comment re-derived (§3, claim 3). |
| `backend/app/provider_replay.py` | **Sound and unusually well-scoped.** No network I/O, no adapter instance, `_parse_response` is the live validator, and the `synthetic`/`recorded` label travels into the result. B5/B6 correctly remain open (`B5-B6-HOW-TO-CLOSE.md:5-10`). |
| `backend/tests/test_attack_surfaces_integrity.py` | **Strengthened, not weakened.** See §1. |
| `backend/tests/test_confidence_reliability.py` | **Sound; additions only.** Assertions are real and reproduce (§3, claim 3). |
| `backend/tests/test_attack_surfaces_controls.py` | **Strong suite, and the best file in the change set.** Two weak spots (F2, F3) and one hole it should have caught (F5). |
| `backend/tests/test_provider_replay.py` | **Sound.** `test_replay_and_the_live_path_produce_the_same_proposals_from_the_same_body` obtains its comparison value from `MandatoryProviderBoundary(...).assess(...)` with a mocked socket (`test_provider_replay.py:138-148, 171-184`), i.e. the live path, and pins `wire_sha256` against the actually-sent request. Not circular. |
| `backend/tests/test_semantic_benchmark.py` | **Sound measurement, one floor too loose.** See F4. |
| `ct3/audit/SEMANTIC-BENCHMARK.md` | **Numbers accurate for the module they measured, stale for the module in the tree.** See C1. |
| `ct3/audit/BACKEND-GRADE.md` | **Two numbers do not reproduce, and disagree with `DECISIONS.md`.** See C4, C4b. |
| `ct3/audit/CONFIDENCE-CALIBRATION.md` | **Reproduces in full.** See C3. |
| `ct3/audit/REVIEW-GUIDE.md` | **Pre-existing stale counts** — 12 decisions where the register has 18, 1779 tests where the suite has 2322. See C6. |
| `ct3/audit/B5-B6-HOW-TO-CLOSE.md` | **Consistent with the code.** The refusal-code list in §3 matches the codes `provider_safety.py` raises; nothing is claimed as done. |

---

## 1. Weakened assertions — **none found**

The complete set of deleted assertion lines across this change set is six lines, all
in `backend/tests/test_attack_surfaces_integrity.py`:

```diff
-# 1. A claim row whose JSON is truncated must surface as a bounded error, never a
-#    traceback or a partially populated claim.
-    assert response.status_code in {500, 503}, response.status_code
-# 2. A record whose timestamp is not a timestamp is the same class of problem.
-    response = call("POST", "/api/investigations", json_body={"question": QUESTION})
-    assert response.status_code in {422, 500, 503}, response.status_code
```

and what replaced them:

```diff
+    assert response.status_code == 503, response.status_code
+    _assert_bounded_failure(response)        # keys == {"detail"}, len <= 200, no leak
+    ...
+    assert response.status_code == 201, response.status_code          # integrity:116
+    _assert_bounded_failure(record_read)     # the read of the bad record is what 503s
```

Both replacements are **stronger** (a 503 with a bounded body replaces "500 or 503"),
so nothing was weakened. But the second one is not a weakening — it is a
**reversal**, and that is the review's first finding.

### F1 — the write path's fail-closed property was inverted, and the new contract is untested at its boundary

Before: a corpus containing an unreadable record made `POST /api/investigations`
answer `500/503/422` (fail closed). After: it answers `201` and assesses the readable
rows only. That is a defensible product decision, but the property that was dropped —
*"a decision is never computed over a corpus the service knows is incomplete without
saying so"* — is not replaced by anything. The new test asserts the 201 and then
checks the *skip report*, which is a Python-only API:

- `backend/tests/test_attack_surfaces_controls.py:205-209` asserts
  `store.list_records_with_report()` reports `BAD-ROW`.
- Nothing asserts the HTTP caller learns anything.

Measured (probe below, plus a second probe): with one corrupt record among 14 rows,
`POST /api/investigations` → `201` with response keys
`['claims', 'created_at', 'id', 'preset_id', 'question', 'version']` — no skip,
degraded or warning field — and `GET /api/records` → `200` serving 12 of the 14
(one is restricted, one unreadable). The only trace is a `logging.warning` line on
the server, emitted twice (once for the list read, once for the assessment):

```
Unreadable stored row records:BAD-ROW (column timestamp): value does not match the record schema
```

So the module docstring's claim that the skip is "reported rather than swallowed"
(`test_attack_surfaces_controls.py:21`) holds for an in-process caller and is
false through the API. A policy decision that silently omitted an unavailable
checklist record is exactly the failure shape the rest of this repo is built to
prevent. **Recommendation:** surface the count (e.g. `incomplete_corpus: 1`) on the
investigation response, or fail closed on the write path and degrade only on reads.

---

## 2. Tests that cannot fail, or whose name claims more than the body checks

### F2 — `test_legitimate_unicode_is_still_accepted_by_ingest` does not check the characters its own docstring promises

`backend/tests/test_attack_surfaces_controls.py:323-332`:

```python
    assert response.status_code == 201, response.text
    stored = response.json()["record"]
    assert stored["department"] == "Réception 👋"
    assert "👋" in stored["text"]
    assert {record["id"] for record in call("GET", "/api/records").json()} >= {stored["id"]}
```

The module docstring (`:29-30`) says "NFC, NFD, combining marks, RTL marks,
U+2028 / U+2029, emoji and ZWJ sequences must keep working". The body checks the
emoji and nothing else. The last line is implied by the 201 (the record was just
created and the list endpoint returned it in every prior run) — it cannot fail
independently.

This matters because the claim is **false for the ingest path**, which no assertion
catches:

```
NOTE  B5 U+2028 survived ingest verbatim: False (len 49 vs 49)
```

`backend/app/ingest.py:44,49`:

```python
_WHITESPACE = re.compile(r"\s+")
    return _WHITESPACE.sub(" ", text).strip()
```

`\s` matches `U+2028` (Zl) and `U+2029` (Zp), so ingest rewrites both to `U+0020`
before storing. The question and challenge-quote paths *do* preserve them (probe
B7/B8, B3-in-`ChallengeCreate`), and `models.py:26` is careful to say only
"category-legal and stay accepted" — which is true. It is the *test module's*
docstring that over-claims, and the test that should have caught it does not.
Fix is either an assertion (`stored["text"] == LEGITIMATE_UNICODE`) or narrowing the
docstring to "accepted, whitespace-normalised".

### F3 — a vacuous assertion

`backend/tests/test_attack_surfaces_controls.py:285`:

```python
    assert text not in [record["text"] for record in call("GET", "/api/records").json()]
```

`text` contains a `Cc` character and every stored record's text comes through
`normalise_text`; the string cannot appear in the corpus whether or not the refusal
worked. The assertion above it (`422` + `U+00XX` + `Cc` in the body) is the real
check; this line adds nothing and can only mislead a later reader into thinking
"nothing was stored" is verified. (Nothing *is* stored only because the request was
refused before the write; no assertion here establishes that independently.)

### F4 — the accuracy floors cannot detect a regression to the number their own docstring quotes

`backend/tests/test_semantic_benchmark.py:696-705`:

```python
def test_dev_accuracy_floor():
    """Regression floor: 50/64 = 0.781 measured after the hedge fix."""
    assert measured["accuracy"] >= 0.78, format_report((DEV,))

def test_holdout_accuracy_floor():
    """Regression floor: the single holdout measurement, 31/41 = 0.756."""
    assert measured["accuracy"] >= 0.75, format_report((HOLDOUT,))
```

`50/64 = 0.78125 ≥ 0.78` — so the floor *passes at* the pre-fix-improvement baseline
it names, and the holdout floor (`0.75 ≤ 0.7561`) likewise. The current code scores
`57/64 = 0.891` and `34/41 = 0.829` (§3, C1), i.e. the pins sit ~11 and ~8 points
below the measured value. A change that re-broke the hedge rule entirely would still
be green. The docstrings are also now stale (they describe wave-1 numbers, not the
current module). Not a weakened assertion — it was never tight — but it is the one
place that would have caught C1 automatically.

### F5 — the control-character boundary is incomplete: `tags` and `source_group` still accept a NUL

This is a code gap that the test file's parametrisation hides.
`backend/app/models.py:226-235` validates `text` and `department`;
`source_group` (`:237-241`) is stripped and **not** checked, and `bounded_tags`
(`:243+`) does not check either. Measured on the same endpoint:

```
$ PYTHONPATH=. python /tmp/wave1-probe-tags.py     # POST /api/records/ingest
tags NUL        -> 201
source_group NUL-> 201
('CANARY-RESTRICTED-001', '["restricted"]', 'CANARY-RESTRICTED-001')
('20710f87-f724-4447-8efb-099d1479c2e7', '["a\\u0000b"]', None)
('4fc1818c-dd52-4d7d-b210-ef9bbbd01ffb', '[]', 'G\x00X')
EXIT=0
```

A NUL inside `tags` is stored JSON-escaped (`["a\u0000b"]`), but a NUL inside
`source_group` lands **raw** in the `records` TEXT column. Both are 201s.
`test_control_characters_in_ingested_text_are_refused`
(`test_attack_surfaces_controls.py:263`) parametrises only `text`, so no test in
this change set can notice. The gap-B docstring says "A NUL byte and other C0/C1
controls survived into stored record text … they are now refused at the schema
boundary" (lines 19-22) — true for the three fields the tests touch, false for the
other two on the same request body. If the rule is "no `Cc` in a stored record
field", `source_group` and every element of `tags` belong under the same validator.

### F6 (hygiene, not a false assertion) — the fixture leaks a database file per test

`backend/tests/test_attack_surfaces_controls.py:60-66` builds
`data/.controls-<uuid>.sqlite3` and never unlinks it. Confirmed: after the suite and
this review, `data/` holds many `.controls-*.sqlite3` and `.attack-*.sqlite3`
files (gitignored, so invisible in `git status`). Repeated runs accumulate them.
Cosmetic, but it means "the suite leaves no state" is not true.

---

## 3. Load-bearing numbers, re-derived

Seven checks across five documents: four reproduce exactly, three do not — and C1
reproduces only against the module the document was actually written for. Every
measurement below is from fingerprint `579c5298`.

### C1 — **Does not reproduce against the current tree** (the most important finding)

`ct3/audit/SEMANTIC-BENCHMARK.md:89-91` claims dev `50/64 = 0.781`, holdout
`31/41 = 0.756`, with three confusion matrices and two misread tables. Its §Files
block (`:10-15`) states the change was "one rule (`_HEDGE_FRAME`, `_is_hedged`, the
`HEDGED_CUE` reason code). **Nothing else in the module was touched.**"

Re-derived by calling `format_report()` three times (a) as the tree stands,
(b) with the two *later* rules neutralised, (c) with the hedge rule also neutralised:

```
(a) current tree         dev 57/64 = 0.891, holdout 34/41 = 0.829, 14 xfail
(b) question+conditional disabled (= wave-1 module)
                         dev 50/64 = 0.781, holdout 31/41 = 0.756, 24 xfail  ← exact match
(c) hedge also disabled  dev 45/64 = 0.703, 24→ xfail                        ← exact match
```

`(b)` reproduces **every** number in the document — both accuracies, all three
confusion matrices, both per-class precision/recall rows, the 12/8 unsafe splits,
and the ten-row holdout misread table. `(c)` reproduces the pre-fix `45/64 = 0.703`
and its matrix, and the claim that all five `hedge-d*` rows were SUPPORTS misreads.

So the document was true when written and is now **stale, not wrong**: the tree in
this change set arrives at the reviewer already 7 dev / 3 holdout rows past the
document, because two rules the document explicitly lists as deferred
("cue-in-question … Listed as the next action", §5) are now implemented in
`semantic_guard.py` (`CUE_IN_QUESTION`, `CONDITIONAL_CUE`), and `KNOWN_MISREADS` in
the test module was shrunk to 14 while the document was not re-measured
(`test_semantic_benchmark.py` mtime 03:43:17 vs document 02:17:39).
**The headline "0.781 / 0.756" in this change set does not describe the code in this
change set.** Either re-measure and rewrite §2–§5, or land the two rules in a
separate change.

### C2 — **Does not reproduce**: `2166 passed, 24 xfailed`

`ct3/audit/SEMANTIC-BENCHMARK.md:259`. Same command, twice, back to back (§5):
**`2322 passed, 14 xfailed, 1 warning`**. Delta 156. In my first run, before the two
wave-2 modules existed, the same command gave `2227 passed, 24 xfailed` (24 xfail
matches the document; 2227 does not). The document's internal arithmetic
(`1959 + 207 = 2166`, and 207 = the benchmark module's passing tests) is
self-consistent, so the figure was measured — on a tree without
`test_attack_surfaces_controls.py`, `test_provider_replay.py`, and the wave-2
modules. A suite total with no tree fingerprint beside it is not re-derivable and
should not be quoted as a state of the tree.

### C3 — **Reproduces exactly**: the confidence-calibration table

`ct3/audit/CONFIDENCE-CALIBRATION.md:39-48` and the new comment at
`backend/app/decision_table.py:281-289`:

| call | claimed | measured |
|---|---|---|
| `decide(1, 0)` | PARTIAL, 0.50 | PARTIAL, 0.5000 |
| `decide(2, 0)` | SUPPORTED, 0.667 | SUPPORTED, 0.6667 |
| `decide(1,0,disputed_contradiction=1)` | PARTIAL, 0.50 | PARTIAL, 0.5000 |
| `decide(2,0,disputed_contradiction=1)` | PARTIAL, 0.25 | PARTIAL, 0.2500 |
| `decide(4,1)` | SUPPORTED at 0.50 | SUPPORTED, 0.5000 |

The non-monotonicity (`0.50` at s=1 → `0.25` at s=2) is real, is now written down as
a known cost in the code, and is pinned by
`test_confidence_reliability.py::test_the_reported_score_is_discontinuous_exactly_at_a_status_switch`.

### C4 — **Does not reproduce**: traceability `88.9% (16/18)`

`ct3/audit/BACKEND-GRADE.md:102`, which this wave changed from `**94.4% (17/18)**`
(`git diff -U1` shows the `-` line, so the removal is not a reconstruction):

> Decision traceability | **88.9% (16/18)** | … row 18 registered open because the
> confidence finding is real. Two rows are now open (7 and 18), so the ratio fell
> even though three rows were pinned

`ct3/audit/DECISIONS.md` holds **18 rows; 1 open (row 7), 17 pinned**, and row 18
reads `pinned (policy, with named cost)` — this wave's own edit to `DECISIONS.md` is
the line that made it pinned. So the register says 17/18 = **94.4%**, which is the
value the same edit removed. The two artifacts disagree; I treat `DECISIONS.md` as
the source of truth because it is the enumerated register and the status is a
per-row cell, while `BACKEND-GRADE.md:102` is prose. Either row 18's cell or that
sentence is wrong; they cannot both be right.

### C4b — the composite `92.3` is not recomputed from the document's own after-values

The composite table (`BACKEND-GRADE.md:13-21`) still carries the **before** values
(traceability `92.9% (13/14)`, coverage `91.8% (2428/2645)`, "14 decisions"), and
sums them to `92.32` — which is arithmetically correct for that table. But the same
document's after-column reports traceability `88.9%` and coverage `91.4%`, and
`BACKEND-GRADE.md:106` claims:

> Composite does not move materially (−0.04 coverage, −0.40 traceability, both
> rounding noise against the earlier 92.3). **A (92.3) stands**

Recomputed with the weights in the document's own table:

```
before-state table (92.9, 91.8)          → 92.32   ← what the document prints
with the after-values (88.9, 91.4)       → 91.88   ← what it should print
with the register's 17/18 (94.4, 91.4)   → 92.43
```

So `92.3` is the *before* composite carrying over: `−0.04 + −0.40 = −0.44`, and
92.32 − 0.44 = 91.88. The claim "both rounding noise against the earlier 92.3" is
the tell — 0.44 of a point is being claimed as rounding. The
grade band is likely unaffected (91.9 and 92.4 are both where 92.3 was), but the
headline `92.3` does not follow from the document's own numbers, and it is quoted
next to two values that contradict it.

### C5 — **Reproduces**: the four pin files, and the corpus size

`SEMANTIC-BENCHMARK.md:240` (`122 passed`) and `:243` ("The corpus list holds 53
rows"):

```
$ pytest -q tests/test_semantic_guard_negation_corpus.py tests/test_semantic_guard_slice18.py \
            tests/test_attack_surfaces_guard_reading.py tests/test_semantic_guard_verb_negation.py
..................................................                       [100%]
122 passed in 0.36s
$ grep -c '^    (' tests/test_semantic_guard_negation_corpus.py
53
```

### C6 — the reviewer's own entry point carries a third denominator (pre-existing, not this wave)

`ct3/audit/REVIEW-GUIDE.md` is unmodified in this change set and says
`DECISIONS.md` has "12 rows" (`:29`) and "1 of 12 decisions is unproven" (`:53`), and
records `Verified output: 1779 passed, 1 warning in 28.51s (exit 0)` (`:13`).
Measured now: `DECISIONS.md` has **18** rows and the suite is **2322 passed** — the
register grew by six decisions this wave without the guide following, and a reader
entering through the guide arrives with the wrong denominator (12, 14 in the
composite table, 18 in the register — three counts for one list). Same failure as
C2 and C4: a count with no tree fingerprint, in an artifact whose whole job is to
be checkable.

---

## 4. The two gaps closed this week — verified by independent probe

Probe: `/tmp/wave1-probe.py` (source in the appendix; not committed). It does not
import any test helper and does not read the new tests — it drives the ASGI app and
raw SQLite directly.

```
cd backend && PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python /tmp/wave1-probe.py
```

Output, verbatim (`B3`/`B7` print `response.text[:200]`, which is why they stop
mid-JSON; the text contains raw U+2028/U+2029, invisible in a terminal):

```
db = /home/alex/policy-evidence-fix/data/.probe-fc6c7a1d047545dba83b96f90e22a93c.sqlite3
PASS  A1 create investigation :: 201
PASS  A2 corrupt claim row -> 503 (was 500 pre-fix) :: 503
PASS  A3 body is one bounded detail sentence :: {'detail': 'Local prototype database is unavailable.'}
PASS  A4 no SQL/table/traceback leak :: []
PASS  A5 healthy investigation still created after corruption :: 201
PASS  A6 healthy investigation still readable :: 200
PASS  A7 GET /api/records before corruption :: 200
PASS  A8 corrupt record does not 500 the list :: 200
PASS  A9 corrupt record skipped, others served :: got 12 ids, expected 12
PASS  A10 skip is reported, not swallowed :: [('BAD-ROW', 'timestamp')]
PASS  A11 write path still assesses readable corpus
PASS  A12 store names the corrupt row :: Unreadable stored row claim_versions:CHECKLIST_UNAVAILABLE (column claim_json): not valid JSON
PASS  B1 ingest refuses NUL with 422 :: 422
PASS  B2 refusal names Cc + U+0000
PASS  B1 ingest refuses ESC with 422 :: 422
PASS  B2 refusal names Cc + U+001B
PASS  B1 ingest refuses DEL with 422 :: 422
PASS  B2 refusal names Cc + U+007F
PASS  B1 ingest refuses C1 with 422 :: 422
PASS  B2 refusal names Cc + U+009F
PASS  B3 ingest accepts RTL/emoji/NFD/U+2028/U+2029/ZWJ :: {"id":"49699929-…","record":{…,"department":"Réception 👋","text":"Réception 👋 Café שלום ‏
PASS  B4 NFD mark, RTL mark, emoji, ZWJ all survive ingest
NOTE  B5 U+2028 survived ingest verbatim: False (len 49 vs 49)
PASS  B6 ingest differs from input only by whitespace normalisation
PASS  B7 question accepts RTL/emoji/U+2028 :: {"id":"ed7f6fa5-…","question":"Did שלום time pressure    affect Café ‏ handover 👋?",…}
PASS  B8 question echoed verbatim (U+2028 included)
PASS  B9 NUL in question refused 422 :: 422
PASS  B10 question refusal names U+0000
PASS  B11 NUL in challenge quote refused 422 :: 422
PASS  B12 quote refusal names U+0000
PASS  B13 tab/newline/CR are still accepted :: {"id":"58f9d3fd-…","record":{…,"text":"multi-line note",…}}

FAILURES: none
```

`EXIT=0`. Observations the probe supports that the tests do not state:

1. **Gap A closes.** A corrupt `claim_versions.claim_json` now yields `503` with
   exactly one key (`detail`), a fixed 40-character sentence, and no
   `Traceback`/`sqlite3`/`claim_versions`/`claim_json`/body-text in the response;
   a different, healthy investigation created *after* the corruption is still
   `201`/`200`. A corrupt `records.timestamp` no longer 500s the list; the row is
   skipped and named in `list_records_with_report()`.
2. **Gap B closes at the schema boundary**, across C0, DEL and C1 (`U+0000`,
   `U+001B`, `U+007F`, `U+009F`), on all three inputs (ingested text, question,
   challenge quote), with the class (`Cc`) and code point named and nothing stored.
   Legitimate Unicode is accepted: NFD combining mark, RTL marks, emoji, ZWJ
   sequences, and `\t`/`\n`/`\r` survive.
3. **One boundary the implementation and its test disagree on:** `U+2028` is not
   preserved on ingest (F2). Nothing is *rejected* that should be accepted, so the
   security control is intact; only the positive-control claim is overstated.
4. **F1's second half:** the degradation is invisible through HTTP — see §1.

---

## 5. Suite runs

Two back-to-back full-suite runs, identical tree fingerprint before and after each
(`579c5298f2bdb102`):

```
=== RUN 1 ===  TREE_BEFORE=579c5298f2bdb102
2322 passed, 14 xfailed, 1 warning in 48.81s
               TREE_AFTER=579c5298f2bdb102

=== RUN 2 ===  TREE_BEFORE=579c5298f2bdb102
2322 passed, 14 xfailed, 1 warning in 47.38s
               TREE_AFTER=579c5298f2bdb102
```

Identical counts; no run-to-run flakiness.

**Ordering probe** (the three DB-touching files, forward vs reversed vs benchmark-
first):

```
=== forward ===
49 passed in 2.94s
=== reversed ===
49 passed in 3.77s
=== benchmark first ===
266 passed, 14 xfailed in 4.90s
```

No ordering sensitivity in the subsets that share the `HACKATHON_DB_PATH` seam.

**One failure was observed and it was not flakiness.** My very first run reported
`1 failed, 2321 passed, 14 xfailed` with
`tests/test_semantic_holdout_v2.py::test_every_row_declares_a_cue_from_the_guard_inventory`
failing. That file was being written at that moment (mtime 03:44:47, i.e. seconds
before the run); on the settled fingerprint it passes in the full suite and in
isolation. It is an artifact of concurrent authors, not a defect — but it is worth
saying plainly: **a change set that is being edited while it is being verified cannot
be verified.** The coordinator should freeze the tree before the final run, and
record the fingerprint next to the result (C2 is exactly the cost of not doing so).

---

## What this review did not cover

- **Coverage.** `pytest-cov` and `coverage` are both absent from
  `/home/alex/policy-evidence-latest/.venv`, so `BACKEND-GRADE.md`'s `91.4%
  (2552/2792)` and the per-file figures (`ingest.py 85.0%`, `dependency_graph.py
  84.6%`) were **not re-derived**. Only the traceability ratio (C4) was checked.
  If the composite grade is load-bearing, it is currently resting on an unrun
  measurement.
- **`app/ingest.py` and `app/dependency_graph.py`** were named in the brief but are
  not in the change set, so I read them only as far as the ingest whitespace
  normaliser (`ingest.py:44,49`) needed for F2. `dependency_graph.py` was not
  opened.
- **The wave-2 material** (`test_semantic_holdout_v2.py`, `test_semantic_guard_mood.py`,
  `SEMANTIC-HOLDOUT-V2.md`) arrived mid-review and is outside this review's scope;
  it is only accounted for in C1 (it is what moved the benchmark) and C2 (it moved
  the suite total). Nobody has reviewed it.
- **`ct3/audit/DECISIONS.md`** was read only to count statuses. Its 18 decision
  justifications were not checked against code.
- **The provider path.** `provider_replay.py` is offline by construction; whether a
  real model returns a conforming body remains `Unknown`, as the module and
  `B5-B6-HOW-TO-CLOSE.md` both say. I did not attempt a live call and had no key.
- **No browser or visual review.** All UI claims in these artifacts are prose I did
  not verify.
- **The formal artifacts** — `ct3/DecisionTable.v`, `decision_table.py` vs SMT
  transcriptions, `ct3/audit/measure_mutations.py` — were not opened or re-run. I
  did not test whether the Lean/SMT transcriptions still describe the current
  engine.
- Nothing was fixed. Every finding above is a report, per the review brief.

---

## Appendix — probe source

```python
"""Independent probe of the two gaps closed this week. Not imported by the suite."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from uuid import uuid4

import httpx

from app import store
from app.main import app

DB = store.DATA_DIR / f".probe-{uuid4().hex}.sqlite3"
os.environ["HACKATHON_DB_PATH"] = str(DB)
store.initialize_database()

QUESTION = "Why was the checklist unavailable during handover?"
LEGIT = (
    "Réception 👋 Cafe\u0301 \u05e9\u05dc\u05d5\u05dd \u200f\u200e "
    "line\u2028sep\u2029family 👨\u200d👩\u200d👧\u200d👦"
)
failures: list[str] = []


def call(method: str, path: str, body=None):
    async def send():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.request(method, path, json=body)
    return asyncio.run(send())


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}{(' :: ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def write(statement: str, params: tuple) -> None:
    con = sqlite3.connect(DB)
    try:
        con.execute(statement, params)
        con.commit()
    finally:
        con.close()


print(f"db = {DB}")

# ---------------------------------------------------------------- Gap A
first = call("POST", "/api/investigations", {"question": QUESTION})
check("A1 create investigation", first.status_code == 201, str(first.status_code))
inv = first.json()
claim_id = inv["claims"][0]["id"]

write("UPDATE claim_versions SET claim_json=? WHERE investigation_id=? AND claim_id=?",
      ('{"id": "x", ', inv["id"], claim_id))

bad = call("GET", f"/api/investigations/{inv['id']}")
body = bad.json() if bad.headers.get("content-type", "").startswith("application/json") else {}
check("A2 corrupt claim row -> 503 (was 500 pre-fix)", bad.status_code == 503, str(bad.status_code))
check("A3 body is one bounded detail sentence", set(body) == {"detail"} and len(str(body.get("detail", ""))) <= 200, str(body))
leaks = [t for t in ("Traceback", "sqlite3", "claim_versions", "claim_json")
         if t in bad.text]
check("A4 no SQL/table/traceback leak", not leaks, str(leaks))

second = call("POST", "/api/investigations", {"question": QUESTION})
check("A5 healthy investigation still created after corruption", second.status_code == 201, str(second.status_code))
if second.status_code == 201:
    healthy = call("GET", f"/api/investigations/{second.json()['id']}")
    check("A6 healthy investigation still readable", healthy.status_code == 200, str(healthy.status_code))

before = call("GET", "/api/records")
check("A7 GET /api/records before corruption", before.status_code == 200, str(before.status_code))
healthy_ids = {r["id"] for r in before.json()}

write("INSERT OR REPLACE INTO records(id,timestamp,department,text,tags_json,restricted,source_group)"
      " VALUES(?,?,?,?,?,?,?)",
      ("BAD-ROW", "yesterday-ish", "Front Office", "The checklist binder was missing.", "[]", 0, "BAD-ROW"))
after = call("GET", "/api/records")
served = {r["id"] for r in after.json()} if after.status_code == 200 else set()
check("A8 corrupt record does not 500 the list", after.status_code == 200, str(after.status_code))
check("A9 corrupt record skipped, others served", served == healthy_ids and "BAD-ROW" not in served,
      f"got {len(served)} ids, expected {len(healthy_ids)}")
records, skipped = store.list_records_with_report()
check("A10 skip is reported, not swallowed", [r.row_id for r in skipped] == ["BAD-ROW"]
      and skipped[0].field == "timestamp", str([(r.row_id, r.field) for r in skipped]))
check("A11 write path still assesses readable corpus",
      call("POST", "/api/investigations", {"question": QUESTION}).status_code == 201)

try:
    store.get_investigation(inv["id"])
    check("A12 store names the corrupt row", False, "no exception raised")
except store.CorruptStoredRow as error:
    check("A12 store names the corrupt row", error.table == "claim_versions"
          and error.row_id == claim_id and error.field == "claim_json", str(error))

# ---------------------------------------------------------------- Gap B
for label, control in (("NUL", "\x00"), ("ESC", "\x1b"), ("DEL", "\x7f"), ("C1", "\x9f")):
    r = call("POST", "/api/records/ingest",
             {"text": f"binder{control} missing", "department": "Front Office"})
    check(f"B1 ingest refuses {label} with 422", r.status_code == 422, str(r.status_code))
    check(f"B2 refusal names Cc + U+{ord(control):04X}",
          f"U+{ord(control):04X}" in json.dumps(r.json()) and "Cc" in json.dumps(r.json()))

r = call("POST", "/api/records/ingest", {"text": LEGIT, "department": "Réception 👋"})
check("B3 ingest accepts RTL/emoji/NFD/U+2028/U+2029/ZWJ", r.status_code == 201, r.text[:200])
if r.status_code == 201:
    stored = r.json()["record"]["text"]
    check("B4 NFD mark, RTL mark, emoji, ZWJ all survive ingest",
          "Cafe\u0301" in stored and "\u200f" in stored and "\U0001f44b" in stored
          and "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466" in stored)
    print(f"NOTE  B5 U+2028 survived ingest verbatim: {'\u2028' in stored}"
          f" (len {len(stored)} vs {len(LEGIT)})")
    check("B6 ingest differs from input only by whitespace normalisation",
          stored == " ".join(LEGIT.split()))

q = "Did \u05e9\u05dc\u05d5\u05dd time pressure \u2028 affect Cafe\u0301 \u200f handover 👋?"
r = call("POST", "/api/investigations", {"question": q})
check("B7 question accepts RTL/emoji/U+2028", r.status_code == 201, r.text[:200])
if r.status_code == 201:
    check("B8 question echoed verbatim (U+2028 included)", r.json()["question"] == q)

r = call("POST", "/api/investigations", {"question": QUESTION + "\x00x"})
check("B9 NUL in question refused 422", r.status_code == 422, str(r.status_code))
check("B10 question refusal names U+0000", "U+0000" in json.dumps(r.json()))

r = call("POST", "/api/investigations/any/claims/any/challenge",
         {"reason": "probe", "source_record_id": "OPS-101", "quote": "binder\x00 was missing"})
check("B11 NUL in challenge quote refused 422", r.status_code == 422, str(r.status_code))
check("B12 quote refusal names U+0000", "U+0000" in json.dumps(r.json()))

r = call("POST", "/api/records/ingest", {"text": "\t\n multi-line\r note", "department": "Ward"})
check("B13 tab/newline/CR are still accepted", r.status_code == 201, r.text[:200])

print()
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
```
