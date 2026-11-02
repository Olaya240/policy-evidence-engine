# W1 — Transport: endpoint pinning and log confinement

Worker 1 of 4. Worktree `/home/alex/policy-evidence-fix` (branch `fix/evidence-decision-table`).
Files edited: **one** — `backend/app/httpx_transport.py`.

No terminal in this session: nothing below was executed, typechecked or tested. Line numbers
are given only where I read them; the post-edit numbering is *not* re-read, so symbols and
quoted code are used as the citation instead.

## Defect 1 — the Baseten chat path bypassed endpoint validation: CONFIRMED

What I read, before editing:

- The module literal `BASETEN_CHAT_COMPLETIONS_ENDPOINT = "https://inference.baseten.co/v1/chat/completions"`, defined next to `APPROVED_PROVIDER_ORIGIN = "https://provider.invalid"`.
- `_parse_endpoint` rejected every endpoint whose path was not the assessment path:

  ```python
  or url.path != ASSESSMENT_PATH
  or url.raw_path != ASSESSMENT_PATH.encode("ascii")
  ```

- `BasetenMuseSparkOpenTransport.__init__` validated **only the API key** (type, non-empty, no surrounding whitespace) and then sealed. It never touched the endpoint.
- `_send_http` posted the literal directly:

  ```python
  request = client.build_request("POST", BASETEN_CHAT_COMPLETIONS_ENDPOINT, content=payload, ...)
  ```

So the import-captured pin protected `HttpxAsyncTransport` and had no reach over the path that
actually carries the bearer token. The two failures compound: the chat path was not validated
*and* nothing in the constructor could have failed closed, because there was nothing to fail on.

### Fix

1. `_parse_endpoint(value: str, path: str = ASSESSMENT_PATH)` — the path is now a parameter, so
   both endpoints pass through the same rules (scheme `https`, no userinfo, no query, no
   fragment, canonical `str(url) == value`, raw path byte-equal to the pinned path). The default
   keeps every existing caller unchanged, which is why `HttpxAsyncTransport`'s behaviour and the
   twelve-endpoint parametrised rejection test in `test_httpx_transport.py` are untouched.
2. Added `BASETEN_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"` and
   `BASETEN_APPROVED_ORIGIN = "https://inference.baseten.co"`, with the endpoint literal now
   *derived* from them rather than written out on its own. A typo can no longer create an
   endpoint that the origin pin does not describe.
3. Added `_is_approved_baseten_origin`, mirroring `_is_approved_origin` including its
   capture-at-definition trick, so reassigning the public constant does not widen admission.
   Two separate pinned helpers are needed because the two endpoints have different approved
   origins; one captured default cannot serve both.
4. `BasetenMuseSparkOpenTransport.__init__` now runs `_parse_endpoint(...)` with the chat path
   and then `_is_approved_baseten_origin(origin)`, and stores the canonical URL in a new
   `_endpoint` slot. `_send_http` posts `self._endpoint` instead of the literal.

Behaviour preserved: same URL string is posted (`str(url) == value` is one of the validator's own
conditions, and `test_baseten_adapter.py` asserts `str(request.url) == BASETEN_CHAT_COMPLETIONS_ENDPOINT`),
the constructor still takes exactly one argument with no endpoint override, and no I/O happens
during construction — the validation is pure string work, so the tests that monkeypatch
`httpx.AsyncHTTPTransport` before constructing still see zero calls.

### Not verified

That construction still succeeds in the suite. `_is_approved_baseten_origin` compares
`https://inference.baseten.co` against the same literal-derived constant, so it must, but I could
not run `pytest`. This is the first thing to run.

## Defect 2 — the log filter could not see propagated records: CONFIRMED

What I read:

```python
class _DropTransportTrace(logging.Filter):
    def filter(self, _record: logging.LogRecord) -> bool:
        return False
```

attached as

```python
for _logger_name in ("httpx", "httpcore.connection", "httpcore.http11", ...):
    logging.getLogger(_logger_name).addFilter(_DROP_TRANSPORT_TRACE)
```

(the tuple lists `httpcore.connection`, `httpcore.http11`, `httpcore.http2`, `httpcore.proxy`,
`httpcore.socks`).

The comment above it even names the mechanism it then relies on getting wrong: HTTPcore emits
from subloggers, and a record created on `httpcore.connection` is passed to `handle()` on that
logger, then to its **handlers**, then to each ancestor's handlers — the ancestor's *filters*
are never consulted. `logging.Logger.addFilter` filters `record` only in `Logger.handle`, i.e.
only for records emitted on that logger. So the five `httpcore.*` filters could never fire, and
only `httpx`-emitted records were dropped. Any httpcore record carrying an `authorization`
header value reached the root handlers.

### Fix

Propagation is stopped at the parent loggers and a `NullHandler` absorbs the records:

```python
for _logger_name in ("httpx", "httpcore"):
    _transport_logger = logging.getLogger(_logger_name)
    _transport_logger.addFilter(_DROP_TRANSPORT_TRACE)
    _transport_logger.addHandler(logging.NullHandler())
    _transport_logger.propagate = False
```

Why this placement works where the old one did not: `propagate = False` is consulted in
`Logger.callHandlers` *before* walking to the parent, so `httpcore.connection`'s record goes to
`httpcore`'s handlers and no further. Setting it on `httpcore` (the parent) covers every
`httpcore.*` sublogger, including ones added by future httpcore versions — the old explicit list
had to enumerate them and would silently miss a new one. `NullHandler` is attached so the logger
is not "handlerless" and emits `No handlers could be found`-class noise. The filter is kept as a
second barrier for the case where a handler is later attached directly to `httpx` or `httpcore`.

Cost, stated plainly: this silences httpx/httpcore logging process-wide, which is the intent
stated in the module docstring's security posture but is a global side effect of importing the
module — the same class of side effect the old code already had.

### Not verified

`test_secret_canary_does_not_enter_logs_or_manifest` emits on `logging.getLogger("httpx")` and
`logging.getLogger("httpcore.connection")` and asserts the canary is absent from `caplog.text`.
Under the new code the record is absorbed by the `NullHandler` and never reaches caplog's handler
on the root logger, so the assertion should still pass — but it passes for a *different reason*
than before (absorption rather than filtering), and it still does not test the propagation path,
because it emits on the leaf loggers rather than proving an ancestor handler saw nothing. A test
that actually exercises the defect would attach a handler to the root logger, emit on
`httpcore.connection`, and assert the handler recorded nothing. **I did not add that test** — the
brief confines this worker to the transport file.

## Memory

`local_memory__memory_store` is not bound to this worker session — my tools are `read_files`,
`str_replace`, `write_file`, `code_search`, `glob`, `list_directory`. I am not claiming a write I
did not make. The two durable facts are in this file for the coordinator to store:

- `policy-evidence-engine Baseten transport` · `VALIDATES_AT_CONSTRUCTION` · `_parse_endpoint(..., BASETEN_CHAT_COMPLETIONS_PATH)` plus `_is_approved_baseten_origin` in `BasetenMuseSparkOpenTransport.__init__`, with `self._endpoint` replacing the literal at the request site.
- `policy-evidence-engine transport log filter` · `STOPS_PROPAGATION` · `propagate = False` and a `NullHandler` on `httpx` and `httpcore`, because logger-level filters never see propagated records.
