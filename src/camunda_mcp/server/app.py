from __future__ import annotations

from fastmcp import FastMCP

from ..camunda.client import CamundaClient
from ..config import Settings
from ..http import build_retrying_client
from .tools import register_tools


def create_app(settings: Settings) -> tuple[FastMCP, CamundaClient]:
    http = build_retrying_client(settings)
    client = CamundaClient(http, max_attempts=settings.http.max_attempts)
    mcp: FastMCP = FastMCP(name="camunda-mcp")
    register_tools(mcp, client, settings.mcp_role)
    return mcp, client
