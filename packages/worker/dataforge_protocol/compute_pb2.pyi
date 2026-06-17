import datetime

from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from dataforge_protocol import enums_pb2 as _enums_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class EngineIdentity(_message.Message):
    __slots__ = ("scope", "reuse_policy", "analysis_id", "datasource_id", "build_id")
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    REUSE_POLICY_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    scope: _enums_pb2.EngineScope
    reuse_policy: _enums_pb2.EngineReusePolicy
    analysis_id: str
    datasource_id: str
    build_id: str
    def __init__(self, scope: _Optional[_Union[_enums_pb2.EngineScope, str]] = ..., reuse_policy: _Optional[_Union[_enums_pb2.EngineReusePolicy, str]] = ..., analysis_id: _Optional[str] = ..., datasource_id: _Optional[str] = ..., build_id: _Optional[str] = ...) -> None: ...

class EngineResourceConfig(_message.Message):
    __slots__ = ("max_threads", "max_memory_mb", "streaming_chunk_size")
    MAX_THREADS_FIELD_NUMBER: _ClassVar[int]
    MAX_MEMORY_MB_FIELD_NUMBER: _ClassVar[int]
    STREAMING_CHUNK_SIZE_FIELD_NUMBER: _ClassVar[int]
    max_threads: int
    max_memory_mb: int
    streaming_chunk_size: int
    def __init__(self, max_threads: _Optional[int] = ..., max_memory_mb: _Optional[int] = ..., streaming_chunk_size: _Optional[int] = ...) -> None: ...

class ComputeCommandEnvelope(_message.Message):
    __slots__ = ("kind", "version", "idempotency_key", "correlation_id", "payload")
    KIND_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    kind: _enums_pb2.ComputeRequestKind
    version: int
    idempotency_key: str
    correlation_id: str
    payload: _struct_pb2.Struct
    def __init__(self, kind: _Optional[_Union[_enums_pb2.ComputeRequestKind, str]] = ..., version: _Optional[int] = ..., idempotency_key: _Optional[str] = ..., correlation_id: _Optional[str] = ..., payload: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class ComputeResponseEnvelope(_message.Message):
    __slots__ = ("kind", "version", "correlation_id", "status", "payload", "error_message")
    KIND_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    kind: _enums_pb2.ComputeRequestKind
    version: int
    correlation_id: str
    status: _enums_pb2.ComputeRequestStatus
    payload: _struct_pb2.Struct
    error_message: str
    def __init__(self, kind: _Optional[_Union[_enums_pb2.ComputeRequestKind, str]] = ..., version: _Optional[int] = ..., correlation_id: _Optional[str] = ..., status: _Optional[_Union[_enums_pb2.ComputeRequestStatus, str]] = ..., payload: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., error_message: _Optional[str] = ...) -> None: ...

class BuildEvent(_message.Message):
    __slots__ = ("build_id", "namespace", "occurred_at", "plan", "step_started", "step_completed", "step_failed", "progress", "resources", "log", "completed", "failed", "cancelled")
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    PLAN_FIELD_NUMBER: _ClassVar[int]
    STEP_STARTED_FIELD_NUMBER: _ClassVar[int]
    STEP_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    STEP_FAILED_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    RESOURCES_FIELD_NUMBER: _ClassVar[int]
    LOG_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    FAILED_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_FIELD_NUMBER: _ClassVar[int]
    build_id: str
    namespace: str
    occurred_at: _timestamp_pb2.Timestamp
    plan: _struct_pb2.Struct
    step_started: _struct_pb2.Struct
    step_completed: _struct_pb2.Struct
    step_failed: _struct_pb2.Struct
    progress: _struct_pb2.Struct
    resources: _struct_pb2.Struct
    log: _struct_pb2.Struct
    completed: _struct_pb2.Struct
    failed: _struct_pb2.Struct
    cancelled: _struct_pb2.Struct
    def __init__(self, build_id: _Optional[str] = ..., namespace: _Optional[str] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., plan: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., step_started: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., step_completed: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., step_failed: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., progress: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., resources: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., log: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., completed: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., failed: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., cancelled: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...
