import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SCHEDULE_DESCRIPTION_MAX_LENGTH = 2000


class ScheduleDescriptionModel(BaseModel):
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.strip() == '':
            return None
        return value


class ScheduleCreate(ScheduleDescriptionModel):
    """Create a schedule targeting a specific dataset.

    The datasource_id is required and determines which analysis/tab
    will be executed (resolved at runtime from the datasource's provenance).
    """

    model_config = ConfigDict(from_attributes=True)

    datasource_id: str = Field(description='Target dataset to build (must be an analysis output)')
    description: str | None = Field(
        default=None,
        max_length=_SCHEDULE_DESCRIPTION_MAX_LENGTH,
        description='Human-readable description of why this schedule exists',
    )
    cron_expression: str = Field(default='0 9 * * *', description='Cron expression for scheduling')
    enabled: bool = Field(default=True, description='Whether the schedule is active')
    depends_on: str | None = Field(default=None, description='Wait for this schedule to complete')
    trigger_on_datasource_id: str | None = Field(default=None, description='Trigger when this datasource updates')

    @field_validator('description')
    @classmethod
    def _normalize_description(cls, value: str | None) -> str | None:
        return cls.normalize_description(value)

    @model_validator(mode='after')
    def validate_trigger(self) -> ScheduleCreate:
        if self.depends_on and self.trigger_on_datasource_id:
            raise ValueError('Schedule trigger must use either depends_on or trigger_on_datasource_id, not both')
        return self


class ScheduleUpdate(ScheduleDescriptionModel):
    """Update an existing schedule."""

    model_config = ConfigDict(from_attributes=True)

    cron_expression: str | None = None
    description: str | None = Field(
        default=None,
        max_length=_SCHEDULE_DESCRIPTION_MAX_LENGTH,
        description='Human-readable description of why this schedule exists',
    )
    enabled: bool | None = None
    datasource_id: str | None = None
    depends_on: str | None = None
    trigger_on_datasource_id: str | None = None

    @field_validator('description')
    @classmethod
    def _normalize_description(cls, value: str | None) -> str | None:
        return cls.normalize_description(value)

    @model_validator(mode='after')
    def validate_trigger(self) -> ScheduleUpdate:
        if self.depends_on and self.trigger_on_datasource_id:
            raise ValueError('Schedule trigger must use either depends_on or trigger_on_datasource_id, not both')
        return self


class ScheduleResponse(BaseModel):
    """Schedule response with target resolution info."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    datasource_id: str
    description: str | None = None
    cron_expression: str
    enabled: bool
    depends_on: str | None = None
    trigger_on_datasource_id: str | None = None
    last_run: dt.datetime | None = None
    next_run: dt.datetime | None = None
    created_at: dt.datetime

    # Resolved at response time from datasource provenance
    analysis_id: str | None = None
    analysis_name: str | None = None
    tab_id: str | None = None
    tab_name: str | None = None
