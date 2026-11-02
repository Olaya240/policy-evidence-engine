# Alternatives to a Baseten key — measured, not assumed

Date: 2026-11-02. Companion to `B5-B6-HOW-TO-CLOSE.md`, which is the capture spec
for the rows themselves. This page answers a narrower question: **can the provider
rows be closed, or the live path exercised, without buying a Baseten key?**

Short answer: **the key is not the blocker.** The blocker is that the live path
pins five things at once — origin, path, model slug, request envelope and the exact
top-level key set of the response — so a different credential changes nothing. What
can substitute is a different *profile*, plus an adapter that admits it.

## 1. What was tested, and what each attempt returned

Every probe below is a real HTTP call from this machine on 2026-11-02, using the
keys already present in the environment. No new account was created, and no key was
copied into a file or printed.

| Route | Credential | Result | Meaning |
|---|---|---|---|
| Groq `api.groq.com/openai/v1` | key present | `403` `error code: 1010` | Cloudflare refused the client before authentication. Not an auth failure, so a fresh key would not change it from this host. |
| OpenRouter | key present | `402` "never purchased credits" | Account has no balance. |
| OpenRouter `:free` slugs | same key | `404` "no longer available" / "unavailable for free" | The free tier no longer serves the models it advertises. |
| NVIDIA NIM `integrate.api.nvidia.com/v1` | key present | `401` then `404` | The key authenticates (the `401` was a model that had been retired); every live model returns `404` "no Function ... for account", i.e. nothing is deployed on this account. |
| **Local `ollama`** | **none** | `200` | Works: no account, no key, no egress to a vendor. |

So on this machine, exactly one route needs no new credential: a local
OpenAI-compatible server. That is the alternative the rest of this page measures.

## 2. Driving the real pipeline against a local model

`ct3/audit/local_provider_probe.py` calls the same functions the live transport
calls — `serialize_provider_request` → `_wire_request` → HTTP → `_parse_response` —
with `app/` unmodified and nothing monkey-patched.

Two substitutions, both printed by the probe:

- the endpoint is loopback, not the pinned Baseten origin;
- the local weights are aliased under the pinned slug (`ollama cp qwen2.5:1.5b-instruct
  meta-models/muse-spark-open`) so the two-way model pin can be exercised at all.
  `--served-by` records which weights answered; without it the run is reported
  `UNATTRIBUTED`.

Result, gold case `supportive-direct`, model `qwen2.5:1.5b-instruct`:

```
http status     : 200
top-level keys  : ['choices','created','id','model','object','system_fingerprint','usage']
model echoed    : 'meta-models/muse-spark-open'
choice keys     : ['finish_reason','index','message']       <- exactly what the parser wants
message keys    : ['content','role']                        <- exactly
finish_reason   : 'stop'
live validator  : unsupported_response
```

`finish_reason`, the choice key set, the message key set and the model echo all
already conform. The refusal is one extra top-level key: Ollama's
`system_fingerprint`. The parser's allowlist is the *exact* Muse schema, so every
OpenAI-compatible vendor — which all add `system_fingerprint` or `provider` — is
refused on arrival.

## 3. The refusal ladder (the discriminating part)

Re-parsing the saved body with one cause removed at a time (`--ladder`):

| Body | Code | Why |
|---|---|---|
| as received | `unsupported_response` | top-level key `system_fingerprint` outside the allowlist |
| `system_fingerprint` removed | `malformed_response` | the model answered in prose, not a JSON array |
| prose replaced by a conforming array | **`ACCEPTED (1 proposals)`** | everything downstream accepts a non-Baseten body |

This is what separates the two explanations. If the credential or the vendor were
the obstacle, the third row could not pass. It passes, which means the transport,
the parser and the grounding checks are vendor-agnostic *by construction* — the
vendor-specific part is one allowlist and one slug, not the security logic.

The second row is the finding worth keeping: a 1.5B model on CPU produced 1 408
characters of plausible narrative and not one JSON object, so it would have failed
even with a permissive allowlist. Capability, not just schema, decides whether a
substitute model produces usable readings — which is precisely what B6 asks and
what one model on one input cannot answer.

## 4. What each alternative would and would not close

| Option | Closes | Does not close |
|---|---|---|
| Another vendor's key (Groq/OpenRouter/NVIDIA) | nothing on its own — refused at the allowlist | B5, B6. Needs an adapter, and the keys here do not work anyway. |
| Local model behind a **new pinned profile** | "a live provider response traversed transport → validator → grounding" as a *new*, correctly-scoped row | B5/B6 as written: they name Muse Spark and Baseten's endpoint. |
| Local model behind the **existing** profile (slug aliasing) | the wire path only | anything about provenance — an aliased slug makes a local 1.5B look like Muse, which is exactly the confusion the pins exist to prevent. Should not be shipped as evidence. |
| One recorded exchange from a real key | B5/B6, per the capture spec | anything without the key. |

**B5/B6 cannot be closed by a substitute.** They are statements about one vendor's
model. Re-scoping them — "the live path has executed against *a* provider" — is a
decision about what the row claims, and it belongs in the register, not in a probe
script. This page supports the re-scoped row; it does not move the existing ones.

## 5. Smallest change that would make a local profile first-class

Not done here, because it edits a pinned constant whose own docstring reserves that
for a reviewed phase. The shape, for whoever decides:

1. `httpx_transport`: one `LOCAL_CHAT_COMPLETIONS_ENDPOINT` constant plus a
   `_parse_endpoint` variant that admits `http://127.0.0.1:<port>` **only** when the
   port is fixed and the host is the loopback literal. HTTPS stays mandatory for
   every non-loopback origin.
2. `provider_safety`: `MODEL_SLUG` becomes a per-instance immutable field drawn from
   a closed two-value set, used by both `_wire_request` and `_parse_response` so the
   echo pin keeps working per profile.
3. The response allowlist gains `system_fingerprint` for the local profile only, so
   the Baseten profile does not silently widen.
4. `MandatoryProviderBoundary`'s `type(provider) in (...)` tuple gains the new exact
   class — the design already uses closed-set membership, so no `type is` chain has
   to be rewritten.
5. `provider_replay` gets a third label for local captures. A local body must never
   carry `label: recorded`; the replay's metadata check already refuses a foreign
   endpoint, which is the right default and should stay.

Cost: roughly a day including tests and the gate. It buys the re-scoped row, not
B5/B6.

## 6. Reproduce

```bash
ollama serve &
ollama pull qwen2.5:1.5b-instruct
ollama cp qwen2.5:1.5b-instruct meta-models/muse-spark-open

PYTHONPATH=backend python3 ct3/audit/local_provider_probe.py \
  --endpoint http://127.0.0.1:11434/v1/chat/completions \
  --served-by qwen2.5:1.5b-instruct --save-body /tmp/local-body.json

PYTHONPATH=backend python3 ct3/audit/local_provider_probe.py \
  --endpoint none --ladder /tmp/local-body.json
```

Then delete the alias (`ollama rm meta-models/muse-spark-open`); leaving a local
model registered under the vendor's slug is how a later run gets misread.

## 7. Not established

- Whether a *capable* local model (7B and up) obeys the JSON instruction here. The
  7B was pulled and aliased, but CPU inference exceeded Ollama's 5-minute request
  ceiling and returned `500` before emitting anything, so no reading from it exists.
- Whether the Groq block is host-specific or account-specific. Only this host was
  tried.
- Any accuracy, stance-quality or injection-resistance claim about a substitute
  model. One response is not calibration, and none of it bears on Muse Spark.
