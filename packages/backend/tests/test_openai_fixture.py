from __future__ import annotations

import io
import socket
from http.server import ThreadingHTTPServer
from typing import cast

import pytest
from scripts.e2e.openai_fixture import OpenAIFixtureHandler


class _DisconnectingWriter:
    def __init__(self, error: Exception, *, fail_on_headers: bool) -> None:
        self.error = error
        self.fail_on_headers = fail_on_headers
        self.headers_written = False
        self.closed = False

    def write(self, data: bytes) -> int:
        if self.fail_on_headers or self.headers_written:
            raise self.error
        self.headers_written = data.endswith(b'\r\n\r\n')
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _RequestSocket:
    def __init__(self, writer: _DisconnectingWriter) -> None:
        self.writer = writer

    def makefile(self, mode: str, _buffering: int = -1) -> io.BytesIO | _DisconnectingWriter:
        if mode == 'rb':
            return io.BytesIO(b'GET /health HTTP/1.1\r\nHost: fixture\r\n\r\n')
        return self.writer

    def sendall(self, data: bytes) -> None:
        self.writer.write(data)

    def close(self) -> None:
        return None


def _run_handler(writer: _DisconnectingWriter) -> OpenAIFixtureHandler:
    request = cast(socket.socket, _RequestSocket(writer))
    server = cast(ThreadingHTTPServer, None)
    return OpenAIFixtureHandler(request, ('fixture-client', 12345), server)


@pytest.mark.parametrize('error_type', [BrokenPipeError, ConnectionResetError])
@pytest.mark.parametrize('fail_on_headers', [True, False], ids=['headers', 'body'])
def test_handler_closes_expected_client_disconnects(error_type: type[OSError], fail_on_headers: bool) -> None:
    writer = _DisconnectingWriter(error_type('client disconnected'), fail_on_headers=fail_on_headers)

    handler = _run_handler(writer)

    assert handler.close_connection is True


def test_handler_still_propagates_unexpected_write_errors() -> None:
    writer = _DisconnectingWriter(RuntimeError('unexpected write failure'), fail_on_headers=False)

    with pytest.raises(RuntimeError, match='unexpected write failure'):
        _run_handler(writer)
