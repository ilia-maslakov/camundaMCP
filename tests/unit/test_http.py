from __future__ import annotations

import httpx
import pytest
import respx

from camunda_mcp.http import request_with_retry


@pytest.mark.asyncio
async def test_retries_on_503_then_succeeds() -> None:
    async with httpx.AsyncClient(base_url="http://c.test") as client, respx.mock() as mock:
        route = mock.get("http://c.test/x").mock(
            side_effect=[
                httpx.Response(503, json={"message": "try later"}),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        resp = await request_with_retry(client, "GET", "/x", max_attempts=3)
        assert resp.status_code == 200
        assert route.call_count == 2


@pytest.mark.asyncio
async def test_does_not_retry_on_400() -> None:
    async with httpx.AsyncClient(base_url="http://c.test") as client, respx.mock() as mock:
        route = mock.get("http://c.test/x").mock(return_value=httpx.Response(400, json={"message": "bad"}))
        resp = await request_with_retry(client, "GET", "/x", max_attempts=3)
        assert resp.status_code == 400
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_retries_on_transport_error() -> None:
    async with httpx.AsyncClient(base_url="http://c.test") as client, respx.mock() as mock:
        route = mock.get("http://c.test/x").mock(
            side_effect=[
                httpx.ConnectError("boom"),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        resp = await request_with_retry(client, "GET", "/x", max_attempts=3)
        assert resp.status_code == 200
        assert route.call_count == 2


@pytest.mark.asyncio
async def test_exhausts_retries_and_raises() -> None:
    async with httpx.AsyncClient(base_url="http://c.test") as client, respx.mock() as mock:
        mock.get("http://c.test/x").mock(return_value=httpx.Response(503))
        with pytest.raises(httpx.HTTPStatusError):
            await request_with_retry(client, "GET", "/x", max_attempts=3)


@pytest.mark.asyncio
async def test_post_is_not_retried_on_503() -> None:
    async with httpx.AsyncClient(base_url="http://c.test") as client, respx.mock() as mock:
        route = mock.post("http://c.test/x").mock(return_value=httpx.Response(503, json={"message": "nope"}))
        resp = await request_with_retry(client, "POST", "/x", max_attempts=5)
        assert resp.status_code == 503
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_post_is_not_retried_on_transport_error() -> None:
    async with httpx.AsyncClient(base_url="http://c.test") as client, respx.mock() as mock:
        route = mock.post("http://c.test/x").mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(httpx.ConnectError):
            await request_with_retry(client, "POST", "/x", max_attempts=5)
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_put_is_retried_on_503() -> None:
    async with httpx.AsyncClient(base_url="http://c.test") as client, respx.mock() as mock:
        route = mock.put("http://c.test/x").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(204),
            ]
        )
        resp = await request_with_retry(client, "PUT", "/x", max_attempts=3)
        assert resp.status_code == 204
        assert route.call_count == 2
