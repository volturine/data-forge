from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from dataforge_protocol import enums_pb2 as _enums_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DatasourceRef(_message.Message):
    __slots__ = ("namespace", "datasource_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ...) -> None: ...

class DatasourceMetadata(_message.Message):
    __slots__ = ("id", "name", "source_type", "created_by", "target_kind", "config", "schema_cache", "is_hidden")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    TARGET_KIND_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_CACHE_FIELD_NUMBER: _ClassVar[int]
    IS_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    source_type: _enums_pb2.DataSourceType
    created_by: _enums_pb2.DataSourceCreatedBy
    target_kind: _enums_pb2.DataSourceTargetKind
    config: _common_pb2.JsonPayload
    schema_cache: _common_pb2.JsonPayload
    is_hidden: bool
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., created_by: _Optional[_Union[_enums_pb2.DataSourceCreatedBy, str]] = ..., target_kind: _Optional[_Union[_enums_pb2.DataSourceTargetKind, str]] = ..., config: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., schema_cache: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., is_hidden: _Optional[bool] = ...) -> None: ...
