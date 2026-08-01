import polars as pl

from datasources.execution import _coerce_database_iceberg_compatible_lazyframe, _compute_histogram


def test_coerce_database_iceberg_compatible_lazyframe_stringifies_nested() -> None:
    lazy = pl.DataFrame({"obj": [{"a": 1}], "nulls": [None]}).lazy()
    coerced = _coerce_database_iceberg_compatible_lazyframe(lazy).collect()
    assert coerced.schema["nulls"] == pl.String
    assert coerced.schema["obj"] == pl.String


def test_compute_histogram_bins() -> None:
    series = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 5.0])
    bins = _compute_histogram(series, bins=2)
    assert len(bins) == 2
    assert sum(int(item["count"]) for item in bins) == 5


def test_csv_opts_coerces_struct_float_skip_rows() -> None:
    from datasources.datasource_loading import _csv_opts

    opts = _csv_opts({"delimiter": ",", "skip_rows": 0.0, "has_header": True})
    assert opts["skip_rows"] == 0
    assert isinstance(opts["skip_rows"], int)
