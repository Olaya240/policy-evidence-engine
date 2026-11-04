# Slice 4 · worker 3 of 10 — `parse_provider_proposals` / `_validate_provider_proposals`

Read: `backend/app/provider_safety.py:912-964` (current file, 1002 lines). Nothing edited.

## What the code actually enforces

| Check | Line | Enforcement |
|---|---|---|
| body is exactly `bytes` | 918-919 | `type(body) is not bytes` → `malformed_response` |
| UTF-8, strict | 921 | `decode(..., errors="strict")` |
| duplicate JSON keys at every depth | 923 | `object_pairs_hook=_reject_duplicate_object_keys` (905-911) |
| `NaN` / `Infinity` | 924 | `parse_constant=_reject_nonstandard_json_constant` (914-915) |
| deep-nesting stack blow-up | 929-933 | `RecursionError` added to the catch tuple |
| top level is a list | 945-946 | `type(proposals) is not list` |
| proposal count | 947-951 | `len(proposals) > MAX_PROPOSALS` — **before** iteration |
| exact item key set | 952, 954-955 | `set(item) != required` |
| record provenance | 956, 957-958 | `source_id not in records` |
| quote grounding | 959-960 | `quote not in records[source_id]` |
| stance vocabulary | 961-962 | membership in `{stance.value for stance in Stance}` |
| rationale non-empty | 963-964 | `not item["rationale"].strip()` |

## Findings, ranked

### 1. The re-parse of the request misattributes internal faults as client errors (Read, 940-944)

```python
try:
    envelope = json.loads(bytes(request).decode("utf-8"))
    records = {item["id"]: item["text"] for item in envelope["input"]["records"]}
except Exception:
    raise ProviderSafetyError("invalid_request") from None
```

`request` here is a *sealed* `SerializedProviderRequest` that already passed the
serializer. A `KeyError`, `TypeError`, `RecursionError` or any future envelope-shape
mistake in this block is therefore not a client error at all — it is an internal
invariant failure, reported to the caller as "your request was invalid", with the cause
discarded (`from None`). This is the same class as the `request_too_large` overload that
slice 1 fixed: a bug wearing a client error's message. It is also the one `except
Exception` in the two functions.

Fix: narrow to `(UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError)`
and raise a distinct code (`request_reparse_failed`), so a defect here pages someone
instead of blaming the caller.

**Falsifier:** inject a request whose envelope lacks `input` and observe the code — it will
be `invalid_request`, indistinguishable from a caller mistake.

### 2. "Grounding" is a 3-character substring test, not evidence (Read, 959-960)

```python
if type(quote) is not str or len(quote.strip()) < 3 or quote not in records[source_id]:
    raise ProviderSafetyError("invalid_quote")
```

The proposal's quote only has to appear *somewhere* in the cited record and strip to three
characters. `"the"`, `"was"`, `"the "` all pass against any record containing them. Since
the quote is precisely what a human auditor reads as the evidence for a claim, this is the
weakest link in the whole chain: a model can attach an arbitrary stance and rationale to a
trivial fragment and the record will show a "grounded" citation.

The floor is a length heuristic standing in for a grounding criterion. Cheapest honest
upgrade: require the quote to be near-complete (`len(quote) >= min(24, len(text))`) or to
be one of the record's sentences; at minimum, record the floor as a known limitation rather
than letting the field name imply provenance.

**Falsifier:** `{"source_record_id": "R1", "quote": "the", ...}` against a record whose text
contains "the" — accepted today.

### 3. Length is measured stripped, membership unstripped (Read, 960)

`len(quote.strip()) < 3` uses the stripped form; `quote not in records[source_id]` uses the
raw form. Two citations of the same sentence with different leading whitespace behave
differently: the padded one fails membership unless the record contains that padding, while
the stripped one passes. Fail-closed, so not a hole — but it is an inconsistency the next
reader will trip over, and it makes "why was this quote refused" unanswerable from the code.

### 4. Duplicate record ids collapse silently (Read, 942)

`{item["id"]: item["text"] for item in ...}` keeps the last text per id. Storage ids are
unique today, so this is latent; if two eligible records ever shared an id, a quote grounded
in the first would be rejected while one grounded in the last would be accepted for a
proposal citing the first. A one-line duplicate check would make it explicit.

### 5. Minor, non-security

- `{stance.value for stance in Stance}` is rebuilt for every proposal (961). Hoist to a
  module constant; it is a per-item allocation on a hot path with a 128-item cap.
- `[]` passes validation and returns `[]`, which is indistinguishable from a vendor adapter
  mapping a refusal to an empty array. The adapter rejects `message.refusal` explicitly, so
  this only matters for future adapters; it is worth a docstring line.

## Answers to the brief's explicit questions

- **Wrong-record grounding:** no — the substring test is against `records[source_id]`, so a
  quote from another record fails *unless* the text also occurs in the cited record. Sharing
  is accepted for either record, which is correct for identical text.
- **Is `< 3` the right floor:** no. It blocks empty/whitespace noise but permits trivial
  fragments; see finding 2.
- **Does the re-parse swallow internal faults:** yes, as `invalid_request`; see finding 1.
- **Is the cap before or after iteration:** before (947-951), so a 129-item array is refused
  without touching an item. Correct.

## Left undone

No execution: without a terminal I cannot show `"the"` being accepted, nor inject a broken
envelope. Both are one-line probes for the coordinator, and the falsifier for each is named
above. I did not read the adapter's `_parse_response` (704-860) — worker 1's slice — so
envelope-level grounding is outside this report.
