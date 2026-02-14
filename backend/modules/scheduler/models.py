import datetime as dt

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


class Schedule(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'schedules'

    id: str = Field(sa_column=Column(String, primary_key=True))
    analysis_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    datasource_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    cron_expression: str = Field(sa_column=Column(String, nullable=False))
    enabled: bool = Field(default=True)
    depends_on: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    last_run: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    next_run: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
