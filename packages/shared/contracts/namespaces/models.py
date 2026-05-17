from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class RuntimeNamespace(SQLModel, table=True):
    __tablename__ = 'runtime_namespaces'  # type: ignore[assignment]

    name: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
