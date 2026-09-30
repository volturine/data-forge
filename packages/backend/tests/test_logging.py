import asyncio
import logging
import logging.handlers
import queue
import threading
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import cast

import psycopg
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

from backend_core import logging as backend_logging
from backend_core.logging import DatabaseLogKind, DatabaseLogWriter, RequestLoggingMiddleware, RequestTimingMiddleware, redact_logged_body
from tests.http_client import TestClient


class TestLoggingRedaction:
    def test_redacts_settings_request_secret_fields(self) -> None:
        body = '{"smtp_password":"pw","telegram_bot_token":"bot","openrouter_api_key":"sk"}'
        redacted = redact_logged_body('/api/v1/settings', body)
        assert redacted == '{"smtp_password": "[REDACTED]", "telegram_bot_token": "[REDACTED]", "openrouter_api_key": "[REDACTED]"}'

    def test_redacts_chat_and_auth_secret_fields(self) -> None:
        body = '{"api_key":"sk-test","password":"pw","current_password":"old","new_password":"new"}'
        redacted = redact_logged_body('/api/v1/ai/chat/sessions', body)
        assert '[REDACTED]' in str(redacted)
        assert 'sk-test' not in str(redacted)
        assert '"password": "[REDACTED]"' in str(redacted)

    def test_leaves_non_sensitive_paths_unchanged(self) -> None:
        body = '{"api_key":"sk-test","value":1}'
        assert redact_logged_body('/api/v1/config', body) == body

    def test_redacts_form_encoded_bodies_on_sensitive_paths(self) -> None:
        body = 'username=user@example.com&password=sup3rsecret&remember=true'
        redacted = redact_logged_body('/api/v1/auth/login', body)
        assert redacted == 'username=user%40example.com&password=%5BREDACTED%5D&remember=true'
        assert 'sup3rsecret' not in redacted

    def test_redacts_token_fields_in_form_encoded_bodies(self) -> None:
        body = 'telegram_bot_token=12345:ABC-DEF&chat_id=42'
        redacted = redact_logged_body('/api/v1/settings/notifications', body)
        assert redacted is not None
        assert '12345:ABC-DEF' not in redacted
        assert 'telegram_bot_token=%5BREDACTED%5D' in redacted
        assert 'chat_id=42' in redacted

    def test_leaves_non_form_non_json_body_unchanged_on_sensitive_path(self) -> None:
        body = 'plain text without pairs'
        assert redact_logged_body('/api/v1/auth/login', body) == body


def test_database_log_kind_marks_control_messages() -> None:
    assert DatabaseLogKind.FLUSH.is_control is True
    assert DatabaseLogKind.STOP.is_control is True
    assert DatabaseLogKind.REQUEST.is_control is False


def test_configure_logging_queues_console_writes_off_request_threads(monkeypatch) -> None:
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, 'handlers', [logging.StreamHandler()])
    monkeypatch.setattr(backend_logging, '_configured', False)
    monkeypatch.setattr(backend_logging, '_writer', None)
    monkeypatch.setattr(backend_logging, '_listener', None)

    class FakeWriter:
        def stop(self) -> None:
            pass

    writer = FakeWriter()
    listener_handlers: list[tuple[object, ...]] = []

    class CapturingListener:
        def __init__(self, _queue, *handlers, **_kwargs) -> None:
            self.handlers = handlers
            listener_handlers.append(handlers)

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    monkeypatch.setattr(backend_logging, 'DatabaseLogWriter', lambda **_kwargs: writer)
    monkeypatch.setattr(backend_logging, '_BoundedQueueListener', CapturingListener)
    monkeypatch.setattr(backend_logging.atexit, 'register', lambda _callback: None)

    backend_logging.configure_logging()

    assert len(root_logger.handlers) == 1
    assert isinstance(root_logger.handlers[0], logging.handlers.QueueHandler)
    log_queue = cast(queue.Queue[logging.LogRecord], root_logger.handlers[0].queue)
    assert log_queue.maxsize == backend_logging.settings.log_queue_max_size
    assert len(listener_handlers) == 1
    assert isinstance(listener_handlers[0][0], logging.StreamHandler)
    assert isinstance(listener_handlers[0][1], backend_logging.DatabaseLogHandler)


def test_queue_handler_defers_message_and_traceback_formatting_to_listener_thread() -> None:
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
    queue_handler = backend_logging._DeferredFormattingQueueHandler(log_queue)
    formatting_threads: list[int] = []
    finished = threading.Event()
    producer_thread = threading.get_ident()

    class DeferredValue:
        def __str__(self) -> str:
            formatting_threads.append(threading.get_ident())
            return 'payload'

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            self.format(record)
            finished.set()

    class TrackingFormatter(logging.Formatter):
        def formatException(self, exc_info) -> str:
            formatting_threads.append(threading.get_ident())
            return super().formatException(exc_info)

    capture_handler = CaptureHandler()
    capture_handler.setFormatter(TrackingFormatter('%(message)s'))
    listener = logging.handlers.QueueListener(log_queue, capture_handler)
    error = ValueError('expected test error')
    record = logging.LogRecord(
        name='test',
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg='request failed: %s',
        args=(DeferredValue(),),
        exc_info=(ValueError, error, None),
    )

    prepared = queue_handler.prepare(record)
    assert prepared is not record
    assert prepared.args is record.args
    assert prepared.exc_info is record.exc_info
    assert formatting_threads == []

    listener.start()
    try:
        queue_handler.emit(record)
        assert finished.wait(timeout=1.0)
    finally:
        listener.stop()

    assert formatting_threads
    assert all(thread_id != producer_thread for thread_id in formatting_threads)


def test_slow_logging_consumer_cannot_grow_outer_queue() -> None:
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=2)
    queue_handler = backend_logging._BoundedFormattingQueueHandler(log_queue)

    for index in range(10):
        queue_handler.emit(logging.LogRecord('test', logging.INFO, __file__, index, 'message %s', (index,), None))

    assert log_queue.qsize() == 2
    assert queue_handler.dropped == 8


def test_bounded_log_queue_reports_overflow_from_listener_thread() -> None:
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=1)
    queue_handler = backend_logging._BoundedFormattingQueueHandler(log_queue)
    output: list[str] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            output.append(record.getMessage())

    console = CaptureHandler()
    listener = backend_logging._BoundedQueueListener(log_queue, console, overflow_handler=queue_handler)
    queue_handler.emit(logging.LogRecord('test', logging.INFO, __file__, 1, 'queued', (), None))
    queue_handler.emit(logging.LogRecord('test', logging.INFO, __file__, 2, 'dropped', (), None))
    listener.handle(logging.LogRecord('test', logging.INFO, __file__, 3, 'consumed', (), None))

    assert output == ['consumed', 'Backend log queue overflow; dropped_total=1']


@pytest.mark.asyncio
async def test_configure_logging_off_loop_runs_database_setup_in_a_thread(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    setup_threads: list[int] = []
    writer = object()

    def configure() -> object:
        setup_threads.append(threading.get_ident())
        return writer

    monkeypatch.setattr(backend_logging, 'configure_logging', configure)

    assert await backend_logging.configure_logging_off_loop() is writer
    assert setup_threads
    assert setup_threads[0] != loop_thread


def test_shutdown_logging_drains_listener_before_closing_writer(monkeypatch) -> None:
    root_logger = logging.getLogger()
    queue_handler = logging.handlers.QueueHandler(queue.Queue())
    console_handler = logging.StreamHandler()
    calls = []

    class FakeListener:
        def stop(self) -> None:
            calls.append('listener')

    class FakeWriter:
        def stop(self) -> None:
            calls.append('writer')

    monkeypatch.setattr(root_logger, 'handlers', [queue_handler])
    monkeypatch.setattr(backend_logging, '_configured', True)
    monkeypatch.setattr(backend_logging, '_listener', FakeListener())
    monkeypatch.setattr(backend_logging, '_writer', FakeWriter())
    monkeypatch.setattr(backend_logging, '_queue_handler', queue_handler)
    monkeypatch.setattr(backend_logging, '_console_handler', console_handler)

    backend_logging.shutdown_logging()

    assert calls == ['listener', 'writer']
    assert queue_handler not in root_logger.handlers
    assert console_handler in root_logger.handlers


class _InMemoryWriter:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.written = threading.Event()

    def write_request_log(self, payload: dict) -> None:
        self.payloads.append(payload)
        self.written.set()

    def wait_for_write(self) -> None:
        assert self.written.wait(timeout=2), 'request log was not processed'


def test_database_log_writer_stop_flushes_pending_rows(postgres_container) -> None:
    writer = DatabaseLogWriter(postgres_container.url, flush_interval=60)
    writer.write_request_log(
        {
            'ts': '2026-01-01T00:00:00Z',
            'method': 'GET',
            'path': '/health',
            'status': 200,
            'duration_ms': 1.0,
            'request_id': 'req-1',
            'client_id': 'client-1',
            'user_agent': 'pytest',
            'ip': '127.0.0.1',
            'referer': None,
            'error': None,
            'request_json': None,
            'response_json': None,
            'chunk_index': 0,
        }
    )

    writer.stop()

    with psycopg.connect(postgres_container.url.replace('+psycopg', ''), autocommit=True) as connection:
        row = connection.execute("SELECT COUNT(*) FROM request_logs WHERE request_id = 'req-1'").fetchone()

    assert row is not None
    assert row[0] == 1


def test_database_log_writer_schema_initialization_is_safe_under_concurrent_startup(postgres_container) -> None:
    start = threading.Barrier(3)

    def make_writer() -> DatabaseLogWriter:
        start.wait(timeout=10)
        return DatabaseLogWriter(postgres_container.url, flush_interval=60)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(make_writer) for _ in range(2)]
        start.wait(timeout=10)
        writers = [future.result(timeout=20) for future in futures]

    for writer in writers:
        writer.stop()

    with psycopg.connect(postgres_container.url.replace('+psycopg', ''), autocommit=True) as connection:
        tables = connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('request_logs', 'app_logs', 'client_logs')"
        ).fetchone()

    assert tables is not None and tables[0] == 3


class TestRequestLoggingMiddleware:
    def test_body_disconnect_during_logging_does_not_escape_as_an_error(self) -> None:
        writer = _InMemoryWriter()
        app_called = False
        sent: list[dict] = []

        async def receive() -> dict[str, str]:
            return {'type': 'http.disconnect'}

        async def send(message: dict) -> None:
            sent.append(message)

        async def app(_scope: dict, _receive, _send) -> None:
            nonlocal app_called
            app_called = True

        middleware = RequestLoggingMiddleware(app, writer=writer)
        scope = {
            'type': 'http',
            'method': 'POST',
            'path': '/upload',
            'raw_path': b'/upload',
            'query_string': b'',
            'headers': [(b'content-length', b'8')],
            'scheme': 'http',
            'client': ('127.0.0.1', 1234),
            'server': ('testserver', 80),
        }

        asyncio.run(middleware(scope, receive, send))

        assert not app_called
        assert not sent
        assert not writer.payloads

    @pytest.mark.asyncio
    async def test_slow_request_log_writer_does_not_delay_response(self) -> None:
        writer_started = threading.Event()
        release_writer = threading.Event()

        class SlowWriter(_InMemoryWriter):
            def write_request_log(self, payload: dict) -> None:
                writer_started.set()
                if not release_writer.wait(timeout=5):
                    raise TimeoutError('test request log writer was not released')
                super().write_request_log(payload)

        writer = SlowWriter()
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        async def app(_scope, _receive, send_for_app) -> None:
            await send_for_app({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send_for_app({'type': 'http.response.body', 'body': b'ok', 'more_body': False})

        middleware = RequestLoggingMiddleware(app, writer=writer)
        scope = {
            'type': 'http',
            'method': 'GET',
            'path': '/api/fast-response',
            'raw_path': b'/api/fast-response',
            'query_string': b'',
            'headers': [],
            'scheme': 'http',
            'client': ('testclient', 1234),
            'server': ('testserver', 80),
        }
        request_task = asyncio.create_task(middleware(scope, receive, send))
        try:
            assert await asyncio.to_thread(writer_started.wait, 1)
            await asyncio.wait_for(request_task, timeout=0.2)
            assert sent[-1]['body'] == b'ok'
        finally:
            release_writer.set()
            await asyncio.gather(request_task, return_exceptions=True)

        writer.wait_for_write()

    def test_lazy_writer_initialization_runs_off_event_loop(self, monkeypatch) -> None:
        app = FastAPI()
        writer = _InMemoryWriter()
        setup_threads: list[int] = []
        route_threads: list[int] = []

        def get_writer() -> _InMemoryWriter:
            setup_threads.append(threading.get_ident())
            return writer

        monkeypatch.setattr(backend_logging, 'get_log_writer', get_writer)
        app.add_middleware(RequestLoggingMiddleware)

        @app.get('/lazy-writer')
        async def lazy_writer() -> dict[str, bool]:
            route_threads.append(threading.get_ident())
            return {'ok': True}

        with TestClient(app) as client:
            response = client.get('/lazy-writer')

        assert response.status_code == 200
        assert setup_threads
        assert route_threads
        assert setup_threads[0] != route_threads[0]
        writer.wait_for_write()
        assert len(writer.payloads) == 1

    def test_large_request_body_is_still_delivered_to_handler(self) -> None:
        app = FastAPI()
        writer = _InMemoryWriter()
        app.add_middleware(RequestLoggingMiddleware, writer=writer, max_body_size=4)

        @app.post('/echo')
        async def echo(request: Request) -> dict[str, int]:
            body = await request.body()
            return {'length': len(body)}

        with TestClient(app) as client:
            response = client.post('/echo', content=b'abcdefghij')

        assert response.status_code == 200
        assert response.json() == {'length': 10}
        writer.wait_for_write()
        assert len(writer.payloads) == 1
        assert writer.payloads[0]['request_json'] is None

    @pytest.mark.asyncio
    async def test_unknown_size_request_body_is_streamed_without_logging_buffer(self) -> None:
        writer = _InMemoryWriter()
        received: list[dict[str, object]] = []
        messages = iter(
            [
                {'type': 'http.request', 'body': b'first-', 'more_body': True},
                {'type': 'http.request', 'body': b'second', 'more_body': False},
            ]
        )

        async def receive() -> dict[str, object]:
            return next(messages)

        async def send(_message: dict[str, object]) -> None:
            return None

        async def app(_scope, receive_for_app, send_for_app) -> None:
            received.append(await receive_for_app())
            received.append(await receive_for_app())
            await send_for_app({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send_for_app({'type': 'http.response.body', 'body': b'ok', 'more_body': False})

        middleware = RequestLoggingMiddleware(app, writer=writer, max_body_size=1024)
        scope = {
            'type': 'http',
            'method': 'POST',
            'path': '/stream-upload',
            'raw_path': b'/stream-upload',
            'query_string': b'',
            'headers': [],
            'scheme': 'http',
            'client': ('testclient', 1234),
            'server': ('testserver', 80),
        }

        async def run() -> None:
            await middleware(scope, receive, send)

        await run()

        assert [message['body'] for message in received] == [b'first-', b'second']
        writer.wait_for_write()
        assert writer.payloads[0]['request_json'] is None

    def test_streaming_response_logs_single_entry(self) -> None:
        app = FastAPI()
        writer = _InMemoryWriter()
        app.add_middleware(RequestLoggingMiddleware, writer=writer, max_body_size=1024)

        @app.get('/stream')
        async def stream() -> StreamingResponse:
            async def generate() -> AsyncIterator[str]:
                yield 'a'
                yield 'b'

            return StreamingResponse(generate(), media_type='text/plain')

        with TestClient(app) as client:
            response = client.get('/stream')

        assert response.status_code == 200
        assert response.text == 'ab'
        writer.wait_for_write()
        assert len(writer.payloads) == 1
        assert writer.payloads[0]['path'] == '/stream'
        assert writer.payloads[0]['chunk_index'] == 0

    def test_frontend_asset_body_is_not_captured(self) -> None:
        app = FastAPI()
        writer = _InMemoryWriter()
        app.add_middleware(RequestLoggingMiddleware, writer=writer, max_body_size=0)

        @app.get('/_app/immutable/chunks/app.js')
        async def asset() -> Response:
            return Response(content=b'javascript' * 1000, media_type='text/javascript')

        with TestClient(app) as client:
            response = client.get('/_app/immutable/chunks/app.js')

        assert response.status_code == 200
        writer.wait_for_write()
        assert writer.payloads[0]['response_json'] is None

    def test_zero_body_limit_disables_body_capture(self) -> None:
        app = FastAPI()
        writer = _InMemoryWriter()
        app.add_middleware(RequestLoggingMiddleware, writer=writer, max_body_size=0)

        @app.post('/body')
        async def body(request: Request) -> Response:
            await request.body()
            return Response(content=b'body', media_type='text/plain')

        with TestClient(app) as client:
            response = client.post('/body', content=b'payload')

        assert response.status_code == 200
        writer.wait_for_write()
        assert writer.payloads[0]['request_json'] is None
        assert writer.payloads[0]['response_json'] is None

    def test_handler_can_observe_disconnect_after_logged_body_replay(self) -> None:
        writer = _InMemoryWriter()
        sent: list[dict] = []
        body_messages: Iterator[dict[str, object]] = iter(
            [
                {'type': 'http.request', 'body': b'', 'more_body': False},
                {'type': 'http.disconnect'},
            ]
        )

        async def receive() -> dict:
            return next(body_messages)

        async def send(message: dict) -> None:
            sent.append(message)

        async def app(scope: dict, receive_for_app, send_for_app) -> None:
            request = Request(scope, receive_for_app)
            await request.body()
            disconnected = await request.is_disconnected()
            status = 204 if disconnected else 200
            await send_for_app({'type': 'http.response.start', 'status': status, 'headers': []})
            await send_for_app({'type': 'http.response.body', 'body': b'', 'more_body': False})

        middleware = RequestLoggingMiddleware(app, writer=writer)
        scope = {
            'type': 'http',
            'method': 'POST',
            'path': '/disconnect',
            'raw_path': b'/disconnect',
            'query_string': b'',
            'headers': [(b'content-length', b'0')],
            'scheme': 'http',
            'client': ('127.0.0.1', 1234),
            'server': ('testserver', 80),
        }

        asyncio.run(middleware(scope, receive, send))

        assert sent[0]['status'] == 204
        writer.wait_for_write()
        assert writer.payloads[0]['status'] == 204

    def test_handler_can_check_disconnect_after_logged_body_while_connected(self) -> None:
        app = FastAPI()
        writer = _InMemoryWriter()
        app.add_middleware(RequestLoggingMiddleware, writer=writer)

        @app.post('/connected')
        async def connected(request: Request) -> dict[str, bool]:
            await request.body()
            return {'disconnected': await request.is_disconnected()}

        with TestClient(app) as client:
            response = client.post('/connected', content=b'{}')

        assert response.status_code == 200
        assert response.json() == {'disconnected': False}


def test_request_timing_middleware_marks_response_serialization_boundary(caplog, monkeypatch) -> None:
    app = FastAPI()
    timestamps = iter([0.0, 5.2, 5.3])

    @contextmanager
    def database_timing(metrics):
        yield
        metrics.update(sql_count=2, sql_ms=3.5, commit_ms=1.26)

    monkeypatch.setattr(backend_logging, 'database_statement_timing', database_timing)

    async def pool_snapshot() -> dict[str, object]:
        return {'settings_checkedout': 3}

    app.add_middleware(
        RequestTimingMiddleware,
        slow_request_seconds=5.0,
        get_time=lambda: next(timestamps, 5.3),
        pool_snapshot=pool_snapshot,
    )

    @app.get('/api/slow-json')
    async def slow_json() -> dict[str, str]:
        return {'status': 'ok'}

    with caplog.at_level('WARNING', logger='backend_core.logging'), TestClient(app) as client:
        response = client.get('/api/slow-json', headers={'x-request-id': 'timing-test'})

    assert response.status_code == 200
    assert response.headers['x-request-id'] == 'timing-test'
    assert response.headers['server-timing'] == 'app;dur=5200.0, api-db-admission;dur=0.0'
    assert 'phase=completed' in caplog.text
    assert 'response_start_ms=5200.0' in caplog.text
    assert 'db_sql_count=2 db_sql_ms=3.5 db_commit_ms=1.3' in caplog.text
    assert 'settings_checkedout' in caplog.text


def test_request_timing_middleware_exposes_accumulated_database_admission_wait() -> None:
    from backend_core.database import record_database_admission_wait

    app = FastAPI()
    timestamps = iter([0.0, 5.2, 5.3])
    app.add_middleware(RequestTimingMiddleware, get_time=lambda: next(timestamps, 5.3))

    @app.get('/api/admission-timing')
    async def admission_timing() -> dict[str, str]:
        record_database_admission_wait(12.5)
        record_database_admission_wait(25.0)
        return {'status': 'ok'}

    with TestClient(app) as client:
        response = client.get('/api/admission-timing')

    assert response.status_code == 200
    assert response.headers['server-timing'] == 'app;dur=5200.0, api-db-admission;dur=37.5'


def test_request_timing_middleware_logs_completed_duration_after_in_flight_warning(caplog) -> None:
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    async def slow_response(scope, receive_for_app, send_for_app) -> None:
        del scope, receive_for_app
        await asyncio.sleep(0.15)
        await send_for_app({'type': 'http.response.start', 'status': 200, 'headers': []})
        await asyncio.sleep(0.15)
        await send_for_app({'type': 'http.response.body', 'body': b'ok', 'more_body': False})

    middleware = RequestTimingMiddleware(slow_response, slow_request_seconds=0.1)
    scope = {
        'type': 'http',
        'method': 'GET',
        'path': '/api/slow',
        'headers': [],
    }

    with caplog.at_level('WARNING', logger='backend_core.logging'):
        asyncio.run(middleware(scope, receive, send))

    timing_logs = [record.getMessage() for record in caplog.records if 'Slow API request' in record.getMessage()]
    assert len(sent) == 2
    assert len(timing_logs) == 2
    assert 'phase=in_flight' in timing_logs[0]
    assert 'response_start_ms=-' in timing_logs[0]
    assert 'phase=completed' in timing_logs[1]
    assert 'status=200' in timing_logs[1]
    assert 'response_start_ms=' in timing_logs[1]
    assert 'response_stream_ms=' in timing_logs[1]


def test_slow_request_and_request_log_share_generated_request_id(monkeypatch) -> None:
    writer = _InMemoryWriter()
    sent: list[dict[str, object]] = []
    slow_request_logs: list[str] = []

    def capture_warning(message: str, *args: object) -> None:
        slow_request_logs.append(message % args)

    monkeypatch.setattr(backend_logging._logger, 'warning', capture_warning)

    async def receive() -> dict[str, object]:
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    async def app(_scope, _receive, send_for_app) -> None:
        await asyncio.sleep(0.15)
        await send_for_app({'type': 'http.response.start', 'status': 200, 'headers': [(b'content-type', b'application/json')]})
        await send_for_app({'type': 'http.response.body', 'body': b'{"ok":true}', 'more_body': False})

    logging_middleware = RequestLoggingMiddleware(app, writer=writer)
    timing_middleware = RequestTimingMiddleware(logging_middleware, slow_request_seconds=0.1)
    scope = {
        'type': 'http',
        'method': 'GET',
        'path': '/api/correlation',
        'raw_path': b'/api/correlation',
        'query_string': b'',
        'headers': [],
        'scheme': 'http',
        'client': ('testclient', 1234),
        'server': ('testserver', 80),
    }

    asyncio.run(timing_middleware(scope, receive, send))

    writer.wait_for_write()
    response_headers = dict(cast(list[tuple[bytes, bytes]], sent[0]['headers']))
    request_id = response_headers[b'x-request-id'].decode()
    assert request_id
    assert len(writer.payloads) == 1
    assert writer.payloads[0]['request_id'] == request_id
    assert any(f'request_id={request_id}' in message for message in slow_request_logs)
