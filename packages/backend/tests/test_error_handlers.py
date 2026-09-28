import logging

import pytest
from fastapi import FastAPI
from starlette.requests import ClientDisconnect

from backend_core.error_handlers import _log_app_error, client_disconnect_handler, handle_errors
from backend_core.exceptions import ClientDisconnectedError, PipelineExecutionCancelledError, PipelineExecutionError
from tests.http_client import TestClient


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


@pytest.mark.asyncio
async def test_client_disconnect_returns_without_an_asgi_traceback() -> None:
    @handle_errors(operation='preview step')
    async def endpoint():
        raise ClientDisconnectedError

    response = await endpoint()

    assert response.status_code == 499


@pytest.mark.asyncio
async def test_request_body_disconnect_is_not_logged_as_an_internal_error(caplog) -> None:
    app = FastAPI()
    app.add_exception_handler(ClientDisconnect, client_disconnect_handler)

    @app.get('/disconnect')
    async def disconnect():
        raise ClientDisconnect

    with caplog.at_level(logging.ERROR, logger='backend_core.error_handlers'), TestClient(app) as client:
        response = client.get('/disconnect')

    assert response.status_code == 499
    assert not caplog.records
