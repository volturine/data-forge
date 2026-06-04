import datetime as dt

import croniter  # type: ignore[import-untyped]
from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


class Schedule(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'schedules'  # type: ignore[assignment]

    @staticmethod
    def compute_next_run(cron_expression: str, *, now: dt.datetime | None = None) -> dt.datetime | None:
        if not cron_expression:
            return None
        base = now or dt.datetime.now(dt.UTC)
        return croniter.croniter(cron_expression, base).get_next(dt.datetime)

    id: str = Field(sa_column=Column(String, primary_key=True))
    datasource_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    cron_expression: str = Field(sa_column=Column(String, nullable=False))
    enabled: bool = Field(default=True)
    depends_on: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    trigger_on_datasource_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    last_run: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    next_run: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    lease_owner: str | None = Field(default=None, sa_column=Column(String, nullable=True, index=True))
    lease_expires_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_claimed_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_triggered_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_success_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_failure_at: dt.datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_successful_build_id: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
