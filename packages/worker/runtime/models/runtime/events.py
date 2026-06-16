from __future__ import annotations

from runtime.models.enums import DataForgeStrEnum


class RuntimePayloadKind(DataForgeStrEnum):
    BUILD = "build"
    ENGINE = "engine"
    JOB = "job"
    COMPUTE_REQUEST = "compute_request"
    COMPUTE_RESPONSE = "compute_response"

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> RuntimePayloadKind | None:
        kind = payload.get("kind")
        if not isinstance(kind, str):
            return None
        try:
            return cls(kind)
        except ValueError:
            return None
