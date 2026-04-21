from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from camunda_mcp.camunda.client import CamundaClient
from camunda_mcp.config import Role, Settings

BASE_URL = "http://camunda.test"
ENGINE_REST_URL = f"{BASE_URL}/engine-rest"


@pytest.fixture
def settings() -> Settings:
    return Settings.model_validate(
        {
            "camunda_base_url": BASE_URL,
            "camunda_user": "demo",
            "camunda_password": "demo",
            "mcp_role": Role.ADMIN,
        }
    )


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=ENGINE_REST_URL) as client:
        yield client


@pytest.fixture
async def camunda_client(http_client: httpx.AsyncClient) -> CamundaClient:
    return CamundaClient(http_client, max_attempts=2)
