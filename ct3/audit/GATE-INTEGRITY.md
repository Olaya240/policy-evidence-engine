# Gate integrity: what `scripts/quality_gate.py` certifies, and what it does not

**Date:** 2026-11-02.
**Gate tested:** `scripts/quality_gate.py`, 680 lines,
`sha256 da410b9a19942e53a44ed53e426400ab11972a12b72930b3f8c93a292d2220ab`.
**Executable form:** `backend/tests/test_gate_integrity.py` — 9 tests, of which
**4 fail by design**; each failure begins `GATE MISS (<check>)` and states the
verdict the check owes. They are not `xfail`: an `xfail` is the same
count-it-as-passed move this audit is about (attack 5).

The question is not "does the gate run". It is: **can the gate be made to print
`PASS` over a tree that is wrong?** Eight attacks were run, on throw-away
copies. Five are caught, four are not (3 and 3b are the same check; 5 and 5b,
6 and 6b likewise).

| # | Attack | Verdict | Decided by |
|---|---|---|---|
| 1 | `Admitted.` lemma appended to `ct3/Bilattice.v` | **caught** | check 2 `FAIL 1 unproved step(s)`, `ct3/Bilattice.v:566: Admitted`. Check 1 `PASS`ed the same file (coqc exit 0), so check 1 alone certifies it. |
| 2 | `Admitted` inside a nested Coq comment | **correctly ignored** | check 2 `PASS 0 unproved steps`; naive `grep -n Admitted` reports the line. |
| 3 | `ct3/refinement/generate_table.v` edited, digest not re-recorded | **caught** | check 3 `FAIL 1 of 2 recorded digests are stale` … `generate_table.v … STALE`. |
| 3b | same edit, digest re-recorded, `decision-table.out` **not** regenerated | **MISSED** | check 3 `PASS 2 of 2 recorded digests match`; refinement test `6 passed`; gate `5 PASS, 0 FAIL`. |
| 4 | two added tests whose bodies assert nothing | **MISSED** | check 4 `PASS 5129 passed, 0 failed, 14 xfailed`. |
| 5 | strict `xfail(reason="")` | **caught** | check 5 `reason too short (0 <= 30 chars, literal): ''`. |
| 5b | non-strict `xfail` on a genuinely failing test | **MISSED** | check 5 `PASS … 1 non-strict, 0 violation(s)`; pytest `1 xfailed`, exit 0. |
| 6 | route raises, `raise_app_exceptions=False` | **caught** | check 6 `500 … UNEXPECTED 5xx`. |
| 6b | route raises `HTTPException(503, detail=<a documented sentence>)` | **MISSED** | check 6 `503 … allowed: documented provider-capacity outage (ProviderError)`. |

**No repository file was written by any attack.** Every attack ran on a
`cp -a` copy under `/tmp` (`backend/tests/test_gate_integrity.py` copies the
same tree's `scripts/`, `ct3/` and `backend/` with `shutil.copytree`, plus an
empty `data/` for check 6); `git status` after the runs shows only the two files
this worker added. `ct3/refinement/decision-table.out` is byte-identical to the
committed artifact (`sha256 777a55e5…43463c5`).

## How to reproduce any row

```bash
V=/home/alex/policy-evidence-latest/.venv/bin/python
T=$(mktemp -d)/repo && cp -a /home/alex/policy-evidence-fix "$T"
check() {  # check <tree> <check function>
  "$V" -c 'import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["g"] = m
spec.loader.exec_module(m)
r = getattr(m, sys.argv[2])(False)
print(r.status, "|", r.detail)
for line in r.lines: print(line)' "$1/scripts/quality_gate.py" "$2"
}
```

The copy has its own `ROOT` (`Path(__file__).resolve().parents[1]`), so the
copied gate inspects the copied tree. Check 1 compiles in a temp copy of
`ct3/`, so it never regenerates the copy's `decision-table.out`.

## 1. Stale proof — caught, and only by check 2

```bash
cat >> "$T/ct3/Bilattice.v" <<'EOF'

Lemma gate_attack_stale : True.
Admitted.
EOF
coqc -Q "$T/ct3" "" "$T/ct3/Bilattice.v"; echo "coqc exit=$?"
check "$T" check_proofs_build
check "$T" check_no_unproved_steps
```

```
coqc exit=0
PASS | 6 .v files compiled in 8.2s (Attribution.v, Bilattice.v, DecisionTable.v, IntervalReport.v, StanceAlgebra.v, generate_table.v)
FAIL | 1 unproved step(s) in 6 .v files
ct3/Bilattice.v:566: Admitted
```

`Admitted.` closes a proof with an axiom; `coqc` accepts axioms. A gate that
stopped at "the proofs build" would certify a proof that proves nothing. Here
check 2 catches it, in the right file and at a line number that matches the
appended text.

## 2. Comment-only proof — correctly not flagged

```bash
cat >> "$T/ct3/Bilattice.v" <<'EOF'

(* outer comment: (* nested Lemma gate_attack_hidden : True. */ Admitted. *)
EOF
grep -n Admitted "$T/ct3/Bilattice.v"
check "$T" check_no_unproved_steps
```

```
565:(* outer comment: (* nested Lemma gate_attack_hidden : True. */ Admitted. *)
PASS | 0 unproved steps in 6 .v files
```

The docstring's warning is true: a naive `grep` produces a false positive here,
and the stripper removes it. It counts `(* *)` depth rather than regexing, so
the nested comment body is blanked and the scan still reports zero. **This
attack does not land** — the scanner does what it claims. (Same file, same
line numbering: the stripper replaces characters, not lines.)

## 3. Refinement freshness — caught only when the digest is left alone

```bash
printf '\n(* gate attack *)\n' >> "$T/ct3/refinement/generate_table.v"
check "$T" check_refinement_freshness
```

```
FAIL | 1 of 2 recorded digests are stale
    DecisionTable.v      recorded 456b2a663a9215ef  actual 456b2a663a9215ef  ok
    generate_table.v     recorded 4f6348d5f0e3ee4e  actual bbb0ac1b42f98c48  STALE
```

### 3b. The miss: re-recording the digest is enough

`GENERATED_FROM_DIGESTS` is a literal inside
`backend/tests/test_decision_table_refinement.py`. The check recomputes
`sha256(.v)[:16]` and compares it with that literal. It never regenerates
`decision-table.out`, and it never hashes `decision-table.out`. So the
"regenerate" half of its own repair message can be skipped as long as the
"re-record" half is done. The edit below is semantic, not cosmetic —
`emit_cell`'s numerator bias moves 8 → 9, which changes every emitted row:

```bash
python3 - "$T" <<'PY'
import hashlib, pathlib, sys
t = pathlib.Path(sys.argv[1])
g = t / "ct3/refinement/generate_table.v"
g.write_text(g.read_text().replace("Z.to_nat (cell_num x + 8);", "Z.to_nat (cell_num x + 9);"))
r = t / "backend/tests/test_decision_table_refinement.py"
r.write_text(r.read_text().replace(
    "'generate_table.v': '4f6348d5f0e3ee4e'",
    f"'generate_table.v': '{hashlib.sha256(g.read_bytes()).hexdigest()[:16]}'"))
PY
check "$T" check_refinement_freshness
cd "$T/backend" && PYTHONPATH=. "$V" -m pytest -q tests/test_decision_table_refinement.py | tail -1
cd "$T" && "$V" scripts/quality_gate.py --fast | tail -4
```

```
PASS | 2 of 2 recorded digests match
6 passed, 1 warning in 0.17s
--- 5 PASS, 0 FAIL, 2 SKIPPED ---
```

The refinement test passes because it reads the **old** `decision-table.out`,
which no longer describes `generate_table.v`; `--fast` skips only checks 4 and
7, so a full run adds a green suite and changes nothing. In the same copy, when
`coqc` *is* run, the table is regenerated and the refinement test fails
(`2 failed, 4 passed`) — the artifact is the only thing that would have caught
the change, and the gate does not look at it. (Run `coqc` in that copy and the
table is regenerated, after which the refinement test fails: `2 failed, 4
passed`.)

**Why it is missed:** the check pins the inputs to a literal that the same edit
can rewrite, so it proves "nobody edited the model since a human said they
regenerated", not "the artifact was regenerated from this model".

## 4. A test that passes for the wrong reason — missed

```bash
cat > "$T/backend/tests/test_gate_noop.py" <<'EOF'
def test_every_route_rejects_hostile_input():
    pass

def test_the_provider_never_sends_secrets():
    assert True
EOF
check "$T" check_suite
```

On the full suite (5 127 tests): `PASS | 5129 passed, 0 failed, 14 xfailed,
0 errors in 58.3s`. The executable test trims the copy's test directory so the
same demonstration costs a second instead of a minute: `PASS | 8 passed`.

**Why it is missed:** check 4 is a count. It reads pytest's exit code and three
integers off the summary line (`passed`, `failed`, `xfailed`, plus `errors`),
and "passed" means only that the test body raised no exception. An empty body
and a strong assertion are the same integer. Nothing in the check counts
assertions, measures coverage, or asks whether the test touches the code under
review, so a file named after a property it never checks is indistinguishable
from one that tests it.

## 5. Xfail discipline — one caught, one missed

```bash
cat > "$T/backend/tests/test_gate_xfail_attack.py" <<'EOF'
import pytest

@pytest.mark.xfail(strict=True, reason="")
def test_strict_xfail_empty_reason():
    assert False

@pytest.mark.xfail(strict=False, reason="known bug: this test fails and must not be counted")
def test_non_strict_xfail_on_a_real_defect():
    assert False
EOF
check "$T" check_xfail_discipline
```

```
FAIL | 3 strict xfail site(s) covering 15 row(s), 1 non-strict, 2 violation(s)
backend/tests/test_gate_xfail_attack.py:5: reason too short (0 <= 30 chars, literal): ''
backend/tests/test_gate_xfail_attack.py:5: no comment within 60 lines above names the defect
```

### 5b. The miss: `strict=False` is exempt

With only the non-strict site present, check 5 returns
`PASS | 4 strict xfail site(s) covering 16 row(s), 1 non-strict, 0 violation(s)`
(the site counts are the tree at audit time; other test files in this wave move
them), and pytest on the same file returns `1 xfailed` / exit 0 — so check 4 also
counts the run as green.

**Why it is missed:** `check_xfail_discipline` treats `strict` as a boolean it
must find as the literal `True` and `continue`s on everything else, so the one
marking that can never fail a run is the marking it never inspects; a
non-strict xfail on a real defect is therefore counted under `N non-strict` and
certified twice — once by check 5 and once by the suite count.

## 6. Hostile 5xx — the bare crash is caught, a quoted sentence is not

The app copy gets two routes and the copied gate gets two requests:

```python
@app.get("/api/gate-crash")
def route_api_gate_crash():
    raise RuntimeError("gate attack: unhandled exception in a route")

@app.get("/api/gate-disguised-crash")
def route_api_gate_disguised_crash():
    raise HTTPException(status_code=503,
                        detail="Assessment provider is unavailable or returned invalid output.")
```

```
raising route          GET /api/gate-crash             500  UNEXPECTED 5xx
disguised 503          GET /api/gate-disguised-crash   503  allowed: documented provider-capacity outage (ProviderError)
```

**Attack 6 is caught.** `raise_app_exceptions=False` turns the unhandled
exception into Starlette's plain-text `500 Internal Server Error`;
`response.json()` yields no detail; `ALLOWED_5XX` has nothing to match, and the
check fails. The documented-code list is not wide enough to swallow it.

**6b is missed.** `ALLOWED_5XX` is consulted as
`next((why for frag, why in ALLOWED_5XX.items() if frag in detail), None)`: a
substring of client-visible prose, not the exception type that produced the
response. Any handler that raises `HTTPException(503, detail=<one of the three
sentences>)` is recorded as the documented outage it names, and the check
passes.

**Why it is missed:** the allow-list is keyed on a string the failing handler
chooses, so the check cannot distinguish a documented provider outage from an
application-level 503 that quotes one; keying it on the exception
(`ProviderError`, `store.DatabaseUnavailable`) would.

## The four misses, one sentence each

1. **Refinement (§3b):** the check hashes the model's input files against
   literals the same edit can rewrite, so re-recording the digest without
   regenerating `decision-table.out` certifies a stale artifact.
2. **Suite (§4):** the check counts pytest outcomes, and a body that asserts
   nothing produces the same `passed` as one that proves the property its name
   claims.
3. **Xfail (§5b):** a site whose `strict` is not the literal `True` is counted
   and exempted rather than judged, so the one marking that can never gate is
   the one never checked.
4. **Hostile 5xx (§6b):** the allow-list matches a substring of client-visible
   detail text rather than the exception that produced the 503, so a handler
   that quotes a documented sentence is certified as the outage it names.

## Consequences, and what was not done

* `backend/tests/test_gate_integrity.py` adds 5 green tests and 4 red ones (the
  four misses). The gate's **check 4 therefore fails on the current tree**, by
  design: the suite now contains four assertions the gate does not satisfy.
  Fixing the four checks turns them green; the messages name the owed verdict.
* **The gate is not patched here.** `scripts/quality_gate.py` is owned by
  another worker in this wave, and each miss above names the smallest repair
  (hash or regenerate the artifact; count or forbid non-strict xfails; assert
  something per test; key the allow-list on the exception).
* Not attacked: check 7 (`SKIPPED` by design — the harness accepts no
  `--fast`), check 1's topological order and cycle handling, check 4's
  1800-second timeout, check 6's rate limiter and its twelve fixed requests,
  and check 2's `Axiom`/`Parameter` patterns (same regex family as `Admitted`,
  not exercised here). A `SKIPPED` check is reported as `SKIPPED` and never
  folds into a 0 — that part is faithful.
