from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.domain_enums import DomainEnumValue, domain_token


class DataSourceTargetKind(DomainEnumValue):
    ANALYSIS: ClassVar[Self]
    RAW: ClassVar[Self]
    DATASOURCE: ClassVar[Self]


DataSourceTargetKind.ANALYSIS = DataSourceTargetKind(
    enums_pb2.DATA_SOURCE_TARGET_KIND_ANALYSIS, domain_token("DataSourceTargetKind", enums_pb2.DATA_SOURCE_TARGET_KIND_ANALYSIS)
)
DataSourceTargetKind.RAW = DataSourceTargetKind(
    enums_pb2.DATA_SOURCE_TARGET_KIND_RAW, domain_token("DataSourceTargetKind", enums_pb2.DATA_SOURCE_TARGET_KIND_RAW)
)
DataSourceTargetKind.DATASOURCE = DataSourceTargetKind(
    enums_pb2.DATA_SOURCE_TARGET_KIND_DATASOURCE, domain_token("DataSourceTargetKind", enums_pb2.DATA_SOURCE_TARGET_KIND_DATASOURCE)
)
