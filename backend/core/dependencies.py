from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from modules.compute.manager import ProcessManager


def get_manager(request: Request) -> ProcessManager:
    """FastAPI dependency that returns the ProcessManager from app state."""
    return request.app.state.manager
