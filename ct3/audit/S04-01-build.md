# Slice 4 / part 1 — request-building half of `BasetenMuseSparkOpenAdapter`

Range read: `backend/app/provider_safety.py:697-770` (`_bind_boundary` tail, `_wire_request`).
File was 1002 lines at read time; the module has been edited twice during this audit,
so line numbers are exact for this revision only.

## 1. Definitions and their contracts

| Definition | Line | Stated contract | Enforced? | Accepted but undescribed |
|---|---|---|---|---|
| `_bind_boundary` | 691 | Bind once, exact boundary type | Yes — `type(...) is` + `self._boundary is not None`, then seals on the transport | Nothing; re-binding is refused |
| `_wire_request` | 697 | Convert a sealed envelope into the vendor wire body | Partly — see findings | An empty `system_instructions`, and an empty `records` list |
| envelope check | 703-709 | Exactly `{system_instructions, input}`, input exactly `{hypothesis, records}` | Yes — `set(...) != {...}` on both levels | — |
| field types | 710-720 | `system_text: str`, `hypothesis: {id: str, label: str}`, `records: list[{id: str, text: str}]` | Yes — `type(...) is` checks, not `isinstance` | Empty strings for any of the four string fields |
| `user_content` | 722-725 | Records and hypothesis re-serialised as JSON for the user turn | Yes — `json.dumps(..., allow_nan=False)` | — |
| `wire_body` | 726-737 | Fixed envelope: pinned `MODEL_SLUG`, developer + user messages | Yes — model is a literal, not taken from the request | — |
| size guard | 751-753 | Reject a wire body larger than `MAX_REQUEST_BYTES` | Yes, **after** the body is fully built | — |

## 2. The five questions, answered

**Is the envelope re-validated identically to what `serialize_provider_request` produced?**
Yes for structure and types, no for semantics: the producer accepts the same shapes, so the
re-validation can only fail on a *forged* sealed payload or on size. It is defence in depth,
not a second opinion.

**Can `system_instructions` be empty?** Yes (`:721` only requires `type(...) is str`). The
developer turn then becomes `"" + _OUTPUT_INSTRUCTIONS`, i.e. the output contract with no
system prompt. Every other string in this function — `model`, `rationale`, `quote` elsewhere —
must be non-empty, so this is the one silent-empty field.

**Does `hypothesis.label` fall through untrusted?** It does, and that is safe *here*: it is
never concatenated into a prompt. Both `label` and record `text` are embedded through
`json.dumps` into the user turn (`:722`), so quotes and newlines are escaped rather than
interpreted. The only concatenation in this function is `system_text + _OUTPUT_INSTRUCTIONS`,
and `system_text` comes from the engine, not from a record.

**Is `wire_body` bounded before or after encoding?** After. The whole body is built in memory,
then measured at `:751`. Input is capped at 16 KiB, but the body is a *re-encoding*: `records`
is serialised once into `user_content`, then that string is serialised again inside
`messages`, so quotes and backslashes are escaped twice. The wire body can therefore be
several times the request, and an input that passed `serialize_provider_request` can be
refused here.

**What happens if `records` is empty?** Accepted. `user_content` becomes
`{"hypothesis":{...},"records":[]}` and a provider call is made with no evidence. Grounding
then makes any returned proposal fail (`invalid_source`), so the path is wasteful rather than
unsafe — but nothing upstream refuses to call with zero records.

## 3. Findings, ranked

**F1 — `MAX_REQUEST_BYTES` measures two different encodings, and the failure is indistinguishable.**
`serialize_provider_request` accepts an envelope ≤ 16 KiB; `_wire_request` enforces the same
constant on a *double-escaped* body (`:751`). A record full of quotes and backslashes grows
under re-serialisation, so a legitimately accepted request can be rejected as
`request_too_large` — a client-error code for what is really a property of the adapter's
encoding, and after the body has been fully materialised. Read (`:697-703`, `:751-753`);
the growth factor is Inferred from `json.dumps` semantics.

**F2 — `system_instructions` may be empty, unlike every other string field.**
`type(system_text) is str` (`:721`) admits `""`, which silently sends the output contract
with no system prompt. One predicate (`and system_text.strip()`) would make the strictness
uniform. Read (`:721`).

**F3 — `RecursionError` is not caught here, though it now is on the response side.**
`json.loads` recurses, so a forged sealed envelope with deep nesting raises `RecursionError`
past the `except` tuple at `:748-750` and escapes as an unclassified error. The trust
argument is the module-level seal, which memory already records as not being an isolation
boundary, so in-process code can reach it. Read (`:748-750`); reachability Inferred.

## 4. Not verified

No terminal in this session: nothing here was executed and no test was run. The growth
factor in F1 is arithmetic on `json.dumps` behaviour, not a measurement — the coordinator
should measure it with a record of `"` characters before deciding whether to split the two
limits.
