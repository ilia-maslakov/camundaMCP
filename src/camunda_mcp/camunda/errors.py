from __future__ import annotations


class CamundaError(RuntimeError):
    def __init__(self, status_code: int, type_: str | None, message: str) -> None:
        super().__init__(f"[{status_code}] {type_ or 'CamundaError'}: {message}")
        self.status_code = status_code
        self.type = type_
        self.message = message


class NotFoundError(CamundaError):
    pass


class ConflictError(CamundaError):
    pass


class BadRequestError(CamundaError):
    pass
