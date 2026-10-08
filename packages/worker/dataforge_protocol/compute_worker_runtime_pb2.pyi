import datetime

from buf.validate import validate_pb2 as _validate_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ComputeWorkerInitializeRequest(_message.Message):
    __slots__ = ("protocol_version", "engine_identity", "token", "object_store_endpoint", "object_store_region", "object_store_access_key", "object_store_secret_key", "object_store_session_token", "polars_max_threads", "polars_streaming_chunk_size")
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    ENGINE_IDENTITY_FIELD_NUMBER: _ClassVar[int]
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    OBJECT_STORE_ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    OBJECT_STORE_REGION_FIELD_NUMBER: _ClassVar[int]
    OBJECT_STORE_ACCESS_KEY_FIELD_NUMBER: _ClassVar[int]
    OBJECT_STORE_SECRET_KEY_FIELD_NUMBER: _ClassVar[int]
    OBJECT_STORE_SESSION_TOKEN_FIELD_NUMBER: _ClassVar[int]
    POLARS_MAX_THREADS_FIELD_NUMBER: _ClassVar[int]
    POLARS_STREAMING_CHUNK_SIZE_FIELD_NUMBER: _ClassVar[int]
    protocol_version: int
    engine_identity: str
    token: str
    object_store_endpoint: str
    object_store_region: str
    object_store_access_key: str
    object_store_secret_key: str
    object_store_session_token: str
    polars_max_threads: int
    polars_streaming_chunk_size: int
    def __init__(self, protocol_version: _Optional[int] = ..., engine_identity: _Optional[str] = ..., token: _Optional[str] = ..., object_store_endpoint: _Optional[str] = ..., object_store_region: _Optional[str] = ..., object_store_access_key: _Optional[str] = ..., object_store_secret_key: _Optional[str] = ..., object_store_session_token: _Optional[str] = ..., polars_max_threads: _Optional[int] = ..., polars_streaming_chunk_size: _Optional[int] = ...) -> None: ...

class ComputeWorkerInitializeResponse(_message.Message):
    __slots__ = ("engine_identity", "ready")
    ENGINE_IDENTITY_FIELD_NUMBER: _ClassVar[int]
    READY_FIELD_NUMBER: _ClassVar[int]
    engine_identity: str
    ready: bool
    def __init__(self, engine_identity: _Optional[str] = ..., ready: _Optional[bool] = ...) -> None: ...

class ComputeWorkerHealthRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ComputeWorkerHealthResponse(_message.Message):
    __slots__ = ("engine_identity", "protocol_version", "application_version", "ready")
    ENGINE_IDENTITY_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    APPLICATION_VERSION_FIELD_NUMBER: _ClassVar[int]
    READY_FIELD_NUMBER: _ClassVar[int]
    engine_identity: str
    protocol_version: int
    application_version: str
    ready: bool
    def __init__(self, engine_identity: _Optional[str] = ..., protocol_version: _Optional[int] = ..., application_version: _Optional[str] = ..., ready: _Optional[bool] = ...) -> None: ...

class ComputeWorkerSubmitJobRequest(_message.Message):
    __slots__ = ("protocol_version", "job_id", "kind", "payload_json")
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_JSON_FIELD_NUMBER: _ClassVar[int]
    protocol_version: int
    job_id: str
    kind: str
    payload_json: bytes
    def __init__(self, protocol_version: _Optional[int] = ..., job_id: _Optional[str] = ..., kind: _Optional[str] = ..., payload_json: _Optional[bytes] = ...) -> None: ...

class ComputeWorkerJobReference(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class ComputeWorkerWatchJobRequest(_message.Message):
    __slots__ = ("job_id", "after_sequence")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    AFTER_SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    after_sequence: int
    def __init__(self, job_id: _Optional[str] = ..., after_sequence: _Optional[int] = ...) -> None: ...

class ComputeWorkerGetJobResultRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class ComputeWorkerCancelJobRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class ComputeWorkerCancelJobResponse(_message.Message):
    __slots__ = ("accepted",)
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    def __init__(self, accepted: _Optional[bool] = ...) -> None: ...

class ComputeWorkerJobEvent(_message.Message):
    __slots__ = ("job_id", "sequence", "emitted_at", "result", "progress_json")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    EMITTED_AT_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_JSON_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    sequence: int
    emitted_at: _timestamp_pb2.Timestamp
    result: ComputeWorkerJobResult
    progress_json: bytes
    def __init__(self, job_id: _Optional[str] = ..., sequence: _Optional[int] = ..., emitted_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., result: _Optional[_Union[ComputeWorkerJobResult, _Mapping]] = ..., progress_json: _Optional[bytes] = ...) -> None: ...

class ComputeWorkerJobResult(_message.Message):
    __slots__ = ("job_id", "error", "error_kind", "step_timings", "query_plan", "read_duration_ms", "write_duration_ms", "collect_duration_ms", "data_json", "error_details_json")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ERROR_KIND_FIELD_NUMBER: _ClassVar[int]
    STEP_TIMINGS_FIELD_NUMBER: _ClassVar[int]
    QUERY_PLAN_FIELD_NUMBER: _ClassVar[int]
    READ_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    WRITE_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    COLLECT_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    DATA_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAILS_JSON_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    error: str
    error_kind: str
    step_timings: _struct_pb2.Struct
    query_plan: str
    read_duration_ms: float
    write_duration_ms: float
    collect_duration_ms: float
    data_json: bytes
    error_details_json: bytes
    def __init__(self, job_id: _Optional[str] = ..., error: _Optional[str] = ..., error_kind: _Optional[str] = ..., step_timings: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., query_plan: _Optional[str] = ..., read_duration_ms: _Optional[float] = ..., write_duration_ms: _Optional[float] = ..., collect_duration_ms: _Optional[float] = ..., data_json: _Optional[bytes] = ..., error_details_json: _Optional[bytes] = ...) -> None: ...

class ComputeWorkerShutdownRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ComputeWorkerShutdownResponse(_message.Message):
    __slots__ = ("accepted",)
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    def __init__(self, accepted: _Optional[bool] = ...) -> None: ...
