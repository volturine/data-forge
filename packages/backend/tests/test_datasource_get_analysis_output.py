"""GET analysis-output datasources must not depend on data-plane availability."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from sqlmodel import Session

from backend_core.persistence.datasource.models import DataSource


def _insert_analysis_output(session: Session, *, datasource_id: str) -> DataSource:
    ds = DataSource(
        id=datasource_id,
        name='analysis_output',
        description=None,
        source_type='iceberg',
        config={
            'catalog_type': 'sql',
            'catalog_uri': 'postgresql+psycopg://postgres:postgres@127.0.0.1:5432/dataforge',
            'warehouse': 's3://dataforge/exports',
            'namespace': 'default',
            'table': f'{datasource_id}_master',
            'table_name': 'analysis_output',
            'metadata_path': f's3://dataforge/exports/{datasource_id}',
            'branch': 'master',
            'namespace_name': 'default',
            'reader': 'native',
            'analysis_tab_id': 'tab-1',
        },
        schema_cache=None,
        created_by='analysis',
        created_by_analysis_id='analysis-1',
        is_hidden=True,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


class TestGetAnalysisOutputDatasource:
    def test_get_returns_row_when_export_branch_listing_fails(
        self,
        test_db_session: Session,
        client,
    ) -> None:
        ds_id = '11111111-1111-4111-8111-111111111111'
        _insert_analysis_output(test_db_session, datasource_id=ds_id)

        with patch(
            'modules.datasource.routes._list_export_branches',
            side_effect=RuntimeError('Worker data-plane gRPC failed with UNAVAILABLE: connection refused'),
        ):
            response = client.get(f'/api/v1/datasource/{ds_id}')

        assert response.status_code == 200
        body = response.json()
        assert body['id'] == ds_id
        assert body['is_hidden'] is True
        assert body['created_by'] == 'analysis'
        # Fallback branch list so the UI still has a usable picker seed.
        assert body['config']['branches'] == ['master']
