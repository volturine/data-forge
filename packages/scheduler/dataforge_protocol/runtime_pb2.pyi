from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from dataforge_protocol import compute_pb2 as _compute_pb2
from dataforge_protocol import errors_pb2 as _errors_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RuntimeEvent(_message.Message):
    __slots__ = ("namespace", "build", "compute_command", "compute_response", "error", "raw")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    BUILD_FIELD_NUMBER: _ClassVar[int]
    COMPUTE_COMMAND_FIELD_NUMBER: _ClassVar[int]
    COMPUTE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    RAW_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    build: _compute_pb2.BuildEvent
    compute_command: _compute_pb2.ComputeCommandEnvelope
    compute_response: _compute_pb2.ComputeResponseEnvelope
    error: _errors_pb2.ErrorInfo
    raw: _common_pb2.JsonPayload
    def __init__(self, namespace: _Optional[str] = ..., build: _Optional[_Union[_compute_pb2.BuildEvent, _Mapping]] = ..., compute_command: _Optional[_Union[_compute_pb2.ComputeCommandEnvelope, _Mapping]] = ..., compute_response: _Optional[_Union[_compute_pb2.ComputeResponseEnvelope, _Mapping]] = ..., error: _Optional[_Union[_errors_pb2.ErrorInfo, _Mapping]] = ..., raw: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...
