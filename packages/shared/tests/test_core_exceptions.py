"""Tests for core exception handling."""

from core.exceptions import (
    AnalysisError,
    AnalysisNotFoundError,
    AnalysisValidationError,
    AppError,
    ComputeError,
    DataSourceError,
    DataSourceNotFoundError,
    DataSourceValidationError,
    FileError,
    FileSizeExceededError,
    JobError,
    JobNotFoundError,
    PipelineError,
)


class TestExceptions:
    """Test custom exception hierarchy."""

    def test_app_error_base(self):
        """Test base AppError."""
        exc = AppError(message='Test error', error_code='TEST_ERROR', details={'field': 'value'})

        assert str(exc) == 'Test error'
        assert exc.message == 'Test error'
        assert exc.error_code == 'TEST_ERROR'
        assert exc.details == {'field': 'value'}

    def test_datasource_error(self):
        """Test DataSourceError."""
        exc = DataSourceError(message='DataSource error', error_code='DATASOURCE_ERROR')

        assert str(exc) == 'DataSource error'
        assert exc.error_code == 'DATASOURCE_ERROR'

    def test_datasource_not_found_error(self):
        """Test DataSourceNotFoundError."""
        exc = DataSourceNotFoundError(datasource_id='ds-123')

        assert 'ds-123' in str(exc)
        assert exc.error_code == 'DATASOURCE_NOT_FOUND'
        assert exc.details['datasource_id'] == 'ds-123'

    def test_datasource_validation_error(self):
        """Test DataSourceValidationError."""
        exc = DataSourceValidationError(message='Validation failed', details={'field': 'name'})

        assert str(exc) == 'Validation failed'
        assert exc.error_code == 'DATASOURCE_VALIDATION_ERROR'
        assert exc.details == {'field': 'name'}

    def test_analysis_error(self):
        """Test AnalysisError."""
        exc = AnalysisError(message='Analysis failed', error_code='ANALYSIS_FAILED')

        assert str(exc) == 'Analysis failed'
        assert exc.error_code == 'ANALYSIS_FAILED'

    def test_analysis_not_found_error(self):
        """Test AnalysisNotFoundError."""
        exc = AnalysisNotFoundError(analysis_id='analysis-123')

        assert 'analysis-123' in str(exc)
        assert exc.error_code == 'ANALYSIS_NOT_FOUND'

    def test_compute_error(self):
        """Test ComputeError."""
        exc = ComputeError(message='Compute job failed', error_code='COMPUTE_FAILED', details={'job_id': '123'})

        assert str(exc) == 'Compute job failed'
        assert exc.error_code == 'COMPUTE_FAILED'
        assert exc.details == {'job_id': '123'}

    def test_pipeline_error(self):
        """Test PipelineError."""
        exc = PipelineError(message='Pipeline failed', error_code='PIPELINE_FAILED')

        assert str(exc) == 'Pipeline failed'
        assert exc.error_code == 'PIPELINE_FAILED'

    def test_job_not_found_error(self):
        """Test JobNotFoundError."""
        exc = JobNotFoundError(job_id='job-123')

        assert 'job-123' in str(exc)
        assert exc.error_code == 'JOB_NOT_FOUND'
        assert exc.details['job_id'] == 'job-123'

    def test_exception_with_none_details(self):
        """Test exception with None details."""
        exc = AppError(message='Test', error_code='TEST', details=None)

        assert exc.details == {}

    def test_exception_with_empty_details(self):
        """Test exception with empty details."""
        exc = AppError(message='Test', error_code='TEST', details={})

        assert exc.details == {}

    def test_exception_inheritance(self):
        """Test that all custom exceptions inherit from AppError."""
        assert issubclass(DataSourceError, AppError)
        assert issubclass(AnalysisError, AppError)
        assert issubclass(ComputeError, AppError)
        assert issubclass(PipelineError, AppError)
        assert issubclass(JobError, AppError)
        assert issubclass(FileError, AppError)

    def test_exception_with_long_message(self):
        """Test exception with very long message."""
        long_message = 'A' * 1000
        exc = AppError(message=long_message, error_code='LONG_ERROR')

        assert len(str(exc)) == 1000

    def test_exception_with_complex_details(self):
        """Test exception with nested details."""
        details = {
            'error': 'validation_failed',
            'fields': {'name': ['required', 'min_length'], 'email': ['invalid_format']},
            'context': {'user_id': 123, 'timestamp': '2024-01-01T00:00:00Z'},
        }

        exc = AnalysisValidationError(message='Multiple validation errors', details=details)

        assert exc.details == details
        assert exc.details['fields']['name'] == ['required', 'min_length']

    def test_file_size_exceeded_error(self):
        """Test FileSizeExceededError."""
        exc = FileSizeExceededError(file_size=1000000, max_size=500000)

        assert '1000000' in str(exc)
        assert '500000' in str(exc)
        assert exc.error_code == 'FILE_SIZE_EXCEEDED'
        assert exc.details['file_size'] == 1000000
        assert exc.details['max_size'] == 500000
