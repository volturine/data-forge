"""Analysis responses annotate output.materialized without probing 404s."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session

from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.datasource.models import DataSource
from modules.analysis import service as analysis_service
from modules.datasource.service import create_placeholder_output_datasource


def _insert_analysis(
    session: Session,
    *,
    analysis_id: str,
    result_id: str,
) -> Analysis:
    analysis = Analysis(
        id=analysis_id,
        name='Materialization test',
        description=None,
        pipeline_definition={
            'tabs': [
                {
                    'id': 'tab-1',
                    'name': 'Main',
                    'parent_id': None,
                    'datasource': {
                        'id': 'ds-input',
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': result_id,
                        'format': 'parquet',
                        'filename': 'out',
                        'build_mode': 'full',
                        'iceberg': {
                            'namespace': 'outputs',
                            'table_name': 'out',
                            'branch': 'master',
                        },
                    },
                    'steps': [],
                }
            ]
        },
        created_at=datetime.now(UTC).replace(tzinfo=None),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
        revision=1,
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


class TestAnalysisOutputMaterialized:
    def test_get_analysis_marks_unmaterialized_output(self, test_db_session: Session) -> None:
        result_id = '550e8400-e29b-41d4-a716-446655440001'
        _insert_analysis(
            test_db_session,
            analysis_id='analysis-unmaterialized',
            result_id=result_id,
        )

        response = analysis_service.get_analysis(test_db_session, 'analysis-unmaterialized')
        tabs = response.pipeline_definition['tabs']
        assert tabs[0]['output']['result_id'] == result_id
        assert tabs[0]['output']['materialized'] is False

    def test_get_analysis_marks_materialized_output_after_placeholder(self, test_db_session: Session) -> None:
        result_id = '550e8400-e29b-41d4-a716-446655440002'
        _insert_analysis(
            test_db_session,
            analysis_id='analysis-materialized',
            result_id=result_id,
        )
        create_placeholder_output_datasource(
            test_db_session,
            result_id=result_id,
            analysis_id='analysis-materialized',
            analysis_tab_id='tab-1',
            name='Built output',
        )
        test_db_session.commit()

        response = analysis_service.get_analysis(test_db_session, 'analysis-materialized')
        tabs = response.pipeline_definition['tabs']
        assert tabs[0]['output']['materialized'] is True

    def test_materialized_flag_is_not_persisted_on_pipeline_write(self, test_db_session: Session) -> None:
        result_id = '550e8400-e29b-41d4-a716-446655440003'
        analysis = _insert_analysis(
            test_db_session,
            analysis_id='analysis-strip-materialized',
            result_id=result_id,
        )
        # Simulate a client echoing the response-only flag into a save path.
        tabs = analysis.pipeline_definition['tabs']
        tabs[0]['output']['materialized'] = True
        analysis.pipeline_definition = {'tabs': tabs}
        test_db_session.add(analysis)
        test_db_session.commit()

        # Even if a dirty flag was written into storage historically, response recomputes.
        # And domain TabOutput strips it when re-hydrating via from_dict/to_dict.
        from backend_core.domain.analysis.pipeline_types import TabOutput

        stored = TabOutput.from_dict(tabs[0]['output']).to_dict()
        assert 'materialized' not in stored

        response = analysis_service.get_analysis(test_db_session, 'analysis-strip-materialized')
        # No datasource row exists, so recomputed flag stays false.
        assert response.pipeline_definition['tabs'][0]['output']['materialized'] is False
        assert test_db_session.get(DataSource, result_id) is None
