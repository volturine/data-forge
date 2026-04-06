"""Custom exception hierarchy for the application."""


class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str, error_code: str | None = None, details: dict | None = None):
        """Initialize the exception with message, error code, and optional details."""
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)


# DataSource Exceptions
class DataSourceError(AppError):
    """Base exception for datasource-related errors."""


class DataSourceNotFoundError(DataSourceError):
    """Raised when a datasource is not found."""

    def __init__(self, datasource_id: str):
        super().__init__(
            message=f'DataSource {datasource_id} not found',
            error_code='DATASOURCE_NOT_FOUND',
            details={'datasource_id': datasource_id},
        )


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


class StepNotFoundError(PipelineError):
    """Raised when a pipeline step is not found."""

    def __init__(self, step_id: str):
        super().__init__(
            message=f'Step with id {step_id} not found in pipeline',
            error_code='STEP_NOT_FOUND',
            details={'step_id': step_id},
        )


# Compute/Engine Exceptions
class ComputeError(AppError):
    """Base exception for compute engine errors."""


class EngineNotFoundError(ComputeError):
    """Raised when an engine is not found."""

    def __init__(self, analysis_id: str):
        super().__init__(
            message=f'Engine for analysis {analysis_id} not found',
            error_code='ENGINE_NOT_FOUND',
            details={'analysis_id': analysis_id},
        )


class EngineStartError(ComputeError):
    """Raised when engine fails to start."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='ENGINE_START_ERROR', details=details)


class EngineTimeoutError(ComputeError):
    """Raised when engine operation times out."""

    def __init__(self, message: str, timeout: int, details: dict | None = None):
        details = details or {}
        details['timeout_seconds'] = timeout
        super().__init__(message=message, error_code='ENGINE_TIMEOUT', details=details)


# Job Exceptions
class JobError(AppError):
    """Base exception for job-related errors."""


class JobNotFoundError(JobError):
    """Raised when a job is not found."""

    def __init__(self, job_id: str):
        super().__init__(
            message=f'Job {job_id} not found',
            error_code='JOB_NOT_FOUND',
            details={'job_id': job_id},
        )


class JobCancelledError(JobError):
    """Raised when a job is cancelled."""

    def __init__(self, job_id: str):
        super().__init__(
            message=f'Job {job_id} was cancelled',
            error_code='JOB_CANCELLED',
            details={'job_id': job_id},
        )


class JobTimeoutError(JobError):
    """Raised when a job times out."""

    def __init__(self, job_id: str, timeout: int):
        super().__init__(
            message=f'Job {job_id} timed out after {timeout} seconds',
            error_code='JOB_TIMEOUT',
            details={'job_id': job_id, 'timeout_seconds': timeout},
        )


# Analysis Exceptions
class AnalysisError(AppError):
    """Base exception for analysis-related errors."""


class AnalysisNotFoundError(AnalysisError):
    """Raised when an analysis is not found."""

    def __init__(self, analysis_id: str):
        super().__init__(
            message=f'Analysis {analysis_id} not found',
            error_code='ANALYSIS_NOT_FOUND',
            details={'analysis_id': analysis_id},
        )


class AnalysisValidationError(AnalysisError):
    """Raised when analysis validation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='ANALYSIS_VALIDATION_ERROR', details=details)


class AnalysisVersionNotFoundError(AnalysisError):
    """Raised when an analysis version is not found."""

    def __init__(self, analysis_id: str, version: int):
        super().__init__(
            message=f'Analysis version {version} not found for analysis {analysis_id}',
            error_code='ANALYSIS_VERSION_NOT_FOUND',
            details={'analysis_id': analysis_id, 'version': version},
        )


class AnalysisCycleError(AnalysisError):
    """Raised when a pipeline cycle is detected."""

    def __init__(self, message: str):
        super().__init__(message=message, error_code='ANALYSIS_CYCLE_ERROR', details={})


# File Exceptions
class FileError(AppError):
    """Base exception for file-related errors."""


class DataFileNotFoundError(FileError):
    """Raised when a file is not found."""

    def __init__(self, file_path: str):
        super().__init__(
            message=f'File not found: {file_path}',
            error_code='FILE_NOT_FOUND',
            details={'file_path': file_path},
        )


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
        super().__init__(
            message=f'Unsupported export format: {format}',
            error_code='UNSUPPORTED_EXPORT_FORMAT',
            details={'format': format},
        )


# Schedule Exceptions
class ScheduleError(AppError):
    """Base exception for schedule-related errors."""


class ScheduleValidationError(ScheduleError):
    """Raised when schedule validation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='SCHEDULE_VALIDATION_ERROR', details=details)


class ScheduleNotFoundError(ScheduleError):
    """Raised when a schedule is not found."""

    def __init__(self, schedule_id: str):
        super().__init__(
            message=f'Schedule {schedule_id} not found',
            error_code='SCHEDULE_NOT_FOUND',
            details={'schedule_id': schedule_id},
        )


class AuthError(AppError):
    """Base exception for authentication errors."""


class InvalidCredentialsError(AuthError):
    def __init__(self):
        super().__init__(message='Invalid email or password', error_code='INVALID_CREDENTIALS')


class EmailAlreadyExistsError(AuthError):
    def __init__(self):
        super().__init__(message='An account with this email already exists', error_code='EMAIL_EXISTS')


class SessionExpiredError(AuthError):
    def __init__(self):
        super().__init__(message='Session has expired', error_code='SESSION_EXPIRED')


class AccountDisabledError(AuthError):
    def __init__(self):
        super().__init__(message='Account is disabled', error_code='ACCOUNT_DISABLED')


class DefaultUserDeletionError(AuthError):
    def __init__(self):
        super().__init__(message='The default account cannot be deleted', error_code='DEFAULT_USER_DELETION_FORBIDDEN')


class ProviderUnlinkError(AuthError):
    def __init__(self, message: str = 'Cannot unlink the last login method'):
        super().__init__(message=message, error_code='PROVIDER_UNLINK_ERROR')


class OAuthError(AuthError):
    def __init__(self, message: str = 'OAuth authentication failed'):
        super().__init__(message=message, error_code='OAUTH_ERROR')


class TokenExpiredError(AuthError):
    def __init__(self):
        super().__init__(message='Token has expired', error_code='TOKEN_EXPIRED')


class TokenInvalidError(AuthError):
    def __init__(self):
        super().__init__(message='Token is invalid or already used', error_code='TOKEN_INVALID')


# UDF Exceptions
class UdfError(AppError):
    """Base exception for UDF-related errors."""


class UdfNotFoundError(UdfError):
    """Raised when a UDF is not found."""

    def __init__(self, udf_id: str):
        super().__init__(
            message=f'UDF {udf_id} not found',
            error_code='UDF_NOT_FOUND',
            details={'udf_id': udf_id},
        )


class UdfValidationError(UdfError):
    """Raised when UDF validation fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='UDF_VALIDATION_ERROR', details=details)


# Healthcheck Exceptions
class HealthcheckError(AppError):
    """Base exception for healthcheck-related errors."""


class HealthcheckNotFoundError(HealthcheckError):
    """Raised when a healthcheck is not found."""

    def __init__(self, healthcheck_id: str):
        super().__init__(
            message=f'Healthcheck {healthcheck_id} not found',
            error_code='HEALTHCHECK_NOT_FOUND',
            details={'healthcheck_id': healthcheck_id},
        )


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
