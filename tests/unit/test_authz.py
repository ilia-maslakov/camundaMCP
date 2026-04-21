from __future__ import annotations

import pytest

from camunda_mcp.authz import PermissionDeniedError, check_allowed
from camunda_mcp.config import Role

ALL_OPS = [
    "get_process_status",
    "list_incidents",
    "start_process",
    "complete_external_task",
    "set_job_retries",
]


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (Role.READER, {"get_process_status", "list_incidents"}),
        (Role.OPERATOR, {"get_process_status", "list_incidents", "start_process", "complete_external_task"}),
        (Role.ADMIN, set(ALL_OPS)),
    ],
)
def test_role_allowlist(role: Role, allowed: set[str]) -> None:
    for op in ALL_OPS:
        if op in allowed:
            check_allowed(role, op)
        else:
            with pytest.raises(PermissionDeniedError):
                check_allowed(role, op)
