"""Error handling utilities for FastAPI routes."""

import inspect
import logging
from collections.abc import Callable, Sequence
from functools import wraps
from typing import Any, Never

from core.app_error_status import status_for_app_error
from core.exceptions import (
    AppError,
    DataSourceSnapshotError,
    EngineNotFoundError,
    InvalidIdError,
    PipelineValidationError,
)
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend_core.auth_exceptions import (
    AccountDisabledError,
    DefaultUserDeletionError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    OAuthError,
    ProviderUnlinkError,
    SessionExpiredError,
    TokenExpiredError,
    TokenInvalidError,
)

logger = logging.getLogger(__name__)


def _error_body(message: str, error_code: str | None = None, details: dict | None = None) -> dict[str, Any]:
    """Build a structured error response body."""
    body: dict[str, Any] = {"detail": message}
    if error_code:
        body["error_code"] = error_code
    if details:
        body["details"] = details
    return body


_BACKEND_EXCEPTION_STATUS_MAP: dict[type[AppError], int] = {
    InvalidCredentialsError: 401,
    SessionExpiredError: 401,
    AccountDisabledError: 403,
    DefaultUserDeletionError: 403,
    EmailAlreadyExistsError: 409,
    ProviderUnlinkError: 400,
    OAuthError: 400,
    TokenExpiredError: 400,
    TokenInvalidError: 400,
}


def _status_for(exc: AppError) -> int:
    return _BACKEND_EXCEPTION_STATUS_MAP.get(type(exc), status_for_app_error(exc))


def _log_app_error(exc: AppError, status: int) -> None:
    msg = f"{type(exc).__name__}: {exc.message}"
    extra = {"error_code": exc.error_code, "details": exc.details}
    if status >= 500:
        logger.error(msg, extra=extra, exc_info=True)
    elif status == 404 or isinstance(
        exc,
        (
            InvalidIdError,
            DataSourceSnapshotError,
            PipelineValidationError,
            EngineNotFoundError,
            InvalidCredentialsError,
        ),
    ):
        logger.info(msg, extra=extra)
    else:
        logger.warning(msg, extra=extra)


def _raise_http(exc: Exception, operation: str, value_error_status: int | None) -> Never:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, AppError):
        raise exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=value_error_status or 400, detail=str(exc)) from exc
    logger.error("Failed to %s: %s", operation, type(exc).__name__, exc_info=True)
    raise HTTPException(status_code=500, detail="An internal error occurred") from exc


def handle_errors(operation: str = "operation", value_error_status: int | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    _raise_http(e, operation, value_error_status)

            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                _raise_http(e, operation, value_error_status)

        return sync_wrapper

    return decorator


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Global handler for AppError exceptions not caught by @handle_errors."""
    status = _status_for(exc)
    _log_app_error(exc, status)
    return JSONResponse(
        status_code=status,
        content=_error_body(exc.message, exc.error_code, exc.details),
    )


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Strip non-serializable ctx values from Pydantic validation errors."""
    sanitized = []
    for e in errors:
        clean: dict[str, Any] = {k: v for k, v in e.items() if k != "ctx"}
        if "ctx" in e and isinstance(e["ctx"], dict):
            clean["ctx"] = {k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v for k, v in e["ctx"].items()}
        sanitized.append(clean)
    return sanitized


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Global handler for Pydantic/FastAPI request validation errors."""
    logger.warning("Validation error: %s", exc.errors())
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "Request validation failed",
            "VALIDATION_ERROR",
            {"errors": _sanitize_validation_errors(exc.errors())},
        ),
    )


async def generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Global fallback handler — never leaks internal details."""
    logger.error("Unhandled exception: %s", type(exc).__name__, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=_error_body("An internal error occurred", "INTERNAL_ERROR"),
    )
