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
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

import psycopg
from fastapi import Request
from starlette.requests import ClientDisconnect

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
_DEFAULT_FLUSH_INTERVAL = 5.0
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
_REQUEST_LOG_MAX_PENDING = 64
_REQUEST_LOG_PENDING_SLOTS = threading.BoundedSemaphore(_REQUEST_LOG_MAX_PENDING)
_REQUEST_LOG_DROP_LOCK = threading.Lock()
_REQUEST_LOG_DROPPED = 0
_REQUEST_LOG_FUTURES_LOCK = threading.Lock()
_REQUEST_LOG_FUTURES: set[Future[Any]] = set()


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


class RequestLogWriter(Protocol):
    def write_request_log(self, payload: dict[str, Any]) -> None: ...


class DatabaseLogKind(DataForgeStrEnum):
    REQUEST = 'request_logs'
    APP = 'app_logs'
    CLIENT = 'client_logs'
    FLUSH = '__flush__'
    STOP = '__stop__'

    @property
    def is_control(self) -> bool:
        return self in {DatabaseLogKind.FLUSH, DatabaseLogKind.STOP}

    def insert_rows(self, conn: psycopg.Connection, rows: list[dict[str, Any]], day: date) -> None:
        day_str = day.isoformat()
        with conn.cursor() as cursor:
            match self:
                case DatabaseLogKind.REQUEST:
                    cursor.executemany(
                        """INSERT INTO request_logs
                   (ts, method, path, status, duration_ms, request_id, client_id,
                    user_agent, ip, referer, error, request_json, response_json,
                    chunk_index, day)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [
                            (
                                row.get('ts'),
                                row.get('method'),
                                row.get('path'),
                                row.get('status'),
                                row.get('duration_ms'),
                                row.get('request_id'),
                                row.get('client_id'),
                                row.get('user_agent'),
                                row.get('ip'),
                                row.get('referer'),
                                row.get('error'),
                                row.get('request_json'),
                                row.get('response_json'),
                                row.get('chunk_index'),
                                day_str,
                            )
                            for row in rows
                        ],
                    )
                case DatabaseLogKind.APP:
                    cursor.executemany(
                        """INSERT INTO app_logs
                   (ts, level, logger, message, module, func, line, extra_json, day)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [
                            (
                                row.get('ts'),
                                row.get('level'),
                                row.get('logger'),
                                row.get('message'),
                                row.get('module'),
                                row.get('func'),
                                row.get('line'),
                                row.get('extra_json'),
                                day_str,
                            )
                            for row in rows
                        ],
                    )
                case DatabaseLogKind.CLIENT:
                    cursor.executemany(
                        """INSERT INTO client_logs
                   (ts, event, action, page, target, form_id, fields_json, client_id, session_id, meta_json, day)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [
                            (
                                row.get('ts'),
                                row.get('event'),
                                row.get('action'),
                                row.get('page'),
                                row.get('target'),
                                row.get('form_id'),
                                row.get('fields_json'),
                                row.get('client_id'),
                                row.get('session_id'),
                                row.get('meta_json'),
                                day_str,
                            )
                            for row in rows
                        ],
                    )
                case _:
                    return


def _adapt_datetime(value: datetime) -> str:
    return value.isoformat()


def _day_from_ts(ts: datetime | None) -> date:
    """Get the date in the configured timezone for daily table partitioning."""
    tz = ZoneInfo(settings.timezone)
    if isinstance(ts, datetime):
        return ts.astimezone(tz).date()
    return datetime.now(tz).date()


class DatabaseLogWriter:
    def __init__(self, database_url: str, *, flush_interval: float = _DEFAULT_FLUSH_INTERVAL, overflow_policy: str = 'block'):
        self._lock = threading.Lock()
        self._queue: queue.Queue[tuple[DatabaseLogKind, list[dict[str, Any]]]] = queue.Queue(maxsize=settings.log_queue_max_size)
        self._stop_event = threading.Event()
        self._flush_timer_lock = threading.Lock()
        self._flush_timer: threading.Timer | None = None
        self._overflow_policy = overflow_policy
        self._dropped_count = 0
        self._database_url = database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
        self._conn: psycopg.Connection | None = None
        self._insert_conn: psycopg.Connection | None = None
        self._insert_conn_lock = threading.Lock()
        self._buffers: dict[tuple[DatabaseLogKind, date], list[dict[str, Any]]] = {}
        self._flush_interval = flush_interval
        self._last_flush = time.monotonic()
        self._worker = threading.Thread(target=self._run, name='postgres-log-writer', daemon=True)
        self._init_db()
        self._worker.start()

    def _init_db(self) -> None:
        self._conn = psycopg.connect(self._database_url, autocommit=True)
        with self._conn.transaction(), self._conn.cursor() as cursor:
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
        row = {
            'ts': payload.get('ts'),
            'method': payload.get('method'),
            'path': payload.get('path'),
            'status': payload.get('status'),
            'duration_ms': payload.get('duration_ms'),
            'request_id': payload.get('request_id'),
            'client_id': payload.get('client_id'),
            'user_agent': payload.get('user_agent'),
            'ip': payload.get('ip'),
            'referer': payload.get('referer'),
            'error': payload.get('error'),
            'request_json': payload.get('request_json'),
            'response_json': payload.get('response_json'),
            'chunk_index': payload.get('chunk_index'),
        }
        # Never block request processing behind a full diagnostics queue;
        # losing a low-value request log is preferable to making the API
        # unavailable.
        self._enqueue_rows(DatabaseLogKind.REQUEST, [row], allow_block=False)

    def write_app_log(self, payload: dict[str, Any]) -> None:
        row = {
            'ts': payload.get('ts'),
            'level': payload.get('level'),
            'logger': payload.get('logger'),
            'message': payload.get('message'),
            'module': payload.get('module'),
            'func': payload.get('func'),
            'line': payload.get('line'),
            'extra_json': payload.get('extra_json'),
        }
        self._enqueue_rows(DatabaseLogKind.APP, [row])

    def write_client_logs(self, payloads: list[dict[str, Any]]) -> None:
        if not payloads:
            return
        rows = [
            {
                'ts': item.get('ts'),
                'event': item.get('event'),
                'action': item.get('action'),
                'page': item.get('page'),
                'target': item.get('target'),
                'form_id': item.get('form_id'),
                'fields_json': item.get('fields_json'),
                'client_id': item.get('client_id'),
                'session_id': item.get('session_id'),
                'meta_json': item.get('meta_json'),
            }
            for item in payloads
        ]
        # Client telemetry can also arrive directly from an HTTP handler.
        self._enqueue_rows(DatabaseLogKind.CLIENT, rows, allow_block=False)

    def flush(self) -> None:
        with self._lock:
            batches = self._buffers
            self._buffers = {}
        for (kind, day), rows in batches.items():
            self._insert_rows(kind, day, rows)
        self._last_flush = time.monotonic()

    def stop(self) -> None:
        self._stop_event.set()
        self._cancel_flush_timer()
        self._queue.put((DatabaseLogKind.STOP, []))
        self._worker.join()
        self.flush()
        with self._insert_conn_lock:
            if self._insert_conn:
                with contextlib.suppress(Exception):
                    self._insert_conn.close()
                self._insert_conn = None
        if self._conn:
            self._conn.close()

    def _enqueue_rows(self, kind: DatabaseLogKind, rows: list[dict[str, Any]], *, allow_block: bool = True) -> None:
        if not rows:
            return
        if self._overflow_policy == 'drop' or not allow_block:
            try:
                self._queue.put_nowait((kind, rows))
            except queue.Full:
                with self._lock:
                    self._dropped_count += len(rows)
                    dropped = self._dropped_count
                if dropped % 100 == 1:
                    _logger.warning(f'Log queue full, dropped {dropped} rows total')
                return
        else:
            self._queue.put((kind, rows))
        self._ensure_flush_timer()

    def _enqueue_flush(self) -> None:
        with self._flush_timer_lock:
            self._flush_timer = None
        if self._stop_event.is_set():
            return
        self._queue.put((DatabaseLogKind.FLUSH, []))

    def _ensure_flush_timer(self) -> None:
        if self._flush_interval <= 0:
            return
        with self._flush_timer_lock:
            if self._flush_timer is not None or self._stop_event.is_set():
                return
            timer = threading.Timer(self._flush_interval, self._enqueue_flush)
            timer.daemon = True
            self._flush_timer = timer
            timer.start()

    def _cancel_flush_timer(self) -> None:
        with self._flush_timer_lock:
            timer = self._flush_timer
            self._flush_timer = None
        if timer is not None:
            timer.cancel()

    def _run(self) -> None:
        while True:
            kind, rows = self._queue.get()
            if kind == DatabaseLogKind.STOP:
                break
            if kind == DatabaseLogKind.FLUSH:
                self.flush()
                continue
            if rows:
                self._buffer_rows(kind, rows)
        self._cancel_flush_timer()
        self.flush()

    def _buffer_rows(self, kind: DatabaseLogKind, rows: list[dict[str, Any]]) -> None:
        with self._lock:
            for row in rows:
                day = _day_from_ts(row.get('ts'))
                key = (kind, day)
                buffer = self._buffers.setdefault(key, [])
                buffer.append(row)

    def _insert_rows(self, kind: DatabaseLogKind, day: date, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            with self._insert_connection() as conn:
                kind.insert_rows(conn, rows, day)
        except Exception as e:
            _logger.error(f'Failed to insert {len(rows)} rows to {kind.value}/{day}: {e}', exc_info=True)

    @contextmanager
    def _insert_connection(self):
        """Reuse one persistent connection for log inserts.

        Opening a new connection per flush batch produced connection storms
        under load; inserts are small and frequent, so the connection is kept
        open, guarded by a lock (timer flushes and the writer thread can
        overlap), and re-established after failures.
        """
        with self._insert_conn_lock:
            try:
                if self._insert_conn is None or self._insert_conn.closed:
                    self._insert_conn = psycopg.connect(self._database_url, autocommit=False)
                yield self._insert_conn
                self._insert_conn.commit()
            except Exception:
                with contextlib.suppress(Exception):
                    self._insert_conn.rollback()
                with contextlib.suppress(Exception):
                    self._insert_conn.close()
                self._insert_conn = None
                raise


class DatabaseLogHandler(logging.Handler):
    def __init__(self, writer: DatabaseLogWriter):
        super().__init__()
        self.writer = writer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            extras = _extract_log_extras(record)
            payload = {
                'ts': datetime.now(UTC),
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage(),
                'module': record.module,
                'func': record.funcName,
                'line': record.lineno,
                'extra_json': record.__dict__.get('extra_json') or extras,
            }
            self.writer.write_app_log(payload)
        except Exception as exc:
            _logger.error('Database log handler failed: %s', exc, exc_info=True)
            self.handleError(record)


class _DeferredFormattingQueueHandler(logging.handlers.QueueHandler):
    """Queue records without formatting messages or tracebacks on request loops.

    This queue is process-local and consumed by ``QueueListener`` in a thread,
    so records do not need the eager stringification that multiprocessing
    queues require.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return copy.copy(record)


class _BoundedFormattingQueueHandler(_DeferredFormattingQueueHandler):
    """Queue log records without waiting for a slow listener thread."""

    def __init__(self, log_queue: queue.Queue[logging.LogRecord]) -> None:
        super().__init__(log_queue)
        self._dropped = 0
        self._reported_dropped = 0
        self._drop_lock = threading.Lock()

    @property
    def dropped(self) -> int:
        with self._drop_lock:
            return self._dropped

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            with self._drop_lock:
                self._dropped += 1

    def take_drop_report(self) -> int | None:
        with self._drop_lock:
            dropped = self._dropped
            if dropped == 0 or dropped & (dropped - 1) != 0:
                return None
            if dropped == self._reported_dropped:
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
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        path = str(scope.get('path') or '')
        if not (path == '/api' or path.startswith('/api/') or path == '/health' or path.startswith('/health/')):
            await self.app(scope, receive, send)
            return

        start = self.get_time()
        response_started_at: float | None = None
        response_status: int | None = None
        state = scope.setdefault('state', {})
        request_id = state.get('request_id')
        for key, value in scope.get('headers') or ():
            if key.lower() == b'x-request-id':
                request_id = request_id or value.decode('latin-1')
                break
        request_id = request_id or uuid.uuid4().hex
        state['request_id'] = request_id
        database_metrics: dict[str, object] = {'sql_count': 0, 'sql_ms': 0.0, 'commit_ms': 0.0, 'api_db_admission_wait_ms': 0.0}

        async def report_slow_request() -> None:
            await asyncio.sleep(self.slow_request_seconds)
            observed_at = self.get_time()
            response_start_ms = None if response_started_at is None else (response_started_at - start) * 1000
            response_stream_ms = None if response_started_at is None else max(0.0, observed_at - response_started_at) * 1000
            await self._log_slow_request(
                scope,
                request_id=request_id,
                response_status=response_status,
                total_ms=(observed_at - start) * 1000,
                response_start_ms=response_start_ms,
                response_stream_ms=response_stream_ms,
                database_metrics=database_metrics,
                phase='in_flight',
            )

        slow_task = asyncio.create_task(report_slow_request())

        async def send_wrapper(message: AsgiMessage) -> None:
            nonlocal response_started_at, response_status
            if message['type'] == 'http.response.start':
                response_started_at = self.get_time()
                response_status = int(message['status'])
                headers = [(name, value) for name, value in message.get('headers', []) if name.lower() not in {b'x-request-id', b'server-timing'}]
                headers.append((b'x-request-id', request_id.encode('latin-1')))
                server_duration_ms = max(0.0, (response_started_at - start) * 1000)
                admission_wait_ms = database_metrics.get('api_db_admission_wait_ms', 0.0)
                if not isinstance(admission_wait_ms, (int, float)):
                    admission_wait_ms = 0.0
                server_timing = f'app;dur={server_duration_ms:.1f}, api-db-admission;dur={admission_wait_ms:.1f}'
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
            total_ms = (self.get_time() - start) * 1000
            if total_ms >= self.slow_request_seconds * 1000:
                response_start_ms = None if response_started_at is None else (response_started_at - start) * 1000
                response_stream_ms = None if response_start_ms is None else max(0.0, total_ms - response_start_ms)
                await self._log_slow_request(
                    scope,
                    request_id=request_id,
                    response_status=response_status,
                    total_ms=total_ms,
                    response_start_ms=response_start_ms,
                    response_stream_ms=response_stream_ms,
                    database_metrics=database_metrics,
                    phase='completed',
                )

    async def _log_slow_request(
        self,
        scope: dict[str, Any],
        *,
        request_id: str,
        response_status: int | None,
        total_ms: float,
        response_start_ms: float | None,
        response_stream_ms: float | None,
        database_metrics: dict[str, object],
        phase: str,
    ) -> None:
        pool = {}
        if self.pool_snapshot is not None:
            with contextlib.suppress(Exception):
                pool = await self.pool_snapshot()
        sql_ms = database_metrics.get('sql_ms')
        commit_ms = database_metrics.get('commit_ms')
        _logger.warning(
            'Slow API request phase=%s method=%s path=%s status=%s total_ms=%.1f response_start_ms=%s '
            'response_stream_ms=%s request_id=%s db_sql_count=%s db_sql_ms=%.1f db_commit_ms=%.1f db_pool=%s',
            phase,
            scope.get('method', '-'),
            scope.get('path', '-'),
            response_status,
            total_ms,
            '-' if response_start_ms is None else f'{response_start_ms:.1f}',
            '-' if response_stream_ms is None else f'{response_stream_ms:.1f}',
            request_id,
            database_metrics.get('sql_count', 0),
            sql_ms if isinstance(sql_ms, (int, float)) else 0.0,
            commit_ms if isinstance(commit_ms, (int, float)) else 0.0,
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
            self.writer = await asyncio.to_thread(get_log_writer)
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
        should_log_body = (
            not is_frontend_asset and self.max_body_size > 0 and content_length is not None and content_length >= 0 and content_length <= self.max_body_size
        )
        body_for_log: bytes | None = None
        replay_body_sent = False
        request_complete = False
        if should_log_body:
            try:
                body = await request.body()
            except ClientDisconnect:
                # The client can disappear while the middleware buffers a
                # body for optional logging, before routing's exception
                # handlers are in scope.
                return
            body_for_log = body
            request_complete = True

        async def receive_for_app() -> AsgiMessage:
            nonlocal replay_body_sent, request_complete
            if should_log_body:
                if not replay_body_sent:
                    replay_body_sent = True
                    return {'type': 'http.request', 'body': body_for_log or b'', 'more_body': False}
                return await receive()

            if not request_complete:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    request_complete = True
                    return message
                if message['type'] == 'http.request' and not message.get('more_body', False):
                    request_complete = True
                return message

            return await receive()

        response_logged = False
        response_status = 500
        response_headers: list[tuple[bytes, bytes]] = []
        response_body: bytes | None = None

        async def send_wrapper(message: AsgiMessage) -> None:
            nonlocal response_logged, response_status, response_headers, response_body
            if message['type'] == 'http.response.start':
                response_status = int(message['status'])
                headers = list(message.get('headers', []))
                response_headers = headers
                filtered_headers = [item for item in headers if item[0].lower() != b'x-request-id']
                filtered_headers.append((b'x-request-id', request_id.encode()))
                message = {**message, 'headers': filtered_headers}
            elif message['type'] == 'http.response.body':
                chunk = message.get('body', b'')
                raw = chunk.encode('utf-8') if isinstance(chunk, str) else bytes(chunk)
                if response_body is None and raw and not is_frontend_asset and self.max_body_size > 0 and len(raw) <= self.max_body_size:
                    response_body = raw
            await send(message)
            if message['type'] == 'http.response.body' and not message.get('more_body', False) and not response_logged:
                duration_ms = (self.get_time() - start) * 1000
                self._submit_request_log(
                    request,
                    response_status,
                    self._header_value(response_headers, b'content-type'),
                    duration_ms,
                    request_id,
                    body_for_log,
                    response_body,
                )
                response_logged = True

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
            duration_ms = (self.get_time() - start) * 1000
            self._submit_request_log(
                request,
                response_status,
                self._header_value(response_headers, b'content-type'),
                duration_ms,
                request_id,
                body_for_log,
                response_body,
            )

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
        except Exception:
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
        chunk_index: int = 0,
    ) -> None:
        if not self.writer:
            self.writer = get_log_writer()
        if not self.writer:
            return
        status = response_status or 500
        if not error and response_status is not None and status >= 400:
            error = f'HTTP {status}'
        ip = client_ip(request)
        if isinstance(ip, str):
            parts = ip.split('.') if '.' in ip else []
            if len(parts) == 4:
                ip = '.'.join([parts[0], parts[1], '0', '0'])
        payload = {
            'ts': datetime.now(UTC),
            'method': request.method,
            'path': request.url.path,
            'status': status,
            'duration_ms': duration_ms,
            'request_id': request_id,
            'client_id': request.headers.get('x-client-id'),
            'user_agent': request.headers.get('user-agent'),
            'ip': ip,
            'referer': request.headers.get('referer'),
            'error': error,
            'request_json': redact_logged_body(request.url.path, self._coerce_body(request.headers.get('content-type'), request_body)),
            'response_json': redact_logged_body(request.url.path, self._coerce_body(response_content_type, response_body)),
            'chunk_index': chunk_index,
        }
        if not self.writer:
            return
        self.writer.write_request_log(payload)

    def _header_value(self, headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
        for header_name, value in headers:
            if header_name.lower() == name:
                return value.decode('latin-1')
        return None

    def _coerce_body(self, content_type: str | None, body: bytes | None) -> str | None:
        if not body:
            return None
        return body.decode('utf-8', errors='ignore')


def _should_redact_path(path: str) -> bool:
    return path.startswith(_SENSITIVE_PATHS)


def _redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (_REDACTED if key in _SENSITIVE_FIELDS else _redact_json_value(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    return value


def redact_logged_body(path: str, body: str | None) -> str | None:
    if not body:
        return None
    if not _should_redact_path(path):
        return body
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return _redact_form_body(body)
    return json.dumps(_redact_json_value(parsed), default=str)


def _redact_form_body(body: str) -> str:
    if '=' not in body:
        return body
    pairs = urllib.parse.parse_qsl(body, keep_blank_values=True)
    if not pairs:
        return body
    redacted = [(key, _REDACTED if key in _SENSITIVE_FIELDS else value) for key, value in pairs]
    return urllib.parse.urlencode(redacted)


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
    return await asyncio.to_thread(configure_logging)


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


def _extract_log_extras(record: logging.LogRecord) -> str | None:
    extras = {key: value for key, value in record.__dict__.items() if key not in _LOG_RECORD_KEYS and key != 'message'}
    if not extras:
        return None
    return json.dumps(extras, default=str)
