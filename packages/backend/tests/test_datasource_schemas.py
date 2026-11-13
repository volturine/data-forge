import pytest
from pydantic import ValidationError

from modules.datasource.schemas import DataSourceUpdate, SnapshotCompareRequest


def test_snapshot_compare_request_defaults_to_bounded_preview() -> None:
    request = SnapshotCompareRequest(snapshot_a='a', snapshot_b='b')

    assert request.row_limit == 100


@pytest.mark.parametrize('row_limit', [0, 1001])
def test_snapshot_compare_request_rejects_unbounded_preview(row_limit: int) -> None:
    with pytest.raises(ValidationError):
        SnapshotCompareRequest(snapshot_a='a', snapshot_b='b', row_limit=row_limit)


@pytest.mark.parametrize('name', ['', '   '])
def test_datasource_update_rejects_blank_name(name: str) -> None:
    with pytest.raises(ValidationError):
        DataSourceUpdate(name=name)


def test_datasource_update_strips_name() -> None:
    assert DataSourceUpdate(name='  sales  ').name == 'sales'
