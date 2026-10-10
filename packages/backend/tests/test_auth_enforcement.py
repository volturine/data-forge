"""Authentication enforcement for API routes and namespace middleware."""

import importlib
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import APIRouter
from fastapi.routing import iter_route_contexts

from backend_core.application import app
from backend_core.database import run_settings_db
from backend_core.domain.analysis.models import AnalysisStatus
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.analysis_versions.models import AnalysisVersion
from modules.auth.dependencies import get_current_user
from tests.http_client import TestClient


def _make_analysis(session, *, owner_id: str | None = None) -> Analysis:
    now = datetime.now(UTC)
    analysis = Analysis(
        id=str(uuid.uuid4()),
        name='Auth Enforcement Analysis',
        description=None,
        pipeline_definition={'tabs': []},
        status=AnalysisStatus.DRAFT,
        created_at=now,
        updated_at=now,
        result_path=None,
        thumbnail=None,
        owner_id=owner_id,
    )
    session.add(analysis)
    session.commit()
    return analysis


def _make_version(session, analysis: Analysis, *, version: int = 1) -> AnalysisVersion:
    row = AnalysisVersion(
        id=str(uuid.uuid4()),
        analysis_id=analysis.id,
        version=version,
        name='v1',
        description=None,
        pipeline_definition={'tabs': []},
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()
    return row


def _require_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
    app.dependency_overrides.pop(get_current_user, None)


class TestRouterLevelAuth:
    def test_startup_auth_audit_rejects_an_unguarded_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        router_module = importlib.import_module('api.v1.router')
        unguarded = APIRouter()
        unguarded.add_api_route('/unprotected', lambda: None, methods=['GET'])
        root = APIRouter(prefix='/v1')
        root.include_router(unguarded, prefix='/nested')
        monkeypatch.setattr(router_module, 'router', root)

        with pytest.raises(RuntimeError, match='GET /v1/nested/unprotected'):
            router_module.verify_v1_auth_coverage()

    def test_startup_auth_audit_fails_closed_when_route_path_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        router_module = importlib.import_module('api.v1.router')
        monkeypatch.setattr(router_module, 'router', type('Router', (), {'routes': [object()]})())

        with pytest.raises(RuntimeError, match='cannot resolve a path'):
            router_module.verify_v1_auth_coverage()

    def test_startup_auth_audit_rejects_an_unauthenticated_nested_websocket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        router_module = importlib.import_module('api.v1.router')
        unguarded = APIRouter()
        unguarded.add_api_websocket_route('/socket', lambda _websocket: None)
        root = APIRouter(prefix='/v1')
        root.include_router(unguarded, prefix='/nested')
        monkeypatch.setattr(router_module, 'router', root)

        with pytest.raises(RuntimeError, match='WS /v1/nested/socket'):
            router_module.verify_v1_auth_coverage()

    def test_v1_route_audit_resolves_latest_fastapi_nested_route_contexts(self) -> None:
        router_module = importlib.import_module('api.v1.router')

        routes = list(iter_route_contexts(router_module.router.routes))
        paths = [router_module._route_path(route) for route in routes]

        assert routes
        assert all(path is not None for path in paths)
        assert all(path.startswith('/v1/') for path in paths if path is not None)

    def test_direct_production_mount_preserves_aggregate_api_paths(self) -> None:
        from fastapi import FastAPI
        from fastapi.routing import APIRoute

        from api.router import _ApiRouteDispatcher, include_api_routes, router

        aggregate_app = FastAPI()
        aggregate_app.include_router(router)
        direct_app = FastAPI()
        include_api_routes(direct_app)

        def route_path(route) -> str | None:
            path = route.path
            if path:
                return path
            effective_route = getattr(route, '_effective_route', None)
            websocket_route = getattr(effective_route, 'starlette_route', None)
            return getattr(websocket_route, 'path', None)

        def api_paths(app: FastAPI) -> set[tuple[str, str]]:
            return {
                (method, path)
                for route in iter_route_contexts(app.routes)
                if (path := route_path(route)) and path.startswith('/api/v1')
                for method in (route.methods or {'WS'})
            }

        assert api_paths(direct_app) == api_paths(aggregate_app)

        dispatcher = next(route for route in direct_app.routes if isinstance(route, _ApiRouteDispatcher))
        api_route_count = sum(1 for route in direct_app.routes if isinstance(route, APIRoute) and (route.path or '').startswith('/api/v1'))
        assert dispatcher.candidate_count('/api/v1/compute/preview') < api_route_count
        assert dispatcher.candidate_count('/prefix/api/v1/compute/preview', root_path='/prefix') == dispatcher.candidate_count('/api/v1/compute/preview')

        from modules.mcp.router import get_mcp_route_meta

        def mcp_routes(app: FastAPI) -> list[tuple[str | None, str, dict[str, object]]]:
            return [
                (route.path, route.name or '', metadata)
                for route in iter_route_contexts(app.routes)
                if isinstance(route.original_route, APIRoute) and isinstance((metadata := get_mcp_route_meta(route.original_route)), dict)
            ]

        assert mcp_routes(direct_app) == mcp_routes(aggregate_app)

    def test_api_route_dispatcher_preserves_path_and_method_matching(self) -> None:
        from fastapi import FastAPI

        from api.router import _ApiRouteDispatcher

        direct_app = FastAPI()

        @direct_app.get('/api/v1/test/{item_id}')
        def read_item(item_id: str) -> dict[str, str]:
            return {'item_id': item_id}

        api_routes = [route for route in direct_app.router.routes if (getattr(route, 'path', '') or '').startswith('/api/')]
        insert_at = direct_app.router.routes.index(api_routes[0])
        direct_app.router.routes.insert(insert_at, _ApiRouteDispatcher(api_routes))
        client = TestClient(direct_app)

        assert client.get('/api/v1/test/item-1').json() == {'item_id': 'item-1'}
        assert client.post('/api/v1/test/item-1').status_code == 405
        assert client.get('/api/v1/test/unknown/extra').status_code == 404

    def test_unauthenticated_requests_rejected_per_router(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _require_unauthenticated(monkeypatch)

        assert client.get('/api/v1/analysis').status_code == 401
        assert client.get(f'/api/v1/analysis/{uuid.uuid4()}/versions').status_code == 401
        assert client.get('/api/v1/datasource').status_code == 401
        assert client.post('/api/v1/ai/providers').status_code == 401
        assert client.get('/api/v1/locks/analysis/test').status_code == 401
        assert client.get('/api/v1/schedules').status_code == 401
        assert client.get('/api/v1/healthchecks/all').status_code == 401
        assert client.post('/api/v1/namespaces', json={'name': 'authcheck'}).status_code == 401
        assert client.post('/api/v1/compute/preview', json={}).status_code == 401

    def test_lock_websocket_rejects_unauthenticated_connection(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _require_unauthenticated(monkeypatch)

        with client.websocket_connect('/api/v1/locks/ws') as websocket:
            message = websocket.receive_json()

        assert message['status_code'] == 401

    def test_namespaces_list_stays_open_when_auth_required(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _require_unauthenticated(monkeypatch)

        response = client.get('/api/v1/namespaces')

        assert response.status_code == 200


class TestEngineWebsocketAuth:
    def test_ws_engines_rejects_unauthenticated(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _require_unauthenticated(monkeypatch)

        with client.websocket_connect('/api/v1/compute/ws/compute-workers') as websocket:
            message = websocket.receive_json()

        assert message['status_code'] == 401


class TestNamespaceMiddleware:
    def test_headerless_health_does_not_register_implicit_namespace_when_auth_is_disabled(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        import backend_core.application as application

        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)

        async def reject_namespace_database_work(*_args, **_kwargs):
            raise AssertionError('Headerless process health must not access the namespace database')

        monkeypatch.setattr(application, '_run_namespace_middleware', reject_namespace_database_work)

        response = client.get('/health')

        assert response.status_code == 200

    def test_rejects_unknown_namespace_without_session(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        namespace = f'ghost-{uuid.uuid4().hex[:8]}'

        response = client.get('/health', headers={'X-Namespace': namespace})

        assert response.status_code == 403

    def test_authenticated_request_registers_unknown_namespace_and_caches_it(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        namespace = f'fresh-{uuid.uuid4().hex[:8]}'

        def _seed(session):
            from modules.auth.service import create_session, create_user

            user = create_user(session, f'{namespace}@example.com', 'Password123', 'NS Owner')
            return create_session(session, user.id, 'pytest-agent', '127.0.0.1')

        user_session = run_settings_db(_seed)
        headers = {'X-Namespace': namespace}

        client.cookies.set('session_token', user_session.id)
        authenticated = client.get('/health', headers=headers)
        client.cookies.clear()
        anonymous_after_registration = client.get('/health', headers=headers)

        assert authenticated.status_code == 200
        assert anonymous_after_registration.status_code == 200

    def test_allows_everything_when_auth_disabled(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)
        namespace = f'open-{uuid.uuid4().hex[:8]}'

        response = client.get('/health', headers={'X-Namespace': namespace})

        assert response.status_code == 200


class TestSharedAnalysisAccess:
    def test_unauthenticated_analysis_mutations_still_require_login(self, client: TestClient, test_db_session, monkeypatch: pytest.MonkeyPatch) -> None:
        _require_unauthenticated(monkeypatch)
        analysis = _make_analysis(test_db_session, owner_id='someone-else')
        version = _make_version(test_db_session, analysis)
        headers = {'If-Match': f'"analysis-{analysis.id}-{analysis.revision}"'}

        update_response = client.put(
            f'/api/v1/analysis/{analysis.id}',
            json={'name': 'Anonymous edit'},
            headers=headers,
        )
        delete_version_response = client.delete(
            f'/api/v1/analysis/{analysis.id}/versions/{version.version}',
            headers=headers,
        )

        assert update_response.status_code == 401
        assert delete_version_response.status_code == 401

    def test_authenticated_non_owner_can_update_analysis(self, client: TestClient, test_db_session, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        analysis = _make_analysis(test_db_session, owner_id='someone-else')

        response = client.put(
            f'/api/v1/analysis/{analysis.id}',
            json={'name': 'Updated by another account'},
            headers={'If-Match': f'"analysis-{analysis.id}-{analysis.revision}"'},
        )

        assert response.status_code == 200
        assert response.json()['name'] == 'Updated by another account'
        test_db_session.refresh(analysis)
        assert analysis.owner_id == 'someone-else'

    def test_authenticated_non_owner_can_delete_analysis_version(self, client: TestClient, test_db_session, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        analysis = _make_analysis(test_db_session, owner_id='someone-else')
        version = _make_version(test_db_session, analysis)

        response = client.delete(
            f'/api/v1/analysis/{analysis.id}/versions/{version.version}',
            headers={'If-Match': f'"analysis-{analysis.id}-{analysis.revision}"'},
        )

        assert response.status_code == 200

    def test_authenticated_non_owner_can_rename_version_with_revision_precondition(
        self, client: TestClient, test_db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        analysis = _make_analysis(test_db_session, owner_id='someone-else')
        version = _make_version(test_db_session, analysis)

        # Version rename now enforces the analysis If-Match precondition like
        # every other mutation; missing header → 428, stale value → 412.
        no_precondition = client.patch(f'/api/v1/analysis/{analysis.id}/versions/{version.version}', json={'name': 'renamed'})
        assert no_precondition.status_code == 428

        stale = client.patch(
            f'/api/v1/analysis/{analysis.id}/versions/{version.version}',
            json={'name': 'renamed'},
            headers={'If-Match': f'"analysis-{analysis.id}-{analysis.revision + 99}"'},
        )
        assert stale.status_code == 412

        response = client.patch(
            f'/api/v1/analysis/{analysis.id}/versions/{version.version}',
            json={'name': 'renamed'},
            headers={'If-Match': f'"analysis-{analysis.id}-{analysis.revision}"'},
        )
        assert response.status_code == 200
        assert response.json()['name'] == 'renamed'
