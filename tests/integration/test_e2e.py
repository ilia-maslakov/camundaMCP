"""Integration tests against a real Camunda 7.21 engine via testcontainers.

Mark all tests here with `integration` so they can be skipped in environments without Docker:
    pytest tests/integration -m integration
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

try:
    import docker  # transitively available with testcontainers
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs
except ImportError:  # pragma: no cover — optional dep
    pytest.skip("testcontainers not installed", allow_module_level=True)

try:
    docker.from_env().ping()
except Exception as exc:  # pragma: no cover — depends on host env  # noqa: BLE001
    pytest.skip(f"docker daemon not available: {exc}", allow_module_level=True)

from camunda_mcp.authz import PermissionDeniedError
from camunda_mcp.camunda.client import CamundaClient
from camunda_mcp.config import Role
from camunda_mcp.server.tools import (
    complete_external_task_impl,
    get_process_status_impl,
    list_incidents_impl,
    set_job_retries_impl,
    start_process_impl,
)

CAMUNDA_IMAGE = "camunda/camunda-bpm-platform:run-7.21.0"
BPMN_PATH = Path(__file__).parent.parent / "fixtures" / "simple_external_task.bpmn"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def camunda_container() -> AsyncIterator[str]:
    container = DockerContainer(CAMUNDA_IMAGE).with_exposed_ports(8080)
    container.start()
    try:
        wait_for_logs(container, "Camunda Platform Run successfully started", timeout=120)
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8080)
        yield f"http://{host}:{port}/engine-rest"
    finally:
        container.stop()


@pytest.fixture(scope="module")
async def engine_ready(camunda_container: str) -> str:
    # additional readiness probe
    async with httpx.AsyncClient(auth=("demo", "demo"), timeout=30) as c:
        for _ in range(60):
            try:
                r = await c.get(f"{camunda_container}/engine")
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
    return camunda_container


@pytest.fixture(scope="module")
async def deployed(engine_ready: str) -> str:
    async with httpx.AsyncClient(auth=("demo", "demo"), timeout=30) as c:
        files = {
            "deployment-name": (None, "e2e-simple"),
            "enable-duplicate-filtering": (None, "true"),
            "simple_external_task.bpmn": (BPMN_PATH.name, BPMN_PATH.read_bytes(), "application/xml"),
        }
        r = await c.post(f"{engine_ready}/deployment/create", files=files)
        r.raise_for_status()
    return engine_ready


@pytest.fixture
async def client(deployed: str) -> AsyncIterator[CamundaClient]:
    async with httpx.AsyncClient(
        base_url=deployed,
        auth=("demo", "demo"),
        timeout=httpx.Timeout(connect=5, read=30, write=30, pool=5),
    ) as http:
        yield CamundaClient(http, max_attempts=3)


async def _fetch_and_lock(engine_url: str, topic: str, worker_id: str) -> dict:
    async with httpx.AsyncClient(auth=("demo", "demo"), timeout=30) as c:
        body = {
            "workerId": worker_id,
            "maxTasks": 1,
            "usePriority": False,
            "topics": [{"topicName": topic, "lockDuration": 30_000}],
        }
        r = await c.post(f"{engine_url}/external-task/fetchAndLock", json=body)
        r.raise_for_status()
        items = r.json()
        assert items, "no external task available"
        return items[0]


async def _handle_failure(engine_url: str, task_id: str, worker_id: str, *, retries: int) -> None:
    async with httpx.AsyncClient(auth=("demo", "demo"), timeout=30) as c:
        r = await c.post(
            f"{engine_url}/external-task/{task_id}/failure",
            json={
                "workerId": worker_id,
                "errorMessage": "injected failure",
                "retries": retries,
                "retryTimeout": 0,
            },
        )
        r.raise_for_status()


@pytest.mark.asyncio
async def test_happy_path(deployed: str, client: CamundaClient) -> None:
    instance = await start_process_impl(client, Role.OPERATOR, "simple", "bk-happy")
    assert instance.reused is False

    worker_id = "e2e-worker"
    task = await _fetch_and_lock(deployed, "simple-topic", worker_id)
    await complete_external_task_impl(
        client, Role.OPERATOR, task["id"], worker_id, variables={"result": "ok"},
    )

    # after completion the instance should no longer be active
    found = await client.find_active_instance("simple", "bk-happy")
    assert found is None


@pytest.mark.asyncio
async def test_retries_recovery(deployed: str, client: CamundaClient) -> None:
    instance = await start_process_impl(client, Role.OPERATOR, "simple", "bk-retries")
    worker_id = "e2e-worker-2"

    # Drive it to zero retries → incident
    task = await _fetch_and_lock(deployed, "simple-topic", worker_id)
    await _handle_failure(deployed, task["id"], worker_id, retries=0)

    incidents = await list_incidents_impl(
        client, Role.READER, process_instance_id=instance.id,
    )
    assert incidents, "expected an incident after exhausting retries"
    job_id = incidents[0].configuration
    assert job_id is not None

    # Recovery via set_job_retries
    await set_job_retries_impl(client, Role.ADMIN, job_id, retries=1)

    task2 = await _fetch_and_lock(deployed, "simple-topic", worker_id)
    await complete_external_task_impl(client, Role.OPERATOR, task2["id"], worker_id)

    status = await get_process_status_impl(client, Role.READER, instance.id)
    assert status.instance.ended is True
    assert status.incidents == []


@pytest.mark.asyncio
async def test_idempotency(client: CamundaClient) -> None:
    first = await start_process_impl(client, Role.OPERATOR, "simple", "bk-idem")
    second = await start_process_impl(client, Role.OPERATOR, "simple", "bk-idem")
    assert second.id == first.id
    assert second.reused is True

    third = await start_process_impl(
        client, Role.OPERATOR, "simple", "bk-idem", allow_duplicate=True,
    )
    assert third.id != first.id


@pytest.mark.asyncio
async def test_rbac_denied_before_network(client: CamundaClient) -> None:
    with pytest.raises(PermissionDeniedError):
        await set_job_retries_impl(client, Role.READER, "does-not-matter", 1)
