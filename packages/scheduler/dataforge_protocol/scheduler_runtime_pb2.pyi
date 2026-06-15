from dataforge_protocol import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SchedulerRegisterRequest(_message.Message):
    __slots__ = ("worker_id", "hostname", "pid", "capacity")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    HOSTNAME_FIELD_NUMBER: _ClassVar[int]
    PID_FIELD_NUMBER: _ClassVar[int]
    CAPACITY_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    hostname: str
    pid: int
    capacity: int
    def __init__(self, worker_id: _Optional[str] = ..., hostname: _Optional[str] = ..., pid: _Optional[int] = ..., capacity: _Optional[int] = ...) -> None: ...

class SchedulerEnqueuedRun(_message.Message):
    __slots__ = ("namespace", "schedule_id", "datasource_id", "build_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    schedule_id: str
    datasource_id: str
    build_id: str
    def __init__(self, namespace: _Optional[str] = ..., schedule_id: _Optional[str] = ..., datasource_id: _Optional[str] = ..., build_id: _Optional[str] = ...) -> None: ...

class SchedulerRunFailure(_message.Message):
    __slots__ = ("namespace", "schedule_id", "datasource_id", "error")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    schedule_id: str
    datasource_id: str
    error: str
    def __init__(self, namespace: _Optional[str] = ..., schedule_id: _Optional[str] = ..., datasource_id: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class SchedulerRunDueResponse(_message.Message):
    __slots__ = ("handled", "enqueued", "failures")
    HANDLED_FIELD_NUMBER: _ClassVar[int]
    ENQUEUED_FIELD_NUMBER: _ClassVar[int]
    FAILURES_FIELD_NUMBER: _ClassVar[int]
    handled: bool
    enqueued: _containers.RepeatedCompositeFieldContainer[SchedulerEnqueuedRun]
    failures: _containers.RepeatedCompositeFieldContainer[SchedulerRunFailure]
    def __init__(self, handled: _Optional[bool] = ..., enqueued: _Optional[_Iterable[_Union[SchedulerEnqueuedRun, _Mapping]]] = ..., failures: _Optional[_Iterable[_Union[SchedulerRunFailure, _Mapping]]] = ...) -> None: ...
