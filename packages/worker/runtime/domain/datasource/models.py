from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.protocol_enums import ProtocolEnumValue, protocol_token


class DataSourceTargetKind(ProtocolEnumValue):
    ANALYSIS: ClassVar[Self]
    RAW: ClassVar[Self]
    DATASOURCE: ClassVar[Self]


DataSourceTargetKind.ANALYSIS = DataSourceTargetKind(
    enums_pb2.DATA_SOURCE_TARGET_KIND_ANALYSIS, protocol_token("DataSourceTargetKind", enums_pb2.DATA_SOURCE_TARGET_KIND_ANALYSIS)
)
DataSourceTargetKind.RAW = DataSourceTargetKind(
    enums_pb2.DATA_SOURCE_TARGET_KIND_RAW, protocol_token("DataSourceTargetKind", enums_pb2.DATA_SOURCE_TARGET_KIND_RAW)
)
DataSourceTargetKind.DATASOURCE = DataSourceTargetKind(
    enums_pb2.DATA_SOURCE_TARGET_KIND_DATASOURCE, protocol_token("DataSourceTargetKind", enums_pb2.DATA_SOURCE_TARGET_KIND_DATASOURCE)
)
