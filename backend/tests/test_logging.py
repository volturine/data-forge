from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from core.logging import RequestLoggingMiddleware, redact_logged_body


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


class _InMemoryWriter:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def write_request_log(self, payload: dict) -> None:
        self.payloads.append(payload)


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
