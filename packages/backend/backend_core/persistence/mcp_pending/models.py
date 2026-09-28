from datetime import datetime

from sqlalchemy import Column, DateTime, Index, String, Text
from sqlmodel import Field, SQLModel


class McpPendingAction(SQLModel, table=True):  # type: ignore[call-arg, assignment]
    __tablename__ = 'mcp_pending_actions'  # type: ignore[assignment]
    __table_args__ = (Index('ix_mcp_pending_actions_expires_at', 'expires_at'),)

    token_hash: str = Field(sa_column=Column(String, primary_key=True))
    owner_id: str = Field(sa_column=Column(String, nullable=False))
    tool_id: str = Field(sa_column=Column(String, nullable=False))
    method: str = Field(sa_column=Column(String, nullable=False))
    path: str = Field(sa_column=Column(String, nullable=False))
    namespace: str = Field(sa_column=Column(String, nullable=False))
    args_encrypted: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
