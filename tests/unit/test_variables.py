from __future__ import annotations

from datetime import UTC, datetime

import pytest

from camunda_mcp.camunda.variables import from_camunda_vars, to_camunda_vars


def test_primitive_types_roundtrip() -> None:
    raw = {"s": "hello", "i": 42, "f": 3.14, "b": True, "n": None}
    out = to_camunda_vars(raw)
    assert out["s"] == {"value": "hello", "type": "String"}
    assert out["i"] == {"value": 42, "type": "Long"}
    assert out["f"] == {"value": 3.14, "type": "Double"}
    assert out["b"] == {"value": True, "type": "Boolean"}
    assert out["n"] == {"value": None, "type": "Null"}

    back = from_camunda_vars(out)
    assert back == raw


def test_datetime_serialized_as_iso() -> None:
    dt = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    out = to_camunda_vars({"when": dt})
    assert out["when"]["type"] == "Date"
    assert out["when"]["value"] == dt.isoformat()


def test_json_dict_and_list() -> None:
    raw = {"d": {"a": 1, "b": [1, 2]}, "l": [1, 2, 3]}
    out = to_camunda_vars(raw)
    assert out["d"]["type"] == "Json"
    assert out["d"]["valueInfo"]["serializationDataFormat"] == "application/json"
    # value is a JSON string
    assert out["d"]["value"].startswith("{")
    back = from_camunda_vars(out)
    assert back == raw


def test_empty_input_returns_empty_dict() -> None:
    assert to_camunda_vars(None) == {}
    assert to_camunda_vars({}) == {}
    assert from_camunda_vars(None) == {}
    assert from_camunda_vars({}) == {}


def test_unsupported_type_raises() -> None:
    class Opaque:
        pass

    with pytest.raises(TypeError):
        to_camunda_vars({"x": Opaque()})
