from __future__ import annotations

from contextvars import ContextVar, Token

_current_compute_request_id: ContextVar[str | None] = ContextVar("current_compute_request_id", default=None)


def set_compute_request_id(request_id: str) -> Token[str | None]:
    return _current_compute_request_id.set(request_id)


def reset_compute_request_id(token: Token[str | None]) -> None:
    _current_compute_request_id.reset(token)


def get_compute_request_id() -> str | None:
    return _current_compute_request_id.get()
