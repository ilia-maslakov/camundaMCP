from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from camunda_mcp.authz import PermissionDeniedError
from camunda_mcp.camunda.client import CamundaClient
from camunda_mcp.camunda.errors import BadRequestError
from camunda_mcp.config import Role
from camunda_mcp.server.tools import (
    register_tools,
    start_process_impl,
)

from ..conftest import ENGINE_REST_URL


@pytest.mark.asyncio
async def test_registered_tool_names(camunda_client: CamundaClient) -> None:
    mcp: FastMCP = FastMCP(name="test")
    register_tools(mcp, camunda_client, Role.ADMIN)
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "start_process",
        "get_process_status",
        "list_incidents",
        "complete_external_task",
        "set_job_retries",
    }


@pytest.mark.asyncio
async def test_reader_denied_for_start_process(camunda_client: CamundaClient) -> None:
    with respx.mock() as mock:
        with pytest.raises(PermissionDeniedError):
            await start_process_impl(camunda_client, Role.READER, "f", "bk-1")
        assert mock.calls.call_count == 0  # denied before network


@pytest.mark.asyncio
async def test_start_process_idempotent_returns_existing(camunda_client: CamundaClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ENGINE_REST_URL}/process-instance").mock(
            return_value=httpx.Response(
                200,
                json=[{
                    "id": "pi-existing", "definitionId": "f:1", "businessKey": "bk",
                    "ended": False, "suspended": False,
                }],
            )
        )
        start_route = mock.post(f"{ENGINE_REST_URL}/process-definition/key/f/start")
        result = await start_process_impl(camunda_client, Role.OPERATOR, "f", "bk")
        assert result.id == "pi-existing"
        assert result.reused is True
        assert start_route.call_count == 0


@pytest.mark.asyncio
async def test_start_process_creates_when_allow_duplicate(camunda_client: CamundaClient) -> None:
    with respx.mock() as mock:
        start_route = mock.post(f"{ENGINE_REST_URL}/process-definition/key/f/start").mock(
            return_value=httpx.Response(
                200,
                json={"id": "pi-new", "definitionId": "f:1", "businessKey": "bk2",
                      "ended": False, "suspended": False},
            )
        )
        result = await start_process_impl(
            camunda_client, Role.OPERATOR, "f", "bk2", allow_duplicate=True,
        )
        assert result.id == "pi-new"
        assert result.reused is False
        assert start_route.call_count == 1


@pytest.mark.asyncio
async def test_start_process_recovers_from_transport_error(camunda_client: CamundaClient) -> None:
    """Engine created the instance, but the POST response was lost on the wire."""
    with respx.mock(assert_all_called=False) as mock:
        find_route = mock.get(f"{ENGINE_REST_URL}/process-instance")
        find_route.side_effect = [
            httpx.Response(200, json=[]),  # pre-check: nothing yet
            httpx.Response(
                200,
                json=[{"id": "pi-recovered", "definitionId": "f:1", "businessKey": "bk-r",
                       "ended": False, "suspended": False}],
            ),  # post-failure probe: engine did create it
        ]
        mock.post(f"{ENGINE_REST_URL}/process-definition/key/f/start").mock(
            side_effect=httpx.ConnectError("lost response")
        )
        result = await start_process_impl(camunda_client, Role.OPERATOR, "f", "bk-r")
        assert result.id == "pi-recovered"
        assert result.reused is True


@pytest.mark.asyncio
async def test_start_process_recovers_from_5xx(camunda_client: CamundaClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        find_route = mock.get(f"{ENGINE_REST_URL}/process-instance")
        find_route.side_effect = [
            httpx.Response(200, json=[]),
            httpx.Response(
                200,
                json=[{"id": "pi-5xx", "definitionId": "f:1", "businessKey": "bk-5",
                       "ended": False, "suspended": False}],
            ),
        ]
        mock.post(f"{ENGINE_REST_URL}/process-definition/key/f/start").mock(
            return_value=httpx.Response(503, json={"message": "engine overloaded"})
        )
        result = await start_process_impl(camunda_client, Role.OPERATOR, "f", "bk-5")
        assert result.id == "pi-5xx"
        assert result.reused is True


@pytest.mark.asyncio
async def test_start_process_does_not_recover_from_4xx(camunda_client: CamundaClient) -> None:
    """4xx is a definitive engine rejection, not an ambiguous in-flight failure."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ENGINE_REST_URL}/process-instance").mock(return_value=httpx.Response(200, json=[]))
        mock.post(f"{ENGINE_REST_URL}/process-definition/key/f/start").mock(
            return_value=httpx.Response(400, json={"type": "InvalidRequestException", "message": "bad key"})
        )
        with pytest.raises(BadRequestError):
            await start_process_impl(camunda_client, Role.OPERATOR, "f", "bk-bad")


@pytest.mark.asyncio
async def test_start_process_raises_when_probe_empty(camunda_client: CamundaClient) -> None:
    """Transport error + no recovered instance: propagate the transport error."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{ENGINE_REST_URL}/process-instance").mock(return_value=httpx.Response(200, json=[]))
        mock.post(f"{ENGINE_REST_URL}/process-definition/key/f/start").mock(
            side_effect=httpx.ConnectError("really lost")
        )
        with pytest.raises(httpx.ConnectError):
            await start_process_impl(camunda_client, Role.OPERATOR, "f", "bk-lost")
