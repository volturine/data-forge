import time

from sqlmodel import Field, SQLModel


class ChatSession(SQLModel, table=True):
    __tablename__ = 'chat_sessions'  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    provider: str = Field(default='openrouter')
    model: str = Field(default='')
    api_key: str = Field(default='')
    messages_json: str = Field(default='[]')
    history_json: str = Field(default='[]')
    created_at: float = Field(default_factory=time.time)
    system_prompt: str = Field(default='')
