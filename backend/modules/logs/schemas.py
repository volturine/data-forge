from pydantic import BaseModel, Field


class ClientLogField(BaseModel):
    name: str
    value: str | None = None
    redacted: bool = False


class ClientLogItem(BaseModel):
    event: str
    action: str | None = None
    page: str | None = None
    target: str | None = None
    form_id: str | None = None
    fields: list[ClientLogField] = Field(default_factory=list)
    client_id: str | None = None
    session_id: str | None = None
    meta: dict | None = None


class ClientLogBatch(BaseModel):
    logs: list[ClientLogItem]
