"""Authorization enforcement: router-level auth, ws auth, namespace middleware, object ownership."""

import uuid
from datetime import UTC, datetime

import pytest

from backend_core.database import run_settings_db
from backend_core.domain.analysis.models import AnalysisStatus
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.analysis_versions.models import AnalysisVersion
from main import app
from modules.analysis.ownership import ensure_mutation_allowed
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
    def test_unauthenticated_requests_rejected_per_router(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _require_unauthenticated(monkeypatch)

        assert client.get('/api/v1/analysis').status_code == 401
        assert client.get(f'/api/v1/analysis/{uuid.uuid4()}/versions').status_code == 401
        assert client.get('/api/v1/schedules').status_code == 401
        assert client.get('/api/v1/healthchecks/all').status_code == 401
        assert client.post('/api/v1/namespaces', json={'name': 'authcheck'}).status_code == 401
        assert client.post('/api/v1/compute/preview', json={}).status_code == 401

    def test_namespaces_list_stays_open_when_auth_required(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _require_unauthenticated(monkeypatch)

        response = client.get('/api/v1/namespaces')

        assert response.status_code == 200


class TestEngineWebsocketAuth:
    def test_ws_engines_rejects_unauthenticated(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _require_unauthenticated(monkeypatch)

        with client.websocket_connect('/api/v1/compute/ws/engines') as websocket:
            message = websocket.receive_json()

        assert message['status_code'] == 401


class TestNamespaceMiddleware:
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


class TestObjectOwnership:
    def test_helper_allows_all_when_auth_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', False)

        ensure_mutation_allowed('owner-1', 'owner-2')
        ensure_mutation_allowed(None, 'owner-2')

    def test_owned_analysis_delete_rejected_for_non_owner(self, client: TestClient, test_db_session, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        analysis = _make_analysis(test_db_session, owner_id='someone-else')

        response = client.delete(f'/api/v1/analysis/{analysis.id}')

        assert response.status_code == 403

    def test_owned_analysis_version_delete_rejected_for_non_owner(self, client: TestClient, test_db_session, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        analysis = _make_analysis(test_db_session, owner_id='someone-else')
        _make_version(test_db_session, analysis)

        response = client.delete(f'/api/v1/analysis/{analysis.id}/versions/1')

        assert response.status_code == 403

    def test_ownerless_version_rename_allowed_for_any_authenticated_user(self, client: TestClient, test_db_session, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('backend_core.auth_config.settings.auth_required', True)
        analysis = _make_analysis(test_db_session, owner_id=None)
        version = _make_version(test_db_session, analysis)

        response = client.patch(f'/api/v1/analysis/{analysis.id}/versions/{version.version}', json={'name': 'renamed'})

        assert response.status_code == 200
        assert response.json()['name'] == 'renamed'
