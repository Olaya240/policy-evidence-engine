"""Regressions for the two transport defects fixed in `app/httpx_transport.py`.

Both defects were *silent*: the pinning helper could not see the chat path, and
the log filter could not see propagated records. Neither produced an error, so
neither could be caught by an existing assertion — only by a test that pins the
specific thing that was unprotected.

ORDERING NOTE: importing `app.httpx_transport` mutates global logging state at
import time (`httpx` and `httpcore` get `propagate = False` plus a NullHandler).
Nothing here restores that, deliberately: a restore would re-open the leak for
whatever test ran next. Tests in this module therefore assume the import has
already happened, which it will have as soon as this module is collected.
"""

import logging

import pytest

from app import httpx_transport
from app.httpx_transport import (
    BASETEN_APPROVED_ORIGIN,
    BASETEN_CHAT_COMPLETIONS_ENDPOINT,
    BASETEN_CHAT_COMPLETIONS_PATH,
    BasetenMuseSparkOpenTransport,
    _is_approved_baseten_origin,
    _parse_endpoint,
)
from app.provider_safety import ProviderSafetyError

FAKE_TOKEN = "sk-live-DO-NOT-LOG-3f9a1c7d"


# ---------------------------------------------------------------------------
# Endpoint pinning: the chat path is validated, not exempted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "endpoint",
    [
        "http://inference.baseten.co/v1/chat/completions",           # not https
        "https://inference.baseten.co/v1/chat/completions/",        # trailing slash
        "https://inference.baseten.co/v1/assess",                   # wrong path
        "https://user:pass@inference.baseten.co/v1/chat/completions",  # userinfo
        "https://inference.baseten.co/v1/chat/completions?x=1",     # query
        "https://inference.baseten.co/v1/chat/completions#frag",    # fragment
        "https://inference.baseten.co/v1/chat/compl\u00e9tions",    # non-ASCII
        "",                                                          # empty
    ],
)
def test_chat_endpoint_validator_rejects_anything_but_the_pinned_shape(endpoint):
    with pytest.raises(ProviderSafetyError):
        _parse_endpoint(endpoint, BASETEN_CHAT_COMPLETIONS_PATH)


def test_the_old_default_path_could_not_validate_the_chat_endpoint():
    """The defect in one line: with the old hard-coded path, the real endpoint
    is rejected — so the reviewed helper was structurally unable to check it."""
    with pytest.raises(ProviderSafetyError):
        _parse_endpoint(BASETEN_CHAT_COMPLETIONS_ENDPOINT)


def test_chat_endpoint_is_canonical_and_pins_its_origin():
    url, origin = _parse_endpoint(
        BASETEN_CHAT_COMPLETIONS_ENDPOINT, BASETEN_CHAT_COMPLETIONS_PATH
    )
    assert str(url) == BASETEN_CHAT_COMPLETIONS_ENDPOINT
    assert origin == BASETEN_APPROVED_ORIGIN
    assert str(url).startswith("https://")
    assert not str(url).endswith("/")


def test_origin_pin_ignores_a_later_reassignment_of_the_constant():
    """The pin is captured at function definition, so rebinding the module
    attribute does not move it. Restored in `finally`."""
    original = httpx_transport.BASETEN_APPROVED_ORIGIN
    try:
        httpx_transport.BASETEN_APPROVED_ORIGIN = "https://evil.example"
        assert _is_approved_baseten_origin("https://evil.example") is False
        assert _is_approved_baseten_origin(original) is True
    finally:
        httpx_transport.BASETEN_APPROVED_ORIGIN = original


# ---------------------------------------------------------------------------
# The transport validates at construction and emits the validated string
# ---------------------------------------------------------------------------

def test_transport_accepts_the_module_endpoint_and_stores_it_canonically():
    transport = BasetenMuseSparkOpenTransport(FAKE_TOKEN)
    assert transport._endpoint == BASETEN_CHAT_COMPLETIONS_ENDPOINT
    assert not transport._endpoint.endswith("/")


def test_transport_repr_does_not_disclose_the_key():
    transport = BasetenMuseSparkOpenTransport(FAKE_TOKEN)
    assert FAKE_TOKEN not in repr(transport)
    assert "redacted" in repr(transport)


def test_transport_refuses_a_malformed_key():
    for bad in ("", "  padded  "):
        with pytest.raises(ProviderSafetyError):
            BasetenMuseSparkOpenTransport(bad)


# ---------------------------------------------------------------------------
# Confidentiality: propagation is what leaked, so propagation is what is pinned
# ---------------------------------------------------------------------------

def test_transport_loggers_do_not_propagate():
    assert logging.getLogger("httpx").propagate is False
    assert logging.getLogger("httpcore").propagate is False


def test_child_logger_record_never_reaches_a_root_handler(caplog):
    """A filter on `httpcore` could never see a record created on
    `httpcore.connection`; stopping propagation is what closes it."""
    caplog.set_level(logging.DEBUG)
    logging.getLogger("httpcore.connection").warning(
        "authorization: Bearer %s", FAKE_TOKEN
    )
    logging.getLogger("httpcore.http11").warning("header %s", FAKE_TOKEN)
    logging.getLogger("httpx").warning("header %s", FAKE_TOKEN)
    assert caplog.records == []
    assert FAKE_TOKEN not in caplog.text


def test_root_handler_sees_no_transport_record_even_at_debug(caplog):
    caplog.set_level(logging.DEBUG)
    for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11",
                 "httpcore.http2", "httpcore.proxy"):
        logging.getLogger(name).debug("x")
        logging.getLogger(name).error("authorization: Bearer %s", FAKE_TOKEN)
    assert [r for r in caplog.records if r.name.startswith(("httpx", "httpcore"))] == []
