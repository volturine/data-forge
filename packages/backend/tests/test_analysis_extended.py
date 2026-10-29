"""Extended tests for analysis module."""

import uuid
from typing import Any

import pytest
from httpx import Response
from sqlmodel import Session

from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.datasource.models import DataSource
from tests.harness.analysis_payloads import tab_payload


@pytest.fixture(autouse=True)
def current_analysis_revision(client, test_db_session: Session, monkeypatch: pytest.MonkeyPatch):
    request = client.request

    def request_with_revision(method: str, url: str, **kwargs: Any) -> Response:
        path = url.split('?', maxsplit=1)[0]
        parts = path.strip('/').split('/')
        if method.upper() in {'POST', 'PUT', 'DELETE'} and len(parts) >= 4 and parts[:3] == ['api', 'v1', 'analysis']:
            test_db_session.expire_all()
            analysis = test_db_session.get(Analysis, parts[3])
            if analysis is not None:
                headers = dict(kwargs.get('headers') or {})
                headers.setdefault('If-Match', str(analysis.revision))
                kwargs['headers'] = headers
        return request(method, url, **kwargs)

    monkeypatch.setattr(client, 'request', request_with_revision)


def _filter_config(column: str, operator: str, value: object) -> dict[str, object]:
    return {
        'conditions': [
            {
                'column': column,
                'operator': operator,
                'value': value,
            }
        ],
        'logic': 'AND',
    }


class TestAnalysisValidation:
    """Test analysis validation logic."""

    @pytest.mark.parametrize(
        'name_fields',
        [
            pytest.param({}, id='missing_name'),
            pytest.param({'name': ''}, id='empty_name'),
        ],
    )
    def test_create_analysis_rejects_missing_or_empty_name(self, client, sample_datasource: DataSource, name_fields: dict[str, str]):
        payload = {
            'description': 'Test',
            'tabs': [tab_payload(sample_datasource.id)],
            **name_fields,
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 422


class TestAnalysisPipeline:
    """Test analysis pipeline functionality."""

    def test_rejects_circular_step_dependencies(self, client, sample_datasource: DataSource):
        """Steps may only depend on earlier steps, so a dependency cycle is rejected."""
        steps = [
            {'id': 'step1', 'type': 'filter', 'config': {}, 'depends_on': ['step2']},
            {'id': 'step2', 'type': 'filter', 'config': {}, 'depends_on': ['step1']},
        ]
        payload = {
            'name': 'Circular Deps',
            'tabs': [tab_payload(sample_datasource.id, steps=steps)],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 400
        assert response.json()['detail'] == "Step depends on unknown step 'step2'"


class TestAnalysisMetadata:
    """Test analysis metadata."""

    def test_update_analysis_thumbnail(self, client, sample_analysis: Analysis):
        """Test updating analysis thumbnail."""
        thumbnail = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        payload = {
            'thumbnail': thumbnail,
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        data = response.json()
        assert 'thumbnail' in data


class TestDeriveTab:
    """Tests for POST /api/v1/analysis/{id}/tabs/{tab_id}/derive."""

    def test_derive_tab_creates_new_tab(self, client, sample_analysis: Analysis):
        """Derive creates a new tab chaining from the source tab's result_id with a default name and fresh result_id."""
        tab_id = 'tab1'
        source_result_id = sample_analysis.pipeline_definition['tabs'][0]['output']['result_id']

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/derive', json={})

        assert response.status_code == 200
        data = response.json()
        assert data['id'] != tab_id
        assert data['parent_id'] == tab_id
        assert data['datasource']['analysis_tab_id'] == tab_id
        assert data['datasource']['id'] == source_result_id
        assert len(data['steps']) == 1
        assert data['steps'][0]['type'] == 'view'
        assert data['name'].startswith('Derived')
        assert data['output']['result_id'] != source_result_id

    def test_derive_tab_custom_name_is_returned_and_persisted(self, client, sample_analysis: Analysis):
        """Derived tab uses the provided name and is persisted in GET /analysis/{id}."""
        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/derive',
            json={'name': 'My Derived Tab'},
        )

        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'My Derived Tab'

        response = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        assert response.status_code == 200
        tabs = response.json()['pipeline_definition']['tabs']
        assert any(t['name'] == 'My Derived Tab' for t in tabs)

    def test_derive_tab_nonexistent_analysis(self, client):
        """Returns 404 for nonexistent analysis."""
        response = client.post(f'/api/v1/analysis/{uuid.uuid4()}/tabs/tab1/derive', json={})

        assert response.status_code == 404

    def test_derive_tab_nonexistent_tab(self, client, sample_analysis: Analysis):
        """Returns 400 for nonexistent tab_id."""
        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/nonexistent/derive',
            json={},
        )

        assert response.status_code == 400

    def test_update_analysis_with_derived_tab(self, client, sample_analysis: Analysis):
        """Updating an analysis that has a derived tab (intra-analysis chain) should succeed."""
        # First derive a tab
        derive_resp = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/derive',
            json={'name': 'Derived'},
        )
        assert derive_resp.status_code == 200

        # Get full analysis with both tabs
        get_resp = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        analysis_data = get_resp.json()
        tabs = analysis_data['pipeline_definition']['tabs']
        assert len(tabs) == 2

        # Update with both tabs (derived tab references same analysis)
        update_resp = client.put(
            f'/api/v1/analysis/{sample_analysis.id}',
            json={'tabs': tabs},
        )
        assert update_resp.status_code == 200


class TestDuplicateTab:
    """Tests for POST /api/v1/analysis/{id}/tabs/{tab_id}/duplicate."""

    def test_duplicate_tab_inserts_adjacent_and_generates_copy_name(self, client, sample_analysis: Analysis):
        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/duplicate', json={})
        assert response.status_code == 200
        duplicated = response.json()
        assert duplicated['name'] == 'Source Copy'
        assert duplicated['id'] != 'tab1'
        assert duplicated['output']['result_id'] != sample_analysis.pipeline_definition['tabs'][0]['output']['result_id']

        read_back = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        assert read_back.status_code == 200
        tabs = read_back.json()['pipeline_definition']['tabs']
        source_idx = next(i for i, tab in enumerate(tabs) if tab['id'] == 'tab1')
        duplicate_idx = next(i for i, tab in enumerate(tabs) if tab['id'] == duplicated['id'])
        assert duplicate_idx == source_idx + 1

        second_response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/duplicate', json={})
        assert second_response.status_code == 200
        assert second_response.json()['name'] == 'Source Copy 2'

    def test_duplicate_tab_rewrites_step_ids_and_dependencies(self, client, sample_analysis: Analysis):
        current = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        assert current.status_code == 200
        tabs = current.json()['pipeline_definition']['tabs']
        tabs[0]['steps'].append(
            {
                'id': 'step2',
                'type': 'filter',
                'config': _filter_config('age', '>', 40),
                'depends_on': ['step1'],
            }
        )
        update = client.put(f'/api/v1/analysis/{sample_analysis.id}', json={'tabs': tabs})
        assert update.status_code == 200

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/duplicate', json={})
        assert response.status_code == 200
        duplicated = response.json()
        assert len(duplicated['steps']) == 2

        first_step = duplicated['steps'][0]
        second_step = duplicated['steps'][1]
        assert first_step['id'] != 'step1'
        assert second_step['id'] != 'step2'
        assert second_step['depends_on'] == [first_step['id']]

    def test_duplicate_derived_tab_preserves_upstream_reference(self, client, sample_analysis: Analysis):
        derived_response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/derive',
            json={'name': 'Derived 1'},
        )
        assert derived_response.status_code == 200
        derived = derived_response.json()

        source_result_id = sample_analysis.pipeline_definition['tabs'][0]['output']['result_id']

        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/{derived["id"]}/duplicate',
            json={},
        )
        assert response.status_code == 200
        duplicated = response.json()
        assert duplicated['datasource']['analysis_tab_id'] == 'tab1'
        assert duplicated['datasource']['id'] == source_result_id
        assert duplicated['output']['result_id'] != derived['output']['result_id']

    def test_duplicate_does_not_rewire_existing_dependents(self, client, sample_analysis: Analysis):
        derived_response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/derive',
            json={'name': 'D1'},
        )
        assert derived_response.status_code == 200
        derived = derived_response.json()

        duplicate_response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/duplicate', json={})
        assert duplicate_response.status_code == 200

        read_back = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        assert read_back.status_code == 200
        tabs = read_back.json()['pipeline_definition']['tabs']
        dependent = next(tab for tab in tabs if tab['id'] == derived['id'])
        assert dependent['datasource']['analysis_tab_id'] == 'tab1'

    def test_duplicate_tab_nonexistent_tab(self, client, sample_analysis: Analysis):
        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/nonexistent/duplicate',
            json={},
        )
        assert response.status_code == 400
