from __future__ import annotations

import contextlib
import functools
import inspect
import io
import json
import math
from collections.abc import Awaitable, Callable, Generator, MutableMapping, Sequence
from concurrent.futures import Future
from contextlib import AbstractContextManager
from types import GeneratorType
from typing import Any, Self, TypedDict, TypeGuard, cast
from urllib.parse import unquote, urljoin

import anyio
import anyio.abc
import anyio.from_thread
import httpx
from anyio.streams.stapled import StapledObjectStream
from fastapi import WebSocketDisconnect

Message = MutableMapping[str, Any]
Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

_PortalFactory = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

ASGIInstance = Callable[[Receive, Send], Awaitable[None]]
ASGI2App = Callable[[Scope], ASGIInstance]
ASGI3App = Callable[[Scope, Receive, Send], Awaitable[None]]
ASGIApp = ASGI2App | ASGI3App


def _is_asgi3(app: ASGI2App | ASGI3App) -> TypeGuard[ASGI3App]:
    app = cast(Any, app)
    while isinstance(app, functools.partial):
        app = app.func
    if inspect.isclass(app):
        return hasattr(app, '__await__')
    if inspect.iscoroutinefunction(app):
        return True
    if not callable(app):
        return False
    return inspect.iscoroutinefunction(cast(Any, app).__call__)


class _WrapASGI2:
    def __init__(self, app: ASGI2App) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope)(receive, send)


class _AsyncBackend(TypedDict):
    backend: str
    backend_options: dict[str, Any]


class _Upgrade(Exception):
    def __init__(self, session: WebSocketTestSession) -> None:
        self.session = session


class WebSocketDenialResponse(httpx.Response, WebSocketDisconnect):  # type: ignore[misc]
    pass


class _TemplateDebugResponse(httpx.Response):
    template: Any
    context: Any


class WebSocketTestSession:
    def __init__(self, app: ASGI3App, scope: Scope, portal_factory: _PortalFactory) -> None:
        self.app = app
        self.scope = scope
        self.portal_factory = portal_factory
        self.accepted_subprotocol: str | None = None
        self.extra_headers: list[tuple[bytes, bytes]] | None = None

    def __enter__(self) -> Self:
        with contextlib.ExitStack() as stack:
            self.portal = portal = stack.enter_context(self.portal_factory())
            fut, cancel_scope = portal.start_task(self._run)
            stack.callback(fut.result)
            stack.callback(portal.call, cancel_scope.cancel)
            self.send({'type': 'websocket.connect'})
            message = self.receive()
            self._raise_on_close(message)
            self.accepted_subprotocol = message.get('subprotocol')
            self.extra_headers = message.get('headers')
            stack.callback(self.close, 1000)
            self.exit_stack = stack.pop_all()
            return self

    def __exit__(self, *args: Any) -> bool | None:
        return self.exit_stack.__exit__(*args)

    async def _run(self, *, task_status: anyio.abc.TaskStatus[anyio.CancelScope]) -> None:
        send_tx, send_rx = anyio.create_memory_object_stream[Message](math.inf)
        receive_tx, receive_rx = anyio.create_memory_object_stream[Message](math.inf)
        with send_tx, send_rx, receive_tx, receive_rx, anyio.CancelScope() as cancel_scope:
            self._receive_tx = receive_tx
            self._send_rx = send_rx
            task_status.started(cancel_scope)
            await self.app(self.scope, receive_rx.receive, send_tx.send)
            await anyio.sleep_forever()

    def _raise_on_close(self, message: Message) -> None:
        if message['type'] == 'websocket.close':
            raise WebSocketDisconnect(code=message.get('code', 1000), reason=message.get('reason', ''))
        if message['type'] == 'websocket.http.response.start':
            status_code = message['status']
            headers = message['headers']
            body: list[bytes] = []
            while True:
                message = self.receive()
                assert message['type'] == 'websocket.http.response.body'
                body.append(message['body'])
                if not message.get('more_body', False):
                    break
            raise WebSocketDenialResponse(status_code=status_code, headers=headers, content=b''.join(body))

    def send(self, message: Message) -> None:
        self.portal.call(self._receive_tx.send, message)

    def send_json(self, data: Any, mode: str = 'text') -> None:
        text = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        if mode == 'text':
            self.send({'type': 'websocket.receive', 'text': text})
            return
        self.send({'type': 'websocket.receive', 'bytes': text.encode('utf-8')})

    def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.send({'type': 'websocket.disconnect', 'code': code, 'reason': reason})

    def receive(self) -> Message:
        return self.portal.call(self._send_rx.receive)

    def receive_json(self, mode: str = 'text') -> Any:
        message = self.receive()
        self._raise_on_close(message)
        payload = message['text'] if mode == 'text' else message['bytes'].decode('utf-8')
        return json.loads(payload)


class _TestClientTransport(httpx.BaseTransport):
    def __init__(
        self,
        app: ASGI3App,
        portal_factory: _PortalFactory,
        raise_server_exceptions: bool,
        root_path: str,
        *,
        client: tuple[str, int],
        app_state: dict[str, Any],
    ) -> None:
        self.app = app
        self.portal_factory = portal_factory
        self.raise_server_exceptions = raise_server_exceptions
        self.root_path = root_path
        self.client = client
        self.app_state = app_state

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        scheme = request.url.scheme
        netloc = request.url.netloc.decode('ascii')
        path = request.url.path
        raw_path = request.url.raw_path
        query = request.url.query.decode('ascii')
        default_port = {'http': 80, 'ws': 80, 'https': 443, 'wss': 443}[scheme]

        if ':' in netloc:
            host, port_string = netloc.split(':', 1)
            port = int(port_string)
        else:
            host = netloc
            port = default_port

        if 'host' in request.headers:
            headers: list[tuple[bytes, bytes]] = []
        elif port == default_port:
            headers = [(b'host', host.encode())]
        else:
            headers = [(b'host', f'{host}:{port}'.encode())]
        headers += [(key.lower().encode(), value.encode()) for key, value in request.headers.multi_items()]

        if scheme in {'ws', 'wss'}:
            subprotocol = request.headers.get('sec-websocket-protocol')
            subprotocols = [] if subprotocol is None else [value.strip() for value in subprotocol.split(',')]
            websocket_scope: dict[str, Any] = {
                'type': 'websocket',
                'path': unquote(path),
                'raw_path': raw_path.split(b'?', 1)[0],
                'root_path': self.root_path,
                'scheme': scheme,
                'query_string': query.encode(),
                'headers': headers,
                'client': self.client,
                'server': [host, port],
                'subprotocols': subprotocols,
                'state': self.app_state.copy(),
                'extensions': {'websocket.http.response': {}},
            }
            raise _Upgrade(WebSocketTestSession(self.app, websocket_scope, self.portal_factory))

        http_scope: dict[str, Any] = {
            'type': 'http',
            'http_version': '1.1',
            'method': request.method,
            'path': unquote(path),
            'raw_path': raw_path.split(b'?', 1)[0],
            'root_path': self.root_path,
            'scheme': scheme,
            'query_string': query.encode(),
            'headers': headers,
            'client': self.client,
            'server': [host, port],
            'extensions': {'http.response.debug': {}},
            'state': self.app_state.copy(),
        }

        request_complete = False
        response_started = False
        response_complete: anyio.Event
        response_stream = io.BytesIO()
        raw_kwargs: dict[str, Any] = {}
        template = None
        context = None

        async def receive() -> Message:
            nonlocal request_complete
            if request_complete:
                if not response_complete.is_set():
                    await response_complete.wait()
                return {'type': 'http.disconnect'}

            body = request.read()
            if isinstance(body, str):
                body_bytes: bytes = body.encode('utf-8')
            elif body is None:
                body_bytes = b''
            elif isinstance(body, GeneratorType):
                try:
                    chunk = body.send(None)
                    if isinstance(chunk, str):
                        chunk = chunk.encode('utf-8')
                    return {'type': 'http.request', 'body': chunk, 'more_body': True}
                except StopIteration:
                    request_complete = True
                    return {'type': 'http.request', 'body': b''}
            else:
                body_bytes = body

            request_complete = True
            return {'type': 'http.request', 'body': body_bytes}

        async def send(message: Message) -> None:
            nonlocal response_started, template, context
            if message['type'] == 'http.response.start':
                assert not response_started, 'Received multiple "http.response.start" messages.'
                raw_kwargs['status_code'] = message['status']
                raw_kwargs['headers'] = [(key.decode(), value.decode()) for key, value in message.get('headers', [])]
                response_started = True
            elif message['type'] == 'http.response.body':
                assert response_started, 'Received "http.response.body" without "http.response.start".'
                assert not response_complete.is_set(), 'Received "http.response.body" after response completed.'
                if request.method != 'HEAD':
                    response_stream.write(message.get('body', b''))
                if not message.get('more_body', False):
                    response_stream.seek(0)
                    response_complete.set()
            elif message['type'] == 'http.response.debug':
                template = message['info']['template']
                context = message['info']['context']

        try:
            with self.portal_factory() as portal:
                response_complete = portal.call(anyio.Event)
                portal.call(self.app, http_scope, receive, send)
        except Exception:
            if self.raise_server_exceptions:
                raise

        if self.raise_server_exceptions:
            assert response_started, 'TestClient did not receive any response.'
        elif not response_started:
            raw_kwargs = {'status_code': 500, 'headers': []}

        if template is None:
            return httpx.Response(
                **raw_kwargs,
                request=request,
                stream=httpx.ByteStream(response_stream.read()),
            )

        response = _TemplateDebugResponse(
            **raw_kwargs,
            request=request,
            stream=httpx.ByteStream(response_stream.read()),
        )
        response.template = template
        response.context = context
        return response


class TestClient(httpx.Client):
    __test__ = False
    task: Future[None]
    portal: anyio.abc.BlockingPortal | None = None

    def __init__(
        self,
        app: ASGIApp,
        base_url: str = 'http://testserver',
        raise_server_exceptions: bool = True,
        root_path: str = '',
        backend: str = 'asyncio',
        backend_options: dict[str, Any] | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
        client: tuple[str, int] = ('testclient', 50000),
    ) -> None:
        self.async_backend = _AsyncBackend(backend=backend, backend_options=backend_options or {})
        asgi_app = app if _is_asgi3(app) else _WrapASGI2(cast(ASGI2App, app))
        self.app = asgi_app
        self.app_state: dict[str, Any] = {}
        transport = _TestClientTransport(
            self.app,
            portal_factory=self._portal_factory,
            raise_server_exceptions=raise_server_exceptions,
            root_path=root_path,
            app_state=self.app_state,
            client=client,
        )
        client_headers = dict(headers or {})
        client_headers.setdefault('user-agent', 'testclient')
        super().__init__(
            base_url=base_url,
            headers=client_headers,
            transport=transport,
            follow_redirects=follow_redirects,
            cookies=cookies,
        )

    @contextlib.contextmanager
    def _portal_factory(self) -> Generator[anyio.abc.BlockingPortal]:
        if self.portal is not None:
            yield self.portal
            return
        with anyio.from_thread.start_blocking_portal(**self.async_backend) as portal:
            yield portal

    def websocket_connect(self, url: str, subprotocols: Sequence[str] | None = None, **kwargs: Any) -> WebSocketTestSession:
        url = urljoin('ws://testserver', url)
        headers = kwargs.get('headers', {})
        headers.setdefault('connection', 'upgrade')
        headers.setdefault('sec-websocket-key', 'testserver==')
        headers.setdefault('sec-websocket-version', '13')
        if subprotocols is not None:
            headers.setdefault('sec-websocket-protocol', ', '.join(subprotocols))
        kwargs['headers'] = headers
        try:
            super().request('GET', url, **kwargs)
        except _Upgrade as exc:
            return exc.session
        raise RuntimeError('Expected WebSocket upgrade')

    def __enter__(self) -> Self:
        with contextlib.ExitStack() as stack:
            self.portal = portal = stack.enter_context(anyio.from_thread.start_blocking_portal(**self.async_backend))
            stack.callback(setattr, self, 'portal', None)

            send_tx, send_rx = anyio.create_memory_object_stream[MutableMapping[str, Any] | None](math.inf)
            receive_tx, receive_rx = anyio.create_memory_object_stream[MutableMapping[str, Any]](math.inf)
            for channel in (send_tx, send_rx, receive_tx, receive_rx):
                stack.callback(channel.close)
            self.stream_send = StapledObjectStream(send_tx, send_rx)
            self.stream_receive = StapledObjectStream(receive_tx, receive_rx)
            self.task = portal.start_task_soon(self.lifespan)
            portal.call(self.wait_startup)
            stack.callback(portal.call, self.wait_shutdown)
            self.exit_stack = stack.pop_all()
        return self

    def __exit__(self, *args: Any) -> None:
        self.exit_stack.close()

    async def lifespan(self) -> None:
        scope = {'type': 'lifespan', 'state': self.app_state}
        try:
            await self.app(scope, self.stream_receive.receive, self.stream_send.send)
        finally:
            await self.stream_send.send(None)

    async def wait_startup(self) -> None:
        await self.stream_receive.send({'type': 'lifespan.startup'})

        async def receive() -> Any:
            message = await self.stream_send.receive()
            if message is None:
                self.task.result()
            return message

        message = await receive()
        assert message['type'] in {'lifespan.startup.complete', 'lifespan.startup.failed'}
        if message['type'] == 'lifespan.startup.failed':
            await receive()

    async def wait_shutdown(self) -> None:
        async def receive() -> Any:
            message = await self.stream_send.receive()
            if message is None:
                self.task.result()
            return message

        await self.stream_receive.send({'type': 'lifespan.shutdown'})
        message = await receive()
        assert message['type'] in {'lifespan.shutdown.complete', 'lifespan.shutdown.failed'}
        if message['type'] == 'lifespan.shutdown.failed':
            await receive()
