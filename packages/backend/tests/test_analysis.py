import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlmodel import Session

from backend_core.persistence.analysis.models import Analysis, AnalysisDataSource, AnalysisFavorite
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.locks.models import ResourceLock
from backend_core.sqlmodel_typing import sa
from main import app
from modules.analysis import service as analysis_service
from modules.analysis.schemas import AnalysisResponseSchema
from modules.auth.dependencies import get_optional_user
from tests.http_client import TestClient


@pytest.fixture(autouse=True)
def _use_current_analysis_revision(client: TestClient) -> None:
    client.headers['If-Match'] = '1'


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


def _groupby_config(column: str, function: str, alias: str) -> dict[str, object]:
    return {
        'group_by': [],
        'aggregations': [
            {
                'column': column,
                'function': function,
                'alias': alias,
            }
        ],
    }


def _join_config(right_source: str, left_column: str = 'id', right_column: str = 'id') -> dict[str, object]:
    return {
        'how': 'inner',
        'right_source': right_source,
        'join_columns': [
            {
                'id': 'join-1',
                'left_column': left_column,
                'right_column': right_column,
            }
        ],
        'right_columns': [],
        'suffix': '_right',
    }


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
                            'config': _filter_config('age', '>', 25),
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
                            'config': _join_config(datasource_ids[1]),
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

    def test_create_analysis_rejects_hidden_datasource_input(
        self,
        client,
        test_db_session: Session,
    ):
        hidden = DataSource(
            id=str(uuid.uuid4()),
            name='hidden-output',
            description=None,
            source_type='iceberg',
            config={'branch': 'master'},
            schema_cache=None,
            created_by='analysis',
            is_hidden=True,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        test_db_session.add(hidden)
        test_db_session.commit()

        payload = {
            'name': 'Hidden Input Analysis',
            'description': 'Must reject hidden datasources as tab inputs',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': hidden.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_hidden',
                    },
                    'steps': [],
                },
            ],
        }

        response = client.post('/api/v1/analysis', json=payload)

        assert response.status_code == 400
        body = response.json()
        assert 'hidden' in body['detail'].lower()

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
                            'config': _filter_config('age', '>', 25),
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
            'name': 'Unsupported Payload',
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
                        'filename': 'source_unsupported',
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
            links = fresh_session.execute(select(AnalysisDataSource).where(sa(AnalysisDataSource.analysis_id == analysis_id))).scalars().all()
            assert [link.datasource_id for link in links] == [sample_datasource.id]


class TestAnalysisGet:
    def test_get_analysis_success(self, client, sample_analysis: Analysis):
        response = client.get(f'/api/v1/analysis/{sample_analysis.id}')

        assert response.status_code == 200
        result = response.json()

        assert result['id'] == sample_analysis.id
        assert result['name'] == sample_analysis.name
        assert result['description'] == sample_analysis.description
        assert result['is_favorite'] is False

    def test_get_analysis_not_found(self, client):
        missing_id = str(uuid.uuid4())
        response = client.get(f'/api/v1/analysis/{missing_id}')

        assert response.status_code == 404
        assert 'not found' in response.json()['detail']


class TestAnalysisCreationTemplates:
    def test_lists_complete_builtin_template_catalog(self, client):
        response = client.get('/api/v1/analysis/templates')

        assert response.status_code == 200
        templates = response.json()
        assert [template['id'] for template in templates] == [
            'blank',
            'data_quality_audit',
            'elt_transform',
            'aggregation_report',
            'time_series_analysis',
            'join_and_enrich',
        ]
        assert all({'name', 'description', 'icon', 'step_count'} <= template.keys() for template in templates)

    def test_gets_template_detail_with_preview_metadata(self, client):
        response = client.get('/api/v1/analysis/templates/data_quality_audit')

        assert response.status_code == 200
        template = response.json()
        assert template['name'] == 'Data Quality Audit'
        assert template['required_input_columns']
        assert [step['type'] for step in template['steps']] == ['view', 'filter', 'with_columns', 'groupby']
        assert template['step_count'] == len(template['steps'])

    def test_rejects_unknown_template(self, client):
        response = client.get('/api/v1/analysis/templates/not-a-template')

        assert response.status_code == 404
        assert "Unknown analysis template 'not-a-template'" in response.json()['detail']


class TestAnalysisGeneration:
    class FakeClient:
        def __init__(self, response: str):
            self.response = response

        def generate(self, prompt: str, *, model: str, options: dict[str, object]) -> str:
            assert 'Operations:' in prompt
            assert model == 'test-model'
            assert options == {'temperature': 0.2}
            return self.response

    @staticmethod
    def _payload(datasource_id: str) -> dict[str, object]:
        return {
            'name': 'Generated Analysis',
            'description': 'Keep adults and select their names',
            'datasources': [{'id': datasource_id, 'branch': 'feature/generated'}],
            'provider': 'openai',
            'model': 'test-model',
        }

    def test_generates_valid_pipeline_with_controlled_provider(
        self,
        client,
        sample_datasource: DataSource,
        monkeypatch: pytest.MonkeyPatch,
    ):
        generated = {
            'explanation': 'Filter to adults and select the useful columns.',
            'tabs': [
                {
                    'name': 'Adults',
                    'datasource_id': sample_datasource.id,
                    'steps': [
                        {'type': 'filter', 'config': _filter_config('age', '>', 18)},
                        {'type': 'select', 'config': {'columns': ['name', 'age'], 'cast_map': {}}},
                    ],
                }
            ],
        }
        fake_client = self.FakeClient(json.dumps(generated))
        monkeypatch.setattr(
            analysis_service,
            '_resolved_generation_provider',
            lambda _provider=None: ('openai', 'test-model', {'api_key': 'test'}),
        )
        monkeypatch.setattr(analysis_service, 'get_ai_client', lambda *_args, **_kwargs: fake_client)

        response = client.post('/api/v1/analysis/generate', json=self._payload(sample_datasource.id))

        assert response.status_code == 200
        body = response.json()
        assert body['provider'] == 'openai'
        assert body['model'] == 'test-model'
        assert body['explanation'] == generated['explanation']
        tab = body['pipeline']['tabs'][0]
        assert tab['datasource']['id'] == sample_datasource.id
        assert tab['datasource']['config']['branch'] == 'feature/generated'
        assert [step['type'] for step in tab['steps']] == ['filter', 'select']
        assert body['validation']['valid'] is True

    @pytest.mark.parametrize(
        ('generated', 'detail'),
        [
            ('not json', 'AI response did not contain JSON'),
            (
                '{"tabs":[{"name":"Bad source","datasource_id":"unknown","steps":[]}]}',
                'AI response referenced an unknown datasource',
            ),
            (
                '{"tabs":[{"name":"Bad operation","datasource_id":"DATASOURCE_ID","steps":[{"type":"unknown_operation","config":{}}]}]}',
                'Unknown step type',
            ),
        ],
    )
    def test_rejects_invalid_generated_pipeline(
        self,
        client,
        sample_datasource: DataSource,
        monkeypatch: pytest.MonkeyPatch,
        generated: str,
        detail: str,
    ):
        fake_client = self.FakeClient(generated.replace('DATASOURCE_ID', sample_datasource.id))
        monkeypatch.setattr(
            analysis_service,
            '_resolved_generation_provider',
            lambda _provider=None: ('openai', 'test-model', {'api_key': 'test'}),
        )
        monkeypatch.setattr(analysis_service, 'get_ai_client', lambda *_args, **_kwargs: fake_client)

        response = client.post('/api/v1/analysis/generate', json=self._payload(sample_datasource.id))

        assert response.status_code == 400
        assert detail in response.json()['detail']


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
        assert item['is_favorite'] is False


class TestAnalysisImport:
    def test_import_analysis_applies_datasource_remap_before_missing_check(self, client, sample_datasource: DataSource):
        imported_source_id = 'imported-source-id'
        payload = {
            'name': 'Imported Analysis',
            'description': 'Imported with datasource remap',
            'datasource_remap': {imported_source_id: sample_datasource.id},
            'pipeline': {
                'tabs': [
                    {
                        'id': 'tab-imported',
                        'name': 'Imported Source',
                        'parent_id': None,
                        'datasource': {
                            'id': imported_source_id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': str(uuid.uuid4()),
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'imported_source',
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

    def test_import_analysis_remaps_join_right_source(self, client, sample_datasource: DataSource):
        imported_source_id = 'imported-source-id'
        payload = {
            'name': 'Imported Join Analysis',
            'description': 'Imported with self-join datasource remap',
            'datasource_remap': {imported_source_id: sample_datasource.id},
            'pipeline': {
                'tabs': [
                    {
                        'id': 'tab-imported',
                        'name': 'Imported Source',
                        'parent_id': None,
                        'datasource': {
                            'id': imported_source_id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': str(uuid.uuid4()),
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'imported_join_source',
                        },
                        'steps': [
                            {
                                'id': 'join-1',
                                'type': 'join',
                                'config': {
                                    'how': 'inner',
                                    'right_source': imported_source_id,
                                    'join_columns': [{'id': 'jc1', 'left_column': 'a', 'right_column': 'a'}],
                                    'suffix': '_right',
                                },
                                'depends_on': [],
                                'is_applied': True,
                            }
                        ],
                    },
                ],
            },
        }

        response = client.post('/api/v1/analysis/import', json=payload)

        assert response.status_code == 200
        body = response.json()
        tab = body['pipeline_definition']['tabs'][0]
        assert tab['datasource']['id'] == sample_datasource.id
        assert tab['steps'][0]['config']['right_source'] == sample_datasource.id


class TestAnalysisDuplicate:
    def test_duplicate_regenerates_pipeline_identities_and_preserves_source_mapping(
        self,
        client,
        sample_analysis: Analysis,
        sample_datasource: DataSource,
    ):
        source_tab = sample_analysis.pipeline_definition['tabs'][0]

        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/duplicate',
            json={'name': 'Copy of Test Analysis', 'description': 'Independent copy'},
        )

        assert response.status_code == 200
        body = response.json()
        duplicate_tab = body['pipeline_definition']['tabs'][0]
        assert body['id'] != sample_analysis.id
        assert body['name'] == 'Copy of Test Analysis'
        assert body['description'] == 'Independent copy'
        assert duplicate_tab['id'] != source_tab['id']
        assert duplicate_tab['output']['result_id'] != source_tab['output']['result_id']
        assert duplicate_tab['steps'][0]['id'] != source_tab['steps'][0]['id']
        assert duplicate_tab['datasource']['id'] == sample_datasource.id

    def test_duplicate_rewrites_derived_tab_and_step_references(
        self,
        client,
        sample_analysis: Analysis,
        test_db_session: Session,
    ):
        source_tab = sample_analysis.pipeline_definition['tabs'][0]
        source_tab['steps'].append(
            {
                'id': 'step2',
                'type': 'sort',
                'config': {'columns': ['age'], 'descending': [False]},
                'depends_on': ['step1'],
            }
        )
        derived_output_id = str(uuid.uuid4())
        derived_tab = {
            'id': 'tab-derived',
            'name': 'Derived',
            'parent_id': source_tab['id'],
            'datasource': {
                'id': source_tab['output']['result_id'],
                'analysis_tab_id': source_tab['id'],
                'config': {'branch': 'master'},
            },
            'output': {
                'result_id': derived_output_id,
                'datasource_type': 'iceberg',
                'format': 'parquet',
                'filename': 'derived_output',
            },
            'steps': [],
        }
        sample_analysis.pipeline_definition = {'tabs': [source_tab, derived_tab]}
        test_db_session.add(sample_analysis)
        test_db_session.commit()

        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/duplicate',
            json={'name': 'Copy with derived tab'},
        )

        assert response.status_code == 200
        duplicated_tabs = response.json()['pipeline_definition']['tabs']
        duplicated_source, duplicated_derived = duplicated_tabs
        assert duplicated_source['id'] != source_tab['id']
        assert duplicated_derived['id'] != derived_tab['id']
        assert duplicated_source['output']['result_id'] != source_tab['output']['result_id']
        assert duplicated_derived['output']['result_id'] != derived_output_id
        assert duplicated_derived['parent_id'] == duplicated_source['id']
        assert duplicated_derived['datasource']['analysis_tab_id'] == duplicated_source['id']
        assert duplicated_derived['datasource']['id'] == duplicated_source['output']['result_id']
        duplicated_steps = duplicated_source['steps']
        assert duplicated_steps[0]['id'] != 'step1'
        assert duplicated_steps[1]['id'] != 'step2'
        assert duplicated_steps[1]['depends_on'] == [duplicated_steps[0]['id']]


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
        assert result['revision'] == 2
        assert response.headers['X-Analysis-Version'] == '2'
        assert response.headers['ETag'] == f'"analysis-{result["id"]}-2"'

    def test_update_analysis_requires_revision(self, client, sample_analysis: Analysis):
        del client.headers['If-Match']
        response = client.put(
            f'/api/v1/analysis/{sample_analysis.id}',
            json={'name': 'Updated', 'tabs': sample_analysis.pipeline_definition['tabs']},
        )

        assert response.status_code == 428
        assert response.json()['detail'] == 'If-Match analysis revision is required'

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

    def test_favorite_analysis_creates_row(self, client, sample_analysis: Analysis, test_db_session, test_user):
        response = client.post(f'/api/v1/analysis/{sample_analysis.id}/favorite')

        assert response.status_code == 200
        assert response.json() == {'analysis_id': sample_analysis.id, 'is_favorite': True}
        stmt = select(AnalysisFavorite).where(sa(AnalysisFavorite.user_id == test_user.id), sa(AnalysisFavorite.analysis_id == sample_analysis.id))
        row = test_db_session.execute(stmt).scalar_one_or_none()
        assert row is not None

    def test_unfavorite_analysis_deletes_row(self, client, sample_analysis: Analysis, test_db_session, test_user):
        test_db_session.add(AnalysisFavorite(user_id=test_user.id, analysis_id=sample_analysis.id))
        test_db_session.commit()

        response = client.delete(f'/api/v1/analysis/{sample_analysis.id}/favorite')

        assert response.status_code == 200
        assert response.json() == {'analysis_id': sample_analysis.id, 'is_favorite': False}
        stmt = select(AnalysisFavorite).where(sa(AnalysisFavorite.user_id == test_user.id), sa(AnalysisFavorite.analysis_id == sample_analysis.id))
        row = test_db_session.execute(stmt).scalar_one_or_none()
        assert row is None

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
                            'config': _groupby_config('age', 'mean', 'mean_age'),
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

        from backend_core.persistence.datasource.models import DataSource as DS

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

        result = test_db_session.execute(select(AnalysisDataSource).where(sa(AnalysisDataSource.analysis_id == analysis_id)))
        links_before = result.scalars().all()
        assert len(links_before) > 0

        response = client.delete(f'/api/v1/analysis/{analysis_id}')
        assert response.status_code == 204

        result = test_db_session.execute(select(AnalysisDataSource).where(sa(AnalysisDataSource.analysis_id == analysis_id)))
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
        valid_categories = {
            'transform',
            'aggregate',
            'reshape',
            'io',
            'visualization',
            'advanced',
        }
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
        assert result['config'] == {'columns': ['name', 'age'], 'cast_map': {}}
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

        response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/nonexistent-tab/steps',
            json=payload,
        )

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
            'config': _filter_config('name', '=', 'Alice'),
        }

        response = client.put(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/{step_id}',
            json=payload,
        )

        assert response.status_code == 200
        result = response.json()
        assert result['config']['conditions'] == [
            {
                'column': 'name',
                'operator': '=',
                'value': 'Alice',
                'value_type': 'string',
                'compare_column': None,
            }
        ]

    def test_update_step_type(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        step_id = sample_analysis.pipeline_definition['tabs'][0]['steps'][0]['id']
        payload = {
            'type': 'limit',
            'config': {'n': 25},
        }

        response = client.put(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/{step_id}',
            json=payload,
        )

        assert response.status_code == 200
        result = response.json()
        assert result['type'] == 'limit'
        assert result['config']['n'] == 25

    def test_update_step_not_found(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        payload = {'config': {'n': 10}}

        response = client.put(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/nonexistent',
            json=payload,
        )

        assert response.status_code == 400

    def test_update_step_invalid_type(self, client, sample_analysis: Analysis):
        tab_id = sample_analysis.pipeline_definition['tabs'][0]['id']
        step_id = sample_analysis.pipeline_definition['tabs'][0]['steps'][0]['id']
        payload = {
            'type': 'invalid_type',
        }

        response = client.put(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps/{step_id}',
            json=payload,
        )

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
        add_response = client.post(
            f'/api/v1/analysis/{sample_analysis.id}/tabs/{tab_id}/steps',
            json=add_payload,
        )
        assert add_response.status_code == 200
        second_step_id = add_response.json()['id']
        client.headers['If-Match'] = add_response.headers['X-Analysis-Version']

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
            [
                {
                    'id': 's1',
                    'type': 'sort',
                    'config': {'descending': {'bad': True}},
                    'depends_on': [],
                }
            ],
        )
        response = client.post('/api/v1/analysis', json=payload)
        assert response.status_code == 400

    def test_rejects_depends_on_nonexistent_step(self, client, sample_datasource: DataSource):
        payload = self._make_payload(
            sample_datasource.id,
            [
                {
                    'id': 's1',
                    'type': 'select',
                    'config': {'columns': ['a']},
                    'depends_on': ['missing'],
                }
            ],
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
                    'config': {
                        'right_source': 'nonexistent_tab',
                        'how': 'inner',
                        'join_columns': [],
                    },
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
