from fastapi import Request

from modules.compute.manager import ProcessManager


def get_manager(request: Request) -> ProcessManager:
    """FastAPI dependency that returns the ProcessManager from app state."""
    return request.app.state.manager
