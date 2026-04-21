from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CamundaVariable(BaseModel):
    value: Any
    type: str
    valueInfo: dict[str, Any] | None = None  # noqa: N815 — Camunda REST shape


def _to_variable(value: Any) -> CamundaVariable:  # noqa: PLR0911
    if value is None:
        return CamundaVariable(value=None, type="Null")
    if isinstance(value, bool):
        return CamundaVariable(value=value, type="Boolean")
    if isinstance(value, int):
        return CamundaVariable(value=value, type="Long")
    if isinstance(value, float):
        return CamundaVariable(value=value, type="Double")
    if isinstance(value, datetime):
        return CamundaVariable(value=value.isoformat(), type="Date")
    if isinstance(value, str):
        return CamundaVariable(value=value, type="String")
    if isinstance(value, (dict, list)):
        return CamundaVariable(
            value=json.dumps(value),
            type="Json",
            valueInfo={"serializationDataFormat": "application/json", "objectTypeName": type(value).__name__},
        )
    msg = f"unsupported variable type: {type(value).__name__}"
    raise TypeError(msg)


def to_camunda_vars(variables: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not variables:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for name, val in variables.items():
        var = _to_variable(val)
        dumped: dict[str, Any] = {"value": var.value, "type": var.type}
        if var.valueInfo is not None:
            dumped["valueInfo"] = var.valueInfo
        result[name] = dumped
    return result


def _from_variable(var: dict[str, Any]) -> Any:
    t = var.get("type")
    v = var.get("value")
    if t == "Json" and isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def from_camunda_vars(variables: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    if not variables:
        return {}
    return {name: _from_variable(v) for name, v in variables.items()}
