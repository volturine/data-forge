import datetime as dt
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class CheckType(StrEnum):
    ROW_COUNT = 'row_count'
    COLUMN_NULL = 'column_null'
    COLUMN_UNIQUE = 'column_unique'
    COLUMN_RANGE = 'column_range'
    COLUMN_COUNT = 'column_count'
    NULL_PERCENTAGE = 'null_percentage'
    DUPLICATE_PERCENTAGE = 'duplicate_percentage'


class HealthCheckCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    datasource_id: str
    name: str
    check_type: CheckType
    config: dict[str, Any]
    enabled: bool = True
    critical: bool = False


class HealthCheckUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    check_type: CheckType | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    critical: bool | None = None


class HealthCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    datasource_id: str
    name: str
    check_type: CheckType
    config: dict[str, Any]
    enabled: bool
    critical: bool
    created_at: dt.datetime


class HealthCheckResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    healthcheck_id: str
    passed: bool
    message: str
    details: dict[str, Any]
    checked_at: dt.datetime
