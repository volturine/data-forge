from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI

from backend_core import database
from backend_core.api_execution_budget import install_api_blocking_executor, remove_api_blocking_executor
from modules.auth.dependencies import get_current_user
from modules.udf import routes as udf_routes


@pytest.mark.asyncio
async def test_udf_route_owns_session_inside_bounded_api_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    observations: dict[str, object] = {}

    class OwnedSession:
        def __init__(self, _engine: object) -> None:
            observations['created_thread'] = threading.get_ident()
            observations['session'] = self

        def __enter__(self) -> OwnedSession:
            return self

        def __exit__(self, *_error: object) -> None:
            observations['closed_thread'] = threading.get_ident()

    def list_udfs(session: OwnedSession, **_filters: object) -> list[object]:
        observations['used_thread'] = threading.get_ident()
        observations['used_session'] = session
        return []

    monkeypatch.setattr(database, '_get_tenant_engine', lambda: object())
    monkeypatch.setattr(database, 'Session', OwnedSession)
    monkeypatch.setattr(udf_routes.service, 'list_udfs', list_udfs)

    app = FastAPI()
    app.include_router(udf_routes.router)
    app.dependency_overrides[get_current_user] = lambda: None

    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='udf-api-test')
    install_api_blocking_executor(loop, executor, 1, max_pending=0)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            response = await client.get('/udf')
    finally:
        remove_api_blocking_executor(loop)
        executor.shutdown(wait=True, cancel_futures=True)

    assert response.status_code == 200
    assert response.json() == []
    assert observations['created_thread'] != loop_thread
    assert observations['created_thread'] == observations['used_thread'] == observations['closed_thread']
    assert observations['used_session'] is observations['session']
