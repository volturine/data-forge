from __future__ import annotations

import asyncio
import contextvars
import os
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from functools import partial
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from backend_core import compute_requests_service, runtime_workers_service
from backend_core.api_execution_budget import (
    BoundedThreadPoolExecutor,
    install_api_blocking_executor,
    remove_api_blocking_executor,
)
from backend_core.compute_response_recovery import ComputeResponseRecovery
from backend_core.database import run_settings_db
from backend_core.domain.compute.schemas import AnalysisPipelinePayload, DownloadRequest
from backend_core.domain.compute_requests.models import command_envelope
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.exceptions import AppError, ClientDisconnectedError
from backend_core.time import utc_now
from dataforge_protocol import compute_pb2, enums_pb2
from modules.compute import executor_client


class _DisconnectedRequest:
    checks = 0

    async def is_disconnected(self) -> bool:
        self.checks += 1
        await asyncio.sleep(0)
        return self.checks >= 2


@pytest.mark.asyncio
async def test_compute_serialization_executor_waits_for_capacity_and_releases_queued_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = BoundedThreadPoolExecutor(max_workers=1, max_pending=1, thread_name_prefix='serialization-admission-test')
    monkeypatch.setattr(executor_client, '_COMPUTE_SERIALIZATION_EXECUTOR', executor)
    started = threading.Event()
    release = threading.Event()

    def block() -> str:
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError('serialization admission test was not released')
        return 'running'

    first = asyncio.create_task(executor_client._run_compute_serialization(block))
    second: asyncio.Task[str] | None = None
    replacement: asyncio.Task[str] | None = None
    waiting: asyncio.Task[str] | None = None
    try:
        assert await asyncio.to_thread(started.wait, 1)
        second = asyncio.create_task(executor_client._run_compute_serialization(lambda: 'cancelled'))
        await asyncio.sleep(0.02)
        waiting = asyncio.create_task(executor_client._run_compute_serialization(lambda: 'waiting'))
        await asyncio.sleep(0)
        assert not waiting.done()

        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        replacement = asyncio.create_task(executor_client._run_compute_serialization(lambda: 'replacement'))
        release.set()
        assert await first == 'running'
        assert await asyncio.wait_for(waiting, timeout=2) == 'waiting'
        assert await asyncio.wait_for(replacement, timeout=2) == 'replacement'
    finally:
        release.set()
        for task in (first, second, replacement, waiting):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second, replacement, waiting) if task is not None), return_exceptions=True)
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_compute_serialization_preserves_contextvars(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = BoundedThreadPoolExecutor(max_workers=1, max_pending=1, thread_name_prefix='serialization-context-test')
    monkeypatch.setattr(executor_client, '_COMPUTE_SERIALIZATION_EXECUTOR', executor)
    request_context = contextvars.ContextVar('request_context', default='missing')
    token = request_context.set('tenant-context')
    try:
        result = await executor_client._run_compute_serialization(request_context.get)
        assert result == 'tenant-context'
    finally:
        request_context.reset(token)
        executor.shutdown(wait=True, cancel_futures=True)


def _staged_request(
    request_id: str,
    namespace: str,
    command: compute_pb2.ComputeCommand,
    *,
    compute_worker_resource_id: str | None = None,
) -> SimpleNamespace:
    kind = enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW
    envelope = command_envelope(
        kind=kind,
        request_id=request_id,
        command=command,
    )
    return SimpleNamespace(
        id=request_id,
        namespace=namespace,
        kind=kind,
        compute_worker_resource_id=compute_worker_resource_id,
        command_envelope=envelope.SerializeToString(),
    )


@pytest.mark.asyncio
async def test_json_response_serializes_model_and_preserves_headers() -> None:
    class Payload(BaseModel):
        value: str = Field(alias='publicValue')
        created_at: datetime

    payload = Payload(publicValue='ready', created_at=datetime(2026, 9, 26, 12, 0))

    loop = asyncio.get_running_loop()
    executor = BoundedThreadPoolExecutor(max_workers=1, max_pending=1, thread_name_prefix='json-response-test')
    install_api_blocking_executor(loop, executor, 1, max_pending=1)
    try:
        response = await executor_client.json_response(
            payload,
            headers={'ETag': '"analysis-1-2"'},
        )

        assert response.media_type == 'application/json'
        assert response.body == b'{"publicValue":"ready","created_at":"2026-09-26T12:00:00"}'
        assert response.headers['ETag'] == '"analysis-1-2"'

        list_response = await executor_client.json_response([payload])
        assert list_response.body == b'[{"publicValue":"ready","created_at":"2026-09-26T12:00:00"}]'
    finally:
        remove_api_blocking_executor(loop)
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_json_response_does_not_consume_compute_serialization_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = BoundedThreadPoolExecutor(max_workers=1, max_pending=0, thread_name_prefix='compute-serialization-saturated-test')
    monkeypatch.setattr(executor_client, '_COMPUTE_SERIALIZATION_EXECUTOR', executor)
    started = threading.Event()
    release = threading.Event()

    def block_compute_serialization() -> None:
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError('compute serialization test was not released')

    blocked = executor.submit(block_compute_serialization)
    loop = asyncio.get_running_loop()
    api_executor = BoundedThreadPoolExecutor(max_workers=1, max_pending=0, thread_name_prefix='json-response-api-test')
    install_api_blocking_executor(loop, api_executor, 1, max_pending=0)
    try:
        assert await asyncio.to_thread(started.wait, 1)
        response = await asyncio.wait_for(executor_client.json_response({'ready': True}), timeout=1)
        assert response.body == b'{"ready":true}'
    finally:
        release.set()
        blocked.result(timeout=1)
        remove_api_blocking_executor(loop)
        api_executor.shutdown(wait=True, cancel_futures=True)
        executor.shutdown(wait=True, cancel_futures=True)


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

    async def submit_and_wait(**_kwargs) -> SimpleNamespace:
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
        request,
    )

    assert result == (b'artifact', 'result.parquet', 'application/octet-stream')
    assert factory_threads and all(thread_id != loop_thread for thread_id in factory_threads)
    assert operation_threads and all(thread_id != loop_thread for thread_id in operation_threads)


@pytest.mark.asyncio
async def test_slow_terminal_compute_request_logs_http_and_durable_ids(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    command = compute_pb2.ComputeCommand()
    staged = _staged_request('durable-request-1', 'tenant-a', command)
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
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=command,
            http_request=request,
        )

    assert result is completed
    assert 'durable_request_id=durable-request-1' in caplog.text
    assert 'http_request_id=http-request-1' in caplog.text
    assert 'namespace=tenant-a' in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        'response_payload',
        'expected_exception',
        'expected_level',
        'expected_verb',
    ),
    [
        pytest.param(
            {
                'error': 'The preview failed',
                'status_code': 500,
                'error_code': 'PIPELINE_EXECUTION_ERROR',
            },
            AppError,
            'WARNING',
            'failed',
            id='compute-failure',
        ),
        pytest.param(
            {'error': executor_client._COMPUTE_WORKER_SHUTDOWN_CANCELLATION},
            executor_client.PipelineExecutionCancelledError,
            'INFO',
            'cancelled',
            id='expected-engine-shutdown-cancellation',
        ),
        pytest.param(
            {
                'error': executor_client._COMPUTE_WORKER_SHUTDOWN_CANCELLATION,
                'status_code': 500,
                'error_code': 'PIPELINE_EXECUTION_ERROR',
            },
            AppError,
            'WARNING',
            'failed',
            id='explicit-error-status-takes-precedence',
        ),
    ],
)
async def test_failed_compute_request_logs_correlation_and_error_code(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    response_payload: dict[str, object],
    expected_exception: type[AppError],
    expected_level: str,
    expected_verb: str,
) -> None:
    command = compute_pb2.ComputeCommand()
    staged = _staged_request('durable-request-2', 'tenant-a', command)
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
        lambda _request: response_payload,
    )
    monkeypatch.setattr(executor_client.response_recovery, 'register', register)
    monkeypatch.setattr(executor_client.response_recovery, 'unregister', unregister)
    request = cast(Request, SimpleNamespace(scope={'state': {'request_id': 'http-request-2'}}))

    with caplog.at_level('INFO', logger='modules.compute.executor_client'), pytest.raises(expected_exception) as exc_info:
        await executor_client._submit_and_wait(
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=command,
            http_request=request,
        )

    assert type(exc_info.value) is expected_exception
    assert exc_info.value.message == response_payload['error']
    durable_request_logs = [record for record in caplog.records if 'Durable compute request' in record.getMessage()]
    assert len(durable_request_logs) == 1
    record = durable_request_logs[0]
    log_message = record.getMessage()
    assert record.levelname == expected_level
    assert f'Durable compute request {expected_verb} ' in log_message
    assert 'durable_request_id=durable-request-2' in log_message
    assert 'http_request_id=http-request-2' in log_message
    assert f'kind={enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW}' in log_message
    assert 'namespace=tenant-a' in log_message
    assert f'status_code={response_payload.get("status_code", "-")}' in log_message
    assert f'error_code={response_payload.get("error_code", "-")}' in log_message
    if expected_verb == 'failed':
        assert exc_info.value.error_code == response_payload['error_code']


@pytest.mark.asyncio
async def test_local_recovery_delivers_batched_terminal_state_without_another_db_read(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request_id = 'durable-request-local-recovery'
    command = compute_pb2.ComputeCommand()
    staged = _staged_request(request_id, 'tenant-a', command)
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
                    kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                    command=command,
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
    command = compute_pb2.ComputeCommand()
    staged = _staged_request(request_id, 'default', command, compute_worker_resource_id='analysis-1')
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
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=command,
            http_request=request,
        )
    )
    await recovery.wait_started.wait()
    recovery.wake.set()

    assert await waiter is completed


@pytest.mark.asyncio
async def test_cancelling_a_shared_flight_waiter_does_not_cancel_the_durable_request(monkeypatch: pytest.MonkeyPatch) -> None:
    request_id = 'shared-preview-cancelled-viewer'
    command = compute_pb2.ComputeCommand()
    staged = _staged_request(request_id, 'default', command, compute_worker_resource_id='analysis-1')
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
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=command,
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
    )

    task = asyncio.create_task(executor_client._stage_shared_request_without_waiting_on_a_database_lock(stage))
    event_loop_ticks = 0

    while not task.done():
        event_loop_ticks += 1
        await asyncio.sleep(0.001)

    assert await task is staged
    assert attempts == 3
    assert event_loop_ticks > 0


_COMPUTE_UNAVAILABLE = 'Compute is unavailable right now; try again shortly.'


def _staged_upload(**kwargs) -> SimpleNamespace:
    envelope = command_envelope(kind=kwargs['kind'], request_id='upload-request-1', command=kwargs['command'])
    return SimpleNamespace(
        id='upload-request-1',
        namespace=kwargs['namespace'],
        kind=kwargs['kind'],
        compute_worker_resource_id=None,
        command_envelope=envelope.SerializeToString(),
    )


async def _create_uploaded_file_datasource():
    return await executor_client.create_file_datasource(
        name='upload',
        description=None,
        file_path='s3://uploads/upload.csv',
        file_type='csv',
    )


def _install_upload_wait(monkeypatch: pytest.MonkeyPatch, state: dict[str, object]) -> list[dict[str, object]]:
    staged_calls: list[dict[str, object]] = []

    def stage(**kwargs):
        staged_calls.append(kwargs)
        return _staged_upload(**kwargs)

    async def register(_request_id: str, _namespace: str) -> None:
        return None

    async def unregister(_request_id: str) -> None:
        return None

    async def terminal_request(_request_id: str):
        return None

    async def never_wake(_request_id: str, _last_seen: int) -> int:
        # No worker manager claims or answers this request, so no wake arrives.
        await asyncio.Future()
        raise AssertionError('upload response wake unexpectedly arrived')

    monkeypatch.setattr(executor_client, 'get_namespace', lambda: 'default')
    monkeypatch.setattr(executor_client, '_stage_validated_request_in_new_session', stage)
    monkeypatch.setattr(executor_client, '_read_request_in_new_session', lambda *_args: SimpleNamespace(status=state['status']))
    monkeypatch.setattr(executor_client.response_recovery, 'register', register)
    monkeypatch.setattr(executor_client.response_recovery, 'unregister', unregister)
    monkeypatch.setattr(executor_client.response_recovery, 'terminal_request', terminal_request)
    monkeypatch.setattr(executor_client.response_recovery, 'wait_for_wake', never_wake)
    return staged_calls


def _register_worker_manager(*, heartbeat_age: timedelta, stopped: bool = False) -> None:
    worker_id = 'worker-manager:upload-admission-test'
    seen_at = utc_now() - heartbeat_age
    run_settings_db(
        runtime_workers_service.register_worker,
        worker_id=worker_id,
        kind=RuntimeWorkerKind.COORDINATOR,
        hostname='worker-host',
        pid=1,
        capacity=1,
        now=seen_at,
    )
    if stopped:
        run_settings_db(runtime_workers_service.mark_worker_stopped, worker_id=worker_id, now=seen_at)


async def _execute_upload_preflight():
    return await executor_client.execute_excel_preflight(
        preflight_id='upload-request-1',
        source_path='s3://uploads/upload.xlsx',
        action=enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL,
        selection={'sheet_name': 'Sheet1'},
        delete_source=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'manager',
    [
        pytest.param(None, id='no-worker-manager'),
        pytest.param({'heartbeat_age': timedelta(minutes=24)}, id='stale-heartbeat-not-stopped'),
        pytest.param({'heartbeat_age': timedelta(minutes=24), 'stopped': True}, id='stopped-long-ago-worker-manager'),
    ],
)
@pytest.mark.parametrize('submit_upload', [_create_uploaded_file_datasource, _execute_upload_preflight], ids=['file-create', 'excel-preflight'])
async def test_upload_admission_fails_fast_without_a_live_worker_manager(
    monkeypatch: pytest.MonkeyPatch, manager: dict[str, Any] | None, submit_upload: Callable[[], Awaitable[object]]
) -> None:
    if manager is not None:
        _register_worker_manager(**manager)
    staged_calls = _install_upload_wait(monkeypatch, {'status': enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED})

    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(submit_upload(), timeout=5)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == _COMPUTE_UNAVAILABLE
    # Callers keep their inputs for a retry on this typed refusal.
    assert isinstance(exc_info.value, executor_client.ComputeUnavailableError)
    assert staged_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'manager',
    [
        pytest.param({'heartbeat_age': timedelta(seconds=1)}, id='live-worker-manager'),
        # A generation restart or takeover stops the row, reconciles, then
        # re-registers before its warm-reserve wait.
        pytest.param({'heartbeat_age': timedelta(seconds=20), 'stopped': True}, id='restarting-worker-manager'),
    ],
)
async def test_upload_admission_queues_behind_a_live_or_restarting_worker_manager(monkeypatch: pytest.MonkeyPatch, manager: dict[str, Any]) -> None:
    _register_worker_manager(**manager)
    staged_calls = _install_upload_wait(monkeypatch, {'status': enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED})
    created = object()

    async def validated_response(_model, _completed):
        return created

    monkeypatch.setattr(executor_client, '_validated_response', validated_response)

    assert await asyncio.wait_for(_create_uploaded_file_datasource(), timeout=5) is created
    assert len(staged_calls) == 1


@pytest.mark.asyncio
async def test_upload_admission_keeps_waiting_while_a_busy_worker_manager_is_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_worker_manager(heartbeat_age=timedelta(seconds=1))
    state: dict[str, object] = {'status': enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED}
    _install_upload_wait(monkeypatch, state)
    liveness_checks = 0
    has_recent_worker = runtime_workers_service.has_recent_worker
    created = object()

    def counted_liveness(session, **kwargs) -> bool:
        nonlocal liveness_checks
        liveness_checks += 1
        if liveness_checks == 4:
            # Every compute slot was busy for several rechecks; a slot frees and
            # the manager finishes the upload.
            state['status'] = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
        return has_recent_worker(session, **kwargs)

    def unexpected_retire(*_args, **_kwargs):
        raise AssertionError('a queued upload inside the queue bound must not be retired while a worker manager is live')

    async def validated_response(_model, _completed):
        return created

    monkeypatch.setattr(executor_client.runtime_workers_service, 'has_recent_worker', counted_liveness)
    monkeypatch.setattr(executor_client, '_COMPUTE_ADMISSION_RECHECK_SECONDS', 0.02)
    monkeypatch.setattr(executor_client, '_retire_unclaimed_request_in_new_session', unexpected_retire)
    monkeypatch.setattr(executor_client, '_validated_response', validated_response)

    assert await asyncio.wait_for(_create_uploaded_file_datasource(), timeout=5) is created
    # One admission check, then rechecks that each found the manager live.
    assert liveness_checks == 4


@pytest.mark.asyncio
async def test_upload_admission_retires_an_unclaimed_request_once_the_worker_manager_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_worker_manager(heartbeat_age=timedelta(seconds=1))
    state: dict[str, object] = {'status': enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED}
    staged_calls = _install_upload_wait(monkeypatch, state)
    retired: list[str] = []
    stage = executor_client._stage_validated_request_in_new_session

    def stage_then_lose_manager(**kwargs):
        staged = stage(**kwargs)
        # The manager dies after admission and stays silent past the liveness window.
        _register_worker_manager(heartbeat_age=timedelta(minutes=24), stopped=True)
        return staged

    monkeypatch.setattr(executor_client, '_stage_validated_request_in_new_session', stage_then_lose_manager)

    def retire(request_id: str, _namespace: str, *, retire_queued: bool):
        assert retire_queued is True
        retired.append(request_id)
        state['status'] = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
        return SimpleNamespace(id=request_id)

    monkeypatch.setattr(executor_client, '_COMPUTE_ADMISSION_RECHECK_SECONDS', 0.05)
    monkeypatch.setattr(executor_client, '_retire_unclaimed_request_in_new_session', retire)

    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(_create_uploaded_file_datasource(), timeout=5)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == _COMPUTE_UNAVAILABLE
    # A retired create raises the same typed refusal, so confirm keeps its preflight.
    assert isinstance(exc_info.value, executor_client.ComputeUnavailableError)
    assert len(staged_calls) == 1
    assert retired == ['upload-request-1']


@pytest.mark.asyncio
async def test_upload_admission_retires_claimed_work_once_its_lease_expires_under_a_heartbeating_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The manager claimed the upload, then its event loop stalled: the
    # heartbeat thread keeps the registration fresh, but nothing renews the
    # claim's lease and no response wake ever arrives.
    _register_worker_manager(heartbeat_age=timedelta(seconds=1))
    state: dict[str, object] = {'status': enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING}
    staged_calls = _install_upload_wait(monkeypatch, state)
    retire_attempts: list[bool] = []

    def retire(request_id: str, _namespace: str, *, retire_queued: bool):
        retire_attempts.append(retire_queued)
        if len(retire_attempts) == 1:
            # The claim's lease has not expired yet; the row stays untouched.
            return None
        state['status'] = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
        return SimpleNamespace(id=request_id)

    monkeypatch.setattr(executor_client, '_COMPUTE_ADMISSION_RECHECK_SECONDS', 0.02)
    monkeypatch.setattr(executor_client, '_retire_unclaimed_request_in_new_session', retire)

    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(_create_uploaded_file_datasource(), timeout=5)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == _COMPUTE_UNAVAILABLE
    assert isinstance(exc_info.value, executor_client.ComputeUnavailableError)
    assert len(staged_calls) == 1
    # Only the expired lease retired it; the live heartbeat kept queued work exempt.
    assert retire_attempts == [False, False]


@pytest.mark.asyncio
async def test_upload_admission_retires_work_left_unclaimed_past_the_queue_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    # The registration keeps heartbeating, but nothing ever claims the upload.
    _register_worker_manager(heartbeat_age=timedelta(seconds=1))
    state: dict[str, object] = {'status': enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED}
    staged_calls = _install_upload_wait(monkeypatch, state)
    retire_attempts: list[bool] = []

    def retire(request_id: str, _namespace: str, *, retire_queued: bool):
        retire_attempts.append(retire_queued)
        state['status'] = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
        return SimpleNamespace(id=request_id)

    monkeypatch.setattr(executor_client, '_COMPUTE_ADMISSION_RECHECK_SECONDS', 0.02)
    monkeypatch.setattr(executor_client, '_COMPUTE_ADMISSION_QUEUE_SECONDS', 0.1)
    monkeypatch.setattr(executor_client, '_retire_unclaimed_request_in_new_session', retire)

    started = asyncio.get_running_loop().time()
    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(_create_uploaded_file_datasource(), timeout=5)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == _COMPUTE_UNAVAILABLE
    assert isinstance(exc_info.value, executor_client.ComputeUnavailableError)
    assert asyncio.get_running_loop().time() - started >= 0.1
    assert len(staged_calls) == 1
    assert retire_attempts == [True]


@pytest.mark.asyncio
async def test_upload_admission_deadline_does_not_cut_off_claimed_work(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_worker_manager(heartbeat_age=timedelta(seconds=1))
    statuses = iter(
        (
            enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
            enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
            enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
        )
    )
    reads: list[int] = []
    created = object()

    def read_request(*_args):
        reads.append(next(statuses))
        return SimpleNamespace(status=reads[-1])

    async def wake_after_claim(_request_id: str, last_seen: int) -> int:
        if reads[-1] == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED:
            # A claim does not publish a response wake.
            await asyncio.Future()
        await asyncio.sleep(0.1)
        return last_seen + 1

    async def validated_response(_model, _completed):
        return created

    retire_attempts: list[bool] = []

    def retire_spared_by_live_lease(_request_id: str, _namespace: str, *, retire_queued: bool):
        # The row lock finds the claim's lease live, so the row stays running.
        retire_attempts.append(retire_queued)

    _install_upload_wait(monkeypatch, {'status': enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED})
    monkeypatch.setattr(executor_client, '_read_request_in_new_session', read_request)
    monkeypatch.setattr(executor_client.response_recovery, 'wait_for_wake', wake_after_claim)
    monkeypatch.setattr(executor_client, '_validated_response', validated_response)
    monkeypatch.setattr(executor_client, '_COMPUTE_ADMISSION_RECHECK_SECONDS', 0.05)
    monkeypatch.setattr(executor_client, '_retire_unclaimed_request_in_new_session', retire_spared_by_live_lease)

    assert await asyncio.wait_for(_create_uploaded_file_datasource(), timeout=5) is created
    assert len(reads) == 3
    # The claimed request was only checked for an expired lease.
    assert retire_attempts == [False]
