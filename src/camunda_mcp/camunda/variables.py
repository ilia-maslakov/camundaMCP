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


def from_camunda_var(var: dict[str, Any]) -> Any:
    """Decode a single Camunda REST variable payload into a native Python value.

    Handles both shapes returned by Camunda:
      - Runtime/get-variables: dict entry ``{"value": ..., "type": ..., "valueInfo": ...}``
      - Historic-variable-instance items: same shape plus ``name`` and bookkeeping fields.

    JSON payloads arrive either as ``type == "Json"`` or as ``type == "Object"`` with
    ``valueInfo.serializationDataFormat == "application/json"`` (the Jackson/Spin default
    for user-defined POJOs and any variable written through spin). Both are decoded.
    """
    t = var.get("type")
    v = var.get("value")
    if not isinstance(v, str):
        return v
    if t == "Json":
        return _try_json_loads(v)
    if t == "Object":
        value_info = var.get("valueInfo") or {}
        if value_info.get("serializationDataFormat") == "application/json":
            return _try_json_loads(v)
    return v


def _try_json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def from_camunda_vars(variables: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    if not variables:
        return {}
    return {name: from_camunda_var(v) for name, v in variables.items()}
