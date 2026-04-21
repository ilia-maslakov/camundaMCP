from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProcessInstance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    definition_id: str = Field(alias="definitionId")
    business_key: str | None = Field(default=None, alias="businessKey")
    ended: bool = False
    suspended: bool = False
    tenant_id: str | None = Field(default=None, alias="tenantId")
    reused: bool = False
    """Set to True when start_process returned an existing instance rather than creating a new one."""


class ActivityInstance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    activity_id: str = Field(alias="activityId")
    activity_name: str | None = Field(default=None, alias="activityName")
    activity_type: str | None = Field(default=None, alias="activityType")


class Incident(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    process_instance_id: str = Field(alias="processInstanceId")
    process_definition_id: str | None = Field(default=None, alias="processDefinitionId")
    execution_id: str | None = Field(default=None, alias="executionId")
    activity_id: str | None = Field(default=None, alias="activityId")
    incident_type: str = Field(alias="incidentType")
    incident_message: str | None = Field(default=None, alias="incidentMessage")
    configuration: str | None = None
    cause_incident_id: str | None = Field(default=None, alias="causeIncidentId")
    root_cause_incident_id: str | None = Field(default=None, alias="rootCauseIncidentId")
    job_definition_id: str | None = Field(default=None, alias="jobDefinitionId")
    incident_timestamp: datetime | None = Field(default=None, alias="incidentTimestamp")


class ProcessStatus(BaseModel):
    instance: ProcessInstance
    activities: list[ActivityInstance] = Field(default_factory=list)
    incidents: list[Incident] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
