"""Custom exception hierarchy for the application."""

from dataforge_protocol import errors_pb2

ErrorCodeInput = int | str | None


def _coerce_error_code(error_code: ErrorCodeInput) -> int:
    if error_code is None:
        return errors_pb2.ERROR_CODE_UNSPECIFIED
    if isinstance(error_code, int):
        errors_pb2.ErrorCode.Name(error_code)
        return error_code
    return errors_pb2.ErrorCode.Value(f'ERROR_CODE_{error_code}')


def _error_code_label(error_code: int) -> str:
    return errors_pb2.ErrorCode.Name(error_code).removeprefix('ERROR_CODE_')


class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str, error_code: ErrorCodeInput = None, details: dict | None = None):
        """Initialize the exception with message, error code, and optional details."""
        self.message = message
        self.error_code_value = _coerce_error_code(error_code)
        self.error_code = _error_code_label(self.error_code_value)
        self.details = details or {}
        super().__init__(message)


def not_found_error(message: str, *, error_code: ErrorCodeInput, details: dict[str, object]) -> AppError:
    """Build a protocol-coded not-found application error."""
    return AppError(message=message, error_code=error_code, details=details)


def datasource_not_found(datasource_id: str) -> AppError:
    return not_found_error(
        f'DataSource {datasource_id} not found',
        error_code='DATASOURCE_NOT_FOUND',
        details={'datasource_id': datasource_id},
    )


def step_not_found(step_id: str) -> AppError:
    return not_found_error(
        f'Step with id {step_id} not found in pipeline',
        error_code='STEP_NOT_FOUND',
        details={'step_id': step_id},
    )


def engine_not_found(resource_id: str) -> AppError:
    return not_found_error(
        f'Engine for resource {resource_id} not found',
        error_code='ENGINE_NOT_FOUND',
        details={'resource_id': resource_id},
    )


def engine_run_not_found(run_id: str) -> AppError:
    return not_found_error(
        f'Engine run {run_id} not found',
        error_code='ENGINE_RUN_NOT_FOUND',
        details={'run_id': run_id},
    )


def job_not_found(job_id: str) -> AppError:
    return not_found_error(
        f'Job {job_id} not found',
        error_code='JOB_NOT_FOUND',
        details={'job_id': job_id},
    )


def analysis_not_found(analysis_id: str) -> AppError:
    return not_found_error(
        f'Analysis {analysis_id} not found',
        error_code='ANALYSIS_NOT_FOUND',
        details={'analysis_id': analysis_id},
    )


def analysis_version_not_found(analysis_id: str, version: int) -> AppError:
    return not_found_error(
        f'Analysis version {version} not found for analysis {analysis_id}',
        error_code='ANALYSIS_VERSION_NOT_FOUND',
        details={'analysis_id': analysis_id, 'version': version},
    )


def data_file_not_found(file_path: str) -> AppError:
    return not_found_error(
        f'File not found: {file_path}',
        error_code='FILE_NOT_FOUND',
        details={'file_path': file_path},
    )


def schedule_not_found(schedule_id: str) -> AppError:
    return not_found_error(
        f'Schedule {schedule_id} not found',
        error_code='SCHEDULE_NOT_FOUND',
        details={'schedule_id': schedule_id},
    )


def udf_not_found(udf_id: str) -> AppError:
    return not_found_error(
        f'UDF {udf_id} not found',
        error_code='UDF_NOT_FOUND',
        details={'udf_id': udf_id},
    )


def healthcheck_not_found(healthcheck_id: str) -> AppError:
    return not_found_error(
        f'Healthcheck {healthcheck_id} not found',
        error_code='HEALTHCHECK_NOT_FOUND',
        details={'healthcheck_id': healthcheck_id},
    )


# DataSource Exceptions
class DataSourceError(AppError):
    """Base exception for datasource-related errors."""


class DataSourceValidationError(DataSourceError):
    """Raised when datasource validation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='DATASOURCE_VALIDATION_ERROR', details=details)


class DataSourceSnapshotError(DataSourceError):
    """Raised when an Iceberg snapshot operation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='DATASOURCE_SNAPSHOT_ERROR', details=details)


class DataSourceConnectionError(DataSourceError):
    """Raised when unable to connect to a datasource."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='DATASOURCE_CONNECTION_ERROR', details=details)


# Pipeline/Compute Exceptions
class PipelineError(AppError):
    """Base exception for pipeline-related errors."""


class PipelineValidationError(PipelineError):
    """Raised when pipeline validation fails."""

    def __init__(self, message: str, step_id: str | None = None, details: dict | None = None):
        details = details or {}
        if step_id:
            details['step_id'] = step_id
        super().__init__(message=message, error_code='PIPELINE_VALIDATION_ERROR', details=details)


class PipelineExecutionError(PipelineError):
    """Raised when pipeline execution fails."""

    def __init__(self, message: str, job_id: str | None = None, details: dict | None = None):
        details = details or {}
        if job_id:
            details['job_id'] = job_id
        super().__init__(message=message, error_code='PIPELINE_EXECUTION_ERROR', details=details)


# Compute/Engine Exceptions
class ComputeError(AppError):
    """Base exception for compute engine errors."""


class EngineStartError(ComputeError):
    """Raised when engine fails to start."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='ENGINE_START_ERROR', details=details)


class EngineBusyError(ComputeError):
    """Raised when an engine cannot accept the requested operation."""

    def __init__(self, analysis_id: str | None = None):
        details = {'analysis_id': analysis_id} if analysis_id is not None else None
        super().__init__(message='Engine has an active job', error_code='ENGINE_BUSY', details=details)


class EngineRunComparisonError(ComputeError):
    """Raised when engine runs cannot be compared."""

    def __init__(self, message: str, *, run_a_id: str | None = None, run_b_id: str | None = None, datasource_id: str | None = None):
        details: dict[str, str] = {}
        if run_a_id is not None:
            details['run_a_id'] = run_a_id
        if run_b_id is not None:
            details['run_b_id'] = run_b_id
        if datasource_id is not None:
            details['datasource_id'] = datasource_id
        super().__init__(message=message, error_code='ENGINE_RUN_COMPARISON_ERROR', details=details)


# Job Exceptions
class JobError(AppError):
    """Base exception for job-related errors."""


class JobCancelledError(JobError):
    """Raised when a job is cancelled."""

    def __init__(self, job_id: str):
        super().__init__(message=f'Job {job_id} was cancelled', error_code='JOB_CANCELLED', details={'job_id': job_id})


# Analysis Exceptions
class AnalysisError(AppError):
    """Base exception for analysis-related errors."""


class AnalysisValidationError(AnalysisError):
    """Raised when analysis validation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='ANALYSIS_VALIDATION_ERROR', details=details)


class AnalysisCycleError(AnalysisError):
    """Raised when a pipeline cycle is detected."""

    def __init__(self, message: str):
        super().__init__(message=message, error_code='ANALYSIS_CYCLE_ERROR', details={})


# File Exceptions
class FileError(AppError):
    """Base exception for file-related errors."""


class FileValidationError(FileError):
    """Raised when file validation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='FILE_VALIDATION_ERROR', details=details)


class FileSizeExceededError(FileError):
    """Raised when file size exceeds the limit."""

    def __init__(self, file_size: int, max_size: int):
        super().__init__(
            message=f'File size {file_size} bytes exceeds maximum allowed size {max_size} bytes',
            error_code='FILE_SIZE_EXCEEDED',
            details={'file_size': file_size, 'max_size': max_size},
        )


# Export Exceptions
class ExportError(AppError):
    """Base exception for export-related errors."""


class UnsupportedExportFormatError(ExportError):
    """Raised when an unsupported export format is requested."""

    def __init__(self, format: str):
        super().__init__(message=f'Unsupported export format: {format}', error_code='UNSUPPORTED_EXPORT_FORMAT', details={'format': format})


# Schedule Exceptions
class ScheduleError(AppError):
    """Base exception for schedule-related errors."""


class ScheduleValidationError(ScheduleError):
    """Raised when schedule validation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='SCHEDULE_VALIDATION_ERROR', details=details)


# UDF Exceptions
class UdfError(AppError):
    """Base exception for UDF-related errors."""


class UdfValidationError(UdfError):
    """Raised when UDF validation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='UDF_VALIDATION_ERROR', details=details)


# Healthcheck Exceptions
class HealthcheckError(AppError):
    """Base exception for healthcheck-related errors."""


class HealthcheckValidationError(HealthcheckError):
    """Raised when healthcheck validation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='HEALTHCHECK_VALIDATION_ERROR', details=details)


# Settings Exceptions
class SettingsError(AppError):
    """Base exception for settings-related errors."""


class SettingsConfigurationError(SettingsError):
    """Raised when a required setting is missing or invalid."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='SETTINGS_CONFIGURATION_ERROR', details=details)


# Validation Exceptions
class InvalidIdError(AppError):
    """Raised when an ID fails format validation."""

    def __init__(self, message: str = 'Invalid ID format', details: dict | None = None):
        super().__init__(message=message, error_code='INVALID_ID', details=details)
