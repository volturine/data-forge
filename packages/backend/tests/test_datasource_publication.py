import uuid
from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.persistence.datasource.models import DataSource
from dataforge_protocol import datasource_pb2
from modules.datasource import publication_service


def test_create_datasource_persists_metadata(test_db_session: Session) -> None:
    datasource_id = str(uuid.uuid4())
    response = publication_service.create_datasource(
        test_db_session,
        datasource_id=datasource_id,
        name='Published',
        description='desc',
        source_type=DataSourceType.ICEBERG.value,
        config={'metadata_path': 's3://bucket/clean/ds/master', 'branch': 'master'},
        owner_id=None,
        schema_info=datasource_pb2.SchemaInfo(
            columns=[datasource_pb2.ColumnSchema(name='a', dtype='Int64', nullable=True)],
            row_count=1,
        ),
    )
    assert response.id == datasource_id
    assert response.source_type == DataSourceType.ICEBERG
    assert response.schema_cache is not None
    stored = test_db_session.get(DataSource, datasource_id)
    assert stored is not None
    assert stored.revision == 1


def test_publish_ingest_fences_on_revision(test_db_session: Session) -> None:
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Ingestable',
            source_type=DataSourceType.ICEBERG.value,
            config={'metadata_path': 's3://bucket/old', 'branch': 'master', 'source': {'source_type': 'file'}},
            revision=3,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    published = publication_service.publish_ingest(
        test_db_session,
        datasource_id=datasource_id,
        config={'metadata_path': 's3://bucket/new', 'branch': 'master', 'source': {'source_type': 'file'}},
        expected_revision=3,
        schema_info=None,
    )
    assert published.config['metadata_path'] == 's3://bucket/new'
    stored = test_db_session.get(DataSource, datasource_id)
    assert stored is not None
    assert stored.revision == 4

    with pytest.raises(publication_service.DatasourcePublicationClaimLost):
        publication_service.publish_ingest(
            test_db_session,
            datasource_id=datasource_id,
            config={'metadata_path': 's3://bucket/stale', 'branch': 'master'},
            expected_revision=3,
            schema_info=None,
        )


def test_publish_schema_cache(test_db_session: Session) -> None:
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Schema',
            source_type=DataSourceType.ICEBERG.value,
            config={'metadata_path': 's3://bucket/ds'},
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    schema = datasource_pb2.SchemaInfo(
        columns=[datasource_pb2.ColumnSchema(name='x', dtype='Utf8', nullable=True, sample_value='a')],
        row_count=2,
    )
    published = publication_service.publish_schema_cache(test_db_session, datasource_id=datasource_id, schema_info=schema)
    assert published.row_count == 2
    stored = test_db_session.get(DataSource, datasource_id)
    assert stored is not None
    assert stored.schema_cache is not None
    assert stored.schema_cache['row_count'] == 2
