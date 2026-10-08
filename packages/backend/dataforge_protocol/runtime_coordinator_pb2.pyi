from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class RuntimeCoordinatorGenerationRequest(_message.Message):
    __slots__ = ("generation",)
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    generation: int
    def __init__(self, generation: _Optional[int] = ...) -> None: ...

class RuntimeCoordinatorGenerationResponse(_message.Message):
    __slots__ = ("generation",)
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    generation: int
    def __init__(self, generation: _Optional[int] = ...) -> None: ...
