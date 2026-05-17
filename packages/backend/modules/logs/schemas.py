import json
from datetime import UTC, datetime
from typing import Any

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
    meta: dict[str, Any] | None = None

    def with_request_context(self, *, client_id: str | None, session_id: str | None) -> "ClientLogItem":
        return self.model_copy(
            update={
                "client_id": self.client_id or client_id,
                "session_id": self.session_id or session_id,
            }
        )

    def to_log_payload(self, *, now: datetime | None = None) -> dict[str, Any]:
        return {
            "ts": now or datetime.now(UTC),
            "event": self.event,
            "action": self.action,
            "page": self.page,
            "target": self.target,
            "form_id": self.form_id,
            "fields_json": json.dumps([field.model_dump() for field in self.fields]),
            "client_id": self.client_id,
            "session_id": self.session_id,
            "meta_json": json.dumps(self.meta) if self.meta else None,
        }


class ClientLogBatch(BaseModel):
    logs: list[ClientLogItem]
