"""Docker health probe for the runtime coordinator process.

A coordinator container is healthy in two states: the active owner, which must
answer ``GetCoordinatorGeneration`` on its own gRPC port, and a standby, which
holds no lease and serves nothing but must stay alive so it can take over.
A gRPC-only probe would mark every standby unhealthy and block the API, worker
and scheduler of its machine from starting. The process reports its state on a
private Unix socket keyed by PID; the probe reads it and, for the active
state, still verifies the gRPC endpoint as before.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal

_ROLE = 'runtime'
_TOKEN_METADATA_KEY = 'x-internal-token'

CoordinatorState = Literal['starting', 'standby', 'active', 'stopped']


def _socket_path(pid: int) -> Path:
    return Path('/tmp') / f'dataforge-{_ROLE}-health-{pid}.sock'


class CoordinatorHealth:
    """Process-owned coordinator state for the Docker probe."""

    def __init__(self) -> None:
        self.pid = os.getpid()
        self._state: CoordinatorState = 'starting'
        self._generation: int | None = None

    def standby(self) -> None:
        self._state = 'standby'
        self._generation = None

    def active(self, generation: int) -> None:
        self._state = 'active'
        self._generation = generation

    def stopped(self) -> None:
        self._state = 'stopped'
        self._generation = None

    def snapshot(self) -> dict[str, object]:
        return {
            'pid': self.pid,
            'state': self._state,
            'generation': self._generation,
            'healthy': self._state in {'standby', 'active'},
        }

    @contextlib.asynccontextmanager
    async def serve(self) -> AsyncIterator[None]:
        path = _socket_path(self.pid)
        path.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(self._respond, path=str(path))
        try:
            yield
        finally:
            self.stopped()
            server.close()
            await server.wait_closed()
            path.unlink(missing_ok=True)

    async def _respond(self, _reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            writer.write(json.dumps(self.snapshot()).encode())
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()


def _grpc_generation() -> int:
    """Ask the local coordinator gRPC endpoint for its generation (0 when unreachable)."""
    import grpc

    from dataforge_protocol import common_pb2, runtime_coordinator_pb2_grpc

    port = os.environ.get('INTERNAL_GRPC_PORT', '50051')
    token = os.environ.get('INTERNAL_API_TOKEN', '')
    channel = grpc.insecure_channel(f'127.0.0.1:{port}')
    try:
        stub = runtime_coordinator_pb2_grpc.RuntimeCoordinatorServiceStub(channel)
        response = stub.GetCoordinatorGeneration(common_pb2.EmptyRequest(), timeout=3, metadata=((_TOKEN_METADATA_KEY, token),))
        return int(response.generation)
    except grpc.RpcError:
        return 0
    finally:
        channel.close()


def probe(pid: int = 1, *, grpc_generation: Callable[[], int] = _grpc_generation) -> bool:
    """Docker probes PID1's own endpoint; another instance cannot satisfy it."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2.0)
            client.connect(str(_socket_path(pid)))
            chunks: list[bytes] = []
            size = 0
            while chunk := client.recv(4096):
                size += len(chunk)
                if size > 4096:
                    return False
                chunks.append(chunk)
            response = json.loads(b''.join(chunks))
    except OSError, ValueError:
        return False
    if not isinstance(response, dict) or response.get('pid') != pid or response.get('healthy') is not True:
        return False
    if response.get('state') == 'active':
        generation = response.get('generation')
        return isinstance(generation, int) and generation > 0 and grpc_generation() == generation
    return response.get('state') == 'standby'


if __name__ == '__main__':
    raise SystemExit(0 if probe() else 1)
