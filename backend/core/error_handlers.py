"""Error handling utilities for FastAPI routes."""

import inspect
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, Never

from fastapi import HTTPException

from core.exceptions import (
    AnalysisCycleError,
    AnalysisNotFoundError,
    AnalysisValidationError,
    AnalysisVersionNotFoundError,
    AppError,
    DataSourceConnectionError,
    DataSourceNotFoundError,
    DataSourceSnapshotError,
    DataSourceValidationError,
    EngineNotFoundError,
    EngineTimeoutError,
    FileNotFoundError,
    FileSizeExceededError,
    FileValidationError,
    JobNotFoundError,
    JobTimeoutError,
    PipelineExecutionError,
    PipelineValidationError,
    ScheduleNotFoundError,
    ScheduleValidationError,
    StepNotFoundError,
    UnsupportedExportFormatError,
)

logger = logging.getLogger(__name__)

# Map custom exceptions to HTTP status codes
EXCEPTION_STATUS_MAP = {
    # 404 - Not Found errors
    DataSourceNotFoundError: 404,
    JobNotFoundError: 404,
    AnalysisNotFoundError: 404,
    AnalysisVersionNotFoundError: 404,
    EngineNotFoundError: 404,
    FileNotFoundError: 404,
    StepNotFoundError: 404,
    ScheduleNotFoundError: 404,
    # 400 - Bad Request errors
    PipelineValidationError: 400,
    FileValidationError: 400,
    UnsupportedExportFormatError: 400,
    ScheduleValidationError: 400,
    DataSourceValidationError: 400,
    AnalysisValidationError: 400,
    AnalysisCycleError: 404,
    DataSourceConnectionError: 502,
    DataSourceSnapshotError: 409,
    # 408 - Timeout errors
    EngineTimeoutError: 408,
    JobTimeoutError: 408,
    # 409 - Conflict errors
    FileSizeExceededError: 413,
    # 500 - Execution errors
    PipelineExecutionError: 500,
}


def convert_exception_to_http(exc: Exception) -> HTTPException:
    """Convert a custom exception to an HTTPException."""
    if isinstance(exc, HTTPException):
        return exc

    if isinstance(exc, AppError):
        status_code = EXCEPTION_STATUS_MAP.get(type(exc), 500)
        logger.error(
            f'{type(exc).__name__}: {exc.message}',
            extra={'error_code': exc.error_code, 'details': exc.details},
            exc_info=True,
        )
        return HTTPException(status_code=status_code, detail=exc.message)

    logger.error(f'Unhandled exception: {str(exc)}', exc_info=True)
    return HTTPException(status_code=500, detail='An internal error occurred')


def _raise_http(exc: Exception, operation: str, value_error_status: int | None) -> Never:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, AppError):
        raise convert_exception_to_http(exc)
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=value_error_status or 400, detail=str(exc)) from exc
    logger.error(f'Failed to {operation}: {str(exc)}', exc_info=True)
    raise HTTPException(status_code=500, detail=f'Failed to {operation}: {str(exc)}') from exc


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
        else:

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    _raise_http(e, operation, value_error_status)

            return sync_wrapper

    return decorator
