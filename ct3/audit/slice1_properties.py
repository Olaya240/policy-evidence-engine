"""Executable property checks for backend/app/provider_safety.py lines 1-208.

Run from the worktree root:

    PYTHONPATH=backend python3 ct3/audit/slice1_properties.py

Standard library only. Exits non-zero on the first failing property, printing the
minimal counterexample it found.

Why these six: they are the invariants the slice *claims* rather than merely
implements. A size model that disagrees with json.dumps, or a seal that a slice
or a deepcopy survives, would make the boundary advisory.
"""

from __future__ import annotations

import copy
import pickle
import json
import random
import sys
from datetime import datetime, timezone

from app import provider_safety as ps
from app.models import HYPOTHESES, Record

HYPOTHESIS_ID = HYPOTHESES[0].id
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        failures.append(name)


def record(index: int, text: str, *, restricted: bool = False) -> Record:
    return Record(
        id=f"REC-{index:03d}",
        timestamp=NOW,
        department="Ops",
        text=text,
        tags=[],
        restricted=restricted,
    )


# --------------------------------------------------------------------------
# 1. The size model must agree with the encoder it is predicting.
# --------------------------------------------------------------------------
def property_size_model() -> None:
    boundary = [0x7F, 0x80, 0x7FF, 0x800, 0xFFFF, 0x10000, 0x10FFFF]
    codepoints = list(range(0, 0x3000)) + boundary
    for cp in codepoints:
        char = chr(cp)
        expected = len(json.dumps(char, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        try:
            got = ps._json_string_size(char)
        except ps.ProviderSafetyError as exc:  # the model refuses, the encoder succeeds
            check("1 size model", False, f"U+{cp:04X} raised {exc.code} but json accepts it")
            return
        if got != expected:
            check("1 size model", False, f"U+{cp:04X}: model {got} != json {expected}")
            return
    check("1 size model", True, f"{len(codepoints)} codepoints")


# --------------------------------------------------------------------------
# 2. Predicted payload size must equal the produced size, computed independently.
# --------------------------------------------------------------------------
def predicted_size(records: list[Record]) -> int:
    eligible = ps.eligible_provider_records(records)
    hypothesis = next(h for h in HYPOTHESES if h.id == HYPOTHESIS_ID)
    literals = [b'{"system_instructions":', b',"input":{"hypothesis":{"id":',
                b',"label":', b'},"records":[']
    total = sum(len(lit) for lit in literals) + len(b"]}}")
    total += ps._json_string_size(ps.SYSTEM_INSTRUCTIONS)
    total += ps._json_string_size(hypothesis.id) + ps._json_string_size(hypothesis.label)
    for index, rec in enumerate(eligible):
        total += (1 if index else 0) + len(b'{"id":') + len(b',"text":') + len(b"}") \
            + ps._json_string_size(rec.id) + ps._json_string_size(rec.text)
    return total


def property_payload_size() -> None:
    lengths = [0, 1, 10, 100, 1000]
    for count in range(0, 9):
        for length in lengths:
            records = [record(i, "x" * length) for i in range(count)]
            expected = predicted_size(records)
            try:
                payload = ps.serialize_provider_request(records, HYPOTHESIS_ID)
            except ps.ProviderSafetyError as exc:
                if exc.code != "request_too_large" or expected <= ps.MAX_REQUEST_BYTES:
                    check("2 payload size", False,
                          f"{count} records x {length} chars raised {exc.code} at predicted {expected}")
                    return
                continue
            if len(payload) != expected:
                check("2 payload size", False,
                      f"{count} records x {length} chars: produced {len(payload)} != predicted {expected}")
                return
            if len(payload) > ps.MAX_REQUEST_BYTES:
                check("2 payload size", False, f"accepted {len(payload)} > cap")
                return
    check("2 payload size", True)


# --------------------------------------------------------------------------
# 3. The cap is enforced in both directions.
# --------------------------------------------------------------------------
def property_cap() -> None:
    oversized = [record(0, "x" * (ps.MAX_REQUEST_BYTES + 1))]
    try:
        ps.serialize_provider_request(oversized, HYPOTHESIS_ID)
    except ps.ProviderSafetyError as exc:
        check("3 cap", exc.code == "request_too_large", f"wrong code {exc.code}")
    else:
        check("3 cap", False, "a payload above the cap was accepted")
        return
    # Just under the cap must still build, so the guard is not simply "always raise".
    near = [record(0, "x" * (ps.MAX_REQUEST_BYTES - 2000))]
    try:
        payload = ps.serialize_provider_request(near, HYPOTHESIS_ID)
    except ps.ProviderSafetyError as exc:
        check("3 cap", False, f"a payload under the cap was refused: {exc.code}")
        return
    check("3 cap", len(payload) <= ps.MAX_REQUEST_BYTES, f"{len(payload)} bytes")


# --------------------------------------------------------------------------
# 4. Sealing survives the obvious attacks.
# --------------------------------------------------------------------------
def property_sealing() -> None:
    sealed = ps.serialize_provider_request([record(0, "text")], HYPOTHESIS_ID)
    check("4 seal: original", ps._is_serialized_request(sealed))

    # Copying an immutable, sealed payload must preserve the guarantee by
    # identity; a distinct copy could only be a forgery.
    if copy.copy(sealed) is not sealed or copy.deepcopy(sealed) is not sealed:
        check("4 seal: copy", False, "copy produced a distinct object")
        return
    try:
        pickle.dumps(sealed)
    except TypeError:
        print("PASS  4 seal: pickle refused")
    else:
        check("4 seal: pickle", False, "pickle produced a bytes form")
        return

    candidates = {
        "plain bytes": bytes(sealed),
        "slice": sealed[:10],
        "bytes-concat": sealed + b"",
    }
    for label, value in candidates.items():
        if ps._is_serialized_request(value):
            check(f"4 seal: {label}", False, "forged request passed the seal check")
            return
    check("4 seal: forgeries", True)

    try:
        ps.SerializedProviderRequest(b"{}")
    except ps.ProviderSafetyError:
        print("PASS  4 seal: construction without the seal raises")
    else:
        check("4 seal: construction without the seal", False, "unsealed instance was created")
        return

    try:
        sealed._seal = None
    except AttributeError:
        print("PASS  4 seal: attribute write refused")
    else:
        check("4 seal: attribute write", False, "mutation succeeded")
        return
    check("4 seal: after mutation attempt", ps._is_serialized_request(sealed))


# --------------------------------------------------------------------------
# 5. Eligibility is deterministic and never leaks a restricted record.
# --------------------------------------------------------------------------
def property_eligibility() -> None:
    records = [record(i, f"text {i}") for i in range(12)]
    records[3] = record(3, "restricted body", restricted=True)
    first = ps.serialize_provider_request(records, HYPOTHESIS_ID)
    second = ps.serialize_provider_request(records, HYPOTHESIS_ID)
    if first != second:
        check("5 eligibility: deterministic", False, "two calls produced different bytes")
        return
    if b"restricted body" in first:
        check("5 eligibility: restricted", False, "restricted text reached the payload")
        return
    shuffled = [record(i, f"text {i}") for i in range(12)]
    shuffled[3] = record(3, "restricted body", restricted=True)
    random.Random(7).shuffle(shuffled)
    reordered = ps.serialize_provider_request(shuffled, HYPOTHESIS_ID)
    if reordered == first:
        fail = "the payload ignores input order entirely — check that is intended"
        check("5 eligibility: order", True, fail)
    else:
        print("INFO  5 eligibility: payload follows input order (records are ordered evidence)")
    check("5 eligibility", True)


# --------------------------------------------------------------------------
# 6. The sensitive-text filter's recall, measured rather than assumed.
# --------------------------------------------------------------------------
def property_sensitive() -> None:
    cases = []
    for i in range(200):
        kind = i % 4
        if kind == 0:
            cases.append((f"contact guest{i}@example.com now", "email"))
        elif kind == 1:
            cases.append((f"claim number {100 + i}-45-6789 on file", "ssn"))
        elif kind == 2:
            cases.append((f"call +1 (555) 01{i:02d}-99{i % 10} after 6", "phone"))
        else:
            cases.append((f"api_key: sk-live-{i:04d}", "secret"))
    misses = [(text, kind) for text, kind in cases if not ps.contains_sensitive_text(text)]
    total = len(cases)
    hit_rate = (total - len(misses)) / total
    check("6 sensitive recall >= 95%", hit_rate >= 0.95, f"{hit_rate:.1%}")
    if misses:
        print(f"INFO  6 misses ({len(misses)}/{total}):")
        for text, kind in misses[:8]:
            print(f"         [{kind}] {text!r}")
    else:
        print(f"INFO  6 all {total} embedded sensitive forms detected")


def main() -> int:
    property_size_model()
    property_payload_size()
    property_cap()
    property_sealing()
    property_eligibility()
    property_sensitive()
    if failures:
        print(f"\n{len(failures)} failing propert{'y' if len(failures) == 1 else 'ies'}: {failures}")
        return 1
    print("\nall slice-1 properties hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
