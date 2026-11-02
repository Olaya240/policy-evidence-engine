# W2 — signed fields on `Claim`

## What changed

`backend/app/models.py`, `class Claim` (lines 84–101):

```python
    evidence_score: Optional[float] = None
    evidence_direction: Optional[Literal["FOR", "AGAINST", "NONE"]] = None
```

Placed immediately after `confidence`, because the three fields describe one
decision and a reader who sees `confidence: 0.5` needs the sign in the same
breath. `uncertainty` and every later field keep their positions; no existing
field was renamed, removed, retyped or reordered.

`Literal` was added to the existing `typing` import line — stdlib, and the file
already imports `Optional` from the same module.

## Why these details

- **Defaults, not validators.** Both fields default to `None`, following the
  `explanation_trace` convention already in this model ("absent legacy snapshots
  serialize as unavailable"). A row written before the signed table existed has
  neither key and must still construct and validate.
- **No bound on `evidence_score`.** `confidence` keeps `Field(ge=0, le=1)`; the
  new field deliberately has none. `decision_table.score` is strictly inside
  (-1, 1) by construction, so a bound would add nothing today and would be one
  more thing able to reject a stored snapshot later — the opposite of the
  compatibility goal. If the coordinator wants the bound, `ge=-1, le=1` is the
  exact form, and it is safe against legacy `null`.
- **`confidence` untouched.** Type, bounds and meaning unchanged; this slice adds
  a view, it does not migrate the field.

## Not verified (no terminal)

- I could not run `pytest`, a typechecker, or a serialisation round-trip. The
  untested risk is exactly the one this slice is about: `Claim.model_validate`
  on a stored dict that predates the fields. It should pass because both default
  to `None`, but "should" is not "did".
- I could not confirm that no other module builds `Claim` positionally. It cannot
  matter: Pydantic v2 rejects positional construction, so any such call would
  already be failing.
- Nothing in `app/engine.py` populates the fields yet — that is worker 3's slice.
  Until then they serialise as `null` on every claim.

## Memory

`local_memory__memory_store` is not bound to this worker session — my tool list
is `read_files`, `str_replace`, `write_file`, `code_search`, `glob`,
`list_directory`. I am not claiming a write I did not make. The durable fact is
recorded above instead: `Claim.evidence_score` / `Claim.evidence_direction` are
optional with `None` defaults, and `confidence` keeps `ge=0, le=1`.
