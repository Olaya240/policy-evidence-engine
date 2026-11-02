# Worker B — transport regression tests

File written: `backend/tests/test_transport_hardening.py` (new). No source file touched.

## What each test pins

| Test | Pins |
|---|---|
| `test_chat_endpoint_validator_rejects_anything_but_the_pinned_shape` (8 params) | scheme, trailing slash, wrong path, userinfo, query, fragment, non-ASCII, empty — all rejected through the *chat* path, so the new `path` parameter is exercised rather than bypassed |
| `test_the_old_default_path_could_not_validate_the_chat_endpoint` | the defect itself: with the default path the real endpoint is rejected, which is why the baseline never validated it |
| `test_chat_endpoint_is_canonical_and_pins_its_origin` | returned string is byte-canonical and the origin matches the Baseten pin |
| `test_origin_pin_ignores_a_later_reassignment_of_the_constant` | the pin is captured at definition; rebinding the module attribute does not move it. Restored in `finally` |
| `test_transport_accepts_the_module_endpoint_and_stores_it_canonically` | construction-time validation stores the validated string, which `send` then posts |
| `test_transport_repr_does_not_disclose_the_key` | redaction survives the new `_endpoint` slot |
| `test_transport_refuses_a_malformed_key` | unrelated but adjacent; cheap |
| `test_transport_loggers_do_not_propagate` | `propagate is False` on both parents — the actual mechanism |
| `test_child_logger_record_never_reaches_a_root_handler` | a record created on `httpcore.connection` reaches no root handler and the token appears in no captured text |
| `test_root_handler_sees_no_transport_record_even_at_debug` | same at DEBUG/ERROR across six sublogger names |

## Unrun, and the two most likely to fail

No terminal in this session: **none of these has been executed.** Ranked by risk:

1. `test_the_old_default_path_could_not_validate_the_chat_endpoint` — it depends on
   `_parse_endpoint`'s default argument still being `ASSESSMENT_PATH`. If the
   signature's default were also changed, this test would pass for the wrong
   reason (or error), and it is the test that documents the defect.
2. `test_child_logger_record_never_reaches_a_root_handler` — `caplog` attaches its
   handler to the root logger and also installs a `LogCaptureHandler` at the
   handler level; whether `caplog.records` is empty depends on pytest's
   propagation handling when `propagate = False` is set at import time. If pytest
   re-enables propagation for capture, this test fails while the code is correct —
   in that case replace it with a manual `logging.Handler` subclass attached to
   `logging.getLogger()` and assert `handler.records == []`.

Also unverified by reading: whether `BasetenMuseSparkOpenTransport.__init__`
accepts `""` before the type check reaches the endpoint validation — the order in
the source is key check first, so the test should be fine, but I could not run it.
