from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from backend_core.application import app as app

__all__ = ['app']


def __getattr__(name: str) -> FastAPI:
    if name != 'app':
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

    # Spawn re-executes this script before Uvicorn starts its healthcheck thread.
    # Defer application imports until the server resolves its ASGI entry point.
    from backend_core.application import app

    globals()['app'] = app
    return app


if __name__ == '__main__':
    from backend_core.application import _run_api_server

    _run_api_server()
