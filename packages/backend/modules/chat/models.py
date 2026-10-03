import time
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlmodel import Field, SQLModel


class ChatSession(SQLModel, table=True):
    __tablename__ = 'chat_sessions'  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, index=True)
    provider: str = Field(default='openrouter')
    model: str = Field(default='')
    api_key: str = Field(default='')
    created_at: float = Field(default_factory=time.time)
    system_prompt: str = Field(default='')


class ChatTurn(SQLModel, table=True):
    __tablename__ = 'chat_turns'  # type: ignore[assignment]
    __table_args__ = (
        Index(
            'uq_chat_turns_active_session',
            'session_id',
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'awaiting_confirmation')"),
            sqlite_where=text("status IN ('queued', 'running', 'awaiting_confirmation')"),
        ),
        Index('ix_chat_turns_ready', 'status', 'created_at'),
        CheckConstraint("status IN ('queued', 'running', 'awaiting_confirmation', 'completed', 'failed', 'interrupted')", name='ck_chat_turns_status'),
    )

    id: str = Field(sa_column=Column(String, primary_key=True))
    session_id: str = Field(sa_column=Column(String, ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False, index=True))
    user_id: str = Field(sa_column=Column(String, nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    tool_ids: list[str] = Field(sa_column=Column(JSON, nullable=False))
    namespace: str = Field(sa_column=Column(String, nullable=False))
    session_token_encrypted: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(default='queued', sa_column=Column(String, nullable=False, server_default='queued'))
    checkpoint: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, server_default='{}'))
    stop_requested: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text('false')))
    confirmation_decision: bool | None = Field(default=None, sa_column=Column(Boolean, nullable=True))
    claim_token: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    coordinator_generation: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text('CURRENT_TIMESTAMP')))


class ChatMessage(SQLModel, table=True):
    __tablename__ = 'chat_messages'  # type: ignore[assignment]
    __table_args__ = (Index('ix_chat_messages_session_sequence', 'session_id', 'sequence'),)

    sequence: int | None = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True))
    session_id: str = Field(sa_column=Column(String, ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False))
    turn_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey('chat_turns.id', ondelete='CASCADE'), nullable=True))
    message: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text('CURRENT_TIMESTAMP')))


class ChatEvent(SQLModel, table=True):
    __tablename__ = 'chat_events'  # type: ignore[assignment]

    sequence: int = Field(sa_column=Column(BigInteger, nullable=False, primary_key=True))
    session_id: str = Field(sa_column=Column(String, ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False, primary_key=True))
    turn_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey('chat_turns.id', ondelete='CASCADE'), nullable=True))
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, server_default=text('CURRENT_TIMESTAMP')))
