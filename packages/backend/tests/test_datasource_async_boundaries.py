from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from backend_core import database
from backend_core.dependencies import get_runtime_availability_probe
from backend_core.namespace import get_namespace, reset_namespace, set_namespace_context
from modules.auth.dependencies import get_current_user
from modules.compute import executor_client, routes as compute_routes
from modules.datasource import routes as datasource_routes
from modules.datasource.schemas import DataSourceResponse, DataSourceUpdate


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['compute-preview', 'datasource-update'])
async def test_async_compute_and_datasource_routes_keep_responses(monkeypatch, route: str) -> None:
    app = FastAPI()
    app.include_router(compute_routes.router)
    app.include_router(datasource_routes.router)

    app.dependency_overrides[get_current_user] = lambda: None
    app.dependency_overrides[get_runtime_availability_probe] = lambda: object()

    async def preview(request, *, runtime_probe, http_request):
        return {'step_id': request.target_step_id, 'total_rows': 0}

    def update(_session, datasource_id, payload):
        return DataSourceResponse(
            id=datasource_id,
            name=payload.name,
            description=None,
            source_type='file',
            config={'file_type': 'csv'},
            schema_cache=None,
            created_at=datetime.now(UTC),
        )

    monkeypatch.setattr(executor_client, 'preview_step', preview)
    monkeypatch.setattr(datasource_routes.service, 'update_datasource', update)
    monkeypatch.setattr(datasource_routes, 'run_db', lambda function, *args: function(object(), *args))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        if route == 'datasource-update':
            response = await client.put('/datasource/datasource-1', json={'name': 'Updated'})
            assert response.status_code == 200
            assert response.json()['name'] == 'Updated'
            return

        response = await client.post(
            '/compute/preview',
            json={
                'target_step_id': 'source',
                'analysis_pipeline': {
                    'analysis_id': 'analysis-1',
                    'tabs': [
                        {
                            'id': 'tab-1',
                            'datasource': {'id': 'datasource-1', 'analysis_tab_id': None, 'config': {'branch': 'master'}},
                            'output': {'result_id': 'result-1', 'filename': 'result.csv', 'format': 'csv'},
                            'steps': [],
                        }
                    ],
                },
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {'step_id': 'source', 'total_rows': 0}


@pytest.mark.asyncio
async def test_update_runs_complete_db_operation_off_loop_with_fresh_session_and_namespace(monkeypatch) -> None:
    event_loop_thread = threading.get_ident()
    db_started = threading.Event()
    release_db = threading.Event()
    observations: dict[str, object] = {}

    class OwnedSession:
        def __init__(self, _engine):
            observations['create_thread'] = threading.get_ident()
            observations['namespace'] = get_namespace()
            observations['session'] = self

        def __enter__(self):
            return self

        def __exit__(self, *_error):
            observations['close_thread'] = threading.get_ident()

    def blocking_update(session, datasource_id, update: DataSourceUpdate, **kwargs) -> dict[str, bool]:
        observations['update_thread'] = threading.get_ident()
        observations['update_session'] = session
        observations['datasource_id'] = datasource_id
        observations['update'] = update
        observations['kwargs'] = kwargs
        db_started.set()
        if not release_db.wait(timeout=2):
            raise TimeoutError('test did not release blocked datasource update')
        return {'updated': True}

    monkeypatch.setattr(database, '_get_tenant_engine', lambda: object())
    monkeypatch.setattr(database, 'Session', OwnedSession)
    monkeypatch.setattr(datasource_routes.service, 'update_datasource', blocking_update)
    namespace_token = set_namespace_context('datasource-update-test')
    try:
        update_task = asyncio.create_task(
            datasource_routes.update_datasource(
                '22222222-2222-4222-8222-000000000099',
                DataSourceUpdate(name='Updated name'),
                runtime_probe=object(),
            )
        )
        assert await asyncio.to_thread(db_started.wait, 1)

        # A row-lock wait inside the DB transaction must not stop this loop.
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.2)
    finally:
        release_db.set()
        reset_namespace(namespace_token)

    assert await update_task == {'updated': True}
    assert observations['create_thread'] != event_loop_thread
    assert observations['update_thread'] == observations['create_thread'] == observations['close_thread']
    assert observations['namespace'] == 'datasource-update-test'
    assert observations['update_session'] is observations['session']
    assert observations['datasource_id'] == '22222222-2222-4222-8222-000000000099'
    observed_update = observations['update']
    assert isinstance(observed_update, DataSourceUpdate)
    assert observed_update.name == 'Updated name'
    assert observations['kwargs'] == {}
