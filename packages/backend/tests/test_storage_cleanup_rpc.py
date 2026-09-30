from __future__ import annotations

from typing import NoReturn, cast

import grpc
import pytest

from backend_grpc import server
from dataforge_protocol import worker_runtime_pb2


class Details(grpc.HandlerCallDetails):
    method = f'/{worker_runtime_pb2.DESCRIPTOR.services_by_name["WorkerRuntimeService"].full_name}/AuthorizeStorageCleanup'
    invocation_metadata = ()


@pytest.mark.asyncio
@pytest.mark.parametrize('generation', [None, '6', '7'])
async def test_generated_cleanup_rpc_path_enforces_the_active_coordinator_epoch(monkeypatch: pytest.MonkeyPatch, generation: str | None) -> None:
    monkeypatch.setattr(server, 'active_runtime_coordinator_generation', lambda: 7)
    called = False
    rejected: list[grpc.StatusCode] = []

    async def echo(request: worker_runtime_pb2.WorkerStorageCleanupClaimRequest, _context: grpc.aio.ServicerContext):
        nonlocal called
        called = True
        return request

    async def continuation(_details: grpc.HandlerCallDetails) -> grpc.RpcMethodHandler:
        return grpc.unary_unary_rpc_method_handler(echo)

    class Context:
        def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
            return ((server._RUNTIME_GENERATION_METADATA_KEY, generation),) if generation is not None else ()

        def time_remaining(self) -> None:
            return None

        async def abort(self, status: grpc.StatusCode, _details: str) -> NoReturn:
            rejected.append(status)
            raise RuntimeError('Rejected coordinator epoch')

    interceptor = server._BackendRequestValidationInterceptor()
    handler = await interceptor.intercept_service(continuation, Details())
    assert handler is not None and handler.unary_unary is not None
    request = worker_runtime_pb2.WorkerStorageCleanupClaimRequest(namespace='default', event_id='cleanup', claim_token='token', lease_generation=1)
    if generation == '7':
        assert await handler.unary_unary(request, cast(grpc.ServicerContext, Context())) is request
        assert called and rejected == []
        return
    with pytest.raises(RuntimeError, match='Rejected coordinator epoch'):
        await handler.unary_unary(request, cast(grpc.ServicerContext, Context()))
    assert not called
    assert rejected == [grpc.StatusCode.UNAUTHENTICATED if generation is None else grpc.StatusCode.FAILED_PRECONDITION]
