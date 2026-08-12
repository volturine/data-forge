from __future__ import annotations

from dataforge_protocol import errors_pb2

ErrorCodeInput = int | str | None


def _coerce_error_code(error_code: ErrorCodeInput) -> int:
    if error_code is None:
        return errors_pb2.ERROR_CODE_UNSPECIFIED
    if isinstance(error_code, int):
        errors_pb2.ErrorCode.Name(error_code)
        return error_code
    return errors_pb2.ErrorCode.Value(f"ERROR_CODE_{error_code}")


def _error_code_label(error_code: int) -> str:
    return errors_pb2.ErrorCode.Name(error_code).removeprefix("ERROR_CODE_")


class AppError(Exception):
    def __init__(self, message: str, error_code: ErrorCodeInput = None, details: dict | None = None):
        self.message = message
        self.error_code_value = _coerce_error_code(error_code)
        self.error_code = _error_code_label(self.error_code_value)
        self.details = details or {}
        super().__init__(message)


def not_found_error(message: str, *, error_code: ErrorCodeInput, details: dict[str, object]) -> AppError:
    return AppError(message=message, error_code=error_code, details=details)


def datasource_not_found(datasource_id: str) -> AppError:
    return not_found_error(
        f"DataSource {datasource_id} not found",
        error_code="DATASOURCE_NOT_FOUND",
        details={"datasource_id": datasource_id},
    )


def step_not_found(step_id: str) -> AppError:
    return not_found_error(
        f"Step with id {step_id} not found in pipeline",
        error_code="STEP_NOT_FOUND",
        details={"step_id": step_id},
    )


def engine_not_found(resource_id: str) -> AppError:
    return not_found_error(
        f"Engine for resource {resource_id} not found",
        error_code="ENGINE_NOT_FOUND",
        details={"resource_id": resource_id},
    )


class DataSourceError(AppError):
    pass


class DataSourceValidationError(DataSourceError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code="DATASOURCE_VALIDATION_ERROR", details=details)


class DataSourceSnapshotError(DataSourceError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code="DATASOURCE_SNAPSHOT_ERROR", details=details)


class DataSourceConnectionError(DataSourceError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code="DATASOURCE_CONNECTION_ERROR", details=details)


class PipelineError(AppError):
    pass


class PipelineValidationError(PipelineError):
    def __init__(self, message: str, step_id: str | None = None, details: dict | None = None):
        next_details = details or {}
        if step_id:
            next_details["step_id"] = step_id
        super().__init__(message=message, error_code="PIPELINE_VALIDATION_ERROR", details=next_details)


class PipelineExecutionError(PipelineError):
    def __init__(self, message: str, job_id: str | None = None, details: dict | None = None):
        next_details = details or {}
        if job_id:
            next_details["job_id"] = job_id
        super().__init__(message=message, error_code="PIPELINE_EXECUTION_ERROR", details=next_details)


class ComputeError(AppError):
    pass


class EngineBusyError(ComputeError):
    def __init__(self, analysis_id: str | None = None):
        details = {"analysis_id": analysis_id} if analysis_id is not None else None
        super().__init__(message="Engine has an active job", error_code="ENGINE_BUSY", details=details)


class EngineShutdownError(ComputeError):
    def __init__(self, details: dict | None = None):
        super().__init__(message="Engine shutdown requested", error_code="JOB_CANCELLED", details=details)


class IcebergMetadataPathNotFoundError(ValueError):
    def __init__(self, metadata_path: str):
        self.metadata_path = metadata_path
        super().__init__(f"Iceberg metadata_path not found: {metadata_path}")


ERROR_CODE_STATUS_MAP: dict[int, int] = {
    errors_pb2.ERROR_CODE_DATASOURCE_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_STEP_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_ENGINE_NOT_FOUND: 404,
    errors_pb2.ERROR_CODE_PIPELINE_VALIDATION_ERROR: 400,
    errors_pb2.ERROR_CODE_DATASOURCE_VALIDATION_ERROR: 400,
    errors_pb2.ERROR_CODE_DATASOURCE_CONNECTION_ERROR: 502,
    errors_pb2.ERROR_CODE_DATASOURCE_SNAPSHOT_ERROR: 409,
    errors_pb2.ERROR_CODE_ENGINE_BUSY: 409,
    errors_pb2.ERROR_CODE_JOB_CANCELLED: 409,
    errors_pb2.ERROR_CODE_PIPELINE_EXECUTION_ERROR: 500,
}


def status_for_app_error(exc: AppError) -> int:
    return ERROR_CODE_STATUS_MAP.get(exc.error_code_value, 500)
