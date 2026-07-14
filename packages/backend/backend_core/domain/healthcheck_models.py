from __future__ import annotations

from typing import ClassVar, Self

from backend_core.domain.api_enums import ApiEnumValue, api_token
from dataforge_protocol import enums_pb2


class HealthCheckType(ApiEnumValue):
    ROW_COUNT: ClassVar[Self]
    COLUMN_NULL: ClassVar[Self]
    COLUMN_UNIQUE: ClassVar[Self]
    COLUMN_RANGE: ClassVar[Self]
    COLUMN_COUNT: ClassVar[Self]
    NULL_PERCENTAGE: ClassVar[Self]
    DUPLICATE_PERCENTAGE: ClassVar[Self]

    @property
    def requires_unique_per_datasource(self) -> bool:
        return self == HealthCheckType.ROW_COUNT

    @property
    def requires_column(self) -> bool:
        return self in {HealthCheckType.COLUMN_NULL, HealthCheckType.COLUMN_UNIQUE, HealthCheckType.COLUMN_RANGE}


HealthCheckType.ROW_COUNT = HealthCheckType(enums_pb2.HEALTH_CHECK_TYPE_ROW_COUNT, api_token('HealthCheckType', enums_pb2.HEALTH_CHECK_TYPE_ROW_COUNT))
HealthCheckType.COLUMN_NULL = HealthCheckType(enums_pb2.HEALTH_CHECK_TYPE_COLUMN_NULL, api_token('HealthCheckType', enums_pb2.HEALTH_CHECK_TYPE_COLUMN_NULL))
HealthCheckType.COLUMN_UNIQUE = HealthCheckType(
    enums_pb2.HEALTH_CHECK_TYPE_COLUMN_UNIQUE, api_token('HealthCheckType', enums_pb2.HEALTH_CHECK_TYPE_COLUMN_UNIQUE)
)
HealthCheckType.COLUMN_RANGE = HealthCheckType(enums_pb2.HEALTH_CHECK_TYPE_COLUMN_RANGE, api_token('HealthCheckType', enums_pb2.HEALTH_CHECK_TYPE_COLUMN_RANGE))
HealthCheckType.COLUMN_COUNT = HealthCheckType(enums_pb2.HEALTH_CHECK_TYPE_COLUMN_COUNT, api_token('HealthCheckType', enums_pb2.HEALTH_CHECK_TYPE_COLUMN_COUNT))
HealthCheckType.NULL_PERCENTAGE = HealthCheckType(
    enums_pb2.HEALTH_CHECK_TYPE_NULL_PERCENTAGE, api_token('HealthCheckType', enums_pb2.HEALTH_CHECK_TYPE_NULL_PERCENTAGE)
)
HealthCheckType.DUPLICATE_PERCENTAGE = HealthCheckType(
    enums_pb2.HEALTH_CHECK_TYPE_DUPLICATE_PERCENTAGE, api_token('HealthCheckType', enums_pb2.HEALTH_CHECK_TYPE_DUPLICATE_PERCENTAGE)
)
