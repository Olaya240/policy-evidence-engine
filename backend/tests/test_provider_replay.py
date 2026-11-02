"""Offline tests for `app.provider_replay`.

Every response body in this file is **synthetic**: hand-written here to exercise
the validator. Nothing here is vendor output, and no vendor behaviour is
asserted -- the tests pin what the *validator* does with a given body.

The parity tests run the *live* path offline (a mocked HTTPX transport, but the
real `BasetenMuseSparkOpenTransport`, `BasetenMuseSparkOpenAdapter`,
`MandatoryProviderBoundary` and request serializer) and assert replay reaches the
same proposal list, or the same refusal code, from the same response bytes.
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from app import provider_replay
from app.engine import AssessmentEngine, ProviderError
from app.httpx_transport import (
    BASETEN_CHAT_COMPLETIONS_ENDPOINT,
    BasetenMuseSparkOpenTransport,
)
from app.models import Record
from app.provider_safety import (
    MAX_PROPOSALS,
    MAX_RESPONSE_BYTES,
    BasetenMuseSparkOpenAdapter,
    MandatoryProviderBoundary,
    ProviderBudgetConfig,
    ProviderCallGate,
    ProviderSafetyError,
    serialize_provider_request,
)

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
MODEL = BasetenMuseSparkOpenAdapter.MODEL_SLUG
CAPTURED_AT = "2026-11-02T12:00:00Z"
RECORD_TEXT = "The handover checklist binder was missing during shift change."
OTHER_TEXT = "Night shift logged two late medication rounds."


def _record(text=RECORD_TEXT, record_id="SYN-1"):
    return Record(
        id=record_id,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        department="Synthetic",
        text=text,
        tags=[],
    )


def _proposal(record_id="SYN-1", quote=RECORD_TEXT, stance="SUPPORTS", rationale="synthetic rationale"):
    return {
        "source_record_id": record_id,
        "quote": quote,
        "stance": stance,
        "rationale": rationale,
    }


def _body(proposals, *, minimal=False):
    """A synthetic wire body in the shape `_parse_response` accepts."""
    content = json.dumps(proposals, separators=(",", ":"))
    if minimal:
        # No optional envelope fields: used where the proposal *count* must be
        # what fires, so the byte cap has to stay clear of the body.
        return json.dumps({
            "model": MODEL,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
        }, separators=(",", ":")).encode("utf-8")
    return json.dumps({
        "id": "chatcmpl-synthetic",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    }, separators=(",", ":")).encode("utf-8")


def _envelope(records, hypothesis_id=HYPOTHESIS):
    return bytes(serialize_provider_request(records, hypothesis_id))


def _cassette(records, body, *, hypothesis_id=HYPOTHESIS, label="synthetic", **overrides):
    envelope = _envelope(records, hypothesis_id)
    payload = {
        "format": provider_replay.CASSETTE_FORMAT,
        "label": label,
        "endpoint": BASETEN_CHAT_COMPLETIONS_ENDPOINT,
        "model": MODEL,
        "timestamp": CAPTURED_AT,
        "request_sha256": hashlib.sha256(envelope).hexdigest(),
        "request_envelope": envelope.decode("utf-8"),
        "response_body": body.decode("utf-8"),
    }
    payload.update(overrides)
    return payload


def _write(tmp_path, payload, name="cassette.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class _AsyncBody(httpx.AsyncByteStream):
    def __init__(self, body):
        self._body = body

    async def __aiter__(self):
        yield self._body

    async def aclose(self):
        return None


def _gate(max_requests=1):
    return ProviderCallGate(ProviderBudgetConfig(
        enabled=True,
        max_requests=max_requests,
        max_estimated_cost_usd=Decimal("0.10") * max_requests,
        conservative_cost_per_request_usd=Decimal("0.10"),
    ))


def _live_adapter(monkeypatch, body, sent):
    """The live provider path with only the socket replaced by a fixed body."""

    def handler(request):
        sent.append(request)
        return httpx.Response(200, stream=_AsyncBody(body))

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_kwargs: httpx.MockTransport(handler))
    transport = BasetenMuseSparkOpenTransport("SYNTHETIC_TEST_KEY_NEVER_SENT")
    return BasetenMuseSparkOpenAdapter(transport, _gate())


# --- happy path -------------------------------------------------------------


def test_a_synthetic_cassette_replays_through_the_live_parser(tmp_path):
    records = [_record()]
    proposals = [_proposal(), _proposal(stance="NEUTRAL", quote="checklist binder", rationale="also neutral")]
    path = _write(tmp_path, _cassette(records, _body(proposals)))

    result = provider_replay.replay_recorded_exchange(
        path, records=records, hypothesis_id=HYPOTHESIS,
    )

    assert result.proposals == tuple(proposals)
    assert result.label == provider_replay.SYNTHETIC_LABEL
    assert result.model == MODEL
    assert result.endpoint == BASETEN_CHAT_COMPLETIONS_ENDPOINT
    assert result.timestamp == CAPTURED_AT
    assert result.request_sha256 == hashlib.sha256(_envelope(records)).hexdigest()
    assert result.response_sha256 == hashlib.sha256(_body(proposals)).hexdigest()


def test_replay_and_the_live_path_produce_the_same_proposals_from_the_same_body(monkeypatch, tmp_path):
    records = [_record(), _record(OTHER_TEXT, "SYN-2")]
    body = _body([_proposal(), _proposal("SYN-2", OTHER_TEXT, "CONTRADICTS", "synthetic")])
    sent = []
    live = MandatoryProviderBoundary(_live_adapter(monkeypatch, body, sent)).assess(records, HYPOTHESIS)

    result = provider_replay.replay_recorded_exchange(
        _write(tmp_path, _cassette(records, body)), records=records, hypothesis_id=HYPOTHESIS,
    )

    assert list(result.proposals) == live
    assert len(sent) == 1
    # The replay rebuilds the exact bytes the live transport would have sent.
    assert result.wire_sha256 == hashlib.sha256(sent[0].content).hexdigest()


def test_replay_preserves_the_synthetic_label_so_no_artifact_can_claim_vendor_output(tmp_path):
    records = [_record()]
    path = _write(tmp_path, _cassette(records, _body([_proposal()])))
    assert provider_replay.load_cassette(path).label == "synthetic"


# --- tampering and reuse ----------------------------------------------------


def test_replay_refuses_a_quote_tampered_by_one_character(tmp_path):
    records = [_record()]
    body = _body([_proposal()])
    tampered = body.replace(b"The handover checklist binder", b"The handover checklixt binder")
    assert tampered != body
    path = _write(tmp_path, _cassette(records, tampered))

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.replay_recorded_exchange(path, records=records, hypothesis_id=HYPOTHESIS)
    assert raised.value.code == "invalid_quote"


def test_replay_refuses_a_cassette_whose_stored_envelope_was_edited(tmp_path):
    records = [_record()]
    payload = _cassette(records, _body([_proposal()]))
    payload["request_envelope"] = payload["request_envelope"].replace("handover", "handovex")
    path = _write(tmp_path, payload)

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.replay_recorded_exchange(path, records=records, hypothesis_id=HYPOTHESIS)
    assert raised.value.code == "cassette_request_mismatch"


@pytest.mark.parametrize("replay_records,replay_hypothesis", [
    ([_record(OTHER_TEXT, "SYN-1")], HYPOTHESIS),
    ([_record()], "TRAINING_GAP"),
    ([_record(), _record(OTHER_TEXT, "SYN-2")], HYPOTHESIS),
])
def test_replay_refuses_a_cassette_recorded_for_another_question_or_corpus(
        tmp_path, replay_records, replay_hypothesis):
    recorded = [_record()]
    path = _write(tmp_path, _cassette(recorded, _body([_proposal()])))

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.replay_recorded_exchange(
            path, records=replay_records, hypothesis_id=replay_hypothesis,
        )
    assert raised.value.code == "cassette_request_mismatch"


# --- response violations the allowlist and grounding checks must catch ------


def test_replay_refuses_a_response_with_a_field_outside_the_allowlist(tmp_path):
    records = [_record()]
    body = json.loads(_body([_proposal()]))
    body["provider_note"] = "synthetic extra field"
    path = _write(tmp_path, _cassette(records, json.dumps(body).encode("utf-8")))

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.replay_recorded_exchange(path, records=records, hypothesis_id=HYPOTHESIS)
    assert raised.value.code == "unsupported_response"


def test_replay_refuses_a_proposal_naming_a_record_it_was_not_given(tmp_path):
    records = [_record()]
    path = _write(tmp_path, _cassette(records, _body([_proposal(record_id="SYN-9", quote=OTHER_TEXT)])))

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.replay_recorded_exchange(path, records=records, hypothesis_id=HYPOTHESIS)
    assert raised.value.code == "invalid_source"


def test_replay_refuses_a_proposal_quoting_a_record_it_was_not_given(tmp_path):
    records = [_record()]
    path = _write(tmp_path, _cassette(records, _body([_proposal(quote=OTHER_TEXT)])))

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.replay_recorded_exchange(path, records=records, hypothesis_id=HYPOTHESIS)
    assert raised.value.code == "invalid_quote"


def test_replay_refuses_a_response_over_the_proposal_budget(tmp_path):
    records = [_record("abc", "R")]
    # Smallest proposal the validator accepts; MAX_PROPOSALS+1 of them still fit
    # under the 4 KiB response cap, so the count bound is what must fire.
    minimal = _proposal(record_id="R", quote="abc", stance="NEUTRAL", rationale="x")
    body = _body([minimal] * (MAX_PROPOSALS + 1), minimal=True)
    assert len(body) <= MAX_RESPONSE_BYTES
    path = _write(tmp_path, _cassette(records, body))

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.replay_recorded_exchange(path, records=records, hypothesis_id=HYPOTHESIS)
    assert raised.value.code == "proposal_capacity_exceeded"


def test_replay_refuses_a_recorded_body_larger_than_the_live_response_cap(tmp_path):
    records = [_record()]
    payload = _cassette(records, b"x")
    payload["response_body"] = "x" * (MAX_RESPONSE_BYTES + 1)
    path = _write(tmp_path, payload)

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.replay_recorded_exchange(path, records=records, hypothesis_id=HYPOTHESIS)
    assert raised.value.code == "response_too_large"


def test_replay_refusal_surfaces_through_the_engine_with_the_live_path_code(monkeypatch, tmp_path):
    """The same body fails identically whether it arrives live or from a cassette."""
    records = [_record()]
    body = _body([_proposal(quote="a quote the model invented")])
    sent = []
    engine = AssessmentEngine(_live_adapter(monkeypatch, body, sent))
    with pytest.raises(ProviderError) as live:
        engine.assess_hypothesis(records, HYPOTHESIS)

    path = _write(tmp_path, _cassette(records, body))
    with pytest.raises(ProviderSafetyError) as replay:
        provider_replay.replay_recorded_exchange(path, records=records, hypothesis_id=HYPOTHESIS)

    assert live.value.code == replay.value.code == "invalid_quote"
    assert len(sent) == 1


# --- cassette container and metadata ---------------------------------------


@pytest.mark.parametrize("override,code", [
    ({"endpoint": BASETEN_CHAT_COMPLETIONS_ENDPOINT + "/"}, "cassette_metadata_mismatch"),
    ({"endpoint": "https://example.invalid/v1/chat/completions"}, "cassette_metadata_mismatch"),
    ({"model": "meta-models/muse-spark"}, "cassette_metadata_mismatch"),
    ({"timestamp": "2026-11-02T12:00:00"}, "cassette_metadata_mismatch"),
    ({"timestamp": "2 November 2026"}, "cassette_metadata_mismatch"),
    ({"label": "vendor"}, "malformed_cassette"),
    ({"format": "provider-replay-cassette-v0"}, "malformed_cassette"),
    ({"request_sha256": "0" * 63}, "malformed_cassette"),
    ({"request_sha256": "Z" * 64}, "malformed_cassette"),
    ({"unexpected": "field"}, "malformed_cassette"),
    ({"request_sha256": hashlib.sha256(b"different request").hexdigest()}, "cassette_request_mismatch"),
])
def test_replay_refuses_a_cassette_with_untrustworthy_metadata(tmp_path, override, code):
    records = [_record()]
    path = _write(tmp_path, _cassette(records, _body([_proposal()]), **override))

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.load_cassette(path)
    assert raised.value.code == code


def test_replay_refuses_a_cassette_with_duplicate_keys(tmp_path):
    records = [_record()]
    payload = _cassette(records, _body([_proposal()]))
    text = json.dumps(payload)
    text = text.replace('{"format":', '{"label":"synthetic","format":', 1)
    path = tmp_path / "duplicate.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.load_cassette(path)
    assert raised.value.code == "malformed_cassette"


def test_replay_refuses_a_cassette_that_is_not_json(tmp_path):
    path = tmp_path / "not-json.json"
    path.write_text("synthetic, but not a cassette", encoding="utf-8")

    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.load_cassette(path)
    assert raised.value.code == "malformed_cassette"


@pytest.mark.parametrize("bad_path", [None, "", "   "])
def test_replay_requires_a_caller_supplied_path(bad_path):
    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.load_cassette(bad_path)
    assert raised.value.code == "malformed_cassette"


def test_replay_refuses_a_missing_path_and_a_directory(tmp_path):
    with pytest.raises(ProviderSafetyError) as missing:
        provider_replay.load_cassette(tmp_path / "absent.json")
    assert missing.value.code == "malformed_cassette"
    with pytest.raises(ProviderSafetyError) as directory:
        provider_replay.load_cassette(tmp_path)
    assert directory.value.code == "malformed_cassette"


def test_replay_refuses_an_oversized_cassette_file(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b"{" + b" " * provider_replay.MAX_CASSETTE_BYTES + b"}")
    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.load_cassette(path)
    assert raised.value.code == "cassette_too_large"


def test_replay_is_not_reachable_without_a_recorded_body(tmp_path):
    """A cassette with no recorded response cannot stand in for one."""
    records = [_record()]
    payload = _cassette(records, _body([_proposal()]))
    del payload["response_body"]
    path = _write(tmp_path, payload)
    with pytest.raises(ProviderSafetyError) as raised:
        provider_replay.load_cassette(path)
    assert raised.value.code == "malformed_cassette"
