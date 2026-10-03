from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    enabled: bool
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class TelegramDetectionClaim:
    request_id: str
    token: str = field(repr=False)
    token_sha256: str
    request_user_id: str
    namespace: str
    owner_generation: int
    deadline_at: datetime


@dataclass(frozen=True, slots=True)
class TelegramDetectionResult:
    status: str
    result: dict[str, object] | None
    error: str | None
    deadline_at: datetime
