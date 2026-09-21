import logging

from backend_core.error_handlers import _log_app_error
from backend_core.exceptions import PipelineExecutionCancelledError, PipelineExecutionError


def test_expected_engine_shutdown_cancellation_is_logged_without_traceback(caplog):
    cancellation = PipelineExecutionCancelledError('Compute request cancelled because its engine was shut down')

    with caplog.at_level(logging.INFO, logger='backend_core.error_handlers'):
        _log_app_error(cancellation, status=500)

    record = caplog.records[-1]
    assert record.levelno == logging.INFO
    assert record.exc_info is None


def test_pipeline_execution_failure_still_logs_as_error(caplog):
    failure = PipelineExecutionError('preview failed')

    with caplog.at_level(logging.INFO, logger='backend_core.error_handlers'):
        _log_app_error(failure, status=500)

    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
