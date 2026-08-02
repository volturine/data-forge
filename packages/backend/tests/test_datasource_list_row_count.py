"""List endpoint projects schema_cache.row_count without loading full cache."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session

from backend_core.persistence.datasource.models import DataSource
from modules.datasource import service as datasource_service


def _insert_datasource(
    session: Session,
    *,
    datasource_id: str,
    name: str,
    schema_cache: dict | None,
) -> DataSource:
    ds = DataSource(
        id=datasource_id,
        name=name,
        description=None,
        source_type='file',
        config={'file_path': 's3://bucket/path.csv', 'file_type': 'csv'},
        schema_cache=schema_cache,
        created_by='import',
        is_hidden=False,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


class TestListDatasourceRowCount:
    def test_list_includes_projected_row_count(self, test_db_session: Session) -> None:
        _insert_datasource(
            test_db_session,
            datasource_id='ds-with-count',
            name='With count',
            schema_cache={
                'columns': [{'name': 'id', 'dtype': 'Int64', 'nullable': False}],
                'row_count': 1234,
            },
        )
        _insert_datasource(
            test_db_session,
            datasource_id='ds-without-count',
            name='Without count',
            schema_cache=None,
        )

        items = {item.id: item for item in datasource_service.list_datasources(test_db_session)}

        assert items['ds-with-count'].row_count == 1234
        assert items['ds-without-count'].row_count is None
        # List items must not include the heavy schema_cache payload.
        assert 'schema_cache' not in items['ds-with-count'].model_dump()

    def test_list_coerces_string_row_count(self, test_db_session: Session) -> None:
        _insert_datasource(
            test_db_session,
            datasource_id='ds-string-count',
            name='String count',
            schema_cache={'row_count': '42', 'columns': []},
        )
        items = {item.id: item for item in datasource_service.list_datasources(test_db_session)}
        assert items['ds-string-count'].row_count == 42


class TestCoerceRowCount:
    def test_accepts_integers_and_whole_floats(self) -> None:
        assert datasource_service._coerce_row_count(10) == 10
        assert datasource_service._coerce_row_count(10.0) == 10
        assert datasource_service._coerce_row_count('7') == 7

    def test_rejects_invalid_values(self) -> None:
        assert datasource_service._coerce_row_count(None) is None
        assert datasource_service._coerce_row_count(True) is None
        assert datasource_service._coerce_row_count(1.5) is None
        assert datasource_service._coerce_row_count('x') is None
        assert datasource_service._coerce_row_count('') is None
