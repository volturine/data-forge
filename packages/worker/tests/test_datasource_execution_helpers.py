import polars as pl

from datasources.execution import _coerce_database_iceberg_compatible_lazyframe, get_column_stats_from_metadata
from runtime.worker_runtime_client import DatasourceMetadata


def test_coerce_database_iceberg_compatible_lazyframe_stringifies_nested() -> None:
    lazy = pl.DataFrame({"obj": [{"a": 1}], "nulls": [None]}).lazy()
    coerced = _coerce_database_iceberg_compatible_lazyframe(lazy).collect()
    assert coerced.schema["nulls"] == pl.String
    assert coerced.schema["obj"] == pl.String


def test_column_stats_histogram_uses_numeric_bins_and_excludes_nulls(tmp_path) -> None:
    csv_path = tmp_path / "values.csv"
    csv_path.write_text("value\n1\n2\n\n4\n5\n")
    metadata = DatasourceMetadata(
        found=True,
        id="source-1",
        name="Values",
        source_type="file",
        config={"file_path": str(csv_path), "file_type": "csv"},
        schema_cache=None,
        is_hidden=False,
    )

    stats = get_column_stats_from_metadata(metadata, column_name="value", use_sample=False)

    assert stats.dtype == "Int64"
    assert stats.null_count == 1
    assert stats.histogram is not None
    assert len(stats.histogram) == 20
    assert all(isinstance(bin.start, float) and isinstance(bin.end, float) for bin in stats.histogram)
    assert sum(bin.count for bin in stats.histogram) == stats.count - stats.null_count


def test_csv_opts_coerces_struct_float_skip_rows() -> None:
    from datasources.datasource_loading import _csv_opts

    opts = _csv_opts({"delimiter": ",", "skip_rows": 0.0, "has_header": True})
    assert opts["skip_rows"] == 0
    assert isinstance(opts["skip_rows"], int)
