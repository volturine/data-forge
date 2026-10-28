"""Custom exception hierarchy for the application."""

from dataforge_protocol import errors_pb2

ErrorCodeInput = str | None


def _coerce_error_code(error_code: ErrorCodeInput) -> int:
    if error_code is None:
        return errors_pb2.ERROR_CODE_UNSPECIFIED
    return errors_pb2.ErrorCode.Value(f'ERROR_CODE_{error_code}')


def _error_code_label(error_code: int) -> str:
    return errors_pb2.ErrorCode.Name(error_code).removeprefix('ERROR_CODE_')


class AppError(Exception):
    def __init__(self, message: str, error_code: ErrorCodeInput = None, details: dict | None = None):
        self.message = message
        self.error_code_value = _coerce_error_code(error_code)
        self.error_code = _error_code_label(self.error_code_value)
        self.details = details or {}
        super().__init__(message)


def datasource_not_found(datasource_id: str) -> AppError:
    return AppError(
        f'DataSource {datasource_id} not found',
        error_code='DATASOURCE_NOT_FOUND',
        details={'datasource_id': datasource_id},
    )


def compute_worker_run_not_found(run_id: str) -> AppError:
    return AppError(
        f'Compute worker run {run_id} not found',
        error_code='ENGINE_RUN_NOT_FOUND',
        details={'run_id': run_id},
    )


def analysis_not_found(analysis_id: str) -> AppError:
    return AppError(
        f'Analysis {analysis_id} not found',
        error_code='ANALYSIS_NOT_FOUND',
        details={'analysis_id': analysis_id},
    )


def analysis_version_not_found(analysis_id: str, version: int) -> AppError:
    return AppError(
        f'Analysis version {version} not found for analysis {analysis_id}',
        error_code='ANALYSIS_VERSION_NOT_FOUND',
        details={'analysis_id': analysis_id, 'version': version},
    )


def schedule_not_found(schedule_id: str) -> AppError:
    return AppError(
        f'Schedule {schedule_id} not found',
        error_code='SCHEDULE_NOT_FOUND',
        details={'schedule_id': schedule_id},
    )


def udf_not_found(udf_id: str) -> AppError:
    return AppError(
        f'UDF {udf_id} not found',
        error_code='UDF_NOT_FOUND',
        details={'udf_id': udf_id},
    )


def healthcheck_not_found(healthcheck_id: str) -> AppError:
    return AppError(
        f'Healthcheck {healthcheck_id} not found',
        error_code='HEALTHCHECK_NOT_FOUND',
        details={'healthcheck_id': healthcheck_id},
    )


class DataSourceValidationError(AppError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='DATASOURCE_VALIDATION_ERROR', details=details)


class DataSourceSnapshotError(AppError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='DATASOURCE_SNAPSHOT_ERROR', details=details)


class PipelineExecutionError(AppError):
    def __init__(self, message: str, job_id: str | None = None, details: dict | None = None):
        details = details or {}
        if job_id:
            details['job_id'] = job_id
        super().__init__(message=message, error_code='PIPELINE_EXECUTION_ERROR', details=details)


class ClientDisconnectedError(Exception):
    """The HTTP client left while a durable compute request was pending."""


class PipelineExecutionCancelledError(PipelineExecutionError):
    """A compute request ended because its engine was intentionally stopped."""


class ComputeWorkerRunComparisonError(AppError):
    def __init__(self, message: str, *, run_a_id: str | None = None, run_b_id: str | None = None, datasource_id: str | None = None):
        details: dict[str, str] = {}
        if run_a_id is not None:
            details['run_a_id'] = run_a_id
        if run_b_id is not None:
            details['run_b_id'] = run_b_id
        if datasource_id is not None:
            details['datasource_id'] = datasource_id
        super().__init__(message=message, error_code='ENGINE_RUN_COMPARISON_ERROR', details=details)


class AnalysisValidationError(AppError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='ANALYSIS_VALIDATION_ERROR', details=details)


class AnalysisCycleError(AppError):
    def __init__(self, message: str):
        super().__init__(message=message, error_code='ANALYSIS_CYCLE_ERROR', details={})


class ScheduleValidationError(AppError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='SCHEDULE_VALIDATION_ERROR', details=details)


class UdfValidationError(AppError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='UDF_VALIDATION_ERROR', details=details)


class HealthcheckValidationError(AppError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='HEALTHCHECK_VALIDATION_ERROR', details=details)


class SettingsConfigurationError(AppError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message=message, error_code='SETTINGS_CONFIGURATION_ERROR', details=details)


class InvalidIdError(AppError):
    def __init__(self, message: str = 'Invalid ID format', details: dict | None = None):
        super().__init__(message=message, error_code='INVALID_ID', details=details)
