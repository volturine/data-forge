from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import queue
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse

from core.config import settings
from core.proxy import client_ip

_writer: SqliteLogWriter | None = None
_listener: logging.handlers.QueueListener | None = None
_configured = False
_LOG_RECORD_KEYS = set(logging.LogRecord('', 0, '', 0, '', (), None).__dict__.keys())
_DEFAULT_FLUSH_INTERVAL = 5.0
_logger = logging.getLogger('core.logging')
_SENSITIVE_FIELDS = {
    'password',
    'smtp_password',
    'telegram_bot_token',
    'openrouter_api_key',
    'openai_api_key',
    'huggingface_api_token',
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


class RequestLogWriter(Protocol):
    def write_request_log(self, payload: dict[str, Any]) -> None: ...


def _adapt_datetime(value: datetime) -> str:
    return value.isoformat()


sqlite3.register_adapter(datetime, _adapt_datetime)


def _day_from_ts(ts: datetime | None) -> date:
    """Get the date in the configured timezone for daily table partitioning."""
    tz = ZoneInfo(settings.timezone)
    if isinstance(ts, datetime):
        return ts.astimezone(tz).date()
    return datetime.now(tz).date()


class SqliteLogWriter:
    def __init__(
        self,
        base_path: str,
        *,
        flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
        overflow_policy: str = 'block',
    ):
        self._lock = threading.Lock()
        self._queue: queue.Queue[tuple[str, list[dict[str, Any]]]] = queue.Queue(maxsize=settings.log_queue_max_size)
        self._stop_event = threading.Event()
        self._overflow_policy = overflow_policy
        self._dropped_count = 0
        self._base_path = Path(base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._db_path = (self._base_path / 'logs.db').resolve()
        self._conn: sqlite3.Connection | None = None
        self._buffers: dict[tuple[str, date], list[dict[str, Any]]] = {}
        self._flush_interval = flush_interval
        self._last_flush = time.monotonic()
        self._worker = threading.Thread(target=self._run, name='sqlite-log-writer', daemon=True)
        self._init_db()
        self._worker.start()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._conn.execute('PRAGMA cache_size=-64000')
        self._conn.execute('PRAGMA temp_store=MEMORY')

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                method TEXT,
                path TEXT,
                status INTEGER,
                duration_ms REAL,
                request_id TEXT,
                client_id TEXT,
                user_agent TEXT,
                ip TEXT,
                referer TEXT,
                error TEXT,
                request_json TEXT,
                response_json TEXT,
                chunk_index INTEGER,
                day TEXT NOT NULL
            )
        """)
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_request_day ON request_logs(day)')

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS app_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                level TEXT,
                logger TEXT,
                message TEXT,
                module TEXT,
                func TEXT,
                line INTEGER,
                extra_json TEXT,
                day TEXT NOT NULL
            )
        """)
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_app_day ON app_logs(day)')

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS client_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                event TEXT,
                action TEXT,
                page TEXT,
                target TEXT,
                form_id TEXT,
                fields_json TEXT,
                client_id TEXT,
                session_id TEXT,
                meta_json TEXT,
                day TEXT NOT NULL
            )
        """)
        self._conn.execute('CREATE INDEX IF NOT EXISTS idx_client_day ON client_logs(day)')

        self._conn.commit()

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
        self._enqueue_rows('request_logs', [row])

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
        self._enqueue_rows('app_logs', [row])

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
        self._enqueue_rows('client_logs', rows)

    def flush(self) -> None:
        with self._lock:
            batches = self._buffers
            self._buffers = {}
        for (kind, day), rows in batches.items():
            self._insert_rows(kind, day, rows)
        self._last_flush = time.monotonic()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(('__stop__', []))
        self._worker.join(timeout=5)
        self.flush()
        if self._conn:
            self._conn.close()

    def _enqueue_rows(self, kind: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        if self._overflow_policy == 'drop':
            try:
                self._queue.put_nowait((kind, rows))
            except queue.Full:
                with self._lock:
                    self._dropped_count += len(rows)
                    dropped = self._dropped_count
                if dropped % 100 == 1:
                    _logger.warning(f'Log queue full, dropped {dropped} rows total')
        else:
            self._queue.put((kind, rows))

    def _run(self) -> None:
        while True:
            if self._stop_event.is_set() and self._queue.empty():
                break
            try:
                kind, rows = self._queue.get(timeout=0.5)
            except queue.Empty:
                kind, rows = '', []
            if kind == '__stop__':
                break
            if rows:
                self._buffer_rows(kind, rows)
            self._maybe_flush()
        self.flush()

    def _buffer_rows(self, kind: str, rows: list[dict[str, Any]]) -> None:
        with self._lock:
            for row in rows:
                day = _day_from_ts(row.get('ts'))
                key = (kind, day)
                buffer = self._buffers.setdefault(key, [])
                buffer.append(row)

    def _maybe_flush(self) -> None:
        if time.monotonic() - self._last_flush < self._flush_interval:
            return
        self.flush()

    def _insert_rows(self, kind: str, day: date, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            with self._lock_for_insert() as conn:
                if kind == 'request_logs':
                    self._insert_request_logs(conn, rows, day)
                elif kind == 'app_logs':
                    self._insert_app_logs(conn, rows, day)
                elif kind == 'client_logs':
                    self._insert_client_logs(conn, rows, day)
        except Exception as e:
            _logger.error(f'Failed to insert {len(rows)} rows to {kind}/{day}: {e}', exc_info=True)

    @contextmanager
    def _lock_for_insert(self):
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        try:
            yield conn
        finally:
            conn.close()

    def _insert_request_logs(self, conn: sqlite3.Connection, rows: list[dict[str, Any]], day: date) -> None:
        day_str = day.isoformat()
        conn.executemany(
            """INSERT INTO request_logs
               (ts, method, path, status, duration_ms, request_id, client_id,
                user_agent, ip, referer, error, request_json, response_json,
                chunk_index, day)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    r.get('ts'),
                    r.get('method'),
                    r.get('path'),
                    r.get('status'),
                    r.get('duration_ms'),
                    r.get('request_id'),
                    r.get('client_id'),
                    r.get('user_agent'),
                    r.get('ip'),
                    r.get('referer'),
                    r.get('error'),
                    r.get('request_json'),
                    r.get('response_json'),
                    r.get('chunk_index'),
                    day_str,
                )
                for r in rows
            ],
        )
        conn.commit()

    def _insert_app_logs(self, conn: sqlite3.Connection, rows: list[dict[str, Any]], day: date) -> None:
        day_str = day.isoformat()
        conn.executemany(
            """INSERT INTO app_logs 
               (ts, level, logger, message, module, func, line, extra_json, day)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    r.get('ts'),
                    r.get('level'),
                    r.get('logger'),
                    r.get('message'),
                    r.get('module'),
                    r.get('func'),
                    r.get('line'),
                    r.get('extra_json'),
                    day_str,
                )
                for r in rows
            ],
        )
        conn.commit()

    def _insert_client_logs(self, conn: sqlite3.Connection, rows: list[dict[str, Any]], day: date) -> None:
        day_str = day.isoformat()
        conn.executemany(
            """INSERT INTO client_logs 
               (ts, event, action, page, target, form_id, fields_json, client_id, session_id, meta_json, day)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    r.get('ts'),
                    r.get('event'),
                    r.get('action'),
                    r.get('page'),
                    r.get('target'),
                    r.get('form_id'),
                    r.get('fields_json'),
                    r.get('client_id'),
                    r.get('session_id'),
                    r.get('meta_json'),
                    day_str,
                )
                for r in rows
            ],
        )
        conn.commit()


class SqliteLogHandler(logging.Handler):
    def __init__(self, writer: SqliteLogWriter):
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
            _logger.error('SQLite log handler failed: %s', exc, exc_info=True)
            self.handleError(record)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        writer: RequestLogWriter | None = None,
        get_time: Callable[[], float] | None = None,
        max_body_size: int = 0,
    ):
        super().__init__(app)
        self.writer = writer
        self.get_time = get_time or time.perf_counter
        self.max_body_size = max_body_size or settings.log_max_body_size

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        if not self.writer:
            self.writer = get_log_writer()
        start = self.get_time()
        request_id = request.headers.get('x-request-id') or uuid.uuid4().hex
        request.state.request_id = request_id

        content_length = int(request.headers.get('content-length', 0))
        should_log_body = self.max_body_size == 0 or content_length <= self.max_body_size
        body_for_log: bytes | None = None
        if should_log_body:
            body = await request.body()
            body_for_log = body

            async def receive():
                return {'type': 'http.request', 'body': body, 'more_body': False}

            request = Request(request.scope, receive)
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (self.get_time() - start) * 1000
            self._log_request(request, None, duration_ms, request_id, body_for_log, None, error=str(exc))
            raise
        duration_ms = (self.get_time() - start) * 1000
        response = await self._capture_response(request, response, duration_ms, request_id, body_for_log)
        response.headers['X-Request-Id'] = request_id
        return response

    async def _capture_response(
        self,
        request: Request,
        response: Response,
        duration_ms: float,
        request_id: str,
        request_body: bytes | None,
    ) -> Response:
        stream = response.body_iterator if isinstance(response, StreamingResponse) else getattr(response, 'body_iterator', None)
        if stream is not None:

            async def stream_wrapper():
                first_chunk: bytes | None = None
                logged = False
                try:
                    async for chunk in stream:
                        if first_chunk is None:
                            raw = chunk.encode('utf-8') if isinstance(chunk, str) else bytes(chunk)
                            if self.max_body_size == 0 or len(raw) <= self.max_body_size:
                                first_chunk = raw
                        yield chunk
                finally:
                    if not logged:
                        self._log_request(
                            request,
                            response,
                            duration_ms,
                            request_id,
                            request_body,
                            first_chunk,
                            chunk_index=0,
                        )
                        logged = True

            streamed = StreamingResponse(
                stream_wrapper(),
                status_code=response.status_code,
                media_type=response.media_type,
                background=response.background,
            )
            streamed.raw_headers = [item for item in response.raw_headers if item[0].lower() != b'content-length']
            return streamed
        response_data = getattr(response, 'body', None)
        if response_data is None:
            self._log_request(request, response, duration_ms, request_id, request_body, None, chunk_index=0)
            return response
        if isinstance(response_data, str):
            response_body = response_data.encode('utf-8')
        elif isinstance(response_data, memoryview):
            response_body = bytes(response_data)
        else:
            response_body = response_data
        body: bytes | None = response_body
        if body is not None and self.max_body_size > 0 and len(body) > self.max_body_size:
            body = None
        self._log_request(request, response, duration_ms, request_id, request_body, body, chunk_index=0)
        return response

    def _log_request(
        self,
        request: Request,
        response: Response | None,
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
        status = response.status_code if response else 500
        if not error and response and status >= 400:
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
            'response_json': redact_logged_body(
                request.url.path,
                self._coerce_body(response.headers.get('content-type') if response else None, response_body),
            ),
            'chunk_index': chunk_index,
        }
        if not self.writer:
            return
        self.writer.write_request_log(payload)

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
        return body
    return json.dumps(_redact_json_value(parsed), default=str)


def configure_logging() -> SqliteLogWriter:
    global _configured, _listener, _writer
    if _configured and _writer:
        return _writer

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    logging.getLogger('httpx').setLevel(logging.WARNING)

    _writer = SqliteLogWriter(
        base_path=str(settings.log_sqlite_path),
        flush_interval=float(settings.log_sqlite_flush_interval_seconds),
        overflow_policy=settings.log_queue_overflow,
    )
    queue_handler = logging.handlers.QueueHandler(queue.Queue())
    _listener = logging.handlers.QueueListener(queue_handler.queue, SqliteLogHandler(_writer))
    _listener.start()
    atexit.register(_listener.stop)
    atexit.register(_writer.stop)

    root_logger = logging.getLogger()
    root_logger.addHandler(queue_handler)
    _configured = True
    return _writer


def get_log_writer() -> SqliteLogWriter:
    if _writer:
        return _writer
    return configure_logging()


def _extract_log_extras(record: logging.LogRecord) -> str | None:
    extras = {key: value for key, value in record.__dict__.items() if key not in _LOG_RECORD_KEYS and key != 'message'}
    if not extras:
        return None
    return json.dumps(extras, default=str)
