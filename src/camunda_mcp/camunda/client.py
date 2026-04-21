from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import Any, NoReturn

import httpx

from ..http import request_with_retry
from ..logging import get_logger
from .errors import BadRequestError, CamundaError, ConflictError, NotFoundError
from .models import ActivityInstance, Incident, ProcessInstance, ProcessStatus
from .variables import from_camunda_vars, to_camunda_vars

log = get_logger(__name__)


def _flatten_activities(root: dict[str, Any]) -> list[ActivityInstance]:
    out: list[ActivityInstance] = []

    def walk(node: dict[str, Any]) -> None:
        if node.get("activityId"):
            out.append(ActivityInstance.model_validate(node))
        for child in node.get("childActivityInstances") or []:
            walk(child)
        for child in node.get("childTransitionInstances") or []:
            walk(child)

    walk(root)
    return out


class CamundaClient:
    def __init__(self, http: httpx.AsyncClient, *, max_attempts: int) -> None:
        self._http = http
        self._max_attempts = max_attempts

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        resp = await request_with_retry(
            self._http,
            method,
            url,
            max_attempts=self._max_attempts,
            **kwargs,
        )
        if resp.is_success or resp.status_code == HTTPStatus.NO_CONTENT:
            return resp
        self._raise_for_response(resp)
        raise AssertionError("unreachable")  # help linters: _raise_for_response is NoReturn

    @staticmethod
    def _raise_for_response(resp: httpx.Response) -> NoReturn:
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        msg = payload.get("message") or resp.text or resp.reason_phrase
        type_ = payload.get("type")
        status = resp.status_code
        if status == HTTPStatus.NOT_FOUND:
            raise NotFoundError(status, type_, msg)
        if status == HTTPStatus.CONFLICT:
            raise ConflictError(status, type_, msg)
        if status == HTTPStatus.BAD_REQUEST:
            raise BadRequestError(status, type_, msg)
        raise CamundaError(status, type_, msg)

    async def find_active_instance(
        self,
        process_definition_key: str,
        business_key: str,
    ) -> ProcessInstance | None:
        resp = await self._request(
            "GET",
            "/process-instance",
            params={
                "processDefinitionKey": process_definition_key,
                "businessKey": business_key,
                "active": "true",
            },
        )
        items = resp.json()
        if not items:
            return None
        return ProcessInstance.model_validate(items[0])

    async def start_process(
        self,
        process_definition_key: str,
        business_key: str,
        variables: dict[str, Any] | None = None,
    ) -> ProcessInstance:
        resp = await self._request(
            "POST",
            f"/process-definition/key/{process_definition_key}/start",
            json={
                "businessKey": business_key,
                "variables": to_camunda_vars(variables),
            },
        )
        return ProcessInstance.model_validate(resp.json())

    async def get_process_instance(self, process_instance_id: str) -> ProcessInstance:
        resp = await self._request("GET", f"/process-instance/{process_instance_id}")
        return ProcessInstance.model_validate(resp.json())

    async def get_activity_instances(self, process_instance_id: str) -> list[ActivityInstance]:
        resp = await self._request("GET", f"/process-instance/{process_instance_id}/activity-instances")
        return _flatten_activities(resp.json())

    async def get_variables(self, process_instance_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/process-instance/{process_instance_id}/variables")
        return from_camunda_vars(resp.json())

    async def get_process_status(self, process_instance_id: str) -> ProcessStatus:
        instance = await self.get_process_instance(process_instance_id)
        activities = await self.get_activity_instances(process_instance_id)
        incidents = await self.list_incidents(process_instance_id=process_instance_id)
        variables = await self.get_variables(process_instance_id)
        return ProcessStatus(
            instance=instance,
            activities=activities,
            incidents=incidents,
            variables=variables,
        )

    async def list_incidents(
        self,
        process_definition_key: str | None = None,
        process_instance_id: str | None = None,
    ) -> list[Incident]:
        params: dict[str, str] = {}
        if process_definition_key is not None:
            params["processDefinitionKeyIn"] = process_definition_key
        if process_instance_id is not None:
            params["processInstanceId"] = process_instance_id
        resp = await self._request("GET", "/incident", params=params)
        return [Incident.model_validate(it) for it in resp.json()]

    async def complete_external_task(
        self,
        external_task_id: str,
        worker_id: str,
        variables: dict[str, Any] | None = None,
    ) -> None:
        await self._request(
            "POST",
            f"/external-task/{external_task_id}/complete",
            json={"workerId": worker_id, "variables": to_camunda_vars(variables)},
        )

    async def set_job_retries(
        self,
        job_id: str,
        retries: int,
        due_date: datetime | None = None,
    ) -> None:
        body: dict[str, Any] = {"retries": retries}
        if due_date is not None:
            body["dueDate"] = due_date.isoformat()
        await self._request("PUT", f"/job/{job_id}/retries", json=body)
