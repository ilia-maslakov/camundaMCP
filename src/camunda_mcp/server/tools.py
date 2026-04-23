from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import Any

import httpx
from fastmcp import FastMCP

from ..authz import check_allowed
from ..camunda.client import CamundaClient
from ..camunda.errors import CamundaError
from ..camunda.models import Incident, ProcessInstance, ProcessStatus
from ..config import Role
from ..logging import get_logger

log = get_logger(__name__)


async def start_process_impl(
    client: CamundaClient,
    role: Role,
    process_definition_key: str,
    business_key: str,
    variables: dict[str, Any] | None = None,
    allow_duplicate: bool = False,
) -> ProcessInstance:
    """Start (or reuse) a process instance by (definition_key, business_key).

    Idempotency guarantees:
      - Repeat invocations: the pre-check by (key, businessKey) returns the existing active
        instance with `reused=True` unless `allow_duplicate=True`.
      - In-flight network failure: if the engine accepts the create but the response is lost
        (TransportError or 5xx), we re-query by businessKey and treat a found instance as the
        recovered result. POST is never auto-retried by the HTTP layer (see http.py).
    """
    check_allowed(role, "start_process")
    if not allow_duplicate:
        existing = await client.find_active_instance(process_definition_key, business_key)
        if existing is not None:
            return existing.model_copy(update={"reused": True})
    try:
        return await client.start_process(process_definition_key, business_key, variables)
    except (httpx.TransportError, CamundaError) as exc:
        if allow_duplicate:
            raise
        # 4xx is a definitive engine rejection, not an ambiguous failure — don't recover.
        if isinstance(exc, CamundaError) and exc.status_code < HTTPStatus.INTERNAL_SERVER_ERROR:
            raise
        log.warning(
            "start_process ambiguous failure, probing for created instance",
            process_definition_key=process_definition_key,
            business_key=business_key,
            error=str(exc),
        )
        recovered = await client.find_active_instance(process_definition_key, business_key)
        if recovered is None:
            raise
        return recovered.model_copy(update={"reused": True})


async def get_process_status_impl(
    client: CamundaClient,
    role: Role,
    process_instance_id: str,
) -> ProcessStatus:
    check_allowed(role, "get_process_status")
    return await client.get_process_status(process_instance_id)


async def list_incidents_impl(
    client: CamundaClient,
    role: Role,
    process_definition_key: str | None = None,
    process_instance_id: str | None = None,
) -> list[Incident]:
    check_allowed(role, "list_incidents")
    return await client.list_incidents(
        process_definition_key=process_definition_key,
        process_instance_id=process_instance_id,
    )


async def complete_external_task_impl(
    client: CamundaClient,
    role: Role,
    external_task_id: str,
    worker_id: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, str]:
    check_allowed(role, "complete_external_task")
    await client.complete_external_task(external_task_id, worker_id, variables)
    return {"status": "completed", "external_task_id": external_task_id}


async def set_job_retries_impl(
    client: CamundaClient,
    role: Role,
    job_id: str,
    retries: int,
    due_date: datetime | None = None,
) -> dict[str, Any]:
    check_allowed(role, "set_job_retries")
    await client.set_job_retries(job_id, retries, due_date)
    return {"status": "updated", "job_id": job_id, "retries": retries}


def register_tools(mcp: FastMCP, client: CamundaClient, role: Role) -> None:
    @mcp.tool()
    async def start_process(
        process_definition_key: str,
        business_key: str,
        variables: dict[str, Any] | None = None,
        allow_duplicate: bool = False,
    ) -> ProcessInstance:
        """Start a process instance by definition key.

        Idempotent by (process_definition_key, business_key): returns the existing active
        instance unless allow_duplicate=True. `reused` in the result distinguishes a newly
        created instance (False) from a pre-existing one (True).
        """
        return await start_process_impl(
            client, role, process_definition_key, business_key, variables, allow_duplicate
        )

    @mcp.tool()
    async def get_process_status(process_instance_id: str) -> ProcessStatus:
        """Return instance state, current activities, incidents, and variables."""
        return await get_process_status_impl(client, role, process_instance_id)

    @mcp.tool()
    async def list_incidents(
        process_definition_key: str | None = None,
        process_instance_id: str | None = None,
    ) -> list[Incident]:
        """List open incidents, optionally filtered by definition key or instance id."""
        return await list_incidents_impl(client, role, process_definition_key, process_instance_id)

    @mcp.tool()
    async def complete_external_task(
        external_task_id: str,
        worker_id: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Complete a locked external task. Caller must supply the worker_id holding the lock."""
        return await complete_external_task_impl(client, role, external_task_id, worker_id, variables)

    @mcp.tool()
    async def set_job_retries(
        job_id: str,
        retries: int,
        due_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Set retries on a job (primary recovery path for failed jobs and external tasks)."""
        return await set_job_retries_impl(client, role, job_id, retries, due_date)
