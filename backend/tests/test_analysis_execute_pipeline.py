import uuid
from unittest.mock import MagicMock, patch

from modules.datasource.models import DataSource


def test_execute_analysis_uses_pipeline_payload(client, sample_datasource: DataSource):
    pipeline = {
        'analysis_id': 'analysis-payload',
        'tabs': [
            {
                'id': 'tab-1',
                'datasource_id': sample_datasource.id,
                'datasource_config': {'snapshot_id': '123'},
                'steps': [
                    {
                        'id': 'step1',
                        'type': 'filter',
                        'config': {'column': 'age', 'operator': '>', 'value': 25},
                        'depends_on': [],
                    }
                ],
            }
        ],
        'sources': {
            sample_datasource.id: {
                'source_type': sample_datasource.source_type,
                **sample_datasource.config,
            }
        },
    }

    def fake_preview_step(*_args, **kwargs):
        return MagicMock(
            column_types={'name': 'String'},
            data=[{'name': 'Alice'}],
            total_rows=1,
        )

    with patch('modules.analysis.routes.compute_service.preview_step') as mock_preview:
        mock_preview.side_effect = fake_preview_step
        analysis_id = str(uuid.uuid4())
        response = client.post(
            f'/api/v1/analysis/{analysis_id}/execute',
            json={'pipeline': {**pipeline, 'analysis_id': analysis_id}},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload['schema'] == {'name': 'String'}
        assert payload['row_count'] == 1
        assert payload['rows'] == [{'name': 'Alice'}]
        assert mock_preview.call_count == 1
        _, kwargs = mock_preview.call_args
        assert kwargs['analysis_pipeline']['analysis_id'] == analysis_id
        assert kwargs['datasource_config']['snapshot_id'] == '123'
