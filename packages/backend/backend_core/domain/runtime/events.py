from __future__ import annotations

from typing import ClassVar, Self

from backend_core.domain.api_enums import ApiEnumValue, api_token
from dataforge_protocol import enums_pb2


class RuntimePayloadKind(ApiEnumValue):
    BUILD: ClassVar[Self]
    ENGINE: ClassVar[Self]
    JOB: ClassVar[Self]
    COMPUTE_REQUEST: ClassVar[Self]
    COMPUTE_RESPONSE: ClassVar[Self]

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> RuntimePayloadKind | None:
        kind = payload.get('kind')
        if not isinstance(kind, str):
            return None
        try:
            return cls.require(kind)
        except ValueError:
            return None


RuntimePayloadKind.BUILD = RuntimePayloadKind(enums_pb2.RUNTIME_PAYLOAD_KIND_BUILD, api_token('RuntimePayloadKind', enums_pb2.RUNTIME_PAYLOAD_KIND_BUILD))
RuntimePayloadKind.ENGINE = RuntimePayloadKind(enums_pb2.RUNTIME_PAYLOAD_KIND_ENGINE, api_token('RuntimePayloadKind', enums_pb2.RUNTIME_PAYLOAD_KIND_ENGINE))
RuntimePayloadKind.JOB = RuntimePayloadKind(enums_pb2.RUNTIME_PAYLOAD_KIND_JOB, api_token('RuntimePayloadKind', enums_pb2.RUNTIME_PAYLOAD_KIND_JOB))
RuntimePayloadKind.COMPUTE_REQUEST = RuntimePayloadKind(
    enums_pb2.RUNTIME_PAYLOAD_KIND_COMPUTE_REQUEST, api_token('RuntimePayloadKind', enums_pb2.RUNTIME_PAYLOAD_KIND_COMPUTE_REQUEST)
)
RuntimePayloadKind.COMPUTE_RESPONSE = RuntimePayloadKind(
    enums_pb2.RUNTIME_PAYLOAD_KIND_COMPUTE_RESPONSE, api_token('RuntimePayloadKind', enums_pb2.RUNTIME_PAYLOAD_KIND_COMPUTE_RESPONSE)
)
