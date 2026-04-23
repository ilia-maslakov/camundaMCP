from __future__ import annotations

import httpx
import pytest
import respx

from camunda_mcp.camunda.client import CamundaClient
from camunda_mcp.camunda.errors import BadRequestError, NotFoundError

from ..conftest import ENGINE_REST_URL


@pytest.mark.asyncio
async def test_start_process_posts_typed_variables(camunda_client: CamundaClient) -> None:
    with respx.mock() as mock:
        route = mock.post(f"{ENGINE_REST_URL}/process-definition/key/orderFlow/start").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "pi-1",
                    "definitionId": "orderFlow:1",
                    "businessKey": "bk-1",
                    "ended": False,
                    "suspended": False,
                },
            )
        )
        result = await camunda_client.start_process("orderFlow", "bk-1", {"amount": 100})
        assert result.id == "pi-1"
        sent = route.calls.last.request.read()
        assert b'"type":"Long"' in sent or b'"type": "Long"' in sent
        assert b'"businessKey":"bk-1"' in sent or b'"businessKey": "bk-1"' in sent


@pytest.mark.asyncio
async def test_find_active_instance_returns_none_when_empty(camunda_client: CamundaClient) -> None:
    with respx.mock() as mock:
        mock.get(f"{ENGINE_REST_URL}/process-instance").mock(return_value=httpx.Response(200, json=[]))
        assert await camunda_client.find_active_instance("orderFlow", "bk-miss") is None


@pytest.mark.asyncio
async def test_find_active_instance_returns_first(camunda_client: CamundaClient) -> None:
    with respx.mock() as mock:
        mock.get(f"{ENGINE_REST_URL}/process-instance").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": "pi-9", "definitionId": "orderFlow:1", "businessKey": "bk-9", "ended": False,
                       "suspended": False}],
            )
        )
        inst = await camunda_client.find_active_instance("orderFlow", "bk-9")
        assert inst is not None
        assert inst.id == "pi-9"


@pytest.mark.asyncio
async def test_not_found_raises_domain_error(camunda_client: CamundaClient) -> None:
    with respx.mock() as mock:
        mock.get(f"{ENGINE_REST_URL}/process-instance/missing").mock(
            return_value=httpx.Response(404, json={"type": "RestException", "message": "not found"})
        )
        with pytest.raises(NotFoundError):
            await camunda_client.get_process_instance("missing")


@pytest.mark.asyncio
async def test_bad_request_raises_domain_error(camunda_client: CamundaClient) -> None:
    with respx.mock() as mock:
        mock.put(f"{ENGINE_REST_URL}/job/j-1/retries").mock(
            return_value=httpx.Response(400, json={"type": "InvalidRequestException", "message": "bad"})
        )
        with pytest.raises(BadRequestError):
            await camunda_client.set_job_retries("j-1", -1)


@pytest.mark.asyncio
async def test_list_incidents_filters(camunda_client: CamundaClient) -> None:
    with respx.mock() as mock:
        route = mock.get(f"{ENGINE_REST_URL}/incident").mock(return_value=httpx.Response(200, json=[]))
        await camunda_client.list_incidents(process_instance_id="pi-1")
        assert "processInstanceId=pi-1" in str(route.calls.last.request.url)


@pytest.mark.asyncio
async def test_complete_external_task_sends_worker_id(camunda_client: CamundaClient) -> None:
    with respx.mock() as mock:
        route = mock.post(f"{ENGINE_REST_URL}/external-task/et-1/complete").mock(
            return_value=httpx.Response(204)
        )
        await camunda_client.complete_external_task("et-1", "worker-a", {"result": "ok"})
        body = route.calls.last.request.read()
        assert b'"workerId":"worker-a"' in body or b'"workerId": "worker-a"' in body


@pytest.mark.asyncio
async def test_get_process_status_falls_back_to_history(camunda_client: CamundaClient) -> None:
    """Runtime endpoint 404s after completion; status must fall back to /history/*."""
    pi_id = "pi-done"
    with respx.mock() as mock:
        mock.get(f"{ENGINE_REST_URL}/process-instance/{pi_id}").mock(
            return_value=httpx.Response(404, json={"type": "RestException", "message": "gone"}),
        )
        mock.get(f"{ENGINE_REST_URL}/history/process-instance/{pi_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": pi_id,
                    "processDefinitionId": "f:1",
                    "businessKey": "bk",
                    "state": "COMPLETED",
                    "endTime": "2026-04-22T12:00:00.000+0000",
                },
            ),
        )
        mock.get(f"{ENGINE_REST_URL}/history/activity-instance").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": "ha1", "activityId": "start", "activityType": "startEvent"},
                    {"id": "ha2", "activityId": "task1", "activityName": "Task 1",
                     "activityType": "serviceTask"},
                ],
            ),
        )
        mock.get(f"{ENGINE_REST_URL}/history/variable-instance").mock(
            return_value=httpx.Response(
                200,
                json=[{"name": "amount", "value": 100, "type": "Long"}],
            ),
        )
        status = await camunda_client.get_process_status(pi_id)
        assert status.instance.id == pi_id
        assert status.instance.ended is True
        assert status.instance.suspended is False
        assert {a.activity_id for a in status.activities} == {"start", "task1"}
        assert status.variables == {"amount": 100}
        assert status.incidents == []


@pytest.mark.asyncio
async def test_get_activity_instances_flattens(camunda_client: CamundaClient) -> None:
    tree = {
        "id": "root",
        "activityId": "root",
        "childActivityInstances": [
            {"id": "a1", "activityId": "task1", "activityName": "Task 1", "activityType": "userTask",
             "childActivityInstances": [], "childTransitionInstances": []},
            {"id": "a2", "activityId": "task2", "childActivityInstances": [], "childTransitionInstances": []},
        ],
        "childTransitionInstances": [],
    }
    with respx.mock() as mock:
        mock.get(f"{ENGINE_REST_URL}/process-instance/pi-1/activity-instances").mock(
            return_value=httpx.Response(200, json=tree)
        )
        activities = await camunda_client.get_activity_instances("pi-1")
        ids = {a.activity_id for a in activities}
        assert ids == {"root", "task1", "task2"}
