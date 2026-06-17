import datetime

from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from dataforge_protocol import object_store_pb2 as _object_store_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class IcebergTableRef(_message.Message):
    __slots__ = ("namespace", "datasource_id", "metadata_path", "branch")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    METADATA_PATH_FIELD_NUMBER: _ClassVar[int]
    BRANCH_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    metadata_path: str
    branch: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ..., metadata_path: _Optional[str] = ..., branch: _Optional[str] = ...) -> None: ...

class IcebergSchemaSyncRequest(_message.Message):
    __slots__ = ("metadata_path", "schema")
    METADATA_PATH_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    metadata_path: str
    schema: _struct_pb2.Struct
    def __init__(self, metadata_path: _Optional[str] = ..., schema: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class IcebergMetadataPathResponse(_message.Message):
    __slots__ = ("metadata_path",)
    METADATA_PATH_FIELD_NUMBER: _ClassVar[int]
    metadata_path: str
    def __init__(self, metadata_path: _Optional[str] = ...) -> None: ...

class IcebergSnapshotInfo(_message.Message):
    __slots__ = ("snapshot_id", "timestamp", "parent_snapshot_id", "operation", "is_current")
    SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    PARENT_SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    IS_CURRENT_FIELD_NUMBER: _ClassVar[int]
    snapshot_id: str
    timestamp: _timestamp_pb2.Timestamp
    parent_snapshot_id: str
    operation: str
    is_current: bool
    def __init__(self, snapshot_id: _Optional[str] = ..., timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., parent_snapshot_id: _Optional[str] = ..., operation: _Optional[str] = ..., is_current: _Optional[bool] = ...) -> None: ...

class IcebergSnapshotsResponse(_message.Message):
    __slots__ = ("datasource_id", "table_path", "snapshots")
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    TABLE_PATH_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOTS_FIELD_NUMBER: _ClassVar[int]
    datasource_id: str
    table_path: str
    snapshots: _containers.RepeatedCompositeFieldContainer[IcebergSnapshotInfo]
    def __init__(self, datasource_id: _Optional[str] = ..., table_path: _Optional[str] = ..., snapshots: _Optional[_Iterable[_Union[IcebergSnapshotInfo, _Mapping]]] = ...) -> None: ...

class IcebergSnapshotDeleteRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id", "snapshot_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    snapshot_id: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ..., snapshot_id: _Optional[str] = ...) -> None: ...

class IcebergSnapshotDeleteResponse(_message.Message):
    __slots__ = ("datasource_id", "snapshot_id")
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    datasource_id: str
    snapshot_id: str
    def __init__(self, datasource_id: _Optional[str] = ..., snapshot_id: _Optional[str] = ...) -> None: ...

class IcebergSnapshotScanRequest(_message.Message):
    __slots__ = ("metadata_path", "snapshot_id", "limit")
    METADATA_PATH_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    metadata_path: str
    snapshot_id: str
    limit: int
    def __init__(self, metadata_path: _Optional[str] = ..., snapshot_id: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class IcebergSnapshotScanResponse(_message.Message):
    __slots__ = ("rows",)
    ROWS_FIELD_NUMBER: _ClassVar[int]
    rows: _struct_pb2.Struct
    def __init__(self, rows: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...
