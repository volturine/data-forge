"""Datasource read responses must mask secret-bearing config fields."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session

from backend_core.persistence.datasource.models import DataSource
from backend_core.secrets import MASKED_SECRET
from modules.datasource import service as datasource_service


def _insert_datasource(
    session: Session,
    *,
    datasource_id: str,
    source_type: str,
    config: dict,
) -> DataSource:
    ds = DataSource(
        id=datasource_id,
        name=datasource_id,
        description=None,
        source_type=source_type,
        config=config,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


class TestConfigMasking:
    def test_get_masks_database_connection_string(self, test_db_session: Session) -> None:
        secret = 'postgresql://user:pass@localhost/db'
        _insert_datasource(
            test_db_session,
            datasource_id='11111111-1111-4111-8111-000000000001',
            source_type='database',
            config={'connection_string': secret, 'query': 'SELECT 1', 'branch': 'master'},
        )

        response = datasource_service.get_datasource(test_db_session, '11111111-1111-4111-8111-000000000001')

        assert response.config['connection_string'] == MASKED_SECRET
        assert response.config['query'] == 'SELECT 1'

    def test_get_masks_iceberg_catalog_uri(self, test_db_session: Session) -> None:
        secret = 'postgresql+psycopg://postgres:postgres@127.0.0.1:5432/dataforge'
        _insert_datasource(
            test_db_session,
            datasource_id='11111111-1111-4111-8111-000000000002',
            source_type='iceberg',
            config={
                'catalog_type': 'sql',
                'catalog_uri': secret,
                'warehouse': 's3://dataforge/exports',
                'namespace': 'default',
                'table': 't_master',
                'metadata_path': 's3://dataforge/exports/t',
                'branch': 'master',
            },
        )

        response = datasource_service.get_datasource(test_db_session, '11111111-1111-4111-8111-000000000002')

        assert response.config['catalog_uri'] == MASKED_SECRET
        assert response.config['warehouse'] == 's3://dataforge/exports'

    def test_get_masks_nested_source_connection_string(self, test_db_session: Session) -> None:
        _insert_datasource(
            test_db_session,
            datasource_id='11111111-1111-4111-8111-000000000003',
            source_type='iceberg',
            config={
                'source': {
                    'source_type': 'database',
                    'connection_string': 'postgresql://user:pass@localhost/db',
                    'query': 'SELECT * FROM users',
                    'end_row': 2,
                },
            },
        )

        response = datasource_service.get_datasource(test_db_session, '11111111-1111-4111-8111-000000000003')

        source = response.config['source']
        assert source['connection_string'] == MASKED_SECRET
        assert source['query'] == 'SELECT * FROM users'

    def test_list_masks_secret_fields(self, test_db_session: Session) -> None:
        _insert_datasource(
            test_db_session,
            datasource_id='11111111-1111-4111-8111-000000000004',
            source_type='database',
            config={'connection_string': 'postgresql://user:pass@localhost/db', 'query': 'SELECT 1'},
        )
        _insert_datasource(
            test_db_session,
            datasource_id='11111111-1111-4111-8111-000000000005',
            source_type='iceberg',
            config={'catalog_type': 'sql', 'catalog_uri': 'postgresql://user:pass@localhost/db'},
        )

        items = {item.id: item for item in datasource_service.list_datasources(test_db_session)}

        assert items['11111111-1111-4111-8111-000000000004'].config['connection_string'] == MASKED_SECRET
        assert items['11111111-1111-4111-8111-000000000005'].config['catalog_uri'] == MASKED_SECRET

    def test_persistence_keeps_real_values(self, test_db_session: Session) -> None:
        secret = 'postgresql://user:pass@localhost/db'
        datasource_id = '11111111-1111-4111-8111-000000000006'
        _insert_datasource(
            test_db_session,
            datasource_id=datasource_id,
            source_type='database',
            config={'connection_string': secret, 'query': 'SELECT 1'},
        )

        datasource_service.get_datasource(test_db_session, datasource_id)

        row = test_db_session.get(DataSource, datasource_id)
        assert row is not None
        assert row.config['connection_string'] == secret
