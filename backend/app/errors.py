from fastapi import Request
from fastapi.responses import JSONResponse
from typing import Any

from app.services.observability import capture_exception


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        *,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    if exc.status_code >= 500:
        capture_exception(exc, correlation_id=getattr(request.state, "correlation_id", None))
    error: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details is not None:
        error["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content={"error": error})
