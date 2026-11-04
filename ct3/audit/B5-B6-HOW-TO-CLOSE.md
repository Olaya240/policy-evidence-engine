# B5/B6 — what it takes to close the provider rows

## Where the rows stand

B5 and B6 are open for one reason: **the live provider path has never executed.**
The validators are covered offline, but every test feeds a hand-written body, so no
existing artifact shows that a real response ever reached them. One recorded
exchange, replayed through `app/provider_replay.py`, is the smallest artifact that
can. This page is its capture spec, not a result: nothing below has been run
against a vendor, and the rows stay open until a replay is produced *and*
adjudicated.

## 1. Capture, once, against a real key

Pick one gold case from `backend/evaluation/gold_cases.json` and record its
exchange **byte-exact**; a re-typed or pretty-printed body is not a recording.

| Capture | How | Why the replay needs it |
|---|---|---|
| Request envelope | the bytes the app sent, exactly (proxy log, or `bytes(serialize_provider_request(records, hypothesis_id))` from the same run), saved as a file | its SHA-256 is the identity of the question and corpus |
| Response body | the HTTP response body exactly as received, unmodified | parsed as-is by the live validator |
| Model identifier | `meta-models/muse-spark-open` (`BasetenMuseSparkOpenAdapter.MODEL_SLUG`) | a cassette naming any other model is refused |
| Timestamp | ISO-8601 with an offset, from the capture log | a capture without an offset cannot be placed on a timeline and is refused |
| Endpoint | `https://inference.baseten.co/v1/chat/completions` (`BASETEN_CHAT_COMPLETIONS_ENDPOINT`) | a cassette from any other endpoint is refused |

## 2. Assemble the cassette

`request_sha256` is computed, never typed; both inputs sit in the current directory:

```bash
PYTHONPATH=backend python -c "
import hashlib, json, pathlib
req = pathlib.Path('request_envelope.json').read_bytes()
body = pathlib.Path('response_body.json').read_bytes()
json.dump({
  'format': 'provider-replay-cassette-v1',
  'label': 'recorded',
  'endpoint': 'https://inference.baseten.co/v1/chat/completions',
  'model': 'meta-models/muse-spark-open',
  'timestamp': '<ISO-8601 with offset, from the capture log>',
  'request_sha256': hashlib.sha256(req).hexdigest(),
  'request_envelope': req.decode('utf-8'),
  'response_body': body.decode('utf-8'),
}, open('cassette.json', 'w'), indent=2)
"
```

`label` is `recorded` for a real capture, `synthetic` for a hand-written fixture.
A synthetic cassette is not vendor output and must never be cited as it; the label
travels into the replay result so an artifact cannot quietly drop it.

## 3. The one command that replays it

For the case named `supportive-direct` (use the case id you captured):

```bash
cd backend && PYTHONPATH=. python -c "
import json
from app.models import Record
from app.provider_replay import replay_recorded_exchange
case = next(c for c in json.load(open('evaluation/gold_cases.json'))['cases'] if c['id'] == 'supportive-direct')
result = replay_recorded_exchange('/absolute/path/to/cassette.json',
                                  records=[Record.model_validate(r) for r in case['records']],
                                  hypothesis_id=case['hypothesis_id'])
print(len(result.proposals), result.request_sha256, result.wire_sha256, result.response_sha256)
"
```

`python` is the interpreter the backend suite runs under. No network call is made:
the module imports no transport and builds no adapter instance. A refusal is a
`ProviderSafetyError` whose `code` names the fired check
(`cassette_request_mismatch`, `cassette_metadata_mismatch`, `malformed_cassette`,
`cassette_too_large`, `response_too_large`, `unsupported_response`,
`proposal_capacity_exceeded`, `invalid_source`, `invalid_quote`, `invalid_stance`,
`invalid_rationale`); record it verbatim, do not rename it in the write-up.

## What the replay proves

1. Those exact bytes pass the same functions a live call passes, in the same
   order, under the same allowlist, budget and grounding checks — there is no
   replay-only validator, `_parse_response` is the live one.
2. The request for this corpus and hypothesis hashes to the cassette's digest, so
   the recording cannot be reused for a different case or an edited corpus.
3. The rebuilt wire body is byte-identical to the one the live transport sent
   (`wire_sha256`), so the capture is an exchange, not a reconstruction.

## What the replay does not prove

- **One response is not calibration.** One sample of one model on one input says
  nothing about accuracy, stance quality, or how often a body will conform.
- **It does not prove the model obeys the injection-resistance sentence across
  inputs.** A conforming response is consistent with a model that ignores that
  sentence on the next hostile record; only many hostile recordings bear on it.
- **It does not prove future behaviour** — the model, decoding or envelope can
  change after the capture — **nor provenance**: the replay cannot tell whether
  the bytes came from the vendor, which is the operator's attestation.
- **It does not close B5 or B6 by itself.** The row closes when a reviewer accepts
  this replay and its capture conditions as sufficient. A refusal also needs
  adjudication: it may be a real contradiction or a mis-captured body.
