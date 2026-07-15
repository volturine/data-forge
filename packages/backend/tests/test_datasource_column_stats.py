import uuid
from datetime import UTC, datetime

import polars as pl
import pytest
from pytest import MonkeyPatch
from sqlmodel import Session

from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.persistence.datasource.models import DataSource
from modules.datasource.runtime_service import get_column_stats


def test_string_column_stats_respects_sample_limit(test_db_session: Session, monkeypatch: MonkeyPatch) -> None:
    datasource_id = str(uuid.uuid4())
    datasource = DataSource(
        id=datasource_id,
        name='Names',
        source_type=DataSourceType.FILE.value,
        config={'file_path': 's3://bucket/names.csv', 'file_type': 'csv'},
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    def fake_load_datasource(config: dict[str, object]) -> pl.LazyFrame:
        assert config['source_type'] == DataSourceType.FILE.value
        return pl.DataFrame({'name': ['a', 'abcd', 'ignored']}).lazy()

    monkeypatch.setattr('modules.datasource.runtime_service.load_datasource', fake_load_datasource)

    result = get_column_stats(test_db_session, datasource_id, 'name', sample_size=2)

    assert result.column == 'name'
    assert result.count == 2
    assert result.min_length == 1
    assert result.max_length == 4
    assert result.avg_length == pytest.approx(2.5)
    assert {item['name'] for item in (result.top_values or [])} == {'a', 'abcd'}


def test_string_column_stats_without_sample_includes_all_rows(test_db_session: Session, monkeypatch: MonkeyPatch) -> None:
    datasource_id = str(uuid.uuid4())
    datasource = DataSource(
        id=datasource_id,
        name='Names',
        source_type=DataSourceType.FILE.value,
        config={'file_path': 's3://bucket/names.csv', 'file_type': 'csv'},
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    test_db_session.add(datasource)
    test_db_session.commit()

    def fake_load_datasource(_config: dict[str, object]) -> pl.LazyFrame:
        return pl.DataFrame({'name': ['a', 'abcd', 'included']}).lazy()

    monkeypatch.setattr('modules.datasource.runtime_service.load_datasource', fake_load_datasource)

    result = get_column_stats(test_db_session, datasource_id, 'name', use_sample=False, datasource_config={'delimiter': ','})

    assert result.count == 3
    assert result.max_length == 8
    assert {item['name'] for item in (result.top_values or [])} == {'a', 'abcd', 'included'}
