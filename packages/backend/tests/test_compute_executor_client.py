from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime
from functools import partial
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

import modules.compute.executor_client as executor_client
from backend_core import compute_requests_service
from backend_core.compute_response_recovery import ComputeResponseRecovery
from backend_core.dependencies import RuntimeAvailabilityProbe
from backend_core.domain.compute.schemas import AnalysisPipelinePayload, DownloadRequest
from backend_core.exceptions import ClientDisconnectedError
from dataforge_protocol import compute_pb2, enums_pb2


class _DisconnectedRequest:
    checks = 0

    async def is_disconnected(self) -> bool:
        self.checks += 1
        await asyncio.sleep(0)
        return self.checks >= 2


@pytest.mark.asyncio
async def test_json_response_serializes_model_and_preserves_headers() -> None:
    class Payload(BaseModel):
        value: str = Field(alias='publicValue')
        created_at: datetime

    payload = Payload(publicValue='ready', created_at=datetime(2026, 9, 26, 12, 0))

    response = await executor_client.json_response(
        payload,
        headers={'ETag': '"analysis-1-2"'},
    )

    assert response.media_type == 'application/json'
    assert response.body == b'{"publicValue":"ready","created_at":"2026-09-26T12:00:00"}'
    assert response.headers['ETag'] == '"analysis-1-2"'

    sync_response = executor_client.json_response_sync(
        payload,
        headers={'ETag': '"analysis-1-2"'},
    )
    assert sync_response.body == response.body
    assert sync_response.headers['ETag'] == response.headers['ETag']

    list_response = await executor_client.json_response([payload])
    assert list_response.body == b'[{"publicValue":"ready","created_at":"2026-09-26T12:00:00"}]'


@pytest.mark.asyncio
async def test_compute_wait_detects_disconnect_without_a_response_wakeup(monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled = asyncio.Event()
    monkeypatch.setattr(executor_client, '_HTTP_DISCONNECT_POLL_SECONDS', 0.001)

    async def never_wake(_request_id: str, _last_seen: int) -> int:
        try:
            await asyncio.Future()
            raise AssertionError('compute response wake unexpectedly arrived')
        finally:
            cancelled.set()

    monkeypatch.setattr(executor_client.response_recovery, 'wait_for_wake', never_wake)
    request = _DisconnectedRequest()

    with pytest.raises(ClientDisconnectedError):
        await executor_client._wait_for_response_or_disconnect('request-1', 0, cast(Request, request))

    assert request.checks >= 2
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_download_step_initializes_data_plane_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    factory_threads: list[int] = []
    operation_threads: list[int] = []

    class DataPlane:
        def classify_object_url(self, _path: str) -> SimpleNamespace:
            operation_threads.append(threading.get_ident())
            return SimpleNamespace(is_object_store=True)

        def download_object_bytes(self, _path: str) -> bytes:
            operation_threads.append(threading.get_ident())
            return b'artifact'

        def delete_object(self, _path: str) -> None:
            operation_threads.append(threading.get_ident())

    def create_data_plane() -> DataPlane:
        factory_threads.append(threading.get_ident())
        return DataPlane()

    async def request_command(*_args, **_kwargs) -> object:
        return object()

    async def submit_and_wait(*_args, **_kwargs) -> SimpleNamespace:
        return SimpleNamespace(
            artifact_path='s3://bucket/result.parquet',
            artifact_name='result.parquet',
            artifact_content_type='application/octet-stream',
        )

    monkeypatch.setattr(executor_client, 'client_from_settings', create_data_plane)
    monkeypatch.setattr(executor_client, '_request_command', request_command)
    monkeypatch.setattr(executor_client, '_submit_and_wait', submit_and_wait)

    request = DownloadRequest(
        target_step_id='source',
        analysis_pipeline=AnalysisPipelinePayload.model_validate(
            {
                'analysis_id': 'analysis-1',
                'tabs': [
                    {
                        'id': 'tab-1',
                        'datasource': {'id': 'datasource-1', 'analysis_tab_id': None, 'config': {'branch': 'master'}},
                        'output': {'result_id': 'result-1', 'filename': 'result.csv', 'format': 'csv'},
                        'steps': [],
                    }
                ],
            }
        ),
    )
    result = await executor_client.download_step(
        cast(Session, None),
        request,
        runtime_probe=cast(RuntimeAvailabilityProbe, None),
    )

    assert result == (b'artifact', 'result.parquet', 'application/octet-stream')
    assert factory_threads and all(thread_id != loop_thread for thread_id in factory_threads)
    assert operation_threads and all(thread_id != loop_thread for thread_id in operation_threads)


@pytest.mark.asyncio
async def test_slow_terminal_compute_request_logs_http_and_durable_ids(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    staged = SimpleNamespace(id='durable-request-1', namespace='tenant-a', engine_resource_id=None)
    completed = SimpleNamespace(status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED)
    clock_values = iter((100.0, 106.0, 106.1))

    async def register(_request_id: str, _namespace: str) -> None:
        return None

    async def unregister(_request_id: str) -> None:
        return None

    monkeypatch.setattr(executor_client, 'get_namespace', lambda: 'tenant-a')
    monkeypatch.setattr(executor_client, '_stage_validated_request_in_new_session', lambda **_kwargs: staged)
    monkeypatch.setattr(executor_client, '_read_request_in_new_session', lambda *_args: completed)
    monkeypatch.setattr(executor_client.response_recovery, 'register', register)
    monkeypatch.setattr(executor_client.response_recovery, 'unregister', unregister)
    monkeypatch.setattr(executor_client, 'time', SimpleNamespace(monotonic=lambda: next(clock_values, 106.1)))
    request = cast(Request, SimpleNamespace(scope={'state': {'request_id': 'http-request-1'}}))

    with caplog.at_level('WARNING', logger='modules.compute.executor_client'):
        result = await executor_client._submit_and_wait(
            cast(Session, None),
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=compute_pb2.ComputeCommand(),
            runtime_probe=cast(RuntimeAvailabilityProbe, None),
            http_request=request,
        )

    assert result is completed
    assert 'durable_request_id=durable-request-1' in caplog.text
    assert 'http_request_id=http-request-1' in caplog.text
    assert 'namespace=tenant-a' in caplog.text


@pytest.mark.asyncio
async def test_failed_compute_request_logs_correlation_and_error_code(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    staged = SimpleNamespace(id='durable-request-2', namespace='tenant-a', engine_resource_id=None)
    failed = SimpleNamespace(status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED)

    async def register(_request_id: str, _namespace: str) -> None:
        return None

    async def unregister(_request_id: str) -> None:
        return None

    monkeypatch.setattr(executor_client, 'get_namespace', lambda: 'tenant-a')
    monkeypatch.setattr(executor_client, '_stage_validated_request_in_new_session', lambda **_kwargs: staged)
    monkeypatch.setattr(executor_client, '_read_request_in_new_session', lambda *_args: failed)
    monkeypatch.setattr(
        executor_client.compute_requests_service,
        'response_payload',
        lambda _request: {
            'error': 'The preview failed',
            'status_code': 500,
            'error_code': 'PIPELINE_EXECUTION_ERROR',
        },
    )
    monkeypatch.setattr(executor_client.response_recovery, 'register', register)
    monkeypatch.setattr(executor_client.response_recovery, 'unregister', unregister)
    request = cast(Request, SimpleNamespace(scope={'state': {'request_id': 'http-request-2'}}))

    with caplog.at_level('WARNING', logger='modules.compute.executor_client'), pytest.raises(HTTPException) as exc_info:
        await executor_client._submit_and_wait(
            cast(Session, None),
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=compute_pb2.ComputeCommand(),
            runtime_probe=cast(RuntimeAvailabilityProbe, None),
            http_request=request,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == 'The preview failed'
    assert 'durable_request_id=durable-request-2' in caplog.text
    assert 'http_request_id=http-request-2' in caplog.text
    assert 'error_code=PIPELINE_EXECUTION_ERROR' in caplog.text


@pytest.mark.asyncio
async def test_local_recovery_delivers_batched_terminal_state_without_another_db_read(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request_id = 'durable-request-local-recovery'
    staged = SimpleNamespace(id=request_id, namespace='tenant-a', engine_resource_id=None)
    pending = SimpleNamespace(status=enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
    completed = compute_requests_service.TerminalComputeRequest(
        id=request_id,
        kind=int(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW),
        status=int(enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED),
        response_envelope=b'completed-response',
        error_message=None,
        artifact_path=None,
        artifact_name=None,
        artifact_content_type=None,
    )
    read_lock = threading.Lock()
    read_count = 0

    def read_request(*_args) -> SimpleNamespace | compute_requests_service.TerminalComputeRequest:
        nonlocal read_count
        with read_lock:
            read_count += 1
            return pending if read_count == 1 else completed

    recovery = ComputeResponseRecovery(
        poll_seconds=0.01,
        poll_namespace=lambda _namespace, _request_ids: [completed],
    )
    stop_event = asyncio.Event()
    recovery_task = asyncio.create_task(recovery.run(stop_event))
    monkeypatch.setattr(executor_client, 'get_namespace', lambda: 'tenant-a')
    monkeypatch.setattr(executor_client, '_stage_validated_request_in_new_session', lambda **_kwargs: staged)
    monkeypatch.setattr(executor_client, '_read_request_in_new_session', read_request)
    monkeypatch.setattr(executor_client, 'response_recovery', recovery)

    async def is_disconnected() -> bool:
        return False

    request = cast(
        Request,
        SimpleNamespace(
            scope={'state': {'request_id': 'http-request-local-recovery'}},
            is_disconnected=is_disconnected,
        ),
    )

    try:
        with caplog.at_level('DEBUG'):
            result = await asyncio.wait_for(
                executor_client._submit_and_wait(
                    cast(Session, None),
                    kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                    command=compute_pb2.ComputeCommand(),
                    runtime_probe=cast(RuntimeAvailabilityProbe, None),
                    http_request=request,
                ),
                timeout=2.0,
            )
    finally:
        stop_event.set()
        await recovery_task

    assert result is completed
    assert read_count == 1
    assert f'process_id={os.getpid()}' in caplog.text
    assert 'Compute response waiter woke' in caplog.text
    assert 'wake_wait_ms=' in caplog.text
    assert f'request_id={request_id}' in caplog.text


@pytest.mark.asyncio
async def test_shared_flight_wait_skips_per_viewer_disconnect_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    request_id = 'shared-preview-request'
    staged = SimpleNamespace(id=request_id, namespace='default', engine_resource_id='analysis-1')
    running = SimpleNamespace(status=enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
    completed = compute_requests_service.TerminalComputeRequest(
        id=request_id,
        kind=int(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW),
        status=int(enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED),
        response_envelope=b'completed-response',
        error_message=None,
        artifact_path=None,
        artifact_name=None,
        artifact_content_type=None,
    )

    class Recovery:
        def __init__(self) -> None:
            self.terminal: compute_requests_service.TerminalComputeRequest | None = None
            self.wait_started = asyncio.Event()
            self.wake = asyncio.Event()

        async def register(self, _request_id: str, _namespace: str) -> None:
            return None

        async def unregister(self, _request_id: str) -> None:
            return None

        async def wake_version(self, _request_id: str) -> int:
            return 0

        async def terminal_request(self, _request_id: str):
            return self.terminal

        async def wait_for_wake(self, _request_id: str, last_seen: int) -> int:
            self.wait_started.set()
            await self.wake.wait()
            self.terminal = completed
            return last_seen + 1

    recovery = Recovery()

    def unexpected_disconnect_poll(*_args, **_kwargs):
        raise AssertionError('shared-flight viewers must wait on durable completion, not poll HTTP disconnect')

    monkeypatch.setattr(executor_client, 'get_namespace', lambda: 'default')
    monkeypatch.setattr(executor_client, '_stage_validated_request_in_new_session', lambda **_kwargs: staged)
    monkeypatch.setattr(executor_client, '_read_request_in_new_session', lambda *_args: running)
    monkeypatch.setattr(executor_client, 'response_recovery', recovery)
    monkeypatch.setattr(executor_client, '_wait_for_response_or_disconnect', unexpected_disconnect_poll)
    request = cast(Request, SimpleNamespace(scope={'state': {'request_id': 'http-viewer-1'}}))

    waiter = asyncio.create_task(
        executor_client._submit_and_wait(
            cast(Session, None),
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=compute_pb2.ComputeCommand(),
            runtime_probe=cast(RuntimeAvailabilityProbe, None),
            http_request=request,
        )
    )
    await recovery.wait_started.wait()
    recovery.wake.set()

    assert await waiter is completed


@pytest.mark.asyncio
async def test_cancelling_a_shared_flight_waiter_does_not_cancel_the_durable_request(monkeypatch: pytest.MonkeyPatch) -> None:
    request_id = 'shared-preview-cancelled-viewer'
    staged = SimpleNamespace(id=request_id, namespace='default', engine_resource_id='analysis-1')
    running = SimpleNamespace(status=enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)

    class Recovery:
        def __init__(self) -> None:
            self.wait_started = asyncio.Event()

        async def register(self, _request_id: str, _namespace: str) -> None:
            return None

        async def unregister(self, _request_id: str) -> None:
            return None

        async def wake_version(self, _request_id: str) -> int:
            return 0

        async def terminal_request(self, _request_id: str):
            return None

        async def wait_for_wake(self, _request_id: str, _last_seen: int) -> int:
            self.wait_started.set()
            return await asyncio.Future[int]()

    recovery = Recovery()

    def unexpected_cancel(*_args, **_kwargs):
        raise AssertionError('a shared-flight follower cannot retire the durable request')

    monkeypatch.setattr(executor_client, 'get_namespace', lambda: 'default')
    monkeypatch.setattr(executor_client, '_stage_validated_request_in_new_session', lambda **_kwargs: staged)
    monkeypatch.setattr(executor_client, '_read_request_in_new_session', lambda *_args: running)
    monkeypatch.setattr(executor_client, 'response_recovery', recovery)
    monkeypatch.setattr(executor_client, '_cancel_disconnected_request_in_new_session', unexpected_cancel)
    request = cast(Request, SimpleNamespace(scope={'state': {'request_id': 'http-viewer-2'}}))

    waiter = asyncio.create_task(
        executor_client._submit_and_wait(
            cast(Session, None),
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=compute_pb2.ComputeCommand(),
            runtime_probe=cast(RuntimeAvailabilityProbe, None),
            http_request=request,
        )
    )
    await recovery.wait_started.wait()
    waiter.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiter


@pytest.mark.asyncio
async def test_shared_flight_lock_wait_retries_without_blocking_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    staged = object()

    def try_stage(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise compute_requests_service.ComputeFlightLockBusy('another viewer is staging this command')
        return staged

    monkeypatch.setattr(executor_client, '_stage_validated_request_in_new_session', try_stage)

    stage = partial(
        executor_client._stage_validated_request_in_new_session,
        namespace='default',
        pipeline=None,
        datasource_ids=(),
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=compute_pb2.ComputeCommand(),
        runtime_probe=cast(RuntimeAvailabilityProbe, None),
    )

    task = asyncio.create_task(executor_client._stage_shared_request_without_waiting_on_a_database_lock(stage))
    event_loop_ticks = 0

    while not task.done():
        event_loop_ticks += 1
        await asyncio.sleep(0.001)

    assert await task is staged
    assert attempts == 3
    assert event_loop_ticks > 0
