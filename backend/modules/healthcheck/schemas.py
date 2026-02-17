import datetime as dt

from pydantic import BaseModel, ConfigDict


class HealthCheckCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    datasource_id: str
    name: str
    check_type: str
    config: dict
    enabled: bool = True
    critical: bool = False


class HealthCheckUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    check_type: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    critical: bool | None = None


class HealthCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    datasource_id: str
    name: str
    check_type: str
    config: dict
    enabled: bool
    critical: bool
    created_at: dt.datetime


class HealthCheckResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    healthcheck_id: str
    passed: bool
    message: str
    details: dict
    checked_at: dt.datetime
