from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings
from .logging import get_logger

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
log = get_logger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


def build_retrying_client(settings: Settings) -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        connect=settings.http.connect_timeout,
        read=settings.http.read_timeout,
        write=settings.http.write_timeout,
        pool=settings.http.connect_timeout,
    )
    auth = httpx.BasicAuth(settings.camunda_user, settings.camunda_password.get_secret_value())
    return httpx.AsyncClient(
        base_url=settings.engine_rest_url,
        auth=auth,
        timeout=timeout,
        headers={"Accept": "application/json"},
    )


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int,
    **kwargs: object,
) -> httpx.Response:
    """Issue a request with exponential-backoff retry on transport errors and retryable 5xx/429.

    Raises the final exception (or its inner HTTPStatusError) on exhaustion.
    """
    async def _do() -> httpx.Response:
        resp = await client.request(method, url, **kwargs)  # type: ignore[arg-type]
        if resp.status_code in _RETRYABLE_STATUS:
            resp.raise_for_status()
        return resp

    retrying: AsyncRetrying = AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=30),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    try:
        return await _execute(retrying, _do)
    except RetryError as exc:  # pragma: no cover — reraise=True should avoid this
        raise exc.last_attempt.exception() or exc  # noqa: B904


async def _execute(
    retrying: AsyncRetrying,
    fn: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response:
    async for attempt in retrying:
        with attempt:
            return await fn()
    msg = "retry loop exited without a result"
    raise RuntimeError(msg)
