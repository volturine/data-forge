from __future__ import annotations

import asyncio
import atexit
import contextlib
import copy
import json
import logging
import logging.handlers
import queue
import threading
import time
import urllib.parse
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

import psycopg
from fastapi import Request
from psycopg import sql
from starlette.requests import ClientDisconnect

from backend_core.api_execution_budget import run_api_blocking
from backend_core.config import settings
from backend_core.database import database_statement_timing
from backend_core.domain.enums import DataForgeStrEnum
from backend_core.proxy import client_ip

_writer: DatabaseLogWriter | None = None
_listener: logging.handlers.QueueListener | None = None
_queue_handler: logging.handlers.QueueHandler | None = None
_console_handler: logging.Handler | None = None
_configured = False
_atexit_registered = False
_logging_lifecycle_lock = threading.RLock()
_LOG_RECORD_KEYS = set(logging.LogRecord('', 0, '', 0, '', (), None).__dict__.keys())
_LOG_SCHEMA_LOCK_KEY = int.from_bytes(b'DFLOGSCH', 'big', signed=True)
_logger = logging.getLogger('backend_core.logging')
_SENSITIVE_FIELDS = {
    'password',
    'smtp_password',
    'telegram_bot_token',
    'openrouter_api_key',
    'openai_api_key',
    'kaggle_api_key',
    'api_key',
    'authorization',
    'bot_token',
    'current_password',
    'new_password',
    'token',
}
_SENSITIVE_PATHS = ('/api/v1/auth', '/api/v1/settings', '/api/v1/ai/chat', '/api/v1/ai/models', '/api/v1/ai/test')
_REDACTED = '[REDACTED]'

# Request bodies and preview responses can be large enough for JSON parsing and
# redaction to become visible event-loop work. Keep diagnostics bounded and
# isolated from the default executor used by application handlers.
_REQUEST_LOG_WORKERS = 2
_REQUEST_LOG_EXECUTOR = ThreadPoolExecutor(max_workers=_REQUEST_LOG_WORKERS, thread_name_prefix='request-log')
_REQUEST_LOG_PENDING_SLOTS = threading.BoundedSemaphore(64)
_REQUEST_LOG_DROP_LOCK = threading.Lock()
_REQUEST_LOG_DROPPED = 0
_REQUEST_LOG_FUTURES_LOCK = threading.Lock()
_REQUEST_LOG_FUTURES: set[Future[Any]] = set()

# The SERVER-TIMING label and request-timing metric for each API lane measurement.
_LANE_TIMINGS = (
    ('api-bootstrap-admission', 'api_bootstrap_admission_wait_ms'),
    ('api-general-admission', 'api_general_admission_wait_ms'),
    ('api-bootstrap-executor-queue', 'api_bootstrap_executor_queue_ms'),
    ('api-general-executor-queue', 'api_general_executor_queue_ms'),
    ('api-bootstrap-work', 'api_bootstrap_work_ms'),
    ('api-general-work', 'api_general_work_ms'),
)


def _finish_request_log(future: Future[Any]) -> None:
    try:
        future.result()
    except Exception:
        _logger.exception('Request log preparation failed')
    finally:
        with _REQUEST_LOG_FUTURES_LOCK:
            _REQUEST_LOG_FUTURES.discard(future)
        _REQUEST_LOG_PENDING_SLOTS.release()


def flush_request_logs() -> None:
    """Wait for accepted request-log preparations before closing their writer."""
    while True:
        with _REQUEST_LOG_FUTURES_LOCK:
            pending = tuple(_REQUEST_LOG_FUTURES)
        if not pending:
            return
        wait(pending)


type AsgiMessage = dict[str, Any]
type AsgiReceive = Callable[[], Awaitable[AsgiMessage]]
type AsgiSend = Callable[[AsgiMessage], Awaitable[None]]
type AsgiApp = Callable[[dict[str, Any], AsgiReceive, AsgiSend], Awaitable[None]]
type _LogRow = tuple[object, ...]


class RequestLogWriter(Protocol):
    def write_request_log(self, payload: dict[str, Any]) -> None: ...


class DatabaseLogKind(DataForgeStrEnum):
    REQUEST = 'request_logs'
    APP = 'app_logs'
    CLIENT = 'client_logs'


# Inserted columns per log table; ``ts`` comes first so rows can be bucketed by day.
_LOG_COLUMNS: dict[DatabaseLogKind, tuple[str, ...]] = {
    DatabaseLogKind.REQUEST: (
        'ts',
        'method',
        'path',
        'status',
        'duration_ms',
        'request_id',
        'client_id',
        'user_agent',
        'ip',
        'referer',
        'error',
        'request_json',
        'response_json',
        'chunk_index',
    ),
    DatabaseLogKind.APP: ('ts', 'level', 'logger', 'message', 'module', 'func', 'line', 'extra_json'),
    DatabaseLogKind.CLIENT: ('ts', 'event', 'action', 'page', 'target', 'form_id', 'fields_json', 'client_id', 'session_id', 'meta_json'),
}


def _log_day(ts: object) -> str:
    """Get the date in the configured timezone for daily table partitioning."""
    tz = ZoneInfo(settings.timezone)
    moment = ts.astimezone(tz) if isinstance(ts, datetime) else datetime.now(tz)
    return moment.date().isoformat()


class DatabaseLogWriter:
    def __init__(self, database_url: str, *, flush_interval: float = 5.0, overflow_policy: str = 'block'):
        self._database_url = database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
        self._queue: queue.Queue[tuple[DatabaseLogKind, list[_LogRow]] | None] = queue.Queue(maxsize=settings.log_queue_max_size)
        self._flush_interval = flush_interval
        self._block_when_full = overflow_policy == 'block'
        self._drop_lock = threading.Lock()
        self._dropped_count = 0
        # Owned by the writer thread (and by ``stop`` after joining it).
        self._buffers: dict[tuple[DatabaseLogKind, str], list[_LogRow]] = {}
        self._insert_conn: psycopg.Connection | None = None
        self._create_tables()
        self._worker = threading.Thread(target=self._run, name='postgres-log-writer', daemon=True)
        self._worker.start()

    def _create_tables(self) -> None:
        with psycopg.connect(self._database_url, autocommit=True) as conn, conn.transaction(), conn.cursor() as cursor:
            # Every API process and the coordinator has a log writer. A
            # transaction-scoped lock makes their create-if-missing DDL
            # safe when the deployment starts against an empty database.
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (_LOG_SCHEMA_LOCK_KEY,))
            cursor.execute(
                """
                    CREATE TABLE IF NOT EXISTS request_logs (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL,
                        method TEXT,
                        path TEXT,
                        status INTEGER,
                        duration_ms DOUBLE PRECISION,
                        request_id TEXT,
                        client_id TEXT,
                        user_agent TEXT,
                        ip TEXT,
                        referer TEXT,
                        error TEXT,
                        request_json TEXT,
                        response_json TEXT,
                        chunk_index INTEGER,
                        day DATE NOT NULL
                    )
                    """
            )
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_request_day ON request_logs(day)')
            cursor.execute(
                """
                    CREATE TABLE IF NOT EXISTS app_logs (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL,
                        level TEXT,
                        logger TEXT,
                        message TEXT,
                        module TEXT,
                        func TEXT,
                        line INTEGER,
                        extra_json TEXT,
                        day DATE NOT NULL
                    )
                    """
            )
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_app_day ON app_logs(day)')
            cursor.execute(
                """
                    CREATE TABLE IF NOT EXISTS client_logs (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL,
                        event TEXT,
                        action TEXT,
                        page TEXT,
                        target TEXT,
                        form_id TEXT,
                        fields_json TEXT,
                        client_id TEXT,
                        session_id TEXT,
                        meta_json TEXT,
                        day DATE NOT NULL
                    )
                    """
            )
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_client_day ON client_logs(day)')

    def write_request_log(self, payload: dict[str, Any]) -> None:
        # Never block request processing behind a full diagnostics queue;
        # losing a low-value request log is preferable to making the API
        # unavailable.
        self._enqueue(DatabaseLogKind.REQUEST, [payload], allow_block=False)

    def write_app_log(self, payload: dict[str, Any]) -> None:
        self._enqueue(DatabaseLogKind.APP, [payload])

    def write_client_logs(self, payloads: list[dict[str, Any]]) -> None:
        # Client telemetry can also arrive directly from an HTTP handler.
        self._enqueue(DatabaseLogKind.CLIENT, payloads, allow_block=False)

    def stop(self) -> None:
        self._queue.put(None)
        self._worker.join()
        if self._insert_conn is not None:
            with contextlib.suppress(Exception):
                self._insert_conn.close()
            self._insert_conn = None

    def _enqueue(self, kind: DatabaseLogKind, payloads: list[dict[str, Any]], *, allow_block: bool = True) -> None:
        if not payloads:
            return
        rows = [tuple(payload.get(column) for column in _LOG_COLUMNS[kind]) for payload in payloads]
        if self._block_when_full and allow_block:
            self._queue.put((kind, rows))
            return
        try:
            self._queue.put_nowait((kind, rows))
        except queue.Full:
            with self._drop_lock:
                self._dropped_count += len(rows)
                dropped = self._dropped_count
            if dropped % 100 == 1:
                _logger.warning(f'Log queue full, dropped {dropped} rows total')

    def _run(self) -> None:
        flush_at: float | None = None
        stopping = False
        while not stopping:
            timeout = None if flush_at is None else max(0.0, flush_at - time.monotonic())
            with contextlib.suppress(queue.Empty):
                item = self._queue.get(timeout=timeout)
                stopping = item is None
                if item is not None:
                    kind, rows = item
                    for row in rows:
                        self._buffers.setdefault((kind, _log_day(row[0])), []).append(row)
                    if flush_at is None and self._flush_interval > 0:
                        flush_at = time.monotonic() + self._flush_interval
            if stopping or (flush_at is not None and time.monotonic() >= flush_at):
                batches, self._buffers = self._buffers, {}
                for (kind, day), rows in batches.items():
                    self._insert_rows(kind, day, rows)
                flush_at = None

    def _insert_rows(self, kind: DatabaseLogKind, day: str, rows: list[_LogRow]) -> None:
        columns = (*_LOG_COLUMNS[kind], 'day')
        statement = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
            sql.Identifier(kind.value),
            sql.SQL(', ').join(map(sql.Identifier, columns)),
            sql.SQL(', ').join(sql.Placeholder() * len(columns)),
        )
        try:
            # Reuse one persistent connection for log inserts: opening one per
            # flush batch produced connection storms under load. It is
            # re-established after failures.
            if self._insert_conn is None or self._insert_conn.closed:
                self._insert_conn = psycopg.connect(self._database_url, autocommit=False)
            with self._insert_conn.cursor() as cursor:
                cursor.executemany(statement, [(*row, day) for row in rows])
            self._insert_conn.commit()
        except Exception as e:
            if self._insert_conn is not None:
                with contextlib.suppress(Exception):
                    self._insert_conn.close()
            self._insert_conn = None
            _logger.error(f'Failed to insert {len(rows)} rows to {kind.value}/{day}: {e}', exc_info=True)


class DatabaseLogHandler(logging.Handler):
    def __init__(self, writer: DatabaseLogWriter):
        super().__init__()
        self.writer = writer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            extras = {key: value for key, value in record.__dict__.items() if key not in _LOG_RECORD_KEYS and key != 'message'}
            self.writer.write_app_log(
                {
                    'ts': datetime.now(UTC),
                    'level': record.levelname,
                    'logger': record.name,
                    'message': record.getMessage(),
                    'module': record.module,
                    'func': record.funcName,
                    'line': record.lineno,
                    'extra_json': record.__dict__.get('extra_json') or (json.dumps(extras, default=str) if extras else None),
                }
            )
        except Exception:
            self.handleError(record)


class _BoundedFormattingQueueHandler(logging.handlers.QueueHandler):
    """Queue records without formatting them on request loops or waiting for a slow listener.

    This queue is process-local and consumed by ``QueueListener`` in a thread,
    so records do not need the eager stringification that multiprocessing
    queues require.
    """

    def __init__(self, log_queue: queue.Queue[logging.LogRecord]) -> None:
        super().__init__(log_queue)
        self._dropped = 0
        self._reported_dropped = 0
        self._drop_lock = threading.Lock()

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return copy.copy(record)

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            with self._drop_lock:
                self._dropped += 1

    def take_drop_report(self) -> int | None:
        """Return the drop total when it reaches a new power of two."""
        with self._drop_lock:
            dropped = self._dropped
            if dropped == 0 or dropped & (dropped - 1) != 0 or dropped == self._reported_dropped:
                return None
            self._reported_dropped = dropped
            return dropped


class _BoundedQueueListener(logging.handlers.QueueListener):
    def __init__(
        self,
        log_queue: queue.Queue[logging.LogRecord],
        *handlers: logging.Handler,
        overflow_handler: _BoundedFormattingQueueHandler,
    ) -> None:
        super().__init__(log_queue, *handlers)
        self._overflow_handler = overflow_handler

    def handle(self, record: logging.LogRecord) -> None:
        super().handle(record)
        dropped = self._overflow_handler.take_drop_report()
        if dropped is not None:
            report = logging.LogRecord(
                'backend_core.logging',
                logging.WARNING,
                __file__,
                0,
                'Backend log queue overflow; dropped_total=%s',
                (dropped,),
                None,
            )
            self.handlers[0].handle(report)

    def enqueue_sentinel(self) -> None:
        # Shutdown runs from the atexit hook; wait for space so accepted log
        # records drain before the listener exits.
        log_queue = cast(queue.Queue[logging.LogRecord | None], self.queue)
        log_queue.put(None)


def _metric_ms(metrics: dict[str, object], name: str) -> float:
    value = metrics.get(name, 0.0)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for header_name, value in headers:
        if header_name.lower() == name:
            return value.decode('latin-1')
    return None


class RequestTimingMiddleware:
    """Report API requests that can threaten the Uvicorn worker heartbeat.

    ``http.response.start`` is emitted after FastAPI has run the endpoint and
    serialized its response. Keeping that timestamp separate from the final
    body send makes a slow route/Pydantic response distinguishable from a slow
    client or response stream. The middleware never writes diagnostics to the
    database synchronously.
    """

    def __init__(
        self,
        app: AsgiApp,
        *,
        slow_request_seconds: float = 5.0,
        pool_snapshot: Callable[[], Awaitable[dict[str, object]]] | None = None,
        get_time: Callable[[], float] | None = None,
    ) -> None:
        self.app = app
        self.slow_request_seconds = max(float(slow_request_seconds), 0.1)
        self.pool_snapshot = pool_snapshot
        self.get_time = get_time or time.perf_counter

    async def __call__(self, scope: dict[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        path = str(scope.get('path') or '')
        is_api_or_health = path == '/api' or path.startswith('/api/') or path == '/health' or path.startswith('/health/')
        if scope.get('type') != 'http' or not is_api_or_health:
            await self.app(scope, receive, send)
            return

        start = self.get_time()
        response_started_at: float | None = None
        response_status: int | None = None
        state = scope.setdefault('state', {})
        request_id = state.get('request_id') or _header_value(scope.get('headers') or [], b'x-request-id') or uuid.uuid4().hex
        state['request_id'] = request_id
        database_metrics: dict[str, object] = {}

        async def report_in_flight_request() -> None:
            await asyncio.sleep(self.slow_request_seconds)
            await self._log_slow_request(
                scope,
                phase='in_flight',
                request_id=request_id,
                response_status=response_status,
                start=start,
                response_started_at=response_started_at,
                observed_at=self.get_time(),
                database_metrics=database_metrics,
            )

        slow_task = asyncio.create_task(report_in_flight_request())

        async def send_wrapper(message: AsgiMessage) -> None:
            nonlocal response_started_at, response_status
            if message['type'] == 'http.response.start':
                response_started_at = self.get_time()
                response_status = int(message['status'])
                headers = [(name, value) for name, value in message.get('headers', []) if name.lower() not in {b'x-request-id', b'server-timing'}]
                headers.append((b'x-request-id', request_id.encode('latin-1')))
                server_timing = ', '.join(
                    [
                        f'app;dur={max(0.0, (response_started_at - start) * 1000):.1f}',
                        f'api-blocking-admission;dur={_metric_ms(database_metrics, "api_blocking_admission_wait_ms"):.1f}',
                        *(f'{label};dur={_metric_ms(database_metrics, metric):.1f}' for label, metric in _LANE_TIMINGS),
                    ]
                )
                headers.append((b'server-timing', server_timing.encode('ascii')))
                message = {**message, 'headers': headers}
            await send(message)

        try:
            with database_statement_timing(database_metrics):
                await self.app(scope, receive, send_wrapper)
        finally:
            slow_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await slow_task
            completed_at = self.get_time()
            if completed_at - start >= self.slow_request_seconds:
                await self._log_slow_request(
                    scope,
                    phase='completed',
                    request_id=request_id,
                    response_status=response_status,
                    start=start,
                    response_started_at=response_started_at,
                    observed_at=completed_at,
                    database_metrics=database_metrics,
                )

    async def _log_slow_request(
        self,
        scope: dict[str, Any],
        *,
        phase: str,
        request_id: str,
        response_status: int | None,
        start: float,
        response_started_at: float | None,
        observed_at: float,
        database_metrics: dict[str, object],
    ) -> None:
        pool = {}
        if self.pool_snapshot is not None:
            # Pool diagnostics are best-effort and must not replace the response.
            with contextlib.suppress(Exception):
                pool = await self.pool_snapshot()
        response_start = '-' if response_started_at is None else f'{(response_started_at - start) * 1000:.1f}'
        response_stream = '-' if response_started_at is None else f'{max(0.0, observed_at - response_started_at) * 1000:.1f}'
        _logger.warning(
            'Slow API request phase=%s method=%s path=%s status=%s total_ms=%.1f response_start_ms=%s '
            'response_stream_ms=%s request_id=%s db_sql_count=%s db_sql_ms=%.1f '
            'api_blocking_admission_wait_ms=%.1f api_bootstrap_admission_wait_ms=%.1f '
            'api_general_admission_wait_ms=%.1f api_bootstrap_executor_queue_ms=%.1f '
            'api_general_executor_queue_ms=%.1f api_bootstrap_work_ms=%.1f api_general_work_ms=%.1f '
            'db_checkout_count=%s db_checkout_ms=%.1f db_checkout_max_ms=%.1f '
            'db_slowest_sql_ms=%.1f db_slowest_sql=%s db_commit_ms=%.1f db_pool=%s',
            phase,
            scope.get('method', '-'),
            scope.get('path', '-'),
            response_status,
            (observed_at - start) * 1000,
            response_start,
            response_stream,
            request_id,
            database_metrics.get('sql_count', 0),
            _metric_ms(database_metrics, 'sql_ms'),
            _metric_ms(database_metrics, 'api_blocking_admission_wait_ms'),
            *(_metric_ms(database_metrics, metric) for _label, metric in _LANE_TIMINGS),
            database_metrics.get('db_pool_checkout_count', 0),
            _metric_ms(database_metrics, 'db_pool_checkout_ms'),
            _metric_ms(database_metrics, 'db_pool_checkout_max_ms'),
            _metric_ms(database_metrics, 'slowest_sql_ms'),
            database_metrics.get('slowest_sql_statement', '-'),
            _metric_ms(database_metrics, 'commit_ms'),
            pool,
        )


class RequestLoggingMiddleware:
    def __init__(
        self,
        app: AsgiApp,
        writer: RequestLogWriter | None = None,
        get_time: Callable[[], float] | None = None,
        max_body_size: int | None = None,
    ):
        self.app = app
        self.writer = writer
        self.get_time = get_time or time.perf_counter
        self.max_body_size = settings.log_max_body_size if max_body_size is None else max(0, max_body_size)

    async def __call__(self, scope: dict[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        if not self.writer:
            self.writer = await run_api_blocking(get_log_writer)
        start = self.get_time()
        request = Request(scope, receive)
        state = scope.setdefault('state', {})
        request_id = state.get('request_id') or request.headers.get('x-request-id') or uuid.uuid4().hex
        state['request_id'] = request_id

        try:
            content_length_header = request.headers.get('content-length')
            content_length = int(content_length_header) if content_length_header is not None else None
        except ValueError:
            content_length = None
        # Frontend chunks are served through this process in the containerized
        # deployment. Never copy their response bodies into the request log: doing
        # so turns diagnostics into a competing workload for the same file/thread
        # I/O path that serves the application.
        is_frontend_asset = request.url.path.startswith('/_app/')
        should_log_body = not is_frontend_asset and content_length is not None and 0 <= content_length <= self.max_body_size and self.max_body_size > 0
        body_for_log: bytes | None = None
        replay_body_sent = False
        request_complete = False
        if should_log_body:
            try:
                body_for_log = await request.body()
            except ClientDisconnect:
                # The client can disappear while the middleware buffers a
                # body for optional logging, before routing's exception
                # handlers are in scope.
                return
            request_complete = True

        async def receive_for_app() -> AsgiMessage:
            nonlocal replay_body_sent, request_complete
            if should_log_body and not replay_body_sent:
                replay_body_sent = True
                return {'type': 'http.request', 'body': body_for_log or b'', 'more_body': False}
            message = await receive()
            if not request_complete and (message['type'] == 'http.disconnect' or (message['type'] == 'http.request' and not message.get('more_body', False))):
                request_complete = True
            return message

        response_logged = False
        response_status = 500
        response_headers: list[tuple[bytes, bytes]] = []
        response_body: bytes | None = None

        def submit_response_log() -> None:
            nonlocal response_logged
            duration_ms = (self.get_time() - start) * 1000
            content_type = _header_value(response_headers, b'content-type')
            self._submit_request_log(request, response_status, content_type, duration_ms, request_id, body_for_log, response_body)
            response_logged = True

        async def send_wrapper(message: AsgiMessage) -> None:
            nonlocal response_status, response_headers, response_body
            if message['type'] == 'http.response.start':
                response_status = int(message['status'])
                response_headers = list(message.get('headers', []))
                headers = [item for item in response_headers if item[0].lower() != b'x-request-id']
                headers.append((b'x-request-id', request_id.encode()))
                message = {**message, 'headers': headers}
            elif message['type'] == 'http.response.body':
                chunk = message.get('body', b'')
                raw = chunk.encode('utf-8') if isinstance(chunk, str) else bytes(chunk)
                if response_body is None and raw and not is_frontend_asset and 0 < len(raw) <= self.max_body_size:
                    response_body = raw
            await send(message)
            if message['type'] == 'http.response.body' and not message.get('more_body', False) and not response_logged:
                submit_response_log()

        try:
            await self.app(scope, receive_for_app, send_wrapper)
        except ClientDisconnect:
            # Request-body disconnects are expected cancellation, not an
            # application error worth persisting to the request log.
            return
        except Exception as exc:
            duration_ms = (self.get_time() - start) * 1000
            self._submit_request_log(request, None, None, duration_ms, request_id, body_for_log, None, error=str(exc))
            raise
        if not response_logged:
            submit_response_log()

    def _submit_request_log(self, *args: Any, **kwargs: Any) -> None:
        """Prepare one best-effort request log without delaying its response.

        Request-body decoding and secret redaction run on a bounded pool. When
        that pool is saturated, drop diagnostics instead of retaining an
        unbounded number of response bodies or holding API tasks open behind
        log formatting.
        """
        global _REQUEST_LOG_DROPPED
        if not _REQUEST_LOG_PENDING_SLOTS.acquire(blocking=False):
            with _REQUEST_LOG_DROP_LOCK:
                _REQUEST_LOG_DROPPED += 1
                dropped = _REQUEST_LOG_DROPPED
            if dropped % 100 == 1:
                _logger.warning('Request log preparation saturated; dropped %s request logs', dropped)
            return
        try:
            future = _REQUEST_LOG_EXECUTOR.submit(self._log_request, *args, **kwargs)
        except RuntimeError:
            # The executor refuses new work during interpreter shutdown.
            _REQUEST_LOG_PENDING_SLOTS.release()
            _logger.debug('Request log preparation could not be queued; dropping one request log', exc_info=True)
            return
        with _REQUEST_LOG_FUTURES_LOCK:
            _REQUEST_LOG_FUTURES.add(future)
        future.add_done_callback(_finish_request_log)

    def _log_request(
        self,
        request: Request,
        response_status: int | None,
        response_content_type: str | None,
        duration_ms: float,
        request_id: str,
        request_body: bytes | None,
        response_body: bytes | None,
        error: str | None = None,
    ) -> None:
        writer = self.writer or get_log_writer()
        status = response_status or 500
        if not error and response_status is not None and status >= 400:
            error = f'HTTP {status}'
        ip = client_ip(request)
        parts = ip.split('.') if ip is not None else []
        if len(parts) == 4:
            ip = '.'.join([parts[0], parts[1], '0', '0'])
        path = request.url.path
        writer.write_request_log(
            {
                'ts': datetime.now(UTC),
                'method': request.method,
                'path': path,
                'status': status,
                'duration_ms': duration_ms,
                'request_id': request_id,
                'client_id': request.headers.get('x-client-id'),
                'user_agent': request.headers.get('user-agent'),
                'ip': ip,
                'referer': request.headers.get('referer'),
                'error': error,
                'request_json': redact_logged_body(path, request_body.decode('utf-8', errors='ignore') if request_body else None),
                'response_json': redact_logged_body(path, response_body.decode('utf-8', errors='ignore') if response_body else None),
                'chunk_index': 0,
            }
        )


def _redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (_REDACTED if key in _SENSITIVE_FIELDS else _redact_json_value(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    return value


def redact_logged_body(path: str, body: str | None) -> str | None:
    if not body or not path.startswith(_SENSITIVE_PATHS):
        return body or None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        pairs = urllib.parse.parse_qsl(body, keep_blank_values=True) if '=' in body else []
        if not pairs:
            return body
        return urllib.parse.urlencode([(key, _REDACTED if key in _SENSITIVE_FIELDS else value) for key, value in pairs])
    return json.dumps(_redact_json_value(parsed), default=str)


def configure_logging() -> DatabaseLogWriter:
    global _atexit_registered, _configured, _console_handler, _listener, _queue_handler, _writer
    with _logging_lifecycle_lock:
        if _configured and _writer:
            return _writer

        level = getattr(logging, settings.log_level.upper(), logging.INFO)
        logging.basicConfig(level=level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        logging.getLogger('httpx').setLevel(logging.WARNING)
        # The application intentionally uses the existing Iceberg SQL catalog
        # schema. PyIceberg emits this migration notice on every catalog instance;
        # keep real catalog errors visible without flooding service diagnostics.
        logging.getLogger('pyiceberg.catalog.sql').setLevel(logging.ERROR)

        _writer = DatabaseLogWriter(
            database_url=settings.database_url, flush_interval=float(settings.log_flush_interval_seconds), overflow_policy=settings.log_queue_overflow
        )
        root_logger = logging.getLogger()
        console_handler = next((handler for handler in root_logger.handlers if type(handler) is logging.StreamHandler), None)
        if console_handler is not None:
            root_logger.removeHandler(console_handler)
        else:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        _console_handler = console_handler

        log_queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=settings.log_queue_max_size)
        _queue_handler = _BoundedFormattingQueueHandler(log_queue)
        _listener = _BoundedQueueListener(
            log_queue,
            console_handler,
            DatabaseLogHandler(_writer),
            overflow_handler=_queue_handler,
        )
        _listener.start()
        if not _atexit_registered:
            atexit.register(shutdown_logging)
            _atexit_registered = True

        root_logger.addHandler(_queue_handler)
        _configured = True
        return _writer


async def configure_logging_off_loop() -> DatabaseLogWriter:
    """Initialize the database-backed logger without blocking an async service loop."""
    return await run_api_blocking(configure_logging)


def shutdown_logging() -> None:
    """Drain the log queue before closing its database writer."""
    global _configured, _console_handler, _listener, _queue_handler, _writer
    with _logging_lifecycle_lock:
        listener, writer, queue_handler, console_handler = _listener, _writer, _queue_handler, _console_handler
        root_logger = logging.getLogger()
        if queue_handler is not None:
            root_logger.removeHandler(queue_handler)
        try:
            if listener is not None:
                listener.stop()
        finally:
            if console_handler is not None and console_handler not in root_logger.handlers:
                root_logger.addHandler(console_handler)
            if writer is not None:
                writer.stop()
            _listener = None
            _writer = None
            _queue_handler = None
            _console_handler = None
            _configured = False


def get_log_writer() -> DatabaseLogWriter:
    if _writer:
        return _writer
    return configure_logging()
