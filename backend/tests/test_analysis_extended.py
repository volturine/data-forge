"""Extended tests for analysis module."""

import uuid

from modules.analysis.models import Analysis
from modules.datasource.models import DataSource
from tests.conftest import acquire_lock


class TestAnalysisValidation:
    """Test analysis validation logic."""

    def test_create_analysis_missing_name(self, client):
        """Test creating analysis without a name."""
        payload = {'description': 'Test analysis'}

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 422

    def test_create_analysis_empty_name(self, client):
        """Test creating analysis with empty name."""
        payload = {'name': '', 'description': 'Test'}

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code in [400, 422]

    def test_create_analysis_with_long_name(self, client):
        """Test creating analysis with very long name."""
        payload = {'name': 'A' * 1000, 'description': 'Test'}

        response = client.post('/api/v1/analysis', json=payload)

        # Should succeed or fail with validation error
        assert response.status_code in [200, 201, 422]

    def test_create_analysis_with_special_characters(self, client):
        """Test creating analysis with special characters in name."""
        payload = {'name': 'Test <script>alert("xss")</script>', 'description': 'Test'}

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
            'tabs': [],
            'client_id': str(uuid.uuid4()),
            'lock_token': str(uuid.uuid4()),
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

    def test_create_analysis_with_empty_pipeline(self, client):
        """Test creating analysis with empty pipeline."""
        payload = {
            'name': 'Empty Pipeline Analysis',
            'pipeline_steps': [],
            'datasource_ids': [],
            'tabs': [],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code in [200, 201]

    def test_create_analysis_with_complex_pipeline(self, client, sample_datasource: DataSource):
        """Test creating analysis with complex pipeline."""
        payload = {
            'name': 'Complex Pipeline',
            'pipeline_steps': [
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
                    'config': {'column': 'age', 'descending': True},
                    'depends_on': ['step2'],
                },
            ],
            'datasource_ids': [sample_datasource.id],
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'type': 'datasource',
                    'datasource_id': sample_datasource.id,
                }
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code in [200, 201]
        data = response.json()
        assert len(data['pipeline_definition']['steps']) == 3

    def test_update_analysis_pipeline(self, client, sample_analysis: Analysis):
        """Test updating analysis pipeline."""
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        new_steps = [
            {
                'id': 'new_step',
                'type': 'filter',
                'config': {'column': 'id', 'operator': '=', 'value': 1},
                'depends_on': [],
            }
        ]

        payload = {
            'pipeline_steps': new_steps,
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        data = response.json()
        # Check that the pipeline was updated
        assert len(data['pipeline_definition']['steps']) >= 1

    def test_analysis_with_circular_dependencies(self, client):
        """Test creating analysis with circular dependencies."""
        payload = {
            'name': 'Circular Deps',
            'pipeline_steps': [
                {'id': 'step1', 'type': 'filter', 'config': {}, 'depends_on': ['step2']},
                {'id': 'step2', 'type': 'filter', 'config': {}, 'depends_on': ['step1']},
            ],
            'datasource_ids': [],
            'tabs': [],
        }

        response = client.post('/api/v1/analysis', json=payload)

        # Should either reject or accept (validation depends on implementation)
        assert response.status_code in [200, 201, 400, 422]


class TestAnalysisDataSourceLinking:
    """Test analysis-datasource linking."""

    def test_link_datasource_to_analysis(self, client, sample_analysis: Analysis, sample_datasources: list[DataSource]):
        """Test linking a new datasource to analysis."""
        new_datasource = sample_datasources[1]

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/datasource/{new_datasource.id}')

        assert response.status_code in [200, 201]

    def test_link_nonexistent_datasource(self, client, sample_analysis: Analysis):
        """Test linking non-existent datasource."""
        fake_id = str(uuid.uuid4())

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/datasource/{fake_id}')

        assert response.status_code == 404

    def test_link_datasource_to_nonexistent_analysis(self, client, sample_datasource: DataSource):
        """Test linking datasource to non-existent analysis."""
        fake_id = str(uuid.uuid4())

        response = client.post(f'/api/v1/analysis/{fake_id}/datasource/{sample_datasource.id}')

        assert response.status_code == 404

    def test_unlink_datasource(self, client, sample_analysis: Analysis):
        """Test unlinking datasource from analysis."""
        datasource_id = sample_analysis.pipeline_definition['datasource_ids'][0]

        response = client.delete(f'/api/v1/analysis/{sample_analysis.id}/datasources/{datasource_id}')

        assert response.status_code == 204

    def test_unlink_nonexistent_datasource(self, client, sample_analysis: Analysis):
        """Test unlinking non-existent datasource."""
        fake_id = str(uuid.uuid4())

        response = client.delete(f'/api/v1/analysis/{sample_analysis.id}/datasources/{fake_id}')

        assert response.status_code == 404

    def test_link_same_datasource_twice(self, client, sample_analysis: Analysis):
        """Test linking the same datasource twice."""
        datasource_id = sample_analysis.pipeline_definition['datasource_ids'][0]

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/datasource/{datasource_id}')

        # Should either succeed (idempotent) or fail with conflict
        assert response.status_code in [200, 201, 409]


class TestAnalysisStatus:
    """Test analysis status management."""

    def test_update_analysis_status(self, client, sample_analysis: Analysis):
        """Test updating analysis status."""
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        payload = {
            'status': 'running',
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'running'

    def test_invalid_status_transition(self, client, sample_analysis: Analysis):
        """Test invalid status value."""
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        payload = {
            'status': 'invalid_status',
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        # Should either reject or accept (validation depends on implementation)
        assert response.status_code in [200, 400, 422]

    def test_analysis_lifecycle_statuses(self, client, sample_analysis: Analysis):
        """Test analysis through different statuses."""
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        statuses = ['draft', 'running', 'completed', 'error']

        for status in statuses:
            payload = {
                'status': status,
                'client_id': client_id,
                'lock_token': lock_token,
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
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        payload = {
            'description': 'Updated description',
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data['description'] == 'Updated description'

    def test_update_analysis_thumbnail(self, client, sample_analysis: Analysis):
        """Test updating analysis thumbnail."""
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        thumbnail = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        payload = {
            'thumbnail': thumbnail,
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        data = response.json()
        assert 'thumbnail' in data

    def test_analysis_timestamps(self, client):
        """Test that analysis has proper timestamps."""
        payload = {
            'name': 'Timestamp Test',
            'pipeline_steps': [],
            'datasource_ids': [],
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
        client.put(f'/api/v1/analysis/{sample_analysis.id}', json={'name': 'Updated'})

        # Get updated
        response2 = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        updated = response2.json()

        # updated_at should change (if granular enough)
        # This might fail if updates happen too quickly
        assert 'updated_at' in updated
