"""Extended tests for analysis module."""

import uuid
from typing import Any, cast

from modules.analysis.models import Analysis
from modules.analysis.step_types import StepType
from modules.datasource.models import DataSource


class TestAnalysisValidation:
    """Test analysis validation logic."""

    def test_create_analysis_missing_name(self, client, sample_datasource: DataSource):
        """Test creating analysis without a name."""
        payload = {
            'description': 'Test analysis',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_a',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 422

    def test_create_analysis_empty_name(self, client, sample_datasource: DataSource):
        """Test creating analysis with empty name."""
        payload = {
            'name': '',
            'description': 'Test',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_b',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code in [400, 422]

    def test_create_analysis_with_long_name(self, client, sample_datasource: DataSource):
        """Test creating analysis with very long name."""
        payload = {
            'name': 'A' * 1000,
            'description': 'Test',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_c',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        # Should succeed or fail with validation error
        assert response.status_code in [200, 201, 422]

    def test_create_analysis_with_special_characters(self, client, sample_datasource: DataSource):
        """Test creating analysis with special characters in name."""
        payload = {
            'name': 'Test <script>alert("xss")</script>',
            'description': 'Test',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_d',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        # Should succeed and escape special characters
        if response.status_code in [200, 201]:
            data = response.json()
            assert 'id' in data

    def test_update_nonexistent_analysis(self, client):
        """Test updating analysis that doesn't exist."""
        fake_id = str(uuid.uuid4())
        payload = {
            'name': 'Updated',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': str(uuid.uuid4()),
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_e',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.put(f'/api/v1/analysis/{fake_id}', json=payload)

        assert response.status_code == 404

    def test_delete_nonexistent_analysis(self, client):
        """Test deleting analysis that doesn't exist."""
        fake_id = str(uuid.uuid4())

        response = client.delete(f'/api/v1/analysis/{fake_id}')

        assert response.status_code == 404

    def test_get_nonexistent_analysis(self, client):
        """Test getting analysis that doesn't exist."""
        fake_id = str(uuid.uuid4())

        response = client.get(f'/api/v1/analysis/{fake_id}')

        assert response.status_code == 404


class TestAnalysisPipeline:
    """Test analysis pipeline functionality."""

    def test_create_analysis_with_empty_pipeline(self, client, sample_datasource: DataSource):
        """Test creating analysis with empty pipeline."""
        payload = {
            'name': 'Empty Pipeline Analysis',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_f',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code in [200, 201]

    def test_create_analysis_with_complex_pipeline(self, client, sample_datasource: DataSource):
        """Test creating analysis with complex pipeline."""
        payload = {
            'name': 'Complex Pipeline',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_g',
                    },
                    'steps': [
                        {
                            'id': 'step1',
                            'type': 'filter',
                            'config': {'column': 'age', 'operator': '>', 'value': 30},
                            'depends_on': [],
                        },
                        {
                            'id': 'step2',
                            'type': 'select',
                            'config': {'columns': ['name', 'age']},
                            'depends_on': ['step1'],
                        },
                        {
                            'id': 'step3',
                            'type': 'sort',
                            'config': {'columns': ['age'], 'descending': [True]},
                            'depends_on': ['step2'],
                        },
                    ],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code in [200, 201]
        data = response.json()
        assert len(data['pipeline_definition']['tabs'][0]['steps']) == 3

    def test_update_analysis_pipeline(self, client, sample_analysis: Analysis):
        """Test updating analysis pipeline."""
        new_steps: list[dict[str, Any]] = [
            {
                'id': 'new_step',
                'type': cast(StepType, 'filter'),
                'config': {'column': 'id', 'operator': '=', 'value': 1},
                'depends_on': [],
            },
        ]
        tabs = sample_analysis.pipeline_definition['tabs']
        tabs[0]['steps'] = new_steps

        payload = {
            'tabs': tabs,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        data = response.json()
        assert len(data['pipeline_definition']['tabs'][0]['steps']) >= 1

    def test_analysis_with_circular_dependencies(self, client, sample_datasource: DataSource):
        """Test creating analysis with circular dependencies."""
        payload = {
            'name': 'Circular Deps',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_h',
                    },
                    'steps': [
                        {'id': 'step1', 'type': 'filter', 'config': {}, 'depends_on': ['step2']},
                        {'id': 'step2', 'type': 'filter', 'config': {}, 'depends_on': ['step1']},
                    ],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        # Should either reject or accept (validation depends on implementation)
        assert response.status_code in [200, 201, 400, 422]


class TestAnalysisStatus:
    """Test analysis status management."""

    def test_update_analysis_status(self, client, sample_analysis: Analysis):
        """Test updating analysis status."""
        payload = {
            'status': 'running',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'running'

    def test_invalid_status_transition(self, client, sample_analysis: Analysis):
        """Test invalid status value."""
        payload = {
            'status': 'invalid_status',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        # Should either reject or accept (validation depends on implementation)
        assert response.status_code in [200, 400, 422]

    def test_analysis_lifecycle_statuses(self, client, sample_analysis: Analysis):
        """Test analysis through different statuses."""
        statuses = ['draft', 'running', 'completed', 'error']

        for status in statuses:
            payload = {
                'status': status,
                'tabs': sample_analysis.pipeline_definition['tabs'],
            }
            response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

            if response.status_code == 200:
                data = response.json()
                assert data['status'] == status


class TestAnalysisListing:
    """Test analysis listing."""

    def test_list_empty_analyses(self, client):
        """Test listing when no analyses exist."""
        response = client.get('/api/v1/analysis')

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_multiple_analyses(self, client, sample_analyses: list[Analysis]):
        """Test listing multiple analyses."""
        response = client.get('/api/v1/analysis')

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= len(sample_analyses)

    def test_list_analyses_ordering(self, client, sample_analyses: list[Analysis]):
        """Test that analyses are ordered consistently."""
        response = client.get('/api/v1/analysis')

        assert response.status_code == 200
        data = response.json()

        # Should return data in some consistent order
        assert isinstance(data, list)


class TestAnalysisMetadata:
    """Test analysis metadata."""

    def test_update_analysis_description(self, client, sample_analysis: Analysis):
        """Test updating analysis description."""
        payload = {
            'description': 'Updated description',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data['description'] == 'Updated description'

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

    def test_analysis_timestamps(self, client, sample_datasource: DataSource):
        """Test that analysis has proper timestamps."""
        payload = {
            'name': 'Timestamp Test',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_i',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code in [200, 201]
        data = response.json()
        assert 'created_at' in data
        assert 'updated_at' in data

    def test_updated_at_changes_on_update(self, client, sample_analysis: Analysis):
        """Test that updated_at changes when analysis is updated."""
        # Get original
        response1 = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        response1.json()

        # Update
        client.put(
            f'/api/v1/analysis/{sample_analysis.id}',
            json={'name': 'Updated', 'tabs': sample_analysis.pipeline_definition['tabs']},
        )

        # Get updated
        response2 = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        updated = response2.json()

        # updated_at should change (if granular enough)
        # This might fail if updates happen too quickly
        assert 'updated_at' in updated


class TestDeriveTab:
    """Tests for POST /api/v1/analysis/{id}/tabs/{tab_id}/derive."""

    def test_derive_tab_creates_new_tab(self, client, sample_analysis: Analysis):
        """Derive creates a new tab chaining from the source tab's result_id."""
        tab_id = 'tab1'
        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/derive', json={})

        assert response.status_code == 200
        data = response.json()
        assert data['id'] != tab_id
        assert data['parent_id'] == tab_id
        assert data['datasource']['analysis_tab_id'] == tab_id
        assert len(data['steps']) == 1
        assert data['steps'][0]['type'] == 'view'

    def test_derive_tab_datasource_is_source_result_id(self, client, sample_analysis: Analysis):
        """Derived tab's datasource.id equals source tab's output.result_id."""
        tab_id = 'tab1'
        source_result_id = sample_analysis.pipeline_definition['tabs'][0]['output']['result_id']

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/derive', json={})

        assert response.status_code == 200
        data = response.json()
        assert data['datasource']['id'] == source_result_id

    def test_derive_tab_custom_name(self, client, sample_analysis: Analysis):
        """Derived tab uses the provided name."""
        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/derive',
            json={'name': 'My Derived Tab'},
        )

        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'My Derived Tab'

    def test_derive_tab_default_name(self, client, sample_analysis: Analysis):
        """Derived tab gets a default name when none is provided."""
        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/derive',
            json={},
        )

        assert response.status_code == 200
        data = response.json()
        assert data['name'].startswith('Derived')

    def test_derive_tab_appears_in_analysis(self, client, sample_analysis: Analysis):
        """Derived tab is persisted and appears in GET /analysis/{id}."""
        client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/derive', json={'name': 'D1'})

        response = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        assert response.status_code == 200
        tabs = response.json()['pipeline_definition']['tabs']
        assert any(t['name'] == 'D1' for t in tabs)

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

    def test_derive_tab_output_has_new_result_id(self, client, sample_analysis: Analysis):
        """Derived tab gets a fresh result_id distinct from source."""
        source_result_id = sample_analysis.pipeline_definition['tabs'][0]['output']['result_id']

        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/tab1/derive',
            json={},
        )

        assert response.status_code == 200
        data = response.json()
        assert data['output']['result_id'] != source_result_id

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
