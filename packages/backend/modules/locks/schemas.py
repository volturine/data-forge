from datetime import datetime
from typing import Annotated

from contracts.enums import DataForgeStrEnum
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

LockText = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class LockAcquireRequest(BaseModel):
    resource_type: LockText
    resource_id: LockText
    ttl_seconds: int | None = Field(default=None, ge=1)


class LockHeartbeatRequest(BaseModel):
    lock_token: LockText
    ttl_seconds: int | None = Field(default=None, ge=1)


class LockReleaseRequest(BaseModel):
    lock_token: LockText


class LockStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resource_type: str
    resource_id: str
    owner_id: str
    lock_token: str
    acquired_at: datetime
    expires_at: datetime
    last_heartbeat: datetime
    is_expired: bool


class LockReleaseResponse(BaseModel):
    released: bool


class LockWebsocketAction(DataForgeStrEnum):
    WATCH = "watch"
    ACQUIRE = "acquire"
    RELEASE = "release"
    PING = "ping"


class LockWebsocketRequest(BaseModel):
    action: LockWebsocketAction
    resource_type: LockText | None = None
    resource_id: LockText | None = None
    lock_token: LockText | None = None
    ttl_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_action(self) -> "LockWebsocketRequest":
        if self.action == LockWebsocketAction.WATCH and (self.resource_type is None or self.resource_id is None):
            raise ValueError("resource_type and resource_id are required for watch")
        return self


class LockWebsocketMessageType(DataForgeStrEnum):
    CONNECTED = "connected"
    STATUS = "status"
    ERROR = "error"


class LockWebsocketConnectedMessage(BaseModel):
    type: LockWebsocketMessageType = LockWebsocketMessageType.CONNECTED


class LockWebsocketStatusMessage(BaseModel):
    type: LockWebsocketMessageType = LockWebsocketMessageType.STATUS
    resource_type: str
    resource_id: str
    lock: LockStatusResponse | None


class LockWebsocketErrorMessage(BaseModel):
    type: LockWebsocketMessageType = LockWebsocketMessageType.ERROR
    error: str
    status_code: int = 400
