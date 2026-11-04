# Slice 4 — verification of the three fixes (worker 5 of 10)

Read-only pass. No file under `app/` or `tests/` edited; nothing executed (no terminal).

## (a) `RecursionError` added to two except tuples

**Lines.** `provider_safety.py:770` (`BasetenMuseSparkOpenAdapter._parse_response`) and
`provider_safety.py:935` (`parse_provider_proposals`):

```python
except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
    raise ProviderSafetyError("malformed_response") from None
```

**Correct?** Yes. `RecursionError` subclasses `RuntimeError`, so it matched none of the
previous arms and escaped as an unclassified error. `json.loads` on deeply nested input
raises it, and `_reject_surrogate_text` (771) recurses once per nesting level, so it can
raise on its own as well.

**Reachable through the boundary?** Yes, despite `MAX_RESPONSE_BYTES = 4096` (line 15).
A body of `b"[" * 2048 + b"]" * 2048` is exactly 4096 bytes and produces a nesting depth
that exceeds CPython's default limit (~1000). The byte cap does not save you; the depth
cap does not exist.

**What it could break.** Catching `RecursionError` leaves the interpreter close to its
stack limit at the moment of the catch. It is safe here because the error is raised while
parsing a local structure and the handler does no further recursion, but the handler must
stay trivial — do not add logging that formats the parsed object into this arm.

**Test can distinguish present from absent?** Yes, cleanly:
`body = b"[" * 2048 + b"]" * 2048` → with the guard, `ProviderSafetyError` code
`malformed_response`; without it, `RecursionError`. That is a discriminating test, not a
"something raised" test.

## (b) Two-way model pin

**Line.** `provider_safety.py:779`:

```python
if result["model"] != BasetenMuseSparkOpenAdapter.MODEL_SLUG:
    raise ProviderSafetyError("unsupported_response")
```

with `MODEL_SLUG = "meta-models/muse-spark-open"` at `:661` and the request pinning the
same literal at `:728`.

**Correct?** As a property, yes: before this, a response could name any model and the pin
was one-way. Layering is also right — the neutral `parse_provider_proposals` must not
check a vendor model, and it does not.

**What it could break — the real risk.** If the vendor echoes anything other than the
requested literal, every live call is rejected. The plausible shapes are a dated suffix
(`meta-models/muse-spark-open-2026-05`), an alias, or the same slug with a provider prefix.
In that case the failure is total, not partial: `_parse_response` raises
`unsupported_response`, the boundary surfaces `ProviderSafetyError`, and the user sees a
controlled provider failure and an investigation that degrades to insufficient evidence —
with nothing in the trace saying "the model name differed". A one-line outage caused by a
string comparison is exactly the failure mode a pin is supposed to prevent, so this check
is only safe once one real response body has been captured.

**Can a test distinguish present from absent?** Yes for the guard (`"model":"other/model"`
→ `unsupported_response` versus accepted before the change). **No** for the value: no
offline test can tell whether `MODEL_SLUG` is what the vendor actually echoes. The
discriminator is one recorded live response, redacted and kept as a fixture; until then
the pin's *value* is an assumption.

**Recommendation.** Either keep exact match and add a fixture from a real call, or accept
`MODEL_SLUG` plus an optional `-<suffix>` while rejecting any other prefix — and either
way make the error say which model was seen (`unsupported_model`) so the outage is
diagnosable rather than generic.

## (c) `MAX_PROPOSALS = 128`

**Lines.** `provider_safety.py:20` (definition), `:952` (enforcement in
`_validate_provider_proposals`).

**Correct?** Not wrong, but it does not bind on the path that matters. Minimum viable item,
given every key is required and `quote` must be at least 3 characters:

```
{"source_record_id":"R","quote":"abc","stance":"SUPPORTS","rationale":"x"}
```

is 74 bytes; with a separating comma, ~75 bytes. Against `MAX_RESPONSE_BYTES = 4096` that
is **~54 proposals**, and longer quotes or rationales only lower it. So through
`BoundedTransportProvider` the byte cap fires at roughly 54 and the 128 limit is
unreachable — the same shape as `budget_exceeded` in slice 2: a guard that reads as
protection and cannot fire.

**Where it does bind.** `parse_provider_proposals` is a module-level public function; a
direct caller that hands it a body larger than the transport's read cap can reach 129. That
is a real caller class (tests, and any future adapter that parses before capping), so the
guard earns its place — but the comment should say so, otherwise the next reader will
assume it is the bound on the provider path.

**Is 128 defensible?** It is arbitrary. It is not derived from the 128-record cap upstream
(multiple proposals may cite one record, so the record count does not bound proposals).
A principled figure would be `MAX_RESPONSE_BYTES // min_item_bytes` (~54) if the intent is
to fail on the parse path before the byte cap, or `records × proposals_per_record` if the
intent is to bound evidence amplification per record. As written, 128 is a round number
that happens to be unreachable where it is most needed.

**Can a test distinguish present from absent?** Yes — 129 minimal items (~9.7 KB) fed
directly to `parse_provider_proposals`: without the cap, accepted; with it,
`malformed_output`. The test **must** call the parser directly; through the boundary the
byte cap fires first and the test would pass for the wrong reason.

## Ranked

1. **(b)** — a total-outage risk on an unverified vendor string. Highest because the
   failure is silent as to cause.
2. **(c)** — harmless in place, misleading in intent; unreachable where the traffic goes.
3. **(a)** — correct as written; only the catch handler needs to stay trivial.

## Durable facts for the coordinator to store

```
s: policy-evidence-engine model pin        p: IS_UNVERIFIED      o: exact match against meta-models/muse-spark-open; one real response needed to confirm the vendor echo
s: policy-evidence-engine MAX_PROPOSALS    p: IS_UNREACHABLE     o: ~54 proposals fit in MAX_RESPONSE_BYTES, so 128 only binds for direct callers of parse_provider_proposals
s: policy-evidence-engine RecursionError   p: IS_REACHABLE       o: 4096 bytes of brackets is enough depth to exceed CPython's recursion limit through the boundary
```

## Worth checking (not verified here)

A recalled note claims `engine.py:171/173/176` replaces a provider-supplied rationale with
a constant, which would matter for slice 9. It is memory, not an artifact, so it is a lead
to open, not a finding to repeat.
