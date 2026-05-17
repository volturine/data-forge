"""Backend-owned healthcheck API schemas."""

import datetime as dt
from typing import Any

from contracts.healthcheck_models import HealthCheckType
from pydantic import BaseModel, ConfigDict


class HealthCheckCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    datasource_id: str
    name: str
    check_type: HealthCheckType
    config: dict[str, Any]
    enabled: bool = True
    critical: bool = False


class HealthCheckUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    check_type: HealthCheckType | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    critical: bool | None = None


class HealthCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    datasource_id: str
    name: str
    check_type: HealthCheckType
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
