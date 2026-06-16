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


class DataSourceError(AppError):
    pass


class DataSourceNotFoundError(DataSourceError):
    def __init__(self, datasource_id: str):
        super().__init__(message=f"DataSource {datasource_id} not found", error_code="DATASOURCE_NOT_FOUND", details={"datasource_id": datasource_id})


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


class StepNotFoundError(PipelineError):
    def __init__(self, step_id: str):
        super().__init__(message=f"Step with id {step_id} not found in pipeline", error_code="STEP_NOT_FOUND", details={"step_id": step_id})


class ComputeError(AppError):
    pass


class EngineNotFoundError(ComputeError):
    def __init__(self, analysis_id: str):
        super().__init__(message=f"Engine for analysis {analysis_id} not found", error_code="ENGINE_NOT_FOUND", details={"analysis_id": analysis_id})


class EngineBusyError(ComputeError):
    def __init__(self, analysis_id: str | None = None):
        details = {"analysis_id": analysis_id} if analysis_id is not None else None
        super().__init__(message="Engine has an active job", error_code="ENGINE_BUSY", details=details)


class IcebergMetadataPathNotFoundError(ValueError):
    def __init__(self, metadata_path: str):
        self.metadata_path = metadata_path
        super().__init__(f"Iceberg metadata_path not found: {metadata_path}")


EXCEPTION_STATUS_MAP: dict[type[AppError], int] = {
    DataSourceNotFoundError: 404,
    StepNotFoundError: 404,
    PipelineValidationError: 400,
    DataSourceValidationError: 400,
    DataSourceConnectionError: 502,
    DataSourceSnapshotError: 409,
    EngineBusyError: 409,
    PipelineExecutionError: 500,
    EngineNotFoundError: 404,
}


def status_for_app_error(exc: AppError) -> int:
    return EXCEPTION_STATUS_MAP.get(type(exc), 500)
