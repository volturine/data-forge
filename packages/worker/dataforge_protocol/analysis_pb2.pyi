from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from dataforge_protocol import enums_pb2 as _enums_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AnalysisPipelineDatasource(_message.Message):
    __slots__ = ("id", "analysis_tab_id", "source_type", "config")
    ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_TAB_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    id: str
    analysis_tab_id: str
    source_type: _enums_pb2.DataSourceType
    config: _common_pb2.JsonPayload
    def __init__(self, id: _Optional[str] = ..., analysis_tab_id: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., config: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...

class AnalysisPipelineStep(_message.Message):
    __slots__ = ("id", "type", "config", "depends_on", "is_applied")
    ID_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    DEPENDS_ON_FIELD_NUMBER: _ClassVar[int]
    IS_APPLIED_FIELD_NUMBER: _ClassVar[int]
    id: str
    type: str
    config: _common_pb2.JsonPayload
    depends_on: _containers.RepeatedScalarFieldContainer[str]
    is_applied: bool
    def __init__(self, id: _Optional[str] = ..., type: _Optional[str] = ..., config: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., depends_on: _Optional[_Iterable[str]] = ..., is_applied: _Optional[bool] = ...) -> None: ...

class AnalysisPipelineOutput(_message.Message):
    __slots__ = ("result_id", "filename", "format", "options")
    RESULT_ID_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_FIELD_NUMBER: _ClassVar[int]
    result_id: str
    filename: str
    format: _enums_pb2.ExportFormat
    options: _common_pb2.JsonPayload
    def __init__(self, result_id: _Optional[str] = ..., filename: _Optional[str] = ..., format: _Optional[_Union[_enums_pb2.ExportFormat, str]] = ..., options: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...

class AnalysisPipelineTab(_message.Message):
    __slots__ = ("id", "name", "datasource", "output", "steps")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    STEPS_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    datasource: AnalysisPipelineDatasource
    output: AnalysisPipelineOutput
    steps: _containers.RepeatedCompositeFieldContainer[AnalysisPipelineStep]
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., datasource: _Optional[_Union[AnalysisPipelineDatasource, _Mapping]] = ..., output: _Optional[_Union[AnalysisPipelineOutput, _Mapping]] = ..., steps: _Optional[_Iterable[_Union[AnalysisPipelineStep, _Mapping]]] = ...) -> None: ...

class AnalysisPipelinePayload(_message.Message):
    __slots__ = ("analysis_id", "tabs")
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    TABS_FIELD_NUMBER: _ClassVar[int]
    analysis_id: str
    tabs: _containers.RepeatedCompositeFieldContainer[AnalysisPipelineTab]
    def __init__(self, analysis_id: _Optional[str] = ..., tabs: _Optional[_Iterable[_Union[AnalysisPipelineTab, _Mapping]]] = ...) -> None: ...
