"""Error handling utilities for FastAPI routes."""

import logging
from functools import wraps
from typing import Any, Callable

from fastapi import HTTPException

from core.exceptions import (
    AnalysisNotFoundError,
    AppError,
    DataSourceNotFoundError,
    EngineNotFoundError,
    EngineTimeoutError,
    FileNotFoundError,
    FileSizeExceededError,
    FileValidationError,
    JobNotFoundError,
    JobTimeoutError,
    PipelineExecutionError,
    PipelineValidationError,
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
    EngineNotFoundError: 404,
    FileNotFoundError: 404,
    StepNotFoundError: 404,
    # 400 - Bad Request errors
    PipelineValidationError: 400,
    FileValidationError: 400,
    UnsupportedExportFormatError: 400,
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
        # Already an HTTPException, return as-is
        return exc

    if isinstance(exc, AppError):
        # Custom application error
        status_code = EXCEPTION_STATUS_MAP.get(type(exc), 500)
        detail = {
            'message': exc.message,
            'error_code': exc.error_code,
            'details': exc.details,
        }
        logger.error(
            f'{type(exc).__name__}: {exc.message}',
            extra={'error_code': exc.error_code, 'details': exc.details},
            exc_info=True,
        )
        return HTTPException(status_code=status_code, detail=detail)

    # Generic exception - log with full traceback
    logger.error(f'Unhandled exception: {str(exc)}', exc_info=True)
    return HTTPException(status_code=500, detail={'message': f'Internal server error: {str(exc)}'})


def handle_errors(operation: str = 'operation') -> Callable:
    """
    Decorator to handle exceptions in FastAPI route handlers.

    Args:
        operation: Description of the operation for error messages

    Usage:
        @router.get('/items/{item_id}')
        @handle_errors(operation='get item')
        async def get_item(item_id: str):
            return await service.get_item(item_id)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                # Re-raise HTTPException as-is
                raise
            except AppError as e:
                # Convert custom app errors to HTTP exceptions
                raise convert_exception_to_http(e)
            except Exception as e:
                # Convert generic exceptions
                logger.error(f'Failed to {operation}: {str(e)}', exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail={'message': f'Failed to {operation}: {str(e)}'},
                )

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                # Re-raise HTTPException as-is
                raise
            except AppError as e:
                # Convert custom app errors to HTTP exceptions
                raise convert_exception_to_http(e)
            except Exception as e:
                # Convert generic exceptions
                logger.error(f'Failed to {operation}: {str(e)}', exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail={'message': f'Failed to {operation}: {str(e)}'},
                )

        # Return the appropriate wrapper based on whether the function is async
        import inspect

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
