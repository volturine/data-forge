import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlmodel import Session

from main import app
from modules.analysis.models import Analysis, AnalysisDataSource
from modules.analysis.schemas import AnalysisResponseSchema
from modules.auth.dependencies import get_optional_user
from modules.datasource.models import DataSource
from modules.locks.models import ResourceLock


def _schema_enum_values(schema: dict, field_name: str) -> list[str]:
    field_schema = schema.get('properties', {}).get(field_name, {})
    if field_schema.get('type') == 'array':
        item_schema = field_schema.get('items', {})
        enum_values = item_schema.get('enum')
        if enum_values is not None:
            return enum_values
        ref = item_schema.get('$ref')
        if isinstance(ref, str):
            return schema.get('$defs', {}).get(ref.split('/')[-1], {}).get('enum', [])
        return []
    enum_values = field_schema.get('enum')
    if enum_values is not None:
        return enum_values
    ref = field_schema.get('$ref')
    if isinstance(ref, str):
        return schema.get('$defs', {}).get(ref.split('/')[-1], {}).get('enum', [])
    return []


def test_analysis_response_schema_omits_status() -> None:
    schema = AnalysisResponseSchema.model_json_schema()
    assert 'status' not in schema.get('properties', {})


class TestAnalysisCreate:
    def test_create_analysis_success(self, client, sample_datasource: DataSource):
        payload = {
            'name': 'New Analysis',
            'description': 'Test analysis description',
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
                        'filename': 'source_1',
                    },
                    'steps': [
                        {
                            'id': 'step1',
                            'type': 'filter',
                            'config': {'column': 'age', 'operator': '>', 'value': 25},
                            'depends_on': [],
                        },
                    ],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'New Analysis'
        assert result['description'] == 'Test analysis description'
        assert 'id' in result
        assert 'created_at' in result
        assert 'updated_at' in result

        assert 'pipeline_definition' in result
        assert len(result['pipeline_definition']['tabs'][0]['steps']) == 1
        assert 'datasource_ids' not in result['pipeline_definition']
        assert result['pipeline_definition']['tabs'][0]['datasource']['id'] == sample_datasource.id

    def test_create_analysis_with_multiple_datasources(self, client, sample_datasources: list[DataSource]):
        datasource_ids = [ds.id for ds in sample_datasources]

        payload = {
            'name': 'Multi-Source Analysis',
            'description': 'Analysis with multiple datasources',
            'tabs': [
                {
                    'id': 'tab-left',
                    'name': 'Left Source',
                    'parent_id': None,
                    'datasource': {
                        'id': datasource_ids[0],
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'left_source',
                    },
                    'steps': [
                        {
                            'id': 'step1',
                            'type': 'join',
                            'config': {'left': datasource_ids[0], 'right': datasource_ids[1], 'on': 'id'},
                            'depends_on': [],
                        },
                    ],
                },
                {
                    'id': 'tab-right',
                    'name': 'Right Source',
                    'parent_id': None,
                    'datasource': {
                        'id': datasource_ids[1],
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'right_source',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Multi-Source Analysis'
        assert 'datasource_ids' not in result['pipeline_definition']

    def test_create_analysis_with_invalid_datasource(self, client):
        payload = {
            'name': 'Invalid Analysis',
            'description': 'Test',
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
                        'filename': 'source_2',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    def test_create_analysis_without_description(self, client, sample_datasource: DataSource):
        payload = {
            'name': 'Analysis Without Description',
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
                        'filename': 'source_3',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Analysis Without Description'
        assert result['description'] is None
        assert result['pipeline_definition']['tabs']

    def test_create_analysis_with_complex_pipeline(self, client, sample_datasource: DataSource):
        payload = {
            'name': 'Complex Pipeline Analysis',
            'description': 'Multi-step pipeline',
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
                        'filename': 'source_4',
                    },
                    'steps': [
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
                            'config': {'columns': ['age'], 'descending': [True]},
                            'depends_on': ['step2'],
                        },
                    ],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert len(result['pipeline_definition']['tabs'][0]['steps']) == 3
        assert result['pipeline_definition']['tabs'][0]['steps'][1]['depends_on'] == ['step1']
        assert result['pipeline_definition']['tabs'][0]['steps'][2]['depends_on'] == ['step2']

    def test_create_analysis_rejects_pipeline_steps(self, client, sample_datasource: DataSource):
        payload = {
            'name': 'Legacy Payload',
            'pipeline_steps': [{'id': 'step1', 'type': 'filter', 'config': {}}],
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
                        'filename': 'source_legacy',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 422

    def test_create_analysis_with_derived_tab_no_datasource_row(self, client, sample_datasource: DataSource):
        tab1_result_id = str(uuid.uuid4())
        payload = {
            'name': 'Derived Tab Analysis',
            'description': 'Tab-2 derives from tab-1 output',
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
                        'result_id': tab1_result_id,
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'derived_source',
                    },
                    'steps': [],
                },
                {
                    'id': 'tab2',
                    'name': 'Derived',
                    'parent_id': 'tab1',
                    'datasource': {
                        'id': tab1_result_id,
                        'analysis_tab_id': 'tab1',
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'derived_output',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        result = response.json()
        assert len(result['pipeline_definition']['tabs']) == 2
        assert result['pipeline_definition']['tabs'][1]['datasource']['id'] == tab1_result_id

    def test_create_analysis_does_not_create_output_datasource_until_build(
        self,
        client,
        sample_datasource: DataSource,
        test_db_session,
    ):
        output_id = str(uuid.uuid4())
        payload = {
            'name': 'Output Placeholder Analysis',
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
                        'result_id': output_id,
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'placeholder_out',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200

        output_ds = test_db_session.get(DataSource, output_id)
        assert output_ds is None

    def test_create_analysis_sets_owner_id_when_optional_user_present(
        self,
        client,
        sample_datasource: DataSource,
        test_db_session,
        test_user,
        monkeypatch,
    ):
        monkeypatch.setitem(app.dependency_overrides, get_optional_user, lambda: test_user)
        payload = {
            'name': 'Owned Analysis',
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
                        'filename': 'owned_source',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)
        assert response.status_code == 200
        analysis_id = response.json()['id']
        created = test_db_session.get(Analysis, analysis_id)
        assert created is not None
        assert created.owner_id == test_user.id

    def test_create_analysis_persists_when_request_session_already_started(
        self,
        client,
        sample_datasource: DataSource,
        test_engine,
    ):
        payload = {
            'name': 'Persisted Analysis',
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
                        'filename': 'persisted_source',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 200
        analysis_id = response.json()['id']
        with Session(test_engine) as fresh_session:
            created = fresh_session.get(Analysis, analysis_id)
            assert created is not None
            links = (
                fresh_session.execute(
                    select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id)  # type: ignore[arg-type]
                )
                .scalars()
                .all()
            )
            assert [link.datasource_id for link in links] == [sample_datasource.id]


class TestAnalysisGet:
    def test_get_analysis_success(self, client, sample_analysis: Analysis):
        response = client.get(f'/api/v1/analysis/{sample_analysis.id}')

        assert response.status_code == 200
        result = response.json()

        assert result['id'] == sample_analysis.id
        assert result['name'] == sample_analysis.name
        assert result['description'] == sample_analysis.description

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


class TestAnalysisImport:
    def test_import_analysis_applies_datasource_remap_before_missing_check(self, client, sample_datasource: DataSource):
        legacy_source_id = 'legacy-source-id'
        payload = {
            'name': 'Imported Analysis',
            'description': 'Imported with datasource remap',
            'datasource_remap': {legacy_source_id: sample_datasource.id},
            'pipeline': {
                'tabs': [
                    {
                        'id': 'tab-legacy',
                        'name': 'Legacy Source',
                        'parent_id': None,
                        'datasource': {
                            'id': legacy_source_id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': str(uuid.uuid4()),
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'legacy_source',
                        },
                        'steps': [],
                    },
                ],
            },
        }

        response = client.post('/api/v1/analysis/import', json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body['name'] == 'Imported Analysis'
        assert body['pipeline_definition']['tabs'][0]['datasource']['id'] == sample_datasource.id


class TestAnalysisUpdate:
    def test_update_analysis_sets_version_headers(self, client, sample_analysis: Analysis):
        current = client.get(f'/api/v1/analysis/{sample_analysis.id}')
        payload = {
            'name': 'Updated Analysis Name',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(
            f'/api/v1/analysis/{sample_analysis.id}',
            json=payload,
            headers={'If-Match': current.headers['ETag']},
        )

        assert response.status_code == 200
        result = response.json()
        assert response.headers['X-Analysis-Version'] == result['updated_at']
        assert response.headers['ETag'] == f'"analysis-{result["id"]}-{result["updated_at"]}"'

    def test_update_analysis_rejects_stale_if_match(self, client, sample_analysis: Analysis):
        payload = {
            'name': 'Updated Analysis Name',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(
            f'/api/v1/analysis/{sample_analysis.id}',
            json=payload,
            headers={'If-Match': '"analysis-stale"'},
        )

        assert response.status_code == 412
        assert response.json()['detail'] == 'Analysis version mismatch'

    def test_update_analysis_blocked_when_locked_by_another_owner(self, client, sample_analysis: Analysis, test_db_session):
        now = datetime.now(UTC).replace(tzinfo=None)
        row = ResourceLock(
            resource_type='analysis',
            resource_id=sample_analysis.id,
            owner_id='other-owner',
            lock_token='lock-token',
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
            last_heartbeat=now,
        )
        test_db_session.add(row)
        test_db_session.commit()

        payload = {
            'name': 'Updated Analysis Name',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }
        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 409
        assert 'locked by another owner' in response.json()['detail']

    def test_update_analysis_name(self, client, sample_analysis: Analysis):
        payload = {
            'name': 'Updated Analysis Name',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Updated Analysis Name'
        assert result['description'] == sample_analysis.description

    def test_update_analysis_description(self, client, sample_analysis: Analysis):
        payload = {
            'description': 'Updated description',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['description'] == 'Updated description'
        assert result['name'] == sample_analysis.name

    def test_update_analysis_tab_steps(self, client, sample_analysis: Analysis):
        payload = {
            'tabs': [
                {
                    'id': 'tab-updated',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_analysis.pipeline_definition['tabs'][0]['datasource']['id'],
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_5',
                    },
                    'steps': [
                        {
                            'id': 'new_step',
                            'type': 'groupby',
                            'config': {'column': 'age', 'operation': 'mean'},
                            'depends_on': [],
                        },
                    ],
                },
            ],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert len(result['pipeline_definition']['tabs'][0]['steps']) == 1
        assert result['pipeline_definition']['tabs'][0]['steps'][0]['id'] == 'new_step'
        assert result['pipeline_definition']['tabs'][0]['steps'][0]['type'] == 'groupby'
        assert result['pipeline_definition']['tabs']

    def test_update_analysis_rejects_status(self, client, sample_analysis: Analysis):
        payload = {
            'status': 'completed',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 422

    def test_update_analysis_multiple_fields(self, client, sample_analysis: Analysis):
        payload: dict[str, object] = {
            'name': 'Updated Name',
            'description': 'Updated Description',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == 'Updated Name'
        assert result['description'] == 'Updated Description'

    def test_update_analysis_not_found(self, client, sample_analysis: Analysis):
        payload = {
            'name': 'Updated Name',
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }
        missing_id = str(uuid.uuid4())

        response = client.put(f'/api/v1/analysis/{missing_id}', json=payload)

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    def test_update_analysis_empty_payload(self, client, sample_analysis: Analysis):
        payload: dict[str, object] = {
            'tabs': sample_analysis.pipeline_definition['tabs'],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert result['name'] == sample_analysis.name
        assert result['description'] == sample_analysis.description

    def test_update_analysis_rejects_pipeline_steps(self, client, sample_analysis: Analysis):
        payload: dict[str, object] = {
            'tabs': sample_analysis.pipeline_definition['tabs'],
            'pipeline_steps': [{'id': 'step1', 'type': 'filter', 'config': {}}],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 422

    def test_update_analysis_derived_tab_no_new_datasource_rows(self, client, sample_analysis: Analysis, test_db_session):
        from sqlalchemy import select as sa_select

        from modules.datasource.models import DataSource as DS

        tab1_result_id = str(uuid.uuid4())
        tab2_result_id = str(uuid.uuid4())
        datasource_id = sample_analysis.pipeline_definition['tabs'][0]['datasource']['id']

        before = test_db_session.execute(sa_select(DS)).scalars().all()

        payload = {
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': datasource_id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': tab1_result_id,
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'upd_source',
                    },
                    'steps': [],
                },
                {
                    'id': 'tab2',
                    'name': 'Derived',
                    'parent_id': 'tab1',
                    'datasource': {
                        'id': tab1_result_id,
                        'analysis_tab_id': 'tab1',
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': tab2_result_id,
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'upd_derived',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}', json=payload)

        assert response.status_code == 200
        after = test_db_session.execute(sa_select(DS)).scalars().all()
        assert len(after) == len(before)


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


class TestStepTypes:
    def test_list_step_types(self, client):
        response = client.get('/api/v1/analysis/step-types')

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, list)
        assert len(result) > 0

        types = {entry['type'] for entry in result}
        assert 'select' in types
        assert 'filter' in types
        assert 'groupby' in types
        assert 'chart' in types

        for entry in result:
            assert 'type' in entry
            assert 'description' in entry
            assert 'category' in entry
            assert 'config_schema' in entry

    def test_step_types_exclude_plot_aliases(self, client):
        response = client.get('/api/v1/analysis/step-types')

        result = response.json()
        types = {entry['type'] for entry in result}
        for t in types:
            assert not t.startswith('plot_')

    def test_step_types_have_valid_categories(self, client):
        response = client.get('/api/v1/analysis/step-types')

        result = response.json()
        valid_categories = {'transform', 'aggregate', 'reshape', 'io', 'visualization', 'advanced'}
        for entry in result:
            assert entry['category'] in valid_categories


class TestAddStep:
    def test_add_step_blocked_when_locked_by_another_owner(self, client, sample_analysis: Analysis, test_db_session):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        now = datetime.now(UTC).replace(tzinfo=None)
        row = ResourceLock(
            resource_type='analysis',
            resource_id=sample_analysis.id,
            owner_id='other-owner',
            lock_token='lock-token',
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
            last_heartbeat=now,
        )
        test_db_session.add(row)
        test_db_session.commit()

        payload = {
            'type': 'select',
            'config': {'columns': ['name', 'age']},
        }

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps', json=payload)

        assert response.status_code == 409
        assert 'locked by another owner' in response.json()['detail']

    def test_add_step_success(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        payload = {
            'type': 'select',
            'config': {'columns': ['name', 'age']},
        }

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps', json=payload)

        assert response.status_code == 200
        result = response.json()
        assert result['type'] == 'select'
        assert result['config'] == {'columns': ['name', 'age']}
        assert 'id' in result
        assert result['depends_on'] == []

    def test_add_step_with_position(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        payload = {
            'type': 'limit',
            'config': {'n': 10},
            'position': 0,
        }

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps', json=payload)

        assert response.status_code == 200
        result = response.json()
        assert result['type'] == 'limit'

        analysis = client.get(f'/api/v1/analysis/{sample_analysis.id}').json()
        assert analysis['pipeline_definition']['tabs'][0]['steps'][0]['type'] == 'limit'

    def test_add_step_with_depends_on(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        existing_step_id = sample_analysis.pipeline_definition['tabs'][0]['steps'][0]['id']
        payload = {
            'type': 'sort',
            'config': {'columns': ['age'], 'descending': [True]},
            'depends_on': [existing_step_id],
        }

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps', json=payload)

        assert response.status_code == 200
        result = response.json()
        assert result['depends_on'] == [existing_step_id]

    def test_add_step_invalid_type(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        payload = {
            'type': 'nonexistent_type',
            'config': {},
        }

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps', json=payload)

        assert response.status_code == 422

    def test_add_step_invalid_tab(self, client, sample_analysis: Analysis):
        payload = {
            'type': 'select',
            'config': {'columns': ['name']},
        }

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/nonexistent-tab/steps', json=payload)

        assert response.status_code == 400

    def test_add_step_analysis_not_found(self, client):
        missing_id = str(uuid.uuid4())
        payload = {
            'type': 'select',
            'config': {'columns': ['name']},
        }

        response = client.post(f'/api/v1/analysis/{missing_id}/tabs/tab1/steps', json=payload)

        assert response.status_code == 404

    def test_add_step_creates_version_snapshot(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        payload = {
            'type': 'limit',
            'config': {'n': 50},
        }

        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps', json=payload)

        assert response.status_code == 200

        versions = client.get(f'/api/v1/analysis/{sample_analysis.id}/versions')
        if versions.status_code == 200:
            assert len(versions.json()) >= 1


class TestUpdateStep:
    def test_update_step_config(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        step_id = sample_analysis.pipeline_definition['tabs'][0]['steps'][0]['id']
        payload = {
            'config': {'column': 'name', 'operator': '=', 'value': 'Alice'},
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/{step_id}', json=payload)

        assert response.status_code == 200
        result = response.json()
        assert result['config']['column'] == 'name'
        assert result['config']['value'] == 'Alice'

    def test_update_step_type(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        step_id = sample_analysis.pipeline_definition['tabs'][0]['steps'][0]['id']
        payload = {
            'type': 'limit',
            'config': {'n': 25},
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/{step_id}', json=payload)

        assert response.status_code == 200
        result = response.json()
        assert result['type'] == 'limit'
        assert result['config']['n'] == 25

    def test_update_step_not_found(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        payload = {'config': {'n': 10}}

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/nonexistent', json=payload)

        assert response.status_code == 400

    def test_update_step_invalid_type(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        step_id = sample_analysis.pipeline_definition['tabs'][0]['steps'][0]['id']
        payload = {
            'type': 'invalid_type',
        }

        response = client.put(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/{step_id}', json=payload)

        assert response.status_code == 422


class TestRemoveStep:
    def test_remove_step_success(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        step_id = sample_analysis.pipeline_definition['tabs'][0]['steps'][0]['id']

        response = client.delete(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/{step_id}')

        assert response.status_code == 204

        analysis = client.get(f'/api/v1/analysis/{sample_analysis.id}').json()
        assert len(analysis['pipeline_definition']['tabs'][0]['steps']) == 0

    def test_remove_step_cleans_depends_on(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        first_step_id = sample_analysis.pipeline_definition['tabs'][0]['steps'][0]['id']

        add_payload = {
            'type': 'sort',
            'config': {'columns': ['age'], 'descending': [False]},
            'depends_on': [first_step_id],
        }
        add_response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps', json=add_payload)
        assert add_response.status_code == 200
        second_step_id = add_response.json()['id']

        delete_response = client.delete(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/{first_step_id}')
        assert delete_response.status_code == 204

        analysis = client.get(f'/api/v1/analysis/{sample_analysis.id}').json()
        remaining = analysis['pipeline_definition']['tabs'][0]['steps']
        assert len(remaining) == 1
        assert remaining[0]['id'] == second_step_id
        assert first_step_id not in remaining[0].get('depends_on', [])

    def test_remove_step_not_found(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']

        response = client.delete(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/nonexistent')

        assert response.status_code == 400

    def test_remove_step_analysis_not_found(self, client):
        missing_id = str(uuid.uuid4())

        response = client.delete(f'/api/v1/analysis/{missing_id}/tabs/tab1/steps/step1')

        assert response.status_code == 404


class TestAnalysisValidate:
    def test_validate_returns_payload_for_valid_input(self, client, sample_datasource: DataSource):
        payload = {
            'name': 'Validate Test',
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
                        'filename': 'out_validate',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis/validate', json=payload)

        assert response.status_code == 200
        result = response.json()
        assert result['valid'] is True
        assert 'payload' in result
        assert 'tabs' in result['payload']
        assert len(result['payload']['tabs']) == 1

    def test_validate_returns_404_for_invalid_datasource_id(self, client):
        payload = {
            'name': 'Validate Test',
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
                        'filename': 'out_validate_bad',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis/validate', json=payload)

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']

    def test_validate_does_not_persist_analysis(self, client, sample_datasource: DataSource):
        payload = {
            'name': 'Validate No Persist',
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
                        'filename': 'out_no_persist',
                    },
                    'steps': [],
                },
            ],
        }

        client.post('/api/v1/analysis/validate', json=payload)

        list_response = client.get('/api/v1/analysis')
        assert list_response.status_code == 200
        analyses = list_response.json()
        names = [a['name'] for a in analyses]
        assert 'Validate No Persist' not in names


class TestStepValidation:
    def _make_payload(self, datasource_id: str, steps: list[dict]) -> dict:
        return {
            'name': 'Step Validation Test',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': datasource_id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'format': 'parquet',
                        'filename': 'test_out',
                    },
                    'steps': steps,
                },
            ],
        }

    def test_rejects_unknown_step_type(self, client, sample_datasource: DataSource):
        payload = self._make_payload(
            sample_datasource.id,
            [{'id': 's1', 'type': 'nonexistent_op', 'config': {}, 'depends_on': []}],
        )
        response = client.post('/api/v1/analysis', json=payload)
        assert response.status_code == 422

    def test_rejects_invalid_sort_config(self, client, sample_datasource: DataSource):
        payload = self._make_payload(
            sample_datasource.id,
            [{'id': 's1', 'type': 'sort', 'config': {'descending': {'bad': True}}, 'depends_on': []}],
        )
        response = client.post('/api/v1/analysis', json=payload)
        assert response.status_code == 400

    def test_rejects_depends_on_nonexistent_step(self, client, sample_datasource: DataSource):
        payload = self._make_payload(
            sample_datasource.id,
            [{'id': 's1', 'type': 'select', 'config': {'columns': ['a']}, 'depends_on': ['missing']}],
        )
        response = client.post('/api/v1/analysis', json=payload)
        assert response.status_code == 400

    def test_rejects_join_with_nonexistent_tab(self, client, sample_datasource: DataSource):
        payload = self._make_payload(
            sample_datasource.id,
            [
                {
                    'id': 's1',
                    'type': 'join',
                    'config': {'right_source': 'nonexistent_tab', 'how': 'inner', 'join_columns': []},
                    'depends_on': [],
                },
            ],
        )
        response = client.post('/api/v1/analysis', json=payload)
        assert response.status_code == 400

    def test_accepts_valid_steps(self, client, sample_datasource: DataSource):
        payload = self._make_payload(
            sample_datasource.id,
            [
                {
                    'id': 's1',
                    'type': 'filter',
                    'config': {
                        'conditions': [{'column': 'age', 'operator': '>', 'value': 25}],
                        'logic': 'AND',
                    },
                    'depends_on': [],
                },
                {
                    'id': 's2',
                    'type': 'select',
                    'config': {'columns': ['name']},
                    'depends_on': ['s1'],
                },
            ],
        )
        response = client.post('/api/v1/analysis', json=payload)
        assert response.status_code == 200

    def test_add_step_rejects_bad_dependency(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        payload = {
            'type': 'select',
            'config': {'columns': ['name']},
            'depends_on': ['nonexistent_step'],
        }
        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps', json=payload)
        assert response.status_code == 400
