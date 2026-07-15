"""Error handling utilities for FastAPI routes."""

import inspect
import logging
from collections.abc import Callable, Sequence
from functools import wraps
from typing import Any, Never

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend_core.exceptions import (
    AppError,
    DataSourceSnapshotError,
    InvalidIdError,
    PipelineValidationError,
)
from dataforge_protocol import errors_pb2

logger = logging.getLogger(__name__)

ERROR_CODE_STATUS_MAP: dict[int, int] = {
    errors_pb2.ERROR_CODE_DATASOURCE_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_JOB_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_ANALYSIS_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_ANALYSIS_VERSION_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_ENGINE_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_ENGINE_RUN_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_FILE_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_STEP_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_SCHEDULE_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_UDF_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_HEALTHCHECK_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_PIPELINE_VALIDATION_ERROR: 400,
    errors_pb2.ERROR_CODE_FILE_VALIDATION_ERROR: 400,
    errors_pb2.ERROR_CODE_UNSUPPORTED_EXPORT_FORMAT: 400,
    errors_pb2.ERROR_CODE_SCHEDULE_VALIDATION_ERROR: 400,
    errors_pb2.ERROR_CODE_DATASOURCE_VALIDATION_ERROR: 400,
    errors_pb2.ERROR_CODE_ANALYSIS_VALIDATION_ERROR: 400,
    errors_pb2.ERROR_CODE_UDF_VALIDATION_ERROR: 400,
    errors_pb2.ERROR_CODE_HEALTHCHECK_VALIDATION_ERROR: 400,
    errors_pb2.ERROR_CODE_INVALID_ID: 400,
    errors_pb2.ERROR_CODE_ENGINE_RUN_COMPARISON_ERROR: 400,
    errors_pb2.ERROR_CODE_PROVIDER_UNLINK_ERROR: 400,
    errors_pb2.ERROR_CODE_OAUTH_ERROR: 400,
    errors_pb2.ERROR_CODE_TOKEN_EXPIRED: 400,
    errors_pb2.ERROR_CODE_TOKEN_INVALID: 400,
    errors_pb2.ERROR_CODE_ANALYSIS_CYCLE_ERROR: 422,
    errors_pb2.ERROR_CODE_DATASOURCE_CONNECTION_ERROR: 502,
    errors_pb2.ERROR_CODE_DATASOURCE_SNAPSHOT_ERROR: 409,
    errors_pb2.ERROR_CODE_ENGINE_BUSY: 409,
    errors_pb2.ERROR_CODE_FILE_SIZE_EXCEEDED: 413,
    errors_pb2.ERROR_CODE_PIPELINE_EXECUTION_ERROR: 500,
    errors_pb2.ERROR_CODE_SETTINGS_CONFIGURATION_ERROR: 500,
    errors_pb2.ERROR_CODE_ENGINE_START_ERROR: 500,
    errors_pb2.ERROR_CODE_INVALID_CREDENTIALS: 401,
    errors_pb2.ERROR_CODE_SESSION_EXPIRED: 401,
    errors_pb2.ERROR_CODE_ACCOUNT_DISABLED: 403,
    errors_pb2.ERROR_CODE_DEFAULT_USER_DELETION_FORBIDDEN: 403,
    errors_pb2.ERROR_CODE_EMAIL_ALREADY_EXISTS: 409,
}


def status_for_app_error(exc: AppError) -> int:
    return ERROR_CODE_STATUS_MAP.get(exc.error_code_value, 500)


def _error_body(message: str, error_code: str | None = None, details: dict | None = None) -> dict[str, Any]:
    """Build a structured error response body."""
    body: dict[str, Any] = {'detail': message}
    if error_code:
        body['error_code'] = error_code
    if details:
        body['details'] = details
    return body


def _log_app_error(exc: AppError, status: int) -> None:
    msg = f'{type(exc).__name__}: {exc.message}'
    extra = {'error_code': exc.error_code, 'details': exc.details}
    if status >= 500:
        logger.error(msg, extra=extra, exc_info=True)
    elif status == 404 or isinstance(
        exc,
        (
            InvalidIdError,
            DataSourceSnapshotError,
            PipelineValidationError,
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
    logger.error('Failed to %s: %s', operation, type(exc).__name__, exc_info=True)
    raise HTTPException(status_code=500, detail='An internal error occurred') from exc


def handle_errors(operation: str = 'operation', value_error_status: int | None = None) -> Callable:
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
    status = status_for_app_error(exc)
    _log_app_error(exc, status)
    return JSONResponse(
        status_code=status,
        content=_error_body(exc.message, exc.error_code, exc.details),
    )


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Strip non-serializable ctx values from Pydantic validation errors."""
    sanitized = []
    for e in errors:
        clean: dict[str, Any] = {k: v for k, v in e.items() if k != 'ctx'}
        if 'ctx' in e and isinstance(e['ctx'], dict):
            clean['ctx'] = {k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v for k, v in e['ctx'].items()}
        sanitized.append(clean)
    return sanitized


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Global handler for Pydantic/FastAPI request validation errors."""
    logger.warning('Validation error: %s', exc.errors())
    return JSONResponse(
        status_code=422,
        content=_error_body(
            'Request validation failed',
            'VALIDATION_ERROR',
            {'errors': _sanitize_validation_errors(exc.errors())},
        ),
    )


async def generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Global fallback handler — never leaks internal details."""
    logger.error('Unhandled exception: %s', type(exc).__name__, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=_error_body('An internal error occurred', 'INTERNAL_ERROR'),
    )
