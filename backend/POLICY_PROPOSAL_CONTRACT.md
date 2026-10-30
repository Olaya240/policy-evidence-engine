# Provider-independent policy proposal contract (version 1)

This document specifies a bounded, provider-neutral envelope for future
candidate-generation experiments. The implementation in
`policy_proposal_contract.py` only builds a local request and normalizes a
caller-supplied response. It has no model SDK, transport, authentication,
credential loader, or runtime dispatch. The fixture-backed fake remains the
only executable generator path in the current application.

## Request

`build_proposal_request()` accepts an exact `PolicyPair` that is round-tripped
through `validate_policy_pair()` and returns:

```json
{
  "schema_version": 1,
  "request_id": "req-syn-<24 lowercase hex characters>",
  "comparison_id": "cmp-syn-...",
  "versions": [
    {
      "side": "OLDER",
      "document_id": "syn-policy-...",
      "version_id": "v1",
      "source_sha256": "<64 lowercase hex characters>",
      "effective_from": "YYYY-MM-DD or null",
      "effective_to_exclusive": "YYYY-MM-DD or null",
      "scope": {
        "departments": {"state": "KNOWN|UNKNOWN|ALL", "ids": []},
        "procedures": {"state": "KNOWN|UNKNOWN|ALL", "ids": []},
        "property_id": "identifier or null"
      },
      "text_coverage": "FULL_DOCUMENT|EXCERPT",
      "passages": [
        {"passage_id": "p...", "start_cp": 0, "end_cp": 12, "text": "..."}
      ]
    },
    {"side": "NEWER", "...": "same validated source fields"}
  ],
  "limitations": [
    "PROPOSALS_ONLY", "SEMANTIC_SUPPORT_UNVERIFIED",
    "PRECEDENCE_UNVERIFIED", "COVERAGE_NOT_ESTABLISHED",
    "HUMAN_REVIEW_REQUIRED"
  ]
}
```

The request is derived from the validated in-memory pair. It is serialized for
size measurement as canonical JSON: keys sorted lexicographically, no optional
whitespace, UTF-8 with non-ASCII characters unescaped, and non-finite numbers
forbidden. A request over 512,000 canonical UTF-8 bytes is rejected. Request
structure is additionally bounded to 50,000 nodes and the policy core's 1,000
passages per version; passages are never truncated. This is intended as context
for a future model call, not proof of complete document coverage.

## Candidate response

The only accepted root keys are `schema_version`, `request_id`, and
`candidates`. Version must be the exact built-in integer `1`; `request_id` must
match the request. At most 20 candidates are accepted. Each candidate has
exactly:

```json
{
  "proposed_relation": "CONTRADICTION|COMPATIBLE_CHANGE|NEW_RULE|SCOPE_OR_TIME_DIFFERENCE|INCONCLUSIVE",
  "reasoning": "bounded, non-empty text",
  "citation_hints": [
    {"side": "OLDER|NEWER", "passage_id": "p...", "quote": "exact source text"}
  ],
  "uncertainty_reasons": [
    "semantic_support_unverified|precedence_unverified|coverage_unverified|scope_or_time_unverified|missing_evidence|unsupported_claim"
  ],
  "abstain": false
}
```

String response inputs are limited by their actual received UTF-8 byte length
before JSON parsing, then also checked against the parsed value's canonical
size. For an already parsed dictionary, the 64,000-byte response limit is
measured after canonicalization using sorted keys, compact separators, UTF-8
with non-ASCII characters unescaped, and `allow_nan=false`; original
whitespace, escape spelling, and dictionary insertion order are therefore not
part of the dictionary measurement. Both paths also enforce depth, node, item,
member, string, and numeric bounds: depth 8, 20,000 nodes, 20 items per array,
16 members per object, and 4,000 code points per string. Candidate count is at
most 20, reasoning and citation quotes are at most 500 code points, and the
schema version and boolean fields require exact built-in types. Byte inputs
are not an accepted public response type.

Each hint must name a passage from the named side and contain a quote occurring
exactly once in that passage. The normalizer derives the source document,
version, hash, and code-point offsets from the validated pair, then calls the
existing citation validator. It rejects duplicate candidate proposals,
duplicate sides, fabricated/misplaced/ambiguous quotes, unknown keys, duplicate
JSON object keys, malformed JSON, oversized structures, and unsupported JSON
types. Comparison relations require both versions; `NEW_RULE` proposals require
newer-side evidence only. An abstention is `INCONCLUSIVE` with no citations;
non-abstentions require citations. Affirmative proposals require
`semantic_support_unverified`.

The normalized result adds locally trusted candidate ID, `PROPOSAL_ONLY`,
`NOT_VERIFIED`, and `human_review_required: true`. It does not accept or produce
a final classification, semantic-support verdict, precedence decision,
complete-coverage assertion, confirmed impact, approval, or publication action.
Valid source provenance establishes only that the exact quote is at the
declared source location. It does not establish that the quote semantically
supports the proposed relationship. Every comparison remains unverified and
requires human review.

## Limits and future work

The request/response bounds are application validation. Revalidation of a
manually constructed `PolicyPair` is defensive input checking, not a way to
contain arbitrary behavior in nested objects. Python same-process
objects do not form a sandbox against malicious code, monkey-patching, or a
compromised interpreter. The synthetic regression fixtures are not independent
held-out evaluation evidence. Any future provider adapter, credential handling,
endpoint choice, deployment identity, and external-request authorization need
separate review and approval. No model endpoint, model identifier, SDK, or wire
protocol is selected here.
