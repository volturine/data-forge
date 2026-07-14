import pytest
from google.protobuf.message import Message
from protovalidate import ValidationError, Validator

from dataforge_protocol import compute_pb2, enums_pb2


@pytest.mark.parametrize(
    "message",
    [
        compute_pb2.ComputeCommandEnvelope(
            kind=enums_pb2.COMPUTE_REQUEST_KIND_UNSPECIFIED,
            version=1,
            idempotency_key="request-1",
            correlation_id="request-1",
        ),
        compute_pb2.EngineStatusResult(
            resource_id="analysis-1",
            status=enums_pb2.ENGINE_STATUS_HEALTHY,
            scope=enums_pb2.ENGINE_SCOPE_UNSPECIFIED,
        ),
        compute_pb2.BuildLogEvent(level=enums_pb2.BUILD_LOG_LEVEL_UNSPECIFIED, message="message"),
    ],
    ids=["required-enum", "present-optional-enum", "event-enum"],
)
def test_protocol_enums_reject_unspecified_values(message: Message) -> None:
    with pytest.raises(ValidationError):
        Validator().validate(message)
