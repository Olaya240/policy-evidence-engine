# Slice 01 — contract pass (companion to `S01-audit.md`)

`S01-audit.md` is the canonical slice report. This file records only the findings the contract pass
added, so the two do not drift into competing accounts.

## Findings unique to this pass

### F1 — the seal docstring claimed a boundary a type cannot provide (High) — Read 35-45, 49-58

`SerializedProviderRequest` said it is "created only by the allowlist serializer". Two routes
contradict it, both inherent to in-process Python:

- `_SERIALIZATION_SEAL` is a module global, so any importing code can call the constructor with it.
- `bytes.__new__(SerializedProviderRequest, b"...")` skips `__new__`; the result is refused because it
  has no seal, but `object.__setattr__(instance, "_seal", real._seal)` then makes it pass.

**Fixed** at the documentation level: the docstring now claims only what holds (no accidental caller
reaches a provider, and no request can be mutated after serialization) and names both bypasses. The
class is unchanged, because a type check is not a memory boundary and pretending otherwise is worse
than the honest limitation.

### F2 — the sensitive-text filter missed credentials without a keyword (High) — Read 97-114

The secret pattern required `api_key|access_token|password|secret` followed by `:` or `=`. A pasted
`Authorization: Bearer …`, a JWT, or a vendor key (`sk-`, `ghp_`, `xoxb-`, `AKIA…`) has no such
keyword and would have crossed the boundary into the payload. **Fixed** by adding six patterns with
long random-looking tails, plus negative tests asserting that ordinary operational text is still
eligible — over-redaction silently deletes evidence and is its own defect.

### F4 — annotation narrower than the runtime check (Low) — Read 119

`Sequence[Record]` accepts `str`; the check is `list`/`tuple`. **Fixed** by narrowing the annotation so
signature and behaviour agree. No behaviour change.

## Verified by arithmetic, not by execution (Inferred)

- Per-record size accounting: `1` separator + `len('{"id":')` + `len(',"text":')` + `len("}")` plus
  the two encoded strings. Matches the construction loop, and the equality check fails closed if it
  ever stops matching.
- The 128-record guard is reachable before the byte cap: an empty record is ~20 bytes, so 129 of them
  is ~2.6 kB against a 16 kB ceiling. Not dead code.
- `_json_string_size` agrees with `json.dumps(..., ensure_ascii=False)` for quote, backslash, the five
  short escapes, other C0 controls, DEL, multi-byte UTF-8, U+2028/U+2029 and astral code points, and
  rejects lone surrogates.

None of this ran. `tests/test_provider_safety_slice1.py` encodes it; the first command on a working
terminal is `pytest -q tests/test_provider_safety_slice1.py tests/test_provider_safety.py`.
