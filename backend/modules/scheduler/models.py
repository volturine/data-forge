import datetime as dt

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


class Schedule(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'schedules'  # type: ignore[assignment]

    id: str = Field(sa_column=Column(String, primary_key=True))
    datasource_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    cron_expression: str = Field(sa_column=Column(String, nullable=False))
    enabled: bool = Field(default=True)
    depends_on: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    trigger_on_datasource_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    last_run: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    next_run: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))

    # Backward compatibility: analysis_id is kept but deprecated
    # New code should derive analysis from datasource at runtime
    # This will be removed in a future migration
    analysis_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
