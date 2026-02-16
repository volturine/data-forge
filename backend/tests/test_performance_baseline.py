import json
import time
import uuid

from modules.compute import service as compute_service
from modules.compute.manager import get_manager


def _measure(func, *args, **kwargs):
    started = time.perf_counter()
    result = func(*args, **kwargs)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return result, duration_ms


def test_performance_baseline(test_db_session, sample_datasource, sample_analysis):
    analysis_id = f'perf-{uuid.uuid4()}'
    pipeline = {
        'analysis_id': analysis_id,
        'tabs': [
            {
                'id': 'tab1',
                'datasource_id': sample_datasource.id,
                'datasource_config': {},
                'steps': [],
            }
        ],
        'sources': {
            sample_datasource.id: {
                'source_type': sample_datasource.source_type,
                **sample_datasource.config,
            }
        },
    }

    manager = get_manager()
    try:
        preview_result, preview_ms = _measure(
            compute_service.preview_step,
            session=test_db_session,
            target_step_id='source',
            analysis_pipeline=pipeline,
            row_limit=100,
            page=1,
            analysis_id=analysis_id,
        )

        schema_result, schema_ms = _measure(
            compute_service.get_step_schema,
            session=test_db_session,
            target_step_id='source',
            analysis_id=analysis_id,
            analysis_pipeline=pipeline,
        )

        export_result, export_ms = _measure(
            compute_service.export_data,
            session=test_db_session,
            target_step_id='source',
            analysis_pipeline=pipeline,
            export_format='csv',
            destination='download',
            datasource_type='file',
            analysis_id=analysis_id,
        )
    finally:
        if manager.get_engine(analysis_id):
            manager.shutdown_engine(analysis_id)

    file_bytes, _name, _content_type, _path, _ds_id, export_meta = export_result

    assert preview_result.total_rows == 5
    assert schema_result.columns
    assert file_bytes is not None
    assert export_meta is not None
    assert export_meta.get('row_count') == 5

    print(
        json.dumps(
            {
                'preview_duration_ms': preview_ms,
                'schema_duration_ms': schema_ms,
                'export_duration_ms': export_ms,
                'preview_rows': preview_result.total_rows,
                'export_rows': export_meta.get('row_count'),
            }
        )
    )
