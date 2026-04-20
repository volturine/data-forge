import polars as pl
import pytest

from core.config import settings
from core.namespace import namespace_paths
from modules.compute.core.exports import get_export_format
from modules.compute.operations.datasource import resolve_iceberg_branch_metadata_path, resolve_iceberg_metadata_path
from modules.compute.operations.fill_null import cast_value, get_fill_strategy, get_polars_type
from modules.compute.operations.filter import get_operator
from modules.compute.operations.groupby import get_aggregation
from modules.compute.operations.timeseries import get_duration, get_extractor


def test_get_operator():
    op = get_operator('==')
    expr = op(pl.col('a'), 1)
    assert isinstance(expr, pl.Expr)


def test_get_operator_invalid():
    with pytest.raises(ValueError, match='Unsupported filter operator'):
        get_operator('nope')


def test_get_aggregation():
    agg = get_aggregation('sum')
    expr = agg('value')
    assert isinstance(expr, pl.Expr)


def test_get_aggregation_invalid():
    with pytest.raises(ValueError, match='Unsupported aggregation'):
        get_aggregation('nope')


def test_timeseries_extractor_and_duration():
    assert get_extractor('year') == 'year'
    duration = get_duration('days', 2)
    assert isinstance(duration, pl.Expr)


def test_timeseries_extractor_invalid():
    with pytest.raises(ValueError, match='Unsupported time component'):
        get_extractor('nope')


def test_timeseries_duration_invalid():
    with pytest.raises(ValueError, match='Unsupported duration unit'):
        get_duration('nope', 1)


def test_fill_strategy():
    strategy = get_fill_strategy('forward')
    assert strategy is not None


def test_export_format():
    fmt = get_export_format('csv')
    assert fmt.extension == '.csv'
    assert fmt.content_type == 'text/csv'


def test_export_format_invalid():
    with pytest.raises(ValueError, match='Unsupported export format'):
        get_export_format('nope')


def test_type_casting():
    assert cast_value('1', 'Int64') == 1
    assert get_polars_type('Float64') == pl.Float64()


def test_resolve_iceberg_metadata_path_allows_symlinked_data_root(tmp_path, monkeypatch):
    real_dir = tmp_path / 'real'
    real_dir.mkdir()
    link_dir = tmp_path / 'link'
    link_dir.symlink_to(real_dir, target_is_directory=True)
    monkeypatch.setattr(settings, 'data_dir', link_dir, raising=False)

    metadata_file = link_dir / 'namespaces' / settings.default_namespace / 'exports' / 'table' / 'metadata' / 'v1.metadata.json'
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_file.write_text('{}', encoding='utf-8')

    assert resolve_iceberg_metadata_path(str(metadata_file)) == str(metadata_file)


def test_resolve_iceberg_metadata_path_accepts_explicit_namespace(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path / 'data', raising=False)
    metadata_file = namespace_paths('alpha').exports_dir / 'table' / 'metadata' / 'v1.metadata.json'
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_file.write_text('{}', encoding='utf-8')

    assert resolve_iceberg_metadata_path(str(metadata_file), namespace_name='alpha') == str(metadata_file)


def test_resolve_iceberg_metadata_path_rejects_wrong_namespace_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', tmp_path / 'data', raising=False)
    metadata_file = namespace_paths('alpha').exports_dir / 'table' / 'metadata' / 'v1.metadata.json'
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_file.write_text('{}', encoding='utf-8')

    with pytest.raises(ValueError, match='Iceberg metadata_path must be inside data directory'):
        resolve_iceberg_metadata_path(str(metadata_file), namespace_name='beta')


def test_resolve_iceberg_branch_metadata_path_accepts_explicit_data_root(tmp_path):
    data_root = tmp_path / 'custom-root'
    metadata_dir = data_root / 'table' / 'metadata'
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = metadata_dir / 'v1.metadata.json'
    metadata_file.write_text('{}', encoding='utf-8')

    assert resolve_iceberg_branch_metadata_path(str(metadata_dir.parent), None, data_root=data_root) == str(metadata_file)
