from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class RuntimeNamespace(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'runtime_namespaces'  # type: ignore[assignment]

    name: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class NamespaceEngineCredential(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'namespace_engine_credentials'  # type: ignore[assignment]
    __table_args__ = (UniqueConstraint('namespace', 'role', name='uq_namespace_engine_credentials_role'),)

    id: str = Field(primary_key=True)
    namespace: str = Field(index=True)
    role: str
    access_key: str = Field(unique=True)
    secret_key_encrypted: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
