from buf.validate import validate_pb2 as _validate_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class EmptyRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RuntimeWorkerRequest(_message.Message):
    __slots__ = ("worker_id",)
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    def __init__(self, worker_id: _Optional[str] = ...) -> None: ...

class RuntimeWorkerResponse(_message.Message):
    __slots__ = ("worker_id",)
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    def __init__(self, worker_id: _Optional[str] = ...) -> None: ...

class JsonPayload(_message.Message):
    __slots__ = ("value",)
    VALUE_FIELD_NUMBER: _ClassVar[int]
    value: _struct_pb2.Struct
    def __init__(self, value: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class JsonPayloadList(_message.Message):
    __slots__ = ("values",)
    VALUES_FIELD_NUMBER: _ClassVar[int]
    values: _containers.RepeatedCompositeFieldContainer[JsonPayload]
    def __init__(self, values: _Optional[_Iterable[_Union[JsonPayload, _Mapping]]] = ...) -> None: ...

class NotificationAttachment(_message.Message):
    __slots__ = ("filename", "content_base64", "content_type")
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_BASE64_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    filename: str
    content_base64: str
    content_type: str
    def __init__(self, filename: _Optional[str] = ..., content_base64: _Optional[str] = ..., content_type: _Optional[str] = ...) -> None: ...
