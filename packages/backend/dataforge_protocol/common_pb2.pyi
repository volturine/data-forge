from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import enums_pb2 as _enums_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class EmptyRequest(_message.Message):
    __slots__ = ("namespace",)
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    def __init__(self, namespace: _Optional[str] = ...) -> None: ...

class RuntimeWorkerRequest(_message.Message):
    __slots__ = ("worker_id", "protocol_version", "allowed_compute_request_kinds", "target_namespace")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    ALLOWED_COMPUTE_REQUEST_KINDS_FIELD_NUMBER: _ClassVar[int]
    TARGET_NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    protocol_version: int
    allowed_compute_request_kinds: _containers.RepeatedScalarFieldContainer[_enums_pb2.ComputeRequestKind]
    target_namespace: str
    def __init__(self, worker_id: _Optional[str] = ..., protocol_version: _Optional[int] = ..., allowed_compute_request_kinds: _Optional[_Iterable[_Union[_enums_pb2.ComputeRequestKind, str]]] = ..., target_namespace: _Optional[str] = ...) -> None: ...

class RuntimeWorkerResponse(_message.Message):
    __slots__ = ("worker_id",)
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    def __init__(self, worker_id: _Optional[str] = ...) -> None: ...

class NotificationAttachment(_message.Message):
    __slots__ = ("filename", "content_base64", "content_type")
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_BASE64_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    filename: str
    content_base64: str
    content_type: str
    def __init__(self, filename: _Optional[str] = ..., content_base64: _Optional[str] = ..., content_type: _Optional[str] = ...) -> None: ...
