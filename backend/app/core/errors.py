"""Erorile API, cu coduri stabile.

`ErrorCode` este oglinda exactă a listei `API_ERROR_CODES` din
`frontend/src/api/types.ts`. Cele două trebuie să rămână identice: frontend-ul
construiește `ApiError` din `code`, `message` și `details`, iar decizia de retry
din `main.tsx` depinde de status.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_var

logger = get_logger(__name__)

# Starlette a redenumit HTTP_422_UNPROCESSABLE_ENTITY în HTTP_422_UNPROCESSABLE_CONTENT.
# Numim noi constanta, ca modulul să nu depindă de versiune.
HTTP_422_UNPROCESSABLE = 422


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_DEFAULT_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: HTTP_422_UNPROCESSABLE,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.UNAUTHORIZED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ErrorCode.CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.PROCESSING_ERROR: HTTP_422_UNPROCESSABLE,
    ErrorCode.EXTERNAL_SERVICE_ERROR: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


class ErrorResponse(BaseModel):
    """Forma unică a oricărui răspuns de eroare (§40)."""

    code: ErrorCode
    message: str
    details: dict[str, list[str]] | None = None
    requestId: str | None = None  # noqa: N815 — contractul JSON este camelCase


class AppError(Exception):
    """Eroare de domeniu. Mesajul ajunge la utilizator, deci este în română."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int | None = None,
        details: dict[str, list[str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code or _DEFAULT_STATUS[code]
        self.details = details
        # Unele erori spun ceva și în antete, nu doar în corp: un `429` fără
        # `Retry-After` lasă clientul să ghicească cât să aștepte.
        self.headers = headers


class NotFoundError(AppError):
    def __init__(self, entity: str, identifier: Any) -> None:
        super().__init__(ErrorCode.NOT_FOUND, f"{entity} inexistent: {identifier}")


class ValidationError(AppError):
    def __init__(self, message: str, details: dict[str, list[str]] | None = None) -> None:
        super().__init__(ErrorCode.VALIDATION_ERROR, message, details=details)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Autentificare necesară.") -> None:
        super().__init__(ErrorCode.UNAUTHORIZED, message)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Nu ai permisiunea necesară pentru această acțiune.") -> None:
        super().__init__(ErrorCode.FORBIDDEN, message)


class ConflictError(AppError):
    def __init__(self, message: str, details: dict[str, list[str]] | None = None) -> None:
        super().__init__(ErrorCode.CONFLICT, message, details=details)


def _render(
    code: ErrorCode,
    message: str,
    status_code: int,
    details: dict[str, list[str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        code=code,
        message=message,
        details=details,
        requestId=request_id_var.get(),
    )
    return JSONResponse(
        status_code=status_code, content=body.model_dump(mode="json"), headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.warning("app_error", code=exc.code.value, message=exc.message)
        return _render(exc.code, exc.message, exc.status_code, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details: dict[str, list[str]] = {}
        for error in exc.errors():
            # `loc` începe cu body/query/path; păstrăm numele câmpului, nu tot drumul.
            location = [str(part) for part in error["loc"][1:]] or ["_"]
            details.setdefault(".".join(location), []).append(error["msg"])
        return _render(
            ErrorCode.VALIDATION_ERROR,
            "Datele trimise nu sunt valide.",
            HTTP_422_UNPROCESSABLE,
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
            status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
            status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
            status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        return _render(code, str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Detaliile interne rămân în log, nu în răspuns.
        logger.exception("unhandled_error", error=type(exc).__name__)
        return _render(
            ErrorCode.INTERNAL_ERROR,
            "A apărut o eroare neașteptată.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
