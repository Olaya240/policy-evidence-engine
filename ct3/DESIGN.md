# Decision table — final state after the ten-worker round

Worktree `/home/alex/policy-evidence-fix`, branch `fix/evidence-decision-table`. Nothing pushed.

## 1. Verified state

| Check | Result |
|---|---|
| `pytest -q` | **1061 passed, 0 failed** (started this round at 1030/3) |
| `coqc ct3/DecisionTable.v` | exit 0, **23 theorems**, no `Admitted` |
| `node --test ct3/frontend/disposition.test.mjs` | exit 0 |
| `git apply --check` frontend patch | clean |
| `vite build` on a patched copy | exit 0, 30 modules |
| Headless Chrome boot of the built app | renders offline fallback; **dispositions panel not exercised** |

## 2. The four open items

**1. Threshold ratification.** Now a `ThresholdPolicy` dataclass with three named policies
(`POLICY_SIGNED_MARGIN` default, `POLICY_CONTEST_BLOCKS`, `POLICY_TWO_TO_ONE`), a `policy_id`
on every `Decision`, and `ct3/THRESHOLD.md` with the consequence grid, the one-line change for
each, and the proof impact. Switching away from the default is explicitly *not* a config change:
`TWO_TO_ONE` falsifies the proved `v2_single_source_is_partial`, and `CONTEST_BLOCKS` changes the
shape of `v2Status` and must be re-proved. Left as a decision with its cost priced.

**2. Sign on the claim.** `Claim.evidence_score` and `Claim.evidence_direction` now carry the sign
outside the trace; `confidence` stays the magnitude `abs(score)` and is documented as meaningful
only next to direction. Contract pinned by `tests/test_claim_signing.py`.

**3. Frontend.** Patch applies, builds and typechecks with an unchanged error set. The renderer
logic is extracted and tested under `node --test`. Not verified: the panel rendering with
backend-shaped rows in a real session — the dispositions view is behind a claim selection that the
headless dump does not drive, so that stays open.

**4. Failing tests.** All three fixed at the cause, not by editing the assertions:
- `scripts/launch_policy_demo.py` compared an unresolved `argv[0]` against a resolved executable,
  so on POSIX (where a venv interpreter is a symlink) the launcher could not terminate its own
  process. It now resolves the argument before comparing.
- `backend/app/main.py` health probe used `SELECT 1`, a constant expression SQLite answers without
  reading the file header, so a corrupt database reported healthy. Now `PRAGMA schema_version`.

## 3. Coherence fix found by the proof-gap audit

A dispute downgrade used to leave the score describing the *undisputed* evidence: `(2 support, 0
against)` with one challenged contradiction returned `PARTIAL` at `+0.667`, so a consumer reading
score alone would infer SUPPORTED. The downgraded branch now reports the challenged configuration
(`+0.25`), so status and score agree. Two Coq lemmas were added for the sign invariant
(`v2_supported_positive`, `v2_contradicted_negative`), which was previously asserted in prose only.

## 4. Performance, measured

Three runs per worktree, 2000 iterations for the table, 200 for `investigate`:

| | v1 | v2 | delta |
|---|---|---|---|
| `_summarize_status_decision`, 10 items, p50 | 7.9 µs | 10.2 µs | +2.3 µs (+29%) |
| `_summarize_status_decision`, p95 | 8.97 µs | 11.40 µs | +2.4 µs |
| `investigate`, 10 records, p50 | 2.09 ms | 2.16 ms | +0.07 ms (+3.4%) |

The whole-request delta is larger than five claims × 2.3 µs, so most of it comes from the two extra
`Claim` fields and the policy plumbing, not the table. It is 3.4% of a call that is dominated by
provider work.

## 5. Still open

1. Ratify or change the threshold — priced in `ct3/THRESHOLD.md`.
2. Browser-level render of the dispositions panel.
3. `ct3/W9-proof-gap.md` lists divergences the Coq model does not cover: dispute downgrade,
   group-vs-record counting in the list lemmas, and the constants appearing as literals in the proof.
4. `ct3/W10-stale-claims.md` flags one live consumer that still prints an unsigned percentage
   (`frontend/src/App.tsx:147`).
