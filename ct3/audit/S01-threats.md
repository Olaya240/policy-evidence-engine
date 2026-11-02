# Slice 01 — adversarial audit of `app/provider_safety.py:1-208`

Read in full (1-208) plus 209-225 to see the boundary of the last function. No execution: this
session has no terminal, so every rating below is **Read** or **Inferred**, never Observed.

Scope bound, stated first: `_is_serialized_request` (50-51) is *defined* here and **has no caller
inside this range**. The seal is only enforced where a boundary consumes a request, which lives at
>= 209 and is not part of this slice. Anything I say about "enforcement" is therefore about the
mechanism, not about a gate that this slice exercises.

## A. Seal forgery — `SerializedProviderRequest`

```python
34  class SerializedProviderRequest(bytes):
37      def __new__(cls, payload: bytes, *, _seal: object = None):
38          if _seal is not _SERIALIZATION_SEAL:
39              raise ProviderSafetyError("invalid_request")
41          object.__setattr__(instance, "_seal", _SERIALIZATION_SEAL)
44      def __setattr__(self, name, value): raise AttributeError(...)
50  def _is_serialized_request(value):
51      return type(value) is SerializedProviderRequest and getattr(value, "_seal", None) is _SERIALIZATION_SEAL
```

| # | Route | Result | Class |
|---|---|---|---|
| A1 | `from app.provider_safety import _SERIALIZATION_SEAL`, then construct with it | **Passes.** Python module privacy is convention, not a capability. | (i) with in-process code execution |
| A2 | Subclass, then construct subclass with the sentinel | Constructor succeeds; `_is_serialized_request` rejects because `type(value) is` is exact. | blocked at the check |
| A3 | `copy.copy(req)` / `pickle.loads(pickle.dumps(req))` | For a `bytes` subclass, the copy protocol reconstructs via `bytes.__new__` with `base=bytes`, bypassing `__new__`'s seal → the copy has **no** `_seal` → a *legitimate* request becomes invalid. | (ii) latent trap |
| A4 | `bytes(req)`, `req[:]`, `req.decode().encode()` | Plain `bytes`; type check fails. | blocked |
| A5 | `object.__setattr__(req, "_seal", ...)` | Bypasses the `__setattr__` override; needs the sentinel anyway. | same as A1 |

A3 is the one worth a decision: either copying a request should stay valid, or copying should raise
a controlled `ProviderSafetyError` instead of producing an object that fails a check somewhere else,
far from the cause. A3 is **Inferred** from CPython's copy protocol for immutable subclasses; the
falsifying run is one line — `_is_serialized_request(copy.copy(sealed))`.

## B. Eligibility — what is actually inspected

`eligible_provider_records` (87-99) inspects exactly three things: `record.restricted`,
`contains_sensitive_text(record.id)`, `contains_sensitive_text(record.text)`.

Not inspected: `department`, `timestamp`, `tags`, `source_group`.

That is **not** a leak in this path, because the serializer emits only `id` and `text`
(173-208). It does mean the filter's unit is the record, so a secret split across two records
(`"api_key:"` in one, the value in the next) passes: each record is clean on its own.

`AssessmentContextRecord.restricted` (property, 54-65) returns `False` unconditionally. A constant
is worse than an absent field: it answers a policy question with "not restricted" when the
projection has no information. Today it is harmless because restricted records never reach the
projection. Tomorrow it is a silent authorization bypass for any consumer that trusts it.

## C. `contains_sensitive_text` — concrete misses, both directions

Patterns (75-80): email, phone-ish (`>= 10` digits), `\d{3}-\d{2}-\d{4}`, and
`(api_key|access_token|password|secret)\s*[:=]\s*\S+`.

**False negatives**
1. `"api\u200b_key: sk-live-abc"` — a zero-width space breaks `api[_ -]?key`. Passes.
2. `"AKIAIOSFODNN7EXAMPLE"` — a bare cloud key id with no `key=` label. Passes.
3. `"josé@exemple.fr"` — the local-part class is ASCII-only. Passes.

**False positives**
1. `"Order 1234567890 was delayed"` — the phone pattern matches; the whole record is dropped.
2. `"Shift 2026.01.01 2026.01.02"` — digits and separators satisfy the phone class; dropped.

**Which direction matters here.** A false positive silently removes a source from an audit product,
and `eligible_provider_records` returns a list with **no reason attached**, so the caller cannot
distinguish "no records" from "every record filtered". That is the more damaging failure for this
system. The privacy direction is bounded by the synthetic corpus and by `MAX_REQUEST_BYTES`; the
audit-integrity direction is bounded by nothing.

## D. Size model — `_json_string_size` (143-162) and the equality check (206)

The per-character model matches `json.dumps(ensure_ascii=False)` for every class it names: short
escapes 2, other C0 controls 6 (`\u00XX`), everything else its UTF-8 length. U+2028/U+2029 are
emitted raw by `json.dumps` and counted as 3 bytes, which is consistent. I found no under-count.

Two semantic problems, not arithmetic ones:

- Line 206 (`if len(payload) != predicted_size: raise ProviderSafetyError("request_too_large")`)
  converts a *model bug* into a client-shaped error. If the model ever drifts, the symptom is
  "your request was too large" for a request that was small. Nothing distinguishes the two.
- `len(permitted) > 128` (176-178) reuses the same code. Three different conditions, one code:
  too many records, payload too large, and internal model mismatch.

## E. Out-of-slice notes, flagged not judged

- `import math` (line 4) is unused in 1-208. Not a defect; likely used later. Out of slice.
- `_TRANSPORT_SINGLE_FLIGHT = Lock()` (20-21) with a comment claiming it "fail[s] fast rather than
  blocking an event loop". That property lives in the acquire site at >= 209; it belongs to slice 05,
  and it is the highest-risk thing in this file, because a blocking `Lock` acquired from async code
  stalls the whole loop.

## Ranked

1. **(ii)** A3 — copying or pickling a sealed request silently invalidates it.
2. **(ii)** B3 — `AssessmentContextRecord.restricted` is a constant `False`.
3. **(ii)** C — silent exclusion of evidence with no reason channel.
4. **(ii)** D2/D3 — one error code for three conditions, one of them an internal inconsistency.
5. **(i, in-process only)** A1 — the sentinel is importable.

## Tests the coordinator should add to make this slice solid

1. `copy.copy(sealed)` and `pickle` round-trip: choose survive-or-raise and pin it.
2. Constructing with a wrong sentinel raises `ProviderSafetyError("invalid_request")`; a subclass is
   rejected by `_is_serialized_request`.
3. Eligibility corpus with the two false-positive strings: either they are eligible, or exclusion is
   documented and a reason is returned.
4. A size-model cross-check over a string containing every C0 control, a quote, a backslash, an
   astral-plane character, and U+2028: `_json_string_size(s) == len(_encode_json_string(s))`.

## What would falsify this report

- A3 is wrong if CPython's `copy` returns the identical object for this subclass rather than
  reconstructing it — one command settles it.
- B assumes `Record.restricted` exists; it is used in constructors elsewhere in this codebase, so an
  `AttributeError` here is unlikely but not checked in this slice.
