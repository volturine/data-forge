from __future__ import annotations

from typing import ClassVar, Self

from backend_core.domain.protocol_enums import ProtocolEnumValue, protocol_token
from dataforge_protocol import enums_pb2


class DataSourceCreatedBy(ProtocolEnumValue):
    IMPORT: ClassVar[Self]
    ANALYSIS: ClassVar[Self]


DataSourceCreatedBy.IMPORT = DataSourceCreatedBy(
    enums_pb2.DATA_SOURCE_CREATED_BY_IMPORT, protocol_token('DataSourceCreatedBy', enums_pb2.DATA_SOURCE_CREATED_BY_IMPORT)
)
DataSourceCreatedBy.ANALYSIS = DataSourceCreatedBy(
    enums_pb2.DATA_SOURCE_CREATED_BY_ANALYSIS, protocol_token('DataSourceCreatedBy', enums_pb2.DATA_SOURCE_CREATED_BY_ANALYSIS)
)


class DataSourceTargetKind(ProtocolEnumValue):
    ANALYSIS: ClassVar[Self]
    RAW: ClassVar[Self]
    DATASOURCE: ClassVar[Self]


DataSourceTargetKind.ANALYSIS = DataSourceTargetKind(
    enums_pb2.DATA_SOURCE_TARGET_KIND_ANALYSIS, protocol_token('DataSourceTargetKind', enums_pb2.DATA_SOURCE_TARGET_KIND_ANALYSIS)
)
DataSourceTargetKind.RAW = DataSourceTargetKind(
    enums_pb2.DATA_SOURCE_TARGET_KIND_RAW, protocol_token('DataSourceTargetKind', enums_pb2.DATA_SOURCE_TARGET_KIND_RAW)
)
DataSourceTargetKind.DATASOURCE = DataSourceTargetKind(
    enums_pb2.DATA_SOURCE_TARGET_KIND_DATASOURCE, protocol_token('DataSourceTargetKind', enums_pb2.DATA_SOURCE_TARGET_KIND_DATASOURCE)
)
