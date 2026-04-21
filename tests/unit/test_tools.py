from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from camunda_mcp.authz import PermissionDeniedError
from camunda_mcp.camunda.client import CamundaClient
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
