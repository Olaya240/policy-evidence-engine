"""What a non-Baseten provider actually returns, and which check refuses it.

This is a probe, not a certification. It drives the live pipeline functions --

    serialize_provider_request -> BasetenMuseSparkOpenAdapter._wire_request
    -> real HTTP POST -> BasetenMuseSparkOpenAdapter._parse_response

-- against a provider that is not Baseten, and reports the exact
`ProviderSafetyError.code` the live validator raises. Nothing in `app/` is
modified or monkey-patched: the same staticmethods the live transport calls are
called here, with the same bytes.

Three substitutions are made, and all are printed rather than hidden:

  * the endpoint is the local one (`--endpoint`), not the pinned Baseten origin;
  * the local weights are aliased under the pinned slug so the two-way model pin
    can be exercised at all -- `--served-by` names them in the output, and a run
    without it is reported as unattributed;
  * the response is whatever that server returns. The `model` field is never
    rewritten, so the pin is tested as it will be in production.

`--ladder` re-parses a saved body with one refusal cause removed at a time, so
the report names *which* check fires first instead of guessing.

Usage:
    python3 ct3/audit/local_provider_probe.py --endpoint http://127.0.0.1:11434/v1/chat/completions \
        --served-by qwen2.5:1.5b-instruct --save-body /tmp/local-body.json
    python3 ct3/audit/local_provider_probe.py --endpoint x --ladder /tmp/local-body.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "backend")

from app.models import Record  # noqa: E402
from app.provider_safety import (  # noqa: E402
    BasetenMuseSparkOpenAdapter,
    ProviderSafetyError,
    serialize_provider_request,
)

GOLD = "backend/evaluation/gold_cases.json"


def build(case_id: str):
    cases = json.load(open(GOLD))["cases"]
    case = next(c for c in cases if c["id"] == case_id)
    records = [Record.model_validate(r) for r in case["records"]]
    request = serialize_provider_request(records, case["hypothesis_id"])
    wire = BasetenMuseSparkOpenAdapter._wire_request(request)
    return case, request, wire


def post(endpoint: str, wire: bytes) -> tuple[object, bytes]:
    req = urllib.request.Request(endpoint, data=wire, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def code_of(request, body: bytes) -> str:
    try:
        proposals = BasetenMuseSparkOpenAdapter._parse_response(body, request)
        return f"ACCEPTED ({len(proposals)} proposals)"
    except ProviderSafetyError as error:
        return error.code


def ladder(path: str) -> int:
    """Remove one refusal cause at a time from a saved body."""
    body = open(path, "rb").read()
    parsed = json.loads(body)
    case, request, _ = build("supportive-direct")
    print(f"body            : {path} ({len(body)} bytes)")
    print(f"as received     : {code_of(request, body)}")

    without_fp = {k: v for k, v in parsed.items() if k != "system_fingerprint"}
    stage1 = json.dumps(without_fp).encode()
    print(f"- system_fingerprint: {code_of(request, stage1)}")

    content = (without_fp["choices"][0]["message"] or {}).get("content") or ""
    proposal = json.dumps([{
        "source_record_id": case["records"][0]["id"],
        "quote": case["records"][0]["text"],
        "stance": "SUPPORTS",
        "rationale": "record states the checklist binder was missing from the desk",
    }])
    conforming = {
        **without_fp,
        "choices": [{
            **without_fp["choices"][0],
            "message": {"role": "assistant", "content": proposal},
        }],
    }
    stage2 = json.dumps(conforming).encode()
    print(f"- model prose replaced by a conforming array: {code_of(request, stage2)}")
    print(f"  (model prose was {len(content)} chars; first 80: {content[:80]!r})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--case", default="supportive-direct")
    parser.add_argument("--served-by", default=None)
    parser.add_argument("--save-body", default=None)
    parser.add_argument("--ladder", default=None)
    args = parser.parse_args()

    if args.ladder:
        return ladder(args.ladder)

    case, request, wire = build(args.case)
    print(f"served by       : {args.served_by or 'UNATTRIBUTED (no --served-by given)'}")
    envelope = json.loads(wire)
    print(f"case            : {case['id']} / {case['hypothesis_id']}")
    print(f"wire model pin  : {envelope['model']!r}")
    print(f"wire roles      : {[m['role'] for m in envelope['messages']]}")
    print(f"request sha256  : {__import__('hashlib').sha256(bytes(request)).hexdigest()}")
    print(f"endpoint        : {args.endpoint}  (NOT the pinned Baseten origin)")
    print()

    status, body = post(args.endpoint, wire)
    if args.save_body:
        open(args.save_body, "wb").write(body)
        print(f"body saved      : {args.save_body}")
    print(f"http status     : {status}")
    print(f"bytes returned  : {len(body)}")
    try:
        parsed = json.loads(body)
    except Exception:
        print(f"body (not json) : {body[:400]!r}")
        return 1
    print(f"top-level keys  : {sorted(parsed) if isinstance(parsed, dict) else type(parsed).__name__}")
    if isinstance(parsed, dict):
        print(f"model echoed    : {parsed.get('model')!r}")
        choices = parsed.get("choices") or []
        if choices:
            print(f"choice keys     : {sorted(choices[0])}")
            print(f"message keys    : {sorted(choices[0].get('message') or {})}")
            print(f"finish_reason   : {choices[0].get('finish_reason')!r}")
            content = (choices[0].get("message") or {}).get("content") or ""
            print(f"content[:300]   : {content[:300]!r}")
    print()

    print(f"live validator  : {code_of(request, body)}")

    # Diagnostic only: which check fires first if the model echo is satisfied?
    # Reported separately so it can never be mistaken for a pass.
    if isinstance(parsed, dict) and parsed.get("model") != envelope["model"]:
        patched = dict(parsed)
        patched["model"] = envelope["model"]
        rewritten = json.dumps(patched).encode()
        print(f"diagnostic      : with model rewritten to the pinned slug -> {code_of(request, rewritten)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
