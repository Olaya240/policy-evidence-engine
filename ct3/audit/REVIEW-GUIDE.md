# Reviewer's guide

What this audit leaves behind, how to run it, and what a green run does and does not prove.
Every command here was executed on 2026-11-01 from the paths shown.

## Run everything

```bash
cd /home/alex/policy-evidence-fix/backend
PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q
```

Verified output: `1779 passed, 1 warning in 28.51s` (exit 0). There is no project virtualenv
in this tree; system `python3` has the runtime dependencies but not pytest, which is why the
interpreter is spelled out.

One focused file, same interpreter:

```bash
cd /home/alex/policy-evidence-fix/backend
PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python -m pytest -q tests/test_threat_controls.py
```

## The artifacts

| File | What it answers | How to read it |
|---|---|---|
| `LEDGER.md` | Was every line of `app/*.py` read, and what was found per slice? | 20 slices, each with its evidence commands and a "recorded, not changed" list. If a row says CERTIFIED, the section under it names the run |
| `DECISIONS.md` | Is each load-bearing design choice explicit, reversible and tested? | 12 rows: decision, alternative rejected, falsifier, test, status. Open rows are open on purpose |
| `DECISIONS-DRIFT.md` | Does the register still describe the code? | 11 CURRENT, 1 UNPROVEN, 0 DRIFTED, with the code and test quoted per row |
| `THREAT-MODEL.md` | What abuse exists per surface, what stops it, and which test proves it? | 25 rows; counts and open rows at the top |
| `THREAT-VERIFICATION.md` | Do the cited control tests exist and pass? | 18 ids run individually, table per row |
| `ARCHITECTURE` invariants | Do the properties hold off the seed corpus? | `tests/test_architecture_invariants.py` and `..._generative.py` (30 seeds) |

## Executable harnesses

```bash
cd /home/alex/policy-evidence-fix && PYTHONPATH=backend /home/alex/policy-evidence-latest/.venv/bin/python ct3/audit/slice8_properties.py
```

This one is **not** green and is not meant to be: property 5b states a literal
"disputed count equals matched challenges", which the boolean `disputed` flag cannot satisfy
when the same record is challenged twice. The failure is documented in `S08-08.md`; idempotence
is the intended behaviour and is pinned by a test.

## What green means, and what it does not

Green means: every test the audit wrote passes against the current code, and the tests that
were mutation-checked (`experiment_control`, `mock_provider`, `semantic_guard`) were shown to
fail when the behaviour they pin was removed.

Green does **not** mean:
- that the design is optimal — 1 of 12 decisions is unproven (the vendor allowlist), because
  no live vendor response exists in this repository;
- that the HTTP-threat controls are removal-sensitive — no mutation sweep exists for
  `test_threat_controls.py`;
- that the architecture is safe against a deployment adversary: host isolation, file
  permissions and reachability are outside what code can assert.

## Known open items

1. Decision 7 / threats B5 and B6 — the provider's strictness against a real Baseten response.
   One recorded response closes all three.
2. `hackathon/README.md` is referenced from the repository README but does not exist; the 503
   message no longer points at it.
3. The two open audit rows are the same vendor dependency; nothing else in `LEDGER.md` is open.
