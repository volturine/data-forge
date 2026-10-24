import json
import logging

import pytest
from fastapi import FastAPI
from starlette.requests import ClientDisconnect, Request

from backend_core.error_handlers import app_error_handler, client_disconnect_handler, handle_errors
from backend_core.exceptions import AppError, ClientDisconnectedError, PipelineExecutionCancelledError, PipelineExecutionError
from tests.http_client import TestClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('error', 'expected_status', 'expected_level'),
    [
        pytest.param(PipelineExecutionCancelledError('Compute worker stopped', job_id='job-1'), 409, logging.INFO, id='typed-shutdown-cancellation'),
        pytest.param(PipelineExecutionError('Preview failed', job_id='job-1'), 500, logging.ERROR, id='execution-failure'),
        pytest.param(
            AppError('Queued input changed', error_code='STALE_COMPUTE_INPUT', details={'datasource_id': 'ds-1'}), 409, logging.INFO, id='stale-input'
        ),
        pytest.param(AppError('Worker stopped', error_code='JOB_CANCELLED', details={'operation': 'preview'}), 409, logging.INFO, id='worker-cancellation'),
    ],
)
async def test_app_errors_preserve_response_status_details_and_log_severity(
    error: AppError,
    expected_status: int,
    expected_level: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger='backend_core.error_handlers'):
        response = await app_error_handler(Request({'type': 'http'}), error)

    assert response.status_code == expected_status
    assert json.loads(bytes(response.body)) == {
        'detail': error.message,
        'error_code': error.error_code,
        'details': error.details,
    }
    record = caplog.records[-1]
    assert record.levelno == expected_level
    assert (record.exc_info is not None) == (expected_status >= 500)


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
