import uuid

from sqlalchemy import select

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource
from tests.conftest import acquire_lock


class TestAnalysisCreate:
    def test_create_analysis_success(self, client, sample_datasource: DataSource):
        payload = {
            'name': 'New Analysis',
            'description': 'Test analysis description',
            'datasource_ids': [sample_datasource.id],
            'pipeline_steps': [
                {
                    'id': 'step1',
                    'type': 'filter',
                    'config': {'column': 'age', 'operator': '>', 'value': 25},
                    'depends_on': [],
                }
            ],
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'type': 'datasource',
                    'parent_id': None,
                    'datasource_id': sample_datasource.id,
                }
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'New Analysis'
        assert result['description'] == 'Test analysis description'
        assert result['status'] == 'draft'
        assert 'id' in result
        assert 'created_at' in result
        assert 'updated_at' in result

        assert 'pipeline_definition' in result
        assert len(result['pipeline_definition']['steps']) == 1
        assert result['pipeline_definition']['datasource_ids'] == [sample_datasource.id]
        assert result['tabs'][0]['datasource_id'] == sample_datasource.id

    def test_create_analysis_with_multiple_datasources(self, client, sample_datasources: list[DataSource]):
        datasource_ids = [ds.id for ds in sample_datasources]

        payload = {
            'name': 'Multi-Source Analysis',
            'description': 'Analysis with multiple datasources',
            'datasource_ids': datasource_ids,
            'pipeline_steps': [
                {
                    'id': 'step1',
                    'type': 'join',
                    'config': {'left': datasource_ids[0], 'right': datasource_ids[1], 'on': 'id'},
                    'depends_on': [],
                }
            ],
            'tabs': [
                {
                    'id': 'tab-left',
                    'name': 'Left Source',
                    'type': 'datasource',
                    'parent_id': None,
                    'datasource_id': datasource_ids[0],
                },
                {
                    'id': 'tab-right',
                    'name': 'Right Source',
                    'type': 'datasource',
                    'parent_id': None,
                    'datasource_id': datasource_ids[1],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Multi-Source Analysis'
        assert set(result['pipeline_definition']['datasource_ids']) == set(datasource_ids)

    def test_create_analysis_with_invalid_datasource(self, client):
        payload = {
            'name': 'Invalid Analysis',
            'description': 'Test',
            'datasource_ids': [str(uuid.uuid4())],
            'pipeline_steps': [],
            'tabs': [],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    def test_create_analysis_without_description(self, client, sample_datasource: DataSource):
        payload = {
            'name': 'Analysis Without Description',
            'datasource_ids': [sample_datasource.id],
            'pipeline_steps': [],
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'type': 'datasource',
                    'parent_id': None,
                    'datasource_id': sample_datasource.id,
                }
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Analysis Without Description'
        assert result['description'] is None
        assert result['tabs']

    def test_create_analysis_with_complex_pipeline(self, client, sample_datasource: DataSource):
        payload = {
            'name': 'Complex Pipeline Analysis',
            'description': 'Multi-step pipeline',
            'datasource_ids': [sample_datasource.id],
            'pipeline_steps': [
                {
                    'id': 'step1',
                    'type': 'filter',
                    'config': {'column': 'age', 'operator': '>', 'value': 25},
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
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'type': 'datasource',
                    'parent_id': None,
                    'datasource_id': sample_datasource.id,
                }
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert len(result['pipeline_definition']['steps']) == 3
        assert result['pipeline_definition']['steps'][1]['depends_on'] == ['step1']
        assert result['pipeline_definition']['steps'][2]['depends_on'] == ['step2']


class TestAnalysisGet:
    def test_get_analysis_success(self, client, sample_analysis: Analysis):
        response = client.get(f'/api/v1/analysis/{sample_analysis.id}')

        assert response.status_code == 200
        result = response.json()

        assert result['id'] == sample_analysis.id
        assert result['name'] == sample_analysis.name
        assert result['description'] == sample_analysis.description
        assert result['status'] == sample_analysis.status

    def test_get_analysis_not_found(self, client):
        missing_id = str(uuid.uuid4())
        response = client.get(f'/api/v1/analysis/{missing_id}')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']


class TestAnalysisList:
    def test_list_empty_analyses(self, client):
        response = client.get('/api/v1/analysis')

        assert response.status_code == 200
        result = response.json()

        assert isinstance(result, list)
        assert len(result) == 0

    def test_list_analyses_with_data(self, client, sample_analyses: list[Analysis]):
        response = client.get('/api/v1/analysis')

        assert response.status_code == 200
        result = response.json()

        assert isinstance(result, list)
        assert len(result) == 3

        for item in result:
            assert 'id' in item
            assert 'name' in item
            assert 'thumbnail' in item
            assert 'created_at' in item
            assert 'updated_at' in item

    def test_list_analyses_returns_gallery_items(self, client, sample_analysis: Analysis):
        response = client.get('/api/v1/analysis')

        assert response.status_code == 200
        result = response.json()

        assert len(result) == 1
        item = result[0]

        assert item['id'] == sample_analysis.id
        assert item['name'] == sample_analysis.name


class TestAnalysisUpdate:
    def test_update_analysis_name(self, client, sample_analysis: Analysis):
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        payload = {
            'name': 'Updated Analysis Name',
            'tabs': [],
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Updated Analysis Name'
        assert result['description'] == sample_analysis.description

    def test_update_analysis_description(self, client, sample_analysis: Analysis):
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        payload = {
            'description': 'Updated description',
            'tabs': [],
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['description'] == 'Updated description'
        assert result['name'] == sample_analysis.name

    def test_update_analysis_pipeline_steps(self, client, sample_analysis: Analysis):
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        payload = {
            'pipeline_steps': [
                {
                    'id': 'new_step',
                    'type': 'aggregate',
                    'config': {'column': 'age', 'operation': 'mean'},
                    'depends_on': [],
                }
            ],
            'tabs': [
                {
                    'id': 'tab-updated',
                    'name': 'Source',
                    'type': 'datasource',
                    'parent_id': None,
                    'datasource_id': sample_analysis.pipeline_definition['datasource_ids'][0],
                }
            ],
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert len(result['pipeline_definition']['steps']) == 1
        assert result['pipeline_definition']['steps'][0]['id'] == 'new_step'
        assert result['pipeline_definition']['steps'][0]['type'] == 'aggregate'
        assert result['tabs']

    def test_update_analysis_status(self, client, sample_analysis: Analysis):
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        payload = {
            'status': 'completed',
            'tabs': [],
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['status'] == 'completed'

    def test_update_analysis_multiple_fields(self, client, sample_analysis: Analysis):
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        payload: dict[str, object] = {
            'name': 'Updated Name',
            'description': 'Updated Description',
            'status': 'running',
            'tabs': [],
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Updated Name'
        assert result['description'] == 'Updated Description'
        assert result['status'] == 'running'

    def test_update_analysis_not_found(self, client):
        payload = {
            'name': 'Updated Name',
            'tabs': [],
            'client_id': str(uuid.uuid4()),
            'lock_token': str(uuid.uuid4()),
        }
        missing_id = str(uuid.uuid4())

        response = client.put(f'/api/v1/analysis/{missing_id}', json=payload)

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    def test_update_analysis_empty_payload(self, client, sample_analysis: Analysis):
        client_id, lock_token = acquire_lock(client, sample_analysis.id)
        payload: dict[str, object] = {
            'tabs': [],
            'client_id': client_id,
            'lock_token': lock_token,
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == sample_analysis.name
        assert result['description'] == sample_analysis.description


class TestAnalysisDelete:
    def test_delete_analysis_success(self, client, sample_analysis: Analysis, test_db_session):
        analysis_id = sample_analysis.id

        response = client.delete(f'/api/v1/analysis/{analysis_id}')

        assert response.status_code == 204

        get_response = client.get(f'/api/v1/analysis/{analysis_id}')
        assert get_response.status_code == 404

    def test_delete_analysis_not_found(self, client):
        missing_id = str(uuid.uuid4())
        response = client.delete(f'/api/v1/analysis/{missing_id}')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    def test_delete_analysis_cascades_links(self, client, sample_analysis: Analysis, test_db_session):
        analysis_id = sample_analysis.id

        result = test_db_session.execute(select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id))  # type: ignore[arg-type]
        links_before = result.scalars().all()
        assert len(links_before) > 0

        response = client.delete(f'/api/v1/analysis/{analysis_id}')
        assert response.status_code == 204

        result = test_db_session.execute(select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id))  # type: ignore[arg-type]
        links_after = result.scalars().all()
        assert len(links_after) == 0


class TestAnalysisDataSourceLink:
    def test_link_datasource_success(self, client, sample_analysis: Analysis, sample_datasources: list[DataSource]):
        new_datasource = sample_datasources[1]

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/datasource/{new_datasource.id}')

        assert response.status_code == 200
        assert 'linked' in response.json()['message']

        get_response = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        result = get_response.json()

        assert new_datasource.id in result['pipeline_definition']['datasource_ids']

    def test_link_datasource_already_linked(self, client, sample_analysis: Analysis, sample_datasource: DataSource):
        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/datasource/{sample_datasource.id}')

        assert response.status_code == 200

        get_response = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        result = get_response.json()

        datasource_count = result['pipeline_definition']['datasource_ids'].count(sample_datasource.id)
        assert datasource_count == 1

    def test_link_datasource_analysis_not_found(self, client, sample_datasource: DataSource):
        missing_id = str(uuid.uuid4())
        response = client.post(f'/api/v1/analysis/{missing_id}/datasource/{sample_datasource.id}')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    def test_link_datasource_datasource_not_found(self, client, sample_analysis: Analysis):
        missing_id = str(uuid.uuid4())
        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/datasource/{missing_id}')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']
