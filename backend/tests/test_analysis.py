import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource


@pytest.mark.asyncio
class TestAnalysisCreate:
    async def test_create_analysis_success(self, client: AsyncClient, sample_datasource: DataSource):
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
        }

        response = await client.post('/api/v1/analysis', json=payload)

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

    async def test_create_analysis_with_multiple_datasources(self, client: AsyncClient, sample_datasources: list[DataSource]):
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
        }

        response = await client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Multi-Source Analysis'
        assert set(result['pipeline_definition']['datasource_ids']) == set(datasource_ids)

    async def test_create_analysis_with_invalid_datasource(self, client: AsyncClient):
        payload = {
            'name': 'Invalid Analysis',
            'description': 'Test',
            'datasource_ids': ['non-existent-id'],
            'pipeline_steps': [],
        }

        response = await client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 400
        assert 'not found' in response.json()['detail']

    async def test_create_analysis_without_description(self, client: AsyncClient, sample_datasource: DataSource):
        payload = {
            'name': 'Analysis Without Description',
            'datasource_ids': [sample_datasource.id],
            'pipeline_steps': [],
        }

        response = await client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Analysis Without Description'
        assert result['description'] is None

    async def test_create_analysis_with_complex_pipeline(self, client: AsyncClient, sample_datasource: DataSource):
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
        }

        response = await client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert len(result['pipeline_definition']['steps']) == 3
        assert result['pipeline_definition']['steps'][1]['depends_on'] == ['step1']
        assert result['pipeline_definition']['steps'][2]['depends_on'] == ['step2']


@pytest.mark.asyncio
class TestAnalysisGet:
    async def test_get_analysis_success(self, client: AsyncClient, sample_analysis: Analysis):
        response = await client.get(f'/api/v1/analysis/{sample_analysis.id}')

        assert response.status_code == 200
        result = response.json()

        assert result['id'] == sample_analysis.id
        assert result['name'] == sample_analysis.name
        assert result['description'] == sample_analysis.description
        assert result['status'] == sample_analysis.status

    async def test_get_analysis_not_found(self, client: AsyncClient):
        response = await client.get('/api/v1/analysis/non-existent-id')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']


@pytest.mark.asyncio
class TestAnalysisList:
    async def test_list_empty_analyses(self, client: AsyncClient):
        response = await client.get('/api/v1/analysis')

        assert response.status_code == 200
        result = response.json()

        assert isinstance(result, list)
        assert len(result) == 0

    async def test_list_analyses_with_data(self, client: AsyncClient, sample_analyses: list[Analysis]):
        response = await client.get('/api/v1/analysis')

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

    async def test_list_analyses_returns_gallery_items(self, client: AsyncClient, sample_analysis: Analysis):
        response = await client.get('/api/v1/analysis')

        assert response.status_code == 200
        result = response.json()

        assert len(result) == 1
        item = result[0]

        assert item['id'] == sample_analysis.id
        assert item['name'] == sample_analysis.name


@pytest.mark.asyncio
class TestAnalysisUpdate:
    async def test_update_analysis_name(self, client: AsyncClient, sample_analysis: Analysis):
        payload = {'name': 'Updated Analysis Name'}

        response = await client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Updated Analysis Name'
        assert result['description'] == sample_analysis.description

    async def test_update_analysis_description(self, client: AsyncClient, sample_analysis: Analysis):
        payload = {'description': 'Updated description'}

        response = await client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['description'] == 'Updated description'
        assert result['name'] == sample_analysis.name

    async def test_update_analysis_pipeline_steps(self, client: AsyncClient, sample_analysis: Analysis):
        payload = {
            'pipeline_steps': [
                {
                    'id': 'new_step',
                    'type': 'aggregate',
                    'config': {'column': 'age', 'operation': 'mean'},
                    'depends_on': [],
                }
            ]
        }

        response = await client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert len(result['pipeline_definition']['steps']) == 1
        assert result['pipeline_definition']['steps'][0]['id'] == 'new_step'
        assert result['pipeline_definition']['steps'][0]['type'] == 'aggregate'

    async def test_update_analysis_status(self, client: AsyncClient, sample_analysis: Analysis):
        payload = {'status': 'completed'}

        response = await client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['status'] == 'completed'

    async def test_update_analysis_multiple_fields(self, client: AsyncClient, sample_analysis: Analysis):
        payload = {
            'name': 'Updated Name',
            'description': 'Updated Description',
            'status': 'running',
        }

        response = await client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Updated Name'
        assert result['description'] == 'Updated Description'
        assert result['status'] == 'running'

    async def test_update_analysis_not_found(self, client: AsyncClient):
        payload = {'name': 'Updated Name'}

        response = await client.put('/api/v1/analysis/non-existent-id', json=payload)

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    async def test_update_analysis_empty_payload(self, client: AsyncClient, sample_analysis: Analysis):
        payload = {}

        response = await client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == sample_analysis.name
        assert result['description'] == sample_analysis.description


@pytest.mark.asyncio
class TestAnalysisDelete:
    async def test_delete_analysis_success(self, client: AsyncClient, sample_analysis: Analysis, test_db_session: AsyncSession):
        analysis_id = sample_analysis.id

        response = await client.delete(f'/api/v1/analysis/{analysis_id}')

        assert response.status_code == 200
        assert 'deleted successfully' in response.json()['message']

        get_response = await client.get(f'/api/v1/analysis/{analysis_id}')
        assert get_response.status_code == 404

    async def test_delete_analysis_not_found(self, client: AsyncClient):
        response = await client.delete('/api/v1/analysis/non-existent-id')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    async def test_delete_analysis_cascades_links(self, client: AsyncClient, sample_analysis: Analysis, test_db_session: AsyncSession):
        from sqlalchemy import select

        analysis_id = sample_analysis.id

        result = await test_db_session.execute(select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id))
        links_before = result.scalars().all()
        assert len(links_before) > 0

        response = await client.delete(f'/api/v1/analysis/{analysis_id}')
        assert response.status_code == 200

        result = await test_db_session.execute(select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id))
        links_after = result.scalars().all()
        assert len(links_after) == 0


@pytest.mark.asyncio
class TestAnalysisDataSourceLink:
    async def test_link_datasource_success(self, client: AsyncClient, sample_analysis: Analysis, sample_datasources: list[DataSource]):
        new_datasource = sample_datasources[1]

        response = await client.post(f'/api/v1/analysis/{sample_analysis.id}/datasource/{new_datasource.id}')

        assert response.status_code == 200
        assert 'linked' in response.json()['message']

        get_response = await client.get(f'/api/v1/analysis/{sample_analysis.id}')
        result = get_response.json()

        assert new_datasource.id in result['pipeline_definition']['datasource_ids']

    async def test_link_datasource_already_linked(self, client: AsyncClient, sample_analysis: Analysis, sample_datasource: DataSource):
        response = await client.post(f'/api/v1/analysis/{sample_analysis.id}/datasource/{sample_datasource.id}')

        assert response.status_code == 200

        get_response = await client.get(f'/api/v1/analysis/{sample_analysis.id}')
        result = get_response.json()

        datasource_count = result['pipeline_definition']['datasource_ids'].count(sample_datasource.id)
        assert datasource_count == 1

    async def test_link_datasource_analysis_not_found(self, client: AsyncClient, sample_datasource: DataSource):
        response = await client.post(f'/api/v1/analysis/non-existent-id/datasource/{sample_datasource.id}')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    async def test_link_datasource_datasource_not_found(self, client: AsyncClient, sample_analysis: Analysis):
        response = await client.post(f'/api/v1/analysis/{sample_analysis.id}/datasource/non-existent-id')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']
