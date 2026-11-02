# Slice 4 — cross-slice consistency check (`provider_safety.py`, 989 lines)

Read via `code_search` over `app/` and `tests/`. Nothing executed; no file edited.

## 1. Error-code inventory

Every `ProviderSafetyError("<code>")` raised in `provider_safety.py`, grouped, with the
question that matters: *does the name say what happened?*

| Code | Lines | Verdict |
|---|---|---|
| `invalid_request` | 57, 578, 608, 700, 739, 949 | **one misuse**: 949 fires while re-parsing our own serialized envelope, i.e. the serializer produced something the parser rejects. That is an internal invariant breach, not a client error. Compare 289, which already has the right shape (`serialization_accounting_mismatch`). |
| `invalid_context` | 151, 156, 238, 246, 253 | accurate — caller passed records/hypothesis the provider may not see |
| `request_too_large` | 225, 258, 274, 291, 580, 610, 702, 741 | accurate; the 289 split removed the old overload |
| `serialization_accounting_mismatch` | 289 | accurate, **never asserted** (see §2) |
| `malformed_response_headers` | 311, 313 | accurate |
| `response_too_large` | 316, 332, 338 | accurate since 328 stopped sharing it |
| `malformed_response_body` | 328 | accurate |
| `invalid_budget` | 356, 360, 362, 382, 415, 419 | accurate |
| `provider_disabled` | 436 | accurate (fail-closed kill switch) |
| `request_limit` | 441 | accurate |
| `budget_exceeded` | 448 | **dead** and **never asserted** — construction already enforces `per_request * count <= ceiling` |
| `mandatory_boundary_required` | 467, 484, 561, 565, 576, 606, 693, 834, 857, 901 | accurate |
| `unsupported_transport` | 546, 674, **900** | **one misuse**: 900 checks `type(provider) is not BoundedTransportProvider` in `bounded_provider_call`, so a bad *provider* is reported as a bad *transport* |
| `unsupported_gate` | 548, 676 | accurate |
| `invalid_timeout` | 589, 619, 844, 867 | accurate |
| `async_context_unsupported` | 596, 849 | accurate |
| `concurrent_request` | 623, 869 | accurate (single-flight refusal) |
| `timeout` | 641, 887 | accurate |
| `provider_failure` | 645, 891 | accurate, but `from None` discards the cause (slice-3 finding) |
| `unsupported_provider` | 672, 979 | accurate |
| `malformed_response` | 748, 760, 771, 778, 784, 788, 809, 821, 908, 914, 925, 938 | broad but honest: "we cannot parse/accept this body" |
| `unsupported_response` | 776, 782, 786, 795, 799, 802, 804, 806, 814, 817 | accurate — well-formed but not the approved shape |
| `provider_refusal` | 813 | accurate; **never asserted** |
| `empty_output` | 824 | accurate |
| `malformed_output` | 951, 955, 959 | accurate |
| `invalid_source` / `invalid_quote` / `invalid_stance` / `invalid_rationale` | 962 / 964 / 966 / 968 | accurate |

**Pattern worth naming:** the three defects this audit has already fixed were all one thing —
an internal fault wearing a client-facing code. Two instances of that pattern remain: line 949
and line 900. Neither is exploitable; both make a diagnosis wrong at the worst moment.

## 2. Codes raised but never asserted

Searched the whole `tests/` tree for each code. Never asserted anywhere:

- `budget_exceeded` (448) — also unreachable
- `serialization_accounting_mismatch` (289) — reachable only if the model and the encoder disagree, so untested *and* hard to reach; that is exactly the case where a silent failure would hurt
- `provider_refusal` (813) — a vendor refusal path with no test

Codes in tests that the module no longer raises: **none found**. `graph_budget_exceeded`
(`test_policy_dependency_graph.py`) belongs to the other import component, not this module.

## 3. Constants

All eight module constants are used: `MAX_REQUEST_BYTES`, `MAX_RESPONSE_BYTES`,
`MAX_RESPONSE_READ_CHUNK_BYTES`, `MAX_CONTENT_LENGTH_HEADER_CHARS`,
`MAX_REQUEST_TIMEOUT_SECONDS`, `MAX_PROPOSALS`, `MAX_EXPERIMENT_REQUESTS` (also imported by
`experiment_control.py`), `MAX_CONFIGURABLE_ESTIMATED_BUDGET_USD` (same importer).

Magic numbers that should be constants:
- `128` as the permitted-record cap in `serialize_provider_request` — now inconsistent with
  `MAX_PROPOSALS = 128`, which has a name. Two caps, one name, no relation.
- `3` as the minimum quote length in `_validate_provider_proposals` — the only place the floor
  exists, so it cannot be reviewed against anything.
- `1024`/`16 * 1024` are fine: they are constants already.

## 4. Definition → slice ownership

Slice ranges as the ledger currently states them: S1 1–291, S2 292–497, S3 498–703,
S4 704–909, S5 910–989.

| Definition | Lines | Slice | Note |
|---|---|---|---|
| constants, module seals, lock | 13–35 | S1 | |
| `SerializedProviderRequest` | 38–80 | S1 | |
| `_is_serialized_request` | 81–85 | S1 | |
| `AssessmentContextRecord` | 86–104 | S1 | |
| `LocalAssessmentProvider` | 105–113 | S1 | |
| `_SENSITIVE_TEXT_PATTERNS`, `contains_sensitive_text` | 114–136 | S1 | |
| `partition_provider_records`, `eligible_provider_records` | 137–179 | S1 | |
| `ProviderSafetyError`, Protocols | 180–221 | S1 | |
| `_json_string_size`, `_encode_json_string` | 222–248 | S1 | |
| `serialize_provider_request` | 249–293 | **S1/S2 split** | the range 1–291 cuts the function's last two lines |
| `_close_quietly`, `_read_bounded_response` | 295–344 | S2 | |
| `ProviderBudgetConfig`, `_positive_decimal`, `ProviderCallGate` | 345–453 | S2 | |
| `_TransportDispatchAuthorization` | 454–497 | S2 | ends exactly at the boundary |
| `_valid_…`, `_consume_…` | 498–535 | S3 | |
| `BoundedTransportProvider` | 536–650 | S3 | |
| `BasetenMuseSparkOpenAdapter` | 651–896 | **S3/S4 split** | head at 651–703 was audited as S3, body as S4 |
| `bounded_provider_call` | 897–903 | S4 | |
| `_reject_duplicate_object_keys`, `_reject_nonstandard_json_constant` | 904–916 | S4 | |
| `parse_provider_proposals` | 917–942 | **not S4** | the S4 brief named it (704–909) but it starts at 917, inside S5 |
| `_validate_provider_proposals` | 943–970 | **not S4** | same; S4's audit read it anyway |
| `MandatoryProviderBoundary` | 971–989 | S5 | |

Four definitions are split or misfiled. The cause is that the file grew 883 → 989 lines during
the audit (slice-1 edits, then slice-2/3/4 fixes), while the ledger ranges were frozen at 206-line
chunks of an older snapshot.

**Recommendation (not applied):** re-derive the ledger from the current file before slice 5, move
`parse_provider_proposals` + `_validate_provider_proposals` explicitly into S4's ownership (they
were audited with it), and start S5 at `MandatoryProviderBoundary` (971). Otherwise slice 5 will
re-audit two functions it does not own and skip the class it does.
