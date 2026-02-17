from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa  # type: ignore[import-untyped]
from fastapi import Request, Response
from pyiceberg.catalog import load_catalog
from pyiceberg.schema import Schema
from pyiceberg.types import DoubleType, IntegerType, StringType, TimestampType
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse

from core.config import settings

_writer: IcebergLogWriter | None = None
_listener: logging.handlers.QueueListener | None = None
_configured = False
_LOG_RECORD_KEYS = set(logging.LogRecord('', 0, '', 0, '', (), None).__dict__.keys())
_DEFAULT_FLUSH_INTERVAL = 300.0
_LOG_TABLE_PROPERTIES = {
    'write.metadata.delete-after-commit.enabled': 'true',
    'write.metadata.previous-versions-max': '1',
}
_logger = logging.getLogger('core.logging')


def _day_from_ts(ts: datetime | None) -> date:
    """Get the date in the configured timezone for daily table partitioning."""
    tz = ZoneInfo(settings.timezone)
    if isinstance(ts, datetime):
        # Convert to configured timezone before extracting date
        return ts.astimezone(tz).date()
    return datetime.now(tz).date()


class IcebergLogWriter:
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
        self._warehouse_path = (self._base_path / 'warehouse').resolve()
        self._warehouse_path.mkdir(parents=True, exist_ok=True)
        self._catalog_path = (self._base_path / 'catalog.db').resolve()
        if not self._catalog_path.exists():
            self._catalog_path.touch()
        self._catalog = load_catalog(
            'local',
            **{
                'type': 'sql',
                'uri': f'sqlite:///{self._catalog_path}',
                'warehouse': f'file://{self._warehouse_path}',
            },
        )
        self._namespace = 'logs'
        self._catalog.create_namespace_if_not_exists(self._namespace)
        self._schema_map = {
            'request_logs': _request_schema(),
            'app_logs': _app_schema(),
            'client_logs': _client_schema(),
        }
        self._arrow_map = {
            'request_logs': _request_arrow_schema(),
            'app_logs': _app_arrow_schema(),
            'client_logs': _client_arrow_schema(),
        }
        self._table_cache: dict[str, Any] = {}
        self._buffers: dict[tuple[str, date], list[dict[str, Any]]] = {}
        self._flush_interval = flush_interval
        self._last_flush = time.monotonic()
        self._worker = threading.Thread(target=self._run, name='iceberg-log-writer', daemon=True)
        self._worker.start()

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
            self._append_rows(kind, day, rows)
        self._last_flush = time.monotonic()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(('__stop__', []))
        self._worker.join(timeout=5)
        self.flush()

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

    def _append_rows(self, kind: str, day: date, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            table = self._get_table(kind, day)
            table.append(pa.Table.from_pylist(rows, schema=self._arrow_map[kind]))
        except Exception as e:
            _logger.error(f'Failed to append {len(rows)} rows to {kind}/{day}: {e}', exc_info=True)

    def _get_table(self, kind: str, day: date):
        name = _daily_table_name(kind, day)
        cached = self._table_cache.get(name)
        if cached:
            return cached
        self._catalog.create_namespace_if_not_exists(self._namespace)
        identifier = f'{self._namespace}.{name}'
        schema = self._schema_map[kind]
        table = self._catalog.create_table_if_not_exists(identifier, schema=schema, properties=_LOG_TABLE_PROPERTIES)
        _apply_table_properties(table)
        self._table_cache[name] = table
        return table


class IcebergLogHandler(logging.Handler):
    def __init__(self, writer: IcebergLogWriter):
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
            _logger.error('Iceberg log handler failed: %s', exc, exc_info=True)
            self.handleError(record)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        writer: IcebergLogWriter | None = None,
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

        # Only read body if within size limit
        content_length = int(request.headers.get('content-length', 0))
        should_log_body = self.max_body_size == 0 or content_length <= self.max_body_size
        body = await request.body() if should_log_body else b''
        body_for_log = body if should_log_body else None

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
            # For streaming responses, only log metadata on first chunk
            # Don't accumulate entire response body
            async def stream_wrapper():
                index = 0
                logged = False
                async for chunk in stream:
                    logged = True
                    # Only log body snippet for first chunk if within size limit
                    part = None
                    if index == 0:
                        raw = chunk.encode('utf-8') if isinstance(chunk, str) else bytes(chunk)
                        if self.max_body_size == 0 or len(raw) <= self.max_body_size:
                            part = raw
                    req_body = request_body if index == 0 else None
                    self._log_request(
                        request,
                        response,
                        duration_ms,
                        request_id,
                        req_body,
                        part,
                        chunk_index=index,
                    )
                    index += 1
                    yield chunk
                if not logged:
                    self._log_request(request, response, duration_ms, request_id, request_body, None, chunk_index=0)

            headers = dict(response.headers)
            headers.pop('content-length', None)
            return StreamingResponse(
                stream_wrapper(),
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
                background=response.background,
            )
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
        # Apply size limit to response body
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
        ip = request.headers.get('x-forwarded-for') or request.client.host if request.client else None
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
            'request_json': self._coerce_body(request.headers.get('content-type'), request_body),
            'response_json': self._coerce_body(response.headers.get('content-type') if response else None, response_body),
            'chunk_index': chunk_index,
        }
        if not self.writer:
            return
        self.writer.write_request_log(payload)

    def _coerce_body(self, content_type: str | None, body: bytes | None) -> str | None:
        if not body:
            return None
        return body.decode('utf-8', errors='ignore')


def configure_logging() -> IcebergLogWriter:
    global _configured, _listener, _writer
    if _configured and _writer:
        return _writer

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    logging.getLogger('httpx').setLevel(logging.WARNING)

    _writer = IcebergLogWriter(
        base_path=str(settings.log_iceberg_path),
        flush_interval=float(settings.log_iceberg_flush_interval_seconds),
        overflow_policy=settings.log_queue_overflow,
    )
    queue_handler = logging.handlers.QueueHandler(queue.Queue())
    _listener = logging.handlers.QueueListener(queue_handler.queue, IcebergLogHandler(_writer))
    _listener.start()
    atexit.register(_listener.stop)
    atexit.register(_writer.stop)

    root_logger = logging.getLogger()
    root_logger.addHandler(queue_handler)
    _configured = True
    return _writer


def get_log_writer() -> IcebergLogWriter:
    if _writer:
        return _writer
    return configure_logging()


def _extract_log_extras(record: logging.LogRecord) -> str | None:
    extras = {key: value for key, value in record.__dict__.items() if key not in _LOG_RECORD_KEYS and key != 'message'}
    if not extras:
        return None
    return json.dumps(extras, default=str)


def _daily_table_name(kind: str, day: date) -> str:
    return f'{kind}_{day.strftime("%Y_%m_%d")}'


def _apply_table_properties(table: Any) -> None:
    try:
        props = table.properties
        updates = {key: value for key, value in _LOG_TABLE_PROPERTIES.items() if props.get(key) != value}
        if not updates:
            return
        updater = table.update_properties()
        for key, value in updates.items():
            updater.set(key, value)
        updater.commit()
    except Exception as e:
        _logger.warning(f'Failed to apply table properties: {e}')


def _request_schema() -> Schema:
    return Schema(
        _field(1, 'ts', TimestampType()),
        _field(2, 'method', StringType()),
        _field(3, 'path', StringType()),
        _field(4, 'status', IntegerType()),
        _field(5, 'duration_ms', DoubleType()),
        _field(6, 'request_id', StringType()),
        _field(7, 'client_id', StringType()),
        _field(8, 'user_agent', StringType()),
        _field(9, 'ip', StringType()),
        _field(10, 'referer', StringType()),
        _field(11, 'error', StringType()),
        _field(12, 'request_json', StringType()),
        _field(13, 'response_json', StringType()),
        _field(14, 'chunk_index', IntegerType()),
    )


def _app_schema() -> Schema:
    return Schema(
        _field(1, 'ts', TimestampType()),
        _field(2, 'level', StringType()),
        _field(3, 'logger', StringType()),
        _field(4, 'message', StringType()),
        _field(5, 'module', StringType()),
        _field(6, 'func', StringType()),
        _field(7, 'line', IntegerType()),
        _field(8, 'extra_json', StringType()),
    )


def _client_schema() -> Schema:
    return Schema(
        _field(1, 'ts', TimestampType()),
        _field(2, 'event', StringType()),
        _field(3, 'action', StringType()),
        _field(4, 'page', StringType()),
        _field(5, 'target', StringType()),
        _field(6, 'form_id', StringType()),
        _field(7, 'fields_json', StringType()),
        _field(8, 'client_id', StringType()),
        _field(9, 'session_id', StringType()),
        _field(10, 'meta_json', StringType()),
    )


def _field(field_id: int, name: str, field_type) -> Any:
    from pyiceberg.types import NestedField

    return NestedField(field_id=field_id, name=name, field_type=field_type, required=False)


def _request_arrow_schema() -> pa.Schema:
    return pa.schema(
        [
            ('ts', pa.timestamp('us')),
            ('method', pa.string()),
            ('path', pa.string()),
            ('status', pa.int32()),
            ('duration_ms', pa.float64()),
            ('request_id', pa.string()),
            ('client_id', pa.string()),
            ('user_agent', pa.string()),
            ('ip', pa.string()),
            ('referer', pa.string()),
            ('error', pa.string()),
            ('request_json', pa.string()),
            ('response_json', pa.string()),
            ('chunk_index', pa.int32()),
        ]
    )


def _app_arrow_schema() -> pa.Schema:
    return pa.schema(
        [
            ('ts', pa.timestamp('us')),
            ('level', pa.string()),
            ('logger', pa.string()),
            ('message', pa.string()),
            ('module', pa.string()),
            ('func', pa.string()),
            ('line', pa.int32()),
            ('extra_json', pa.string()),
        ]
    )


def _client_arrow_schema() -> pa.Schema:
    return pa.schema(
        [
            ('ts', pa.timestamp('us')),
            ('event', pa.string()),
            ('action', pa.string()),
            ('page', pa.string()),
            ('target', pa.string()),
            ('form_id', pa.string()),
            ('fields_json', pa.string()),
            ('client_id', pa.string()),
            ('session_id', pa.string()),
            ('meta_json', pa.string()),
        ]
    )


def _catalog_path(base_path: str) -> str:
    return f'{base_path}/catalog.db'


def _warehouse_path(base_path: str) -> str:
    return f'{base_path}/warehouse'
