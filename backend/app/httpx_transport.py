"""Owned, bounded HTTPX transport for a future explicitly approved provider.

This module deliberately has no authentication support. A later key-loading
design must add one fixed, single-request authentication mechanism.
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


class _DropTransportTrace(logging.Filter):
    """Drop HTTPX/httpcore records that may include endpoint or header data."""

    def filter(self, _record: logging.LogRecord) -> bool:
        return False


_DROP_TRANSPORT_TRACE = _DropTransportTrace()
# HTTPX uses the root `httpx` logger; HTTPcore emits from subloggers whose
# records do not pass through the parent logger's filters when propagated.
for _logger_name in (
    "httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
    "httpcore.proxy", "httpcore.socks",
):
    logging.getLogger(_logger_name).addFilter(_DROP_TRANSPORT_TRACE)


def _parse_endpoint(value: str) -> tuple[httpx.URL, str]:
    if not isinstance(value, str) or not value or any(ord(ch) < 0x21 or ord(ch) > 0x7e for ch in value):
        raise ProviderSafetyError("invalid_transport")
    try:
        url = httpx.URL(value)
    except Exception:
        raise ProviderSafetyError("invalid_transport") from None
    if (str(url) != value or "?" in value or "#" in value or b"@" in url.netloc
            or url.scheme != "https" or not url.host or url.username or url.password
            or url.query or url.fragment or url.path != ASSESSMENT_PATH
            or url.raw_path != ASSESSMENT_PATH.encode("ascii")):
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
    async def _cleanup(response: httpx.Response | None, client: httpx.AsyncClient | None) -> None:
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
