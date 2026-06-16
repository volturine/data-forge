from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

import grpc
from google.protobuf.message import Message
from protovalidate import ValidationError, Validator


class ProtovalidateAioInterceptor(grpc.aio.ServerInterceptor):
    def __init__(self) -> None:
        self._validator = Validator()

    async def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], Awaitable[grpc.RpcMethodHandler | None]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        handler = await continuation(handler_call_details)
        if handler is None or handler.unary_unary is None:
            return handler
        unary_unary = cast(
            Callable[[Message, grpc.aio.ServicerContext], Awaitable[Any]],
            handler.unary_unary,
        )

        async def validated_unary_unary(
            request: Message,
            context: grpc.aio.ServicerContext,
        ) -> Any:
            try:
                self._validator.validate(request)
            except ValidationError as exc:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return await unary_unary(request, context)

        return grpc.unary_unary_rpc_method_handler(
            validated_unary_unary,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )
