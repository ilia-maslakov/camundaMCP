from __future__ import annotations

from .config import Role

Op = str

ROLE_ALLOWLIST: dict[Role, frozenset[Op]] = {
    Role.READER: frozenset({"get_process_status", "list_incidents"}),
    Role.OPERATOR: frozenset({
        "get_process_status",
        "list_incidents",
        "start_process",
        "complete_external_task",
    }),
    Role.ADMIN: frozenset({
        "get_process_status",
        "list_incidents",
        "start_process",
        "complete_external_task",
        "set_job_retries",
    }),
}


class PermissionDeniedError(PermissionError):
    def __init__(self, role: Role, op: Op) -> None:
        super().__init__(f"role {role.value!r} is not allowed to perform {op!r}")
        self.role = role
        self.op = op


def check_allowed(role: Role, op: Op) -> None:
    if op not in ROLE_ALLOWLIST.get(role, frozenset()):
        raise PermissionDeniedError(role, op)
