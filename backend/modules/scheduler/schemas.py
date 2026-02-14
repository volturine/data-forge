import datetime as dt

from pydantic import BaseModel, ConfigDict


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    cron_expression: str
    enabled: bool = True
    datasource_id: str | None = None
    depends_on: str | None = None


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cron_expression: str | None = None
    enabled: bool | None = None
    datasource_id: str | None = None
    depends_on: str | None = None


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    datasource_id: str | None = None
    cron_expression: str
    enabled: bool
    depends_on: str | None = None
    last_run: dt.datetime | None
    next_run: dt.datetime | None
    created_at: dt.datetime
