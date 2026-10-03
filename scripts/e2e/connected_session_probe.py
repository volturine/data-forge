"""Measure authenticated, watched lock WebSockets against an E2E API."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidStatus, WebSocketException

_DEFAULT_PASSWORD = 'E2eTestPw12345'
_HEARTBEAT_TIMEOUT_SECONDS = 20.0
_READINESS_INTERVAL_SECONDS = 5.0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError('must be a positive finite number')
    return parsed


def _ratio(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError('must be between 0 and 1 inclusive')
    return parsed


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sessions', required=True, type=_positive_int)
    parser.add_argument('--api-url', default='http://api:8000')
    parser.add_argument('--namespace', default='default')
    parser.add_argument('--run-id')
    parser.add_argument('--duration-seconds', type=_positive_float, default=60.0)
    parser.add_argument('--active-ratio', type=_ratio, default=0.0)
    parser.add_argument('--heartbeat-seconds', type=_positive_float, default=10.0)
    parser.add_argument('--registration-concurrency', type=_positive_int, default=16)
    parser.add_argument('--connect-concurrency', type=_positive_int, default=64)
    parser.add_argument('--password', default=_DEFAULT_PASSWORD)
    args = parser.parse_args()
    if not args.password:
        parser.error('--password must not be empty')
    if not args.namespace.strip():
        parser.error('--namespace must not be empty')
    if not args.api_url.startswith(('http://', 'https://')):
        parser.error('--api-url must use http:// or https://')
    return args


def _percentiles(samples_ms: list[float]) -> dict[str, float | int | None]:
    ordered = sorted(samples_ms)

    def percentile(fraction: float) -> float | None:
        if not ordered:
            return None
        return round(ordered[math.ceil(fraction * len(ordered)) - 1], 2)

    return {
        'count': len(ordered),
        'p50_ms': percentile(0.50),
        'p95_ms': percentile(0.95),
        'p99_ms': percentile(0.99),
    }


def _is_success_status(status: str) -> bool:
    return status.isdecimal() and 200 <= int(status) < 300


def _session_token(response: httpx.Response) -> str | None:
    cookies = SimpleCookie()
    for header in response.headers.get_list('set-cookie'):
        cookies.load(header)
    morsel = cookies.get('session_token')
    return morsel.value if morsel is not None and morsel.value else None


def _exception_chain(exc: BaseException) -> str:
    details: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and len(details) < 4 and id(current) not in seen:
        seen.add(id(current))
        message = 'cancelled' if isinstance(current, asyncio.CancelledError) else ' '.join(str(current).split())[:160]
        details.append(f'{type(current).__name__}: {message}' if message else type(current).__name__)
        current = current.__cause__ or current.__context__
    return ' <- '.join(details)


async def _receive_json(socket: ClientConnection, timeout_seconds: float) -> dict[str, object]:
    raw = await asyncio.wait_for(socket.recv(), timeout=timeout_seconds)
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise TypeError('WebSocket response was not a JSON object')
    return message


async def _register_account(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    *,
    email: str,
    password: str,
    display_name: str,
) -> tuple[bool, str | None, str | None]:
    async with semaphore:
        try:
            response = await client.post(
                '/api/v1/auth/register',
                json={
                    'email': email,
                    'password': password,
                    'display_name': display_name,
                },
            )
        except httpx.HTTPError:
            return False, None, 'transport'
        if response.status_code < 200 or response.status_code >= 300:
            return False, None, f'http_{response.status_code}'
        token = _session_token(response)
        return True, token, None if token is not None else 'missing_cookie'


async def _open_socket(
    ws_url: str,
    token: str,
    resource_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[ClientConnection | None, float | None, float | None, str | None]:
    async with semaphore:
        started = time.perf_counter()
        try:
            socket = await connect(
                ws_url,
                additional_headers={'Cookie': f'session_token={token}'},
                open_timeout=20,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=20,
                max_size=1_048_576,
            )
        except InvalidStatus as exc:
            status_code = getattr(exc.response, 'status_code', 'unknown')
            return None, None, None, f'websocket_http_{status_code}'
        except OSError, TimeoutError, ValueError, WebSocketException:
            return None, None, None, 'websocket_connect'
        connection_ms = (time.perf_counter() - started) * 1000

        try:
            connected = await _receive_json(socket, 20)
        except asyncio.CancelledError:
            await socket.close()
            raise
        except OSError, TimeoutError, TypeError, ValueError, WebSocketException:
            await socket.close()
            return None, connection_ms, None, 'websocket_handshake'
        if connected.get('type') != 'connected':
            status_code = connected.get('status_code')
            failure = f'websocket_auth_{status_code}' if isinstance(status_code, int) else 'websocket_auth'
            await socket.close()
            return None, connection_ms, None, failure
        try:
            await socket.send(
                json.dumps(
                    {
                        'action': 'watch',
                        'resource_type': 'analysis',
                        'resource_id': resource_id,
                    },
                    separators=(',', ':'),
                )
            )
            status = await _receive_json(socket, 20)
        except asyncio.CancelledError:
            await socket.close()
            raise
        except OSError, TimeoutError, TypeError, ValueError, WebSocketException:
            await socket.close()
            return None, connection_ms, None, 'watch'
        if status.get('type') != 'status' or status.get('resource_type') != 'analysis' or status.get('resource_id') != resource_id:
            status_code = status.get('status_code')
            failure = f'watch_http_{status_code}' if isinstance(status_code, int) else 'watch'
            await socket.close()
            return None, connection_ms, None, failure
        ready_ms = (time.perf_counter() - started) * 1000
        return socket, connection_ms, ready_ms, None


async def _heartbeat_session(
    socket: ClientConnection,
    resource_id: str,
    index: int,
    *,
    interval_seconds: float,
    steady_started: float,
    steady_ends: float,
    heartbeat_latencies: list[float],
    errors: Counter[str],
    live_sockets: set[ClientConnection],
) -> None:
    # A stable irrational phase spreads the first pings without random jitter.
    phase = (index * 0.6180339887498949) % 1.0
    next_ping = steady_started + phase * interval_seconds
    loop = asyncio.get_running_loop()
    try:
        while next_ping < steady_ends:
            await asyncio.sleep(max(0.0, next_ping - loop.time()))
            if loop.time() >= steady_ends:
                break
            sent_at = time.perf_counter()
            await socket.send('{"action":"ping"}')
            response = await _receive_json(socket, _HEARTBEAT_TIMEOUT_SECONDS)
            if response.get('type') != 'status' or response.get('resource_type') != 'analysis' or response.get('resource_id') != resource_id:
                status_code = response.get('status_code')
                error = f'heartbeat_status_{status_code}' if isinstance(status_code, int) else 'heartbeat'
                errors[error] += 1
                live_sockets.discard(socket)
                return
            heartbeat_latencies.append((time.perf_counter() - sent_at) * 1000)
            next_ping += interval_seconds
            if next_ping <= loop.time():
                next_ping = loop.time() + interval_seconds
    except asyncio.CancelledError:
        raise
    except OSError, TimeoutError, TypeError, ValueError, WebSocketException:
        errors['heartbeat'] += 1
        live_sockets.discard(socket)


async def _monitor_readiness(
    client: httpx.AsyncClient,
    stop: asyncio.Event,
    latencies_ms: list[float],
    statuses: Counter[str],
    last_status: list[str | None],
    transport_errors: Counter[str],
    errors: Counter[str],
) -> None:
    loop = asyncio.get_running_loop()
    next_poll = loop.time()
    while not stop.is_set():
        started = time.perf_counter()
        try:
            response = await client.get('/health/ready')
            latencies_ms.append((time.perf_counter() - started) * 1000)
            last_status[0] = str(response.status_code)
            statuses[last_status[0]] += 1
            if response.status_code != 200:
                errors[f'readiness_http_{response.status_code}'] += 1
        except httpx.HTTPError as exc:
            latencies_ms.append((time.perf_counter() - started) * 1000)
            error_type = type(exc).__name__
            last_status[0] = f'error:{error_type}'
            statuses[last_status[0]] += 1
            transport_errors[error_type] += 1
            errors[f'readiness_{error_type}'] += 1
        next_poll += _READINESS_INTERVAL_SECONDS
        delay = max(0.0, next_poll - loop.time())
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            continue


_PROFILE_ROUTES = (
    '/api/v1/analysis',
    '/api/v1/datasource',
    '/api/v1/udf',
    '/api/v1/settings',
)
_PROFILE_INTERVAL_SECONDS = 20.0
_PROFILE_HTTP_SESSIONS_PER_CLIENT = 64


@dataclass
class _ProfileOperationMetrics:
    client_latency_ms: list[float] = field(default_factory=list)
    server_app_ms: list[float] = field(default_factory=list)
    api_blocking_admission_ms: list[float] = field(default_factory=list)
    api_server_timings_ms: dict[str, list[float]] = field(default_factory=dict)
    client_network_timings_ms: dict[str, list[float]] = field(default_factory=dict)
    client_network_trace_samples: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    errors: Counter[str] = field(default_factory=Counter)
    error_details: Counter[str] = field(default_factory=Counter)


def _record_httpx_trace(
    operation_metrics: _ProfileOperationMetrics,
    request_started: float,
    events: list[tuple[str, float]],
) -> None:
    operation_metrics.client_network_trace_samples += 1

    def first_event(name: str) -> float | None:
        return next((timestamp for event_name, timestamp in events if event_name == name), None)

    connect_started = first_event('connection.connect_tcp.started')
    connect_completed = first_event('connection.connect_tcp.complete')
    headers_sent = first_event('http11.send_request_headers.started')
    response_headers_received = first_event('http11.receive_response.complete')
    body_started = first_event('http11.receive_response_body.started')
    body_completed = first_event('http11.receive_response_body.complete')

    timings: dict[str, float] = {}
    pool_ready_at = connect_started if connect_started is not None else headers_sent
    if pool_ready_at is not None:
        timings['pool_wait'] = (pool_ready_at - request_started) * 1000
    if connect_started is not None and connect_completed is not None:
        timings['tcp_connect'] = (connect_completed - connect_started) * 1000
    if headers_sent is not None and response_headers_received is not None:
        timings['response_headers'] = (response_headers_received - headers_sent) * 1000
    if body_started is not None and body_completed is not None:
        timings['response_body'] = (body_completed - body_started) * 1000
    for name, duration in timings.items():
        operation_metrics.client_network_timings_ms.setdefault(name, []).append(max(duration, 0.0))


async def _profile_request(
    client: httpx.AsyncClient,
    operation: str,
    path: str,
    *,
    session_token: str,
    method: str = 'GET',
    json_body: dict[str, object] | None = None,
    capture_trace: bool = False,
    metrics: dict[str, _ProfileOperationMetrics],
) -> None:
    started = time.perf_counter()
    operation_metrics = metrics[operation]
    trace_events: list[tuple[str, float]] = []

    async def trace(event_name: str, _info: dict[str, object]) -> None:
        trace_events.append((event_name, time.perf_counter()))

    try:
        request_options: dict[str, object] = {}
        if capture_trace:
            # HTTPX's trace extension reports connection-pool, TCP, and HTTP/1.1 phases.
            request_options['extensions'] = {'trace': trace}
        response = await client.request(
            method,
            path,
            headers={'Cookie': f'session_token={session_token}'},
            json=json_body,
            **request_options,
        )
        operation_metrics.statuses[str(response.status_code)] += 1
        if response.status_code < 200 or response.status_code >= 300:
            operation_metrics.errors[f'http_{response.status_code}'] += 1
        server_timing = response.headers.get('server-timing', '')
        app_duration = re.search(r'app;dur=([\d.]+)', server_timing)
        if app_duration is not None:
            operation_metrics.server_app_ms.append(float(app_duration.group(1)))
        admission_wait = re.search(r'api-blocking-admission;dur=([\d.]+)', server_timing)
        if admission_wait is not None:
            operation_metrics.api_blocking_admission_ms.append(float(admission_wait.group(1)))
        for timing_name in (
            'api-bootstrap-admission',
            'api-general-admission',
            'api-bootstrap-executor-queue',
            'api-general-executor-queue',
            'api-bootstrap-work',
            'api-general-work',
        ):
            timing = re.search(rf'{timing_name};dur=([\d.]+)', server_timing)
            if timing is not None:
                operation_metrics.api_server_timings_ms.setdefault(timing_name, []).append(float(timing.group(1)))
    except httpx.HTTPError as exc:
        operation_metrics.statuses[f'error:{type(exc).__name__}'] += 1
        operation_metrics.errors[type(exc).__name__] += 1
        operation_metrics.error_details[_exception_chain(exc)] += 1
    finally:
        operation_metrics.client_latency_ms.append((time.perf_counter() - started) * 1000)
        if capture_trace:
            _record_httpx_trace(operation_metrics, started, trace_events)


async def _profile_session(
    client: httpx.AsyncClient,
    index: int,
    session_token: str,
    *,
    steady_started: float,
    steady_ends: float,
    stop: asyncio.Event,
    metrics: dict[str, _ProfileOperationMetrics],
) -> None:
    loop = asyncio.get_running_loop()
    phase = (index * 0.6180339887498949) % 1.0
    capture_trace = index % 16 == 0
    next_cycle = steady_started + phase * _PROFILE_INTERVAL_SECONDS
    cycle_number = 1
    route = _PROFILE_ROUTES[index % len(_PROFILE_ROUTES)]
    route_operation = route.rsplit('/', 1)[-1]
    while next_cycle < steady_ends and not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.0, next_cycle - loop.time()))
            return
        except TimeoutError:
            pass
        if stop.is_set() or loop.time() >= steady_ends:
            return

        await asyncio.gather(
            _profile_request(
                client, 'auth_me', '/api/v1/auth/me',
                session_token=session_token,
                capture_trace=capture_trace,
                metrics=metrics,
            ),
            _profile_request(
                client, 'config', '/api/v1/config',
                session_token=session_token,
                capture_trace=capture_trace,
                metrics=metrics,
            ),
        )
        await _profile_request(
            client,
            route_operation,
            route,
            session_token=session_token,
            capture_trace=capture_trace,
            metrics=metrics,
        )
        if cycle_number % 3 == 0:
            await _profile_request(
                client,
                'profile_update',
                '/api/v1/auth/profile',
                method='PUT',
                session_token=session_token,
                capture_trace=capture_trace,
                json_body={
                    'preferences': {
                        'capacity_probe': 'active-v1',
                        'cycle_number': cycle_number,
                    }
                },
                metrics=metrics,
            )
        cycle_number += 1
        next_cycle = loop.time() + _PROFILE_INTERVAL_SECONDS


def _profile_summary(
    active_ratio: float,
    active_count: int,
    elapsed_seconds: float,
    metrics: dict[str, _ProfileOperationMetrics],
    *,
    http_client_count: int,
    http_connections_per_client: int,
) -> dict[str, object]:
    completed_requests = sum(
        count
        for operation_metrics in metrics.values()
        for status, count in operation_metrics.statuses.items()
        if _is_success_status(status)
    )
    operations = {
        operation: {
            'request_count': len(operation_metrics.client_latency_ms),
            'completed_requests': sum(
                count for status, count in operation_metrics.statuses.items() if _is_success_status(status)
            ),
            'status_counts': dict(sorted(operation_metrics.statuses.items())),
            'errors': dict(sorted(operation_metrics.errors.items())),
            'error_details': dict(sorted(operation_metrics.error_details.items())),
            'client_latency': _percentiles(operation_metrics.client_latency_ms),
            'server_app_latency': _percentiles(operation_metrics.server_app_ms),
            'api_blocking_admission_wait': _percentiles(operation_metrics.api_blocking_admission_ms),
            'api_server_timings': {
                name: _percentiles(samples) for name, samples in sorted(operation_metrics.api_server_timings_ms.items())
            },
            'client_network_trace_samples': operation_metrics.client_network_trace_samples,
            'client_network_timings': {
                name: _percentiles(samples) for name, samples in sorted(operation_metrics.client_network_timings_ms.items())
            },
            'server_timing_missing': len(operation_metrics.client_latency_ms) - len(operation_metrics.server_app_ms),
        }
        for operation, operation_metrics in sorted(metrics.items())
    }
    request_count = sum(len(operation.client_latency_ms) for operation in metrics.values())
    failure_count = sum(sum(operation.errors.values()) for operation in metrics.values())
    return {
        'assumptions': {
            'profile': 'active authenticated sessions repeat AppBootstrap, one stable-index collection GET, and periodic profile updates',
            'cycle_interval_seconds': _PROFILE_INTERVAL_SECONDS,
            'cycle_order': 'concurrent auth/me and config GETs, then selected route GET, then optional profile PUT',
            'bootstrap_requests_concurrent': True,
            'profile_update_every_cycles': 3,
            'retries': 0,
            'route_selection': 'stable session index modulo four; evenly distributed across all listed routes',
            'routes': list(_PROFILE_ROUTES),
            'think_time_after_cycle_seconds': _PROFILE_INTERVAL_SECONDS,
            'http_client_connection_limit': http_client_count * http_connections_per_client,
            'http_clients': http_client_count,
            'http_connections_per_client': http_connections_per_client,
            'http_sessions_per_client_target': _PROFILE_HTTP_SESSIONS_PER_CLIENT,
            'per_account_max_concurrency': 2,
            'http_keepalive_expiry_seconds': 2.0,
        },
        'active_ratio': active_ratio,
        'active_user_count': active_count,
        'cycle_interval_seconds': _PROFILE_INTERVAL_SECONDS,
        'operations': operations,
        'completed_requests': completed_requests,
        'request_count': request_count,
        'aggregate_requests_per_second': round(completed_requests / elapsed_seconds, 3) if elapsed_seconds > 0 else 0.0,
        'http_failures': failure_count,
        'duration_seconds': round(elapsed_seconds, 3),
    }


async def _run(args: argparse.Namespace) -> int:
    run_id = args.run_id or datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    email_stamp = re.sub(r'[^a-zA-Z0-9-]', '-', run_id).strip('-')[:24]
    if not email_stamp:
        email_stamp = uuid4().hex[:12]
    email_stamp = f'{email_stamp}-{uuid4().hex[:8]}'
    errors: Counter[str] = Counter()
    registration_statuses: Counter[str] = Counter()
    connection_latencies: list[float] = []
    session_ready_latencies: list[float] = []
    heartbeat_latencies: list[float] = []
    readiness_latencies: list[float] = []
    readiness_statuses: Counter[str] = Counter()
    readiness_transport_errors: Counter[str] = Counter()
    readiness_last_status: list[str | None] = [None]
    sockets: list[ClientConnection] = []
    socket_resources: dict[ClientConnection, str] = {}
    live_sockets: set[ClientConnection] = set()
    heartbeat_tasks: list[asyncio.Task[None]] = []
    monitor_stop = asyncio.Event()
    monitor_task: asyncio.Task[None] | None = None
    steady_elapsed = 0.0
    started_at = time.perf_counter()
    registered_accounts = 0
    registered_tokens: list[str] = []
    registered_profile_users: list[tuple[int, str]] = []
    websocket_profile_tokens: set[str] = set()
    profile_clients: list[httpx.AsyncClient] = []
    profile_tasks: list[asyncio.Task[None]] = []
    profile_stop = asyncio.Event()
    profile_metrics = {
        name: _ProfileOperationMetrics()
        for name in ('auth_me', 'config', *(route.rsplit('/', 1)[-1] for route in _PROFILE_ROUTES), 'profile_update')
    }
    profile_elapsed = 0.0
    active_profile_count = 0
    profile_client_count = 0
    profile_connections_per_client = 0
    registration_elapsed = 0.0
    connection_elapsed = 0.0
    websocket_url = args.api_url.rstrip('/') + '/api/v1/locks/ws?' + urlencode({'namespace': args.namespace})
    websocket_url = websocket_url.replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)

    timeout = httpx.Timeout(15.0, connect=10.0, pool=10.0)
    limits = httpx.Limits(
        max_connections=args.registration_concurrency + 2,
        max_keepalive_connections=args.registration_concurrency,
    )
    # The probe polls every five seconds, matching Uvicorn's default keep-alive
    # timeout. Expire this client connection sooner so the next poll never races
    # the server closing an idle keep-alive socket.
    readiness_limits = httpx.Limits(
        max_connections=2,
        max_keepalive_connections=1,
        keepalive_expiry=2.0,
    )
    async with (
        httpx.AsyncClient(base_url=args.api_url.rstrip('/'), timeout=timeout, limits=limits) as client,
        httpx.AsyncClient(base_url=args.api_url.rstrip('/'), timeout=timeout, limits=readiness_limits) as readiness_client,
    ):
        monitor_task = asyncio.create_task(
            _monitor_readiness(
                readiness_client,
                monitor_stop,
                readiness_latencies,
                readiness_statuses,
                readiness_last_status,
                readiness_transport_errors,
                errors,
            )
        )
        try:
            registration_slots = asyncio.Semaphore(args.registration_concurrency)
            registration_started = time.perf_counter()
            registrations = await asyncio.gather(
                *(
                    _register_account(
                        client,
                        registration_slots,
                        email=f'e2e-{email_stamp}-{index}@example.com',
                        password=args.password,
                        display_name=f'E2E Connected Session {index + 1}',
                    )
                    for index in range(args.sessions)
                )
            )
            registration_elapsed = time.perf_counter() - registration_started
            for index, (registered, token, failure) in enumerate(registrations):
                if not registered:
                    errors['registration'] += 1
                    registration_statuses[failure or 'unknown'] += 1
                    continue
                registered_accounts += 1
                if token is None:
                    errors['session_cookie'] += 1
                    registration_statuses[failure or 'missing_cookie'] += 1
                    continue
                registered_tokens.append(token)
                registered_profile_users.append((index, token))

            socket_slots = asyncio.Semaphore(args.connect_concurrency)
            connection_started = time.perf_counter()
            results = await asyncio.gather(
                *(
                    _open_socket(
                        websocket_url,
                        token,
                        f'e2e-{email_stamp}-{index}',
                        socket_slots,
                    )
                    for index, token in enumerate(registered_tokens)
                )
            )
            connection_elapsed = time.perf_counter() - connection_started
            for index, (socket, handshake_ms, ready_ms, failure) in enumerate(results):
                if handshake_ms is not None:
                    connection_latencies.append(handshake_ms)
                if ready_ms is not None:
                    session_ready_latencies.append(ready_ms)
                if failure is not None:
                    errors[failure] += 1
                if socket is None:
                    continue
                sockets.append(socket)
                socket_resources[socket] = f'e2e-{email_stamp}-{index}'
                live_sockets.add(socket)
                websocket_profile_tokens.add(registered_tokens[index])

            steady_started = asyncio.get_running_loop().time()
            steady_ends = steady_started + args.duration_seconds
            steady_wall_started = time.perf_counter()
            active_count = min(math.ceil(args.sessions * args.active_ratio), len(registered_profile_users))
            active_profile_users = [
                (index, token)
                for index, token in registered_profile_users
                if token in websocket_profile_tokens
            ][:active_count]
            active_count = len(active_profile_users)
            active_profile_count = active_count
            profile_started = time.perf_counter()
            if active_profile_users:
                profile_client_count = math.ceil(active_count / _PROFILE_HTTP_SESSIONS_PER_CLIENT)
                profile_connections_per_client = math.ceil(active_count * 2 / profile_client_count) + 8
                profile_clients = [
                    httpx.AsyncClient(
                        base_url=args.api_url.rstrip('/'),
                        timeout=timeout,
                        limits=httpx.Limits(
                            max_connections=profile_connections_per_client,
                            max_keepalive_connections=profile_connections_per_client,
                            keepalive_expiry=2.0,
                        ),
                    )
                    for _ in range(profile_client_count)
                ]
                profile_tasks = [
                    asyncio.create_task(
                        _profile_session(
                            profile_clients[session_index % profile_client_count],
                            index,
                            token,
                            steady_started=steady_started,
                            steady_ends=steady_ends,
                            stop=profile_stop,
                            metrics=profile_metrics,
                        )
                    )
                    for session_index, (index, token) in enumerate(active_profile_users)
                ]
            heartbeat_tasks = [
                asyncio.create_task(
                    _heartbeat_session(
                        socket,
                        socket_resources[socket],
                        index,
                        interval_seconds=args.heartbeat_seconds,
                        steady_started=steady_started,
                        steady_ends=steady_ends,
                        heartbeat_latencies=heartbeat_latencies,
                        errors=errors,
                        live_sockets=live_sockets,
                    )
                )
                for index, socket in enumerate(sockets)
            ]
            await asyncio.sleep(args.duration_seconds)
            steady_elapsed = time.perf_counter() - steady_wall_started
            profile_stop.set()
            if profile_tasks:
                await asyncio.gather(*profile_tasks)
                profile_elapsed = time.perf_counter() - profile_started
            for socket in live_sockets.copy():
                if socket.state.name != 'OPEN':
                    live_sockets.discard(socket)
                    errors['heartbeat'] += 1
        finally:
            profile_stop.set()
            if profile_tasks:
                await asyncio.gather(*profile_tasks, return_exceptions=True)
            if profile_clients:
                await asyncio.gather(*(client.aclose() for client in profile_clients), return_exceptions=True)
            monitor_stop.set()
            if monitor_task is not None:
                monitor_task.cancel()
                await asyncio.gather(monitor_task, return_exceptions=True)
            for task in heartbeat_tasks:
                task.cancel()
            if heartbeat_tasks:
                await asyncio.gather(*heartbeat_tasks, return_exceptions=True)
            if sockets:
                await asyncio.gather(*(socket.close() for socket in sockets), return_exceptions=True)

    total_elapsed = time.perf_counter() - started_at
    profile_result = None
    if args.active_ratio > 0:
        profile_result = _profile_summary(
            args.active_ratio,
            active_profile_count,
            profile_elapsed,
            profile_metrics,
            http_client_count=profile_client_count,
            http_connections_per_client=profile_connections_per_client,
        )
        for operation, operation_metrics in profile_metrics.items():
            for error, count in operation_metrics.errors.items():
                errors[f'http_profile_{operation}_{error}'] += count
    error_counts = dict(sorted(errors.items()))
    summary = {
        'run_id': run_id,
        'namespace': args.namespace,
        'requested_sessions': args.sessions,
        'registered_accounts': registered_accounts,
        'distinct_accounts': registered_accounts,
        'distinct_tokens': len(set(registered_tokens)),
        'registration_duration_seconds': round(registration_elapsed, 3),
        'connection_establishment_seconds': round(connection_elapsed, 3),
        'opened_sockets': len(sockets),
        'websocket_handshakes': len(connection_latencies),
        'sessions_ready': len(session_ready_latencies),
        'sockets_open_at_end': len(live_sockets),
        'websocket_handshake_latency': _percentiles(connection_latencies),
        'session_ready_latency': _percentiles(session_ready_latencies),
        'heartbeat_rtt': _percentiles(heartbeat_latencies),
        'readiness': {
            'latency': _percentiles(readiness_latencies),
            'status_counts': dict(sorted(readiness_statuses.items())),
            'transport_errors': dict(sorted(readiness_transport_errors.items())),
            'last_status': readiness_last_status[0],
        },
        'steady_duration_seconds': round(steady_elapsed, 3),
        'total_duration_seconds': round(total_elapsed, 3),
        'registration_statuses': dict(sorted(registration_statuses.items())),
        'errors': {'total': sum(errors.values()), 'by_operation': error_counts},
    }
    if profile_result is not None:
        summary['http_profile'] = profile_result
    print(json.dumps(summary, sort_keys=True, separators=(',', ':')))
    return int(
        sum(errors.values()) > 0
        or registered_accounts != args.sessions
        or len(registered_tokens) != args.sessions
        or len(sockets) != args.sessions
        or len(live_sockets) != args.sessions
        or len(set(registered_tokens)) != args.sessions
        or (profile_result is not None and profile_result['http_failures'] > 0)
    )


def main() -> None:
    args = _arguments()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == '__main__':
    main()
