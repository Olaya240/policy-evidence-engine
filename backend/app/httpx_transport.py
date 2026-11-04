"""Owned, bounded HTTPX transports for explicitly constructed providers.

The generic placeholder transport is unauthenticated. The Baseten prototype
accepts an explicitly injected key, but this module has no key-loading path.
"""
from __future__ import annotations

import asyncio
import logging
import httpx

from .provider_safety import ProviderSafetyError, StreamingResponse

ASSESSMENT_PATH = "/v1/assess"
# Reserved placeholder origin. A future reviewed integration must change this
# trusted constant in a separate phase; callers cannot approve their own host.
APPROVED_PROVIDER_ORIGIN = "https://provider.invalid"
BASETEN_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
BASETEN_APPROVED_ORIGIN = "https://inference.baseten.co"
BASETEN_CHAT_COMPLETIONS_ENDPOINT = BASETEN_APPROVED_ORIGIN + BASETEN_CHAT_COMPLETIONS_PATH
META_APPROVED_ORIGIN = "https://api.meta.ai"
META_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
META_CHAT_COMPLETIONS_ENDPOINT = META_APPROVED_ORIGIN + META_CHAT_COMPLETIONS_PATH
_REQUEST_HEADERS = {
    "accept": "application/json",
    "accept-encoding": "identity",
    "content-type": "application/json",
}
_MAX_RESPONSE_HEADER_COUNT = 64
_MAX_RESPONSE_HEADER_BYTES = 16 * 1024


def _is_approved_origin(origin: str, _pinned_origin: str = APPROVED_PROVIDER_ORIGIN) -> bool:
    """Compare against the origin captured when this module defines the helper.

    Reassigning the public module reference does not change the captured default.
    This protects ordinary configuration mistakes, not deliberate same-process
    mutation of Python internals or monkey-patching.
    """
    return origin == _pinned_origin


def _is_approved_baseten_origin(origin: str, _pinned_origin: str = BASETEN_APPROVED_ORIGIN) -> bool:
    """Baseten counterpart of `_is_approved_origin`, pinned the same way.

    The two endpoints have different approved origins, so one captured default
    cannot serve both; each is compared against the constant that was defined
    beside its path.
    """
    return origin == _pinned_origin


class _DropTransportTrace(logging.Filter):
    """Drop HTTPX/httpcore records that may include endpoint or header data."""

    def filter(self, _record: logging.LogRecord) -> bool:
        return False


_DROP_TRANSPORT_TRACE = _DropTransportTrace()
# A logger filter only sees records emitted on that exact logger: a record
# created on httpcore.connection is filtered by httpcore.connection, never by an
# ancestor's filters. Attaching the filter to each httpcore sublogger therefore
# leaves every propagated record free to reach the root handlers, where the
# authorization header can be written out. Propagation is stopped at the parent
# loggers instead, and a NullHandler absorbs the records, so no handler anywhere
# in the process receives them. The filter is kept on each logger as a second
# barrier in case a handler is later attached directly to httpx or httpcore.
for _logger_name in ("httpx", "httpcore"):
    _transport_logger = logging.getLogger(_logger_name)
    _transport_logger.addFilter(_DROP_TRANSPORT_TRACE)
    _transport_logger.addHandler(logging.NullHandler())
    _transport_logger.propagate = False


def _parse_endpoint(value: str, path: str = ASSESSMENT_PATH) -> tuple[httpx.URL, str]:
    """Parse and canonicalise an endpoint, pinning it to one exact path.

    `path` is a parameter so the Baseten chat path is validated by the same
    rules as the assessment path rather than bypassing them.
    """
    if not isinstance(value, str) or not value or any(ord(ch) < 0x21 or ord(ch) > 0x7e for ch in value):
        raise ProviderSafetyError("invalid_transport")
    try:
        url = httpx.URL(value)
    except Exception:
        raise ProviderSafetyError("invalid_transport") from None
    if (str(url) != value or "?" in value or "#" in value or b"@" in url.netloc
            or url.scheme != "https" or not url.host or url.username or url.password
            or url.query or url.fragment or url.path != path
            or url.raw_path != path.encode("ascii")):
        raise ProviderSafetyError("invalid_transport")
    origin = f"https://{url.netloc.decode('ascii')}"
    return url, origin


class _OwnedStreamingResponse:
    """Streaming view that closes both response and the per-call owned client."""

    def __init__(self, response: httpx.Response, client: httpx.AsyncClient):
        self._response = response
        self._client = client
        self._iterator = response.aiter_raw().__aiter__()
        self._pending = b""
        self._closed = False

    @property
    def content_length(self) -> str | None:
        values = self._response.headers.get_list("content-length")
        if not values:
            return None
        # Multiple or combined values are ambiguous and fail closed.
        if len(values) != 1:
            return "invalid"
        return values[0]

    async def read_chunk(self, max_bytes: int) -> bytes:
        if self._closed:
            return b""
        if self._pending:
            result, self._pending = self._pending[:max_bytes], self._pending[max_bytes:]
            return result
        try:
            chunk = await self._iterator.__anext__()
        except StopAsyncIteration:
            return b""
        except httpx.TimeoutException:
            raise ProviderSafetyError("timeout") from None
        # HTTPX's stream yields byte chunks. Avoid copying/splitting an
        # oversized chunk more than necessary; the upstream transport has
        # already materialized that chunk, so the hard pre-buffer guarantee
        # still depends on HTTPX/httpcore and the underlying transport.
        if len(chunk) > max_bytes:
            result, self._pending = chunk[:max_bytes], chunk[max_bytes:]
            return result
        return chunk

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._response.aclose()
        finally:
            await self._client.aclose()


class HttpxAsyncTransport:
    """HTTPS-only transport with an internally owned, single-request client.

    Production construction always makes a fresh AsyncHTTPTransport with
    verified TLS defaults and no caller-controlled auth, mounts, proxy, hooks,
    cookies, or redirects. Offline tests replace AsyncHTTPTransport itself.
    """

    __slots__ = ("_endpoint", "_sealed")

    def __init__(self, endpoint: str):
        try:
            url, origin = _parse_endpoint(endpoint)
        except (TypeError, ValueError):
            raise ProviderSafetyError("invalid_transport") from None
        if not _is_approved_origin(origin):
            raise ProviderSafetyError("invalid_transport")
        object.__setattr__(self, "_endpoint", str(url))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("transport configuration is immutable")
        object.__setattr__(self, name, value)

    @staticmethod
    async def _cleanup(
        response: httpx.Response | None,
        client: httpx.AsyncClient | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if response is not None:
            try:
                await response.aclose()
            except Exception:
                pass
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
        elif transport is not None:
            # AsyncClient owns the transport after successful construction. If
            # client construction fails, close the still-unowned transport.
            try:
                await transport.aclose()
            except Exception:
                pass

    async def send(self, payload: bytes, *, timeout_seconds: float) -> StreamingResponse:
        if type(payload) is not bytes:
            raise ProviderSafetyError("invalid_request")
        client: httpx.AsyncClient | None = None
        response: httpx.Response | None = None
        try:
            # Public retry setting. No caller-supplied AsyncClient or transport
            # is accepted in the production construction path.
            transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False, verify=True)
            client = httpx.AsyncClient(
                transport=transport,
                auth=None,
                headers=_REQUEST_HEADERS,
                cookies=httpx.Cookies(),
                event_hooks={"request": [], "response": []},
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(timeout_seconds),
            )
            request = client.build_request(
                "POST", self._endpoint, content=payload,
                headers=_REQUEST_HEADERS, timeout=httpx.Timeout(timeout_seconds),
            )
            response = await client.send(request, stream=True, follow_redirects=False)
            header_size = sum(len(name) + len(value) + 4 for name, value in response.headers.raw)
            if len(response.headers.raw) > _MAX_RESPONSE_HEADER_COUNT or header_size > _MAX_RESPONSE_HEADER_BYTES:
                raise ProviderSafetyError("response_headers_too_large")
            if response.status_code < 200 or response.status_code >= 300:
                raise ProviderSafetyError("provider_failure")
            return _OwnedStreamingResponse(response, client)
        except asyncio.CancelledError:
            await self._cleanup(response, client)
            raise
        except ProviderSafetyError:
            await self._cleanup(response, client)
            raise
        except httpx.TimeoutException:
            await self._cleanup(response, client)
            raise ProviderSafetyError("timeout") from None
        except Exception:
            await self._cleanup(response, client)
            raise ProviderSafetyError("provider_failure") from None


class BasetenMuseSparkOpenTransport:
    """Fixed-endpoint transport for the offline-reviewed Baseten prototype.

    The key is an explicit constructor input, never loaded from the environment.
    Normal application startup does not construct this transport, and the
    associated provider call gate is disabled unless separately supplied.
    """

    __slots__ = ("_api_key", "_adapter", "_boundary", "_endpoint", "_sealed")

    def __init__(self, api_key: str):
        if type(api_key) is not str or not api_key or api_key.strip() != api_key:
            raise ProviderSafetyError("invalid_transport")
        # The chat endpoint is now admitted through the same validator as the
        # assessment endpoint, with its own pinned path and origin. Before this,
        # the reviewed pinning helper could not validate /v1/chat/completions and
        # the live Baseten path posted a module literal that nothing checked.
        url, origin = _parse_endpoint(BASETEN_CHAT_COMPLETIONS_ENDPOINT, BASETEN_CHAT_COMPLETIONS_PATH)
        if not _is_approved_baseten_origin(origin):
            raise ProviderSafetyError("invalid_transport")
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "_adapter", None)
        object.__setattr__(self, "_boundary", None)
        object.__setattr__(self, "_endpoint", str(url))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("transport configuration is immutable")
        object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        return "BasetenMuseSparkOpenTransport(api_key=<redacted>)"

    def _bind_adapter(self, adapter: object) -> None:
        from .provider_safety import BasetenMuseSparkOpenAdapter
        if type(adapter) is not BasetenMuseSparkOpenAdapter or self._adapter is not None:
            raise ProviderSafetyError("unsupported_provider")
        object.__setattr__(self, "_adapter", adapter)

    def _bind_boundary(self, adapter: object, boundary: object) -> None:
        from .provider_safety import BasetenMuseSparkOpenAdapter, MandatoryProviderBoundary
        if (type(adapter) is not BasetenMuseSparkOpenAdapter or self._adapter is not adapter
                or adapter._boundary is not None or type(boundary) is not MandatoryProviderBoundary
                or boundary._provider is not adapter or self._boundary is not None):
            raise ProviderSafetyError("mandatory_boundary_required")
        object.__setattr__(self, "_boundary", boundary)

    async def send(self, payload: bytes, *, timeout_seconds: float) -> StreamingResponse:
        raise ProviderSafetyError("mandatory_boundary_required")

    async def _send_from_adapter(self, payload: bytes, adapter: object, boundary: object,
                                 *, timeout_seconds: float,
                                 _authorization: object = None) -> StreamingResponse:
        from .provider_safety import (
            BasetenMuseSparkOpenAdapter,
            MandatoryProviderBoundary,
            _valid_transport_dispatch_authorization,
        )
        if (type(adapter) is not BasetenMuseSparkOpenAdapter or self._adapter is not adapter
                or adapter._transport is not self or type(boundary) is not MandatoryProviderBoundary
                or adapter._boundary is not boundary or self._boundary is not boundary
                or boundary._provider is not adapter
                or not _valid_transport_dispatch_authorization(
                    _authorization, self, payload, timeout_seconds,
                )):
            raise ProviderSafetyError("mandatory_boundary_required")
        return await self._send_http(
            payload, timeout_seconds=timeout_seconds, _authorization=_authorization,
        )

    async def _send_http(self, payload: bytes, *, timeout_seconds: float,
                         _authorization: object = None) -> StreamingResponse:
        from .provider_safety import _consume_transport_dispatch_authorization
        if not _consume_transport_dispatch_authorization(
                _authorization, self, payload, timeout_seconds):
            raise ProviderSafetyError("mandatory_boundary_required")
        if type(payload) is not bytes:
            raise ProviderSafetyError("invalid_request")
        client: httpx.AsyncClient | None = None
        response: httpx.Response | None = None
        transport: httpx.AsyncBaseTransport | None = None
        headers = {
            "accept": "application/json",
            "accept-encoding": "identity",
            "content-type": "application/json",
            "authorization": f"Bearer {self._api_key}",
        }
        try:
            transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False, verify=True)
            client = httpx.AsyncClient(
                transport=transport,
                auth=None,
                headers=headers,
                cookies=httpx.Cookies(),
                event_hooks={"request": [], "response": []},
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(timeout_seconds),
            )
            request = client.build_request(
                "POST", self._endpoint, content=payload,
                headers=headers, timeout=httpx.Timeout(timeout_seconds),
            )
            response = await client.send(request, stream=True, follow_redirects=False)
            header_size = sum(len(name) + len(value) + 4 for name, value in response.headers.raw)
            if len(response.headers.raw) > _MAX_RESPONSE_HEADER_COUNT or header_size > _MAX_RESPONSE_HEADER_BYTES:
                raise ProviderSafetyError("response_headers_too_large")
            if response.status_code < 200 or response.status_code >= 300:
                raise ProviderSafetyError("provider_failure")
            return _OwnedStreamingResponse(response, client)
        except asyncio.CancelledError:
            await HttpxAsyncTransport._cleanup(response, client, transport)
            raise
        except ProviderSafetyError:
            await HttpxAsyncTransport._cleanup(response, client, transport)
            raise
        except httpx.TimeoutException:
            await HttpxAsyncTransport._cleanup(response, client, transport)
            raise ProviderSafetyError("timeout") from None
        except Exception:
            await HttpxAsyncTransport._cleanup(response, client, transport)
            raise ProviderSafetyError("provider_failure") from None


class MetaMuseSparkTransport:
    """Fixed Meta Model API transport. Credentials are explicit and repr-redacted."""

    __slots__ = ("_api_key", "_adapter", "_boundary", "_endpoint", "_sealed")

    def __init__(self, api_key: str):
        if type(api_key) is not str or not api_key or api_key.strip() != api_key:
            raise ProviderSafetyError("invalid_transport")
        url, origin = _parse_endpoint(META_CHAT_COMPLETIONS_ENDPOINT, META_CHAT_COMPLETIONS_PATH)
        if origin != META_APPROVED_ORIGIN:
            raise ProviderSafetyError("invalid_transport")
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "_adapter", None)
        object.__setattr__(self, "_boundary", None)
        object.__setattr__(self, "_endpoint", str(url))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("transport configuration is immutable")
        object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        return "MetaMuseSparkTransport(api_key=<redacted>)"

    def _bind_adapter(self, adapter: object) -> None:
        from .provider_safety import MetaMuseSparkAdapter
        if type(adapter) is not MetaMuseSparkAdapter or self._adapter is not None:
            raise ProviderSafetyError("unsupported_provider")
        object.__setattr__(self, "_adapter", adapter)

    def _bind_boundary(self, adapter: object, boundary: object) -> None:
        from .provider_safety import MandatoryProviderBoundary, MetaMuseSparkAdapter
        if (type(adapter) is not MetaMuseSparkAdapter or self._adapter is not adapter
                or adapter._boundary is not None or type(boundary) is not MandatoryProviderBoundary
                or boundary._provider is not adapter or self._boundary is not None):
            raise ProviderSafetyError("mandatory_boundary_required")
        object.__setattr__(self, "_boundary", boundary)

    async def send(self, payload: bytes, *, timeout_seconds: float) -> StreamingResponse:
        raise ProviderSafetyError("mandatory_boundary_required")

    async def _send_from_adapter(self, payload: bytes, adapter: object, boundary: object,
                                 *, timeout_seconds: float,
                                 _authorization: object = None) -> StreamingResponse:
        from .provider_safety import (MandatoryProviderBoundary, MetaMuseSparkAdapter,
                                      _valid_transport_dispatch_authorization)
        if (type(adapter) is not MetaMuseSparkAdapter or self._adapter is not adapter
                or adapter._transport is not self or type(boundary) is not MandatoryProviderBoundary
                or adapter._boundary is not boundary or self._boundary is not boundary
                or boundary._provider is not adapter
                or not _valid_transport_dispatch_authorization(_authorization, self, payload, timeout_seconds)):
            raise ProviderSafetyError("mandatory_boundary_required")
        return await self._send_http(payload, timeout_seconds=timeout_seconds,
                                      _authorization=_authorization)

    async def _send_http(self, payload: bytes, *, timeout_seconds: float,
                         _authorization: object = None) -> StreamingResponse:
        from .provider_safety import _consume_transport_dispatch_authorization
        if not _consume_transport_dispatch_authorization(_authorization, self, payload, timeout_seconds):
            raise ProviderSafetyError("mandatory_boundary_required")
        if type(payload) is not bytes:
            raise ProviderSafetyError("invalid_request")
        client = response = transport = None
        headers = {**_REQUEST_HEADERS, "authorization": f"Bearer {self._api_key}"}
        try:
            transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False, verify=True)
            client = httpx.AsyncClient(transport=transport, auth=None, headers=headers,
                cookies=httpx.Cookies(), event_hooks={"request": [], "response": []},
                follow_redirects=False, trust_env=False, timeout=httpx.Timeout(timeout_seconds))
            request = client.build_request("POST", self._endpoint, content=payload,
                                           headers=headers, timeout=httpx.Timeout(timeout_seconds))
            response = await client.send(request, stream=True, follow_redirects=False)
            header_size = sum(len(n) + len(v) + 4 for n, v in response.headers.raw)
            if len(response.headers.raw) > _MAX_RESPONSE_HEADER_COUNT or header_size > _MAX_RESPONSE_HEADER_BYTES:
                raise ProviderSafetyError("response_headers_too_large")
            status = response.status_code
            if status in (401, 403):
                raise ProviderSafetyError("authentication_failed")
            if status == 429:
                raise ProviderSafetyError("rate_limited")
            if 500 <= status < 600:
                raise ProviderSafetyError("provider_server_error")
            if status < 200 or status >= 300:
                raise ProviderSafetyError("provider_failure")
            return _OwnedStreamingResponse(response, client)
        except asyncio.CancelledError:
            await HttpxAsyncTransport._cleanup(response, client, transport)
            raise
        except ProviderSafetyError:
            await HttpxAsyncTransport._cleanup(response, client, transport)
            raise
        except httpx.TimeoutException:
            await HttpxAsyncTransport._cleanup(response, client, transport)
            raise ProviderSafetyError("timeout") from None
        except Exception:
            await HttpxAsyncTransport._cleanup(response, client, transport)
            raise ProviderSafetyError("provider_failure") from None
