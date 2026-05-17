from collections.abc import AsyncIterator

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from core.logging import DatabaseLogKind, DatabaseLogWriter, RequestLoggingMiddleware, redact_logged_body


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


def test_database_log_kind_marks_control_messages() -> None:
    assert DatabaseLogKind.FLUSH.is_control is True
    assert DatabaseLogKind.STOP.is_control is True
    assert DatabaseLogKind.REQUEST.is_control is False


class _InMemoryWriter:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def write_request_log(self, payload: dict) -> None:
        self.payloads.append(payload)


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


class TestRequestLoggingMiddleware:
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
        assert len(writer.payloads) == 1
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
        assert len(writer.payloads) == 1
        assert writer.payloads[0]['path'] == '/stream'
        assert writer.payloads[0]['chunk_index'] == 0
