import datetime as dt

from sqlalchemy import JSON, Column, DateTime, String
from sqlmodel import Field, SQLModel


class HealthCheck(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'healthchecks'

    id: str = Field(sa_column=Column(String, primary_key=True))
    datasource_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    name: str = Field(sa_column=Column(String, nullable=False))
    check_type: str = Field(sa_column=Column(String, nullable=False))
    config: dict = Field(sa_column=Column(JSON, nullable=False))
    enabled: bool = Field(default=True)
    critical: bool = Field(default=False)
    created_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class HealthCheckResult(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'healthcheck_results'

    id: str = Field(sa_column=Column(String, primary_key=True))
    healthcheck_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    passed: bool = Field(default=False)
    message: str = Field(sa_column=Column(String, nullable=False))
    details: dict = Field(sa_column=Column(JSON, nullable=False))
    checked_at: dt.datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
