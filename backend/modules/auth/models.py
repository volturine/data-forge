import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class UserStatus(StrEnum):
    ACTIVE = 'active'
    DISABLED = 'disabled'


class AuthProviderName(StrEnum):
    PASSWORD = 'password'
    GOOGLE = 'google'
    GITHUB = 'github'


class VerificationTokenType(StrEnum):
    EMAIL_VERIFY = 'email_verify'
    PASSWORD_RESET = 'password_reset'


class User(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'users'

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, sa_column=Column(String, primary_key=True))
    email: str = Field(sa_column=Column(String, nullable=False, unique=True, index=True))
    display_name: str = Field(sa_column=Column(String, nullable=False))
    avatar_url: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    status: UserStatus = Field(default=UserStatus.ACTIVE, sa_column=Column(String, nullable=False, server_default='active'))
    email_verified: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default='0'))
    has_password: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default='0'))
    preferences: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
    last_login_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class AuthProvider(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'auth_providers'
    __table_args__ = (
        UniqueConstraint('provider', 'provider_subject', name='uq_auth_provider_subject'),
        Index('ix_auth_providers_user_id', 'user_id'),
    )

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, sa_column=Column(String, primary_key=True))
    user_id: str = Field(sa_column=Column(String, ForeignKey('users.id', ondelete='CASCADE'), nullable=False))
    provider: AuthProviderName = Field(sa_column=Column(String, nullable=False))
    provider_subject: str = Field(sa_column=Column(String, nullable=False))
    provider_metadata: dict[str, object] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))


class UserSession(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'user_sessions'

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, sa_column=Column(String, primary_key=True))
    user_id: str = Field(sa_column=Column(String, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True))
    device_info: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    ip_address: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    created_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default='0'))


class VerificationToken(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = 'verification_tokens'
    __table_args__ = (Index('ix_verification_tokens_user_id', 'user_id'),)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, sa_column=Column(String, primary_key=True))
    user_id: str = Field(sa_column=Column(String, ForeignKey('users.id', ondelete='CASCADE'), nullable=False))
    token: str = Field(sa_column=Column(String, nullable=False, unique=True, index=True))
    token_type: VerificationTokenType = Field(sa_column=Column(String, nullable=False))
    created_at: datetime = Field(default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    used: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default='0'))
