from pathlib import Path

import polars as pl
import pytest
from contracts.step_config_enums import TimeComponent
from core.config import settings
from core.export_formats import get_export_format
from core.iceberg_metadata import (
    IcebergMetadataPathNotFoundError,
    resolve_iceberg_branch_metadata_path,
    resolve_iceberg_metadata_path,
)
from core.namespace import namespace_paths

from operations.fill_null import cast_value, get_fill_strategy, get_polars_type
from operations.filter import FilterOperatorDefinition
from operations.groupby import GroupByAggregationDefinition
from operations.plot import ChartAggregationDefinition
from operations.template_placeholders import render_template_placeholders
from operations.timeseries import TimeseriesParams


def test_filter_operator_definition():
    definition = FilterOperatorDefinition.require("==")
    expr = definition.apply(pl.col("a"), 1)
    assert isinstance(expr, pl.Expr)


def test_filter_operator_definition_invalid():
    with pytest.raises(ValueError, match="Unsupported filter operator"):
        FilterOperatorDefinition.require("nope")


def test_groupby_aggregation_definition():
    definition = GroupByAggregationDefinition.require("sum")
    expr = definition.apply("value")
    assert isinstance(expr, pl.Expr)


def test_groupby_aggregation_definition_invalid():
    with pytest.raises(ValueError, match="Unsupported aggregation"):
        GroupByAggregationDefinition.require("nope")


def test_chart_aggregation_definition():
    definition = ChartAggregationDefinition.require("sum")
    expr = definition.apply("value")
    assert isinstance(expr, pl.Expr)


def test_chart_aggregation_definition_invalid():
    with pytest.raises(ValueError, match="Unsupported chart aggregation"):
        ChartAggregationDefinition.require("nope")


def test_timeseries_extractor_and_duration():
    extract = TimeseriesParams.model_validate(
        {
            "column": "ts",
            "operation_type": "extract",
            "new_column": "year",
            "component": "year",
        }
    )
    duration = TimeseriesParams.model_validate({"column": "ts", "operation_type": "add", "new_column": "next", "unit": "days"})
    assert extract.extractor_name() == "year"
    assert isinstance(duration.duration_expr(2), pl.Expr)


def test_timeseries_extractor_invalid():
    with pytest.raises(ValueError):
        TimeComponent.require("nope")


def test_timeseries_duration_invalid():
    params = TimeseriesParams.model_validate({"column": "ts", "operation_type": "add", "new_column": "bad", "unit": "nope"})
    with pytest.raises(ValueError, match="Unsupported duration unit"):
        params.duration_expr(1)


def test_fill_strategy():
    strategy = get_fill_strategy("forward")
    assert strategy is not None


def test_export_format():
    fmt = get_export_format("csv")
    assert fmt.extension == ".csv"
    assert fmt.content_type == "text/csv"


def test_export_format_invalid():
    with pytest.raises(ValueError, match="Unsupported export format"):
        get_export_format("nope")


def test_type_casting():
    assert cast_value("1", "Int64") == 1
    assert get_polars_type("Float64") == pl.Float64()


def test_resolve_iceberg_metadata_path_allows_symlinked_data_root(tmp_path, monkeypatch):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link"
    link_dir.symlink_to(real_dir, target_is_directory=True)
    monkeypatch.setattr(settings, "data_dir", link_dir, raising=False)

    metadata_file = link_dir / "namespaces" / settings.default_namespace / "exports" / "table" / "metadata" / "v1.metadata.json"
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_file.write_text("{}", encoding="utf-8")

    assert resolve_iceberg_metadata_path(str(metadata_file)) == str(metadata_file)


def test_resolve_iceberg_metadata_path_accepts_explicit_namespace(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data", raising=False)
    metadata_file = namespace_paths("alpha").exports_dir / "table" / "metadata" / "v1.metadata.json"
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_file.write_text("{}", encoding="utf-8")

    assert resolve_iceberg_metadata_path(str(metadata_file), namespace_name="alpha") == str(metadata_file)


def test_resolve_iceberg_metadata_path_rejects_wrong_namespace_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data", raising=False)
    metadata_file = namespace_paths("alpha").exports_dir / "table" / "metadata" / "v1.metadata.json"
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_file.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Iceberg metadata_path must be inside data directory"):
        resolve_iceberg_metadata_path(str(metadata_file), namespace_name="beta")


def test_resolve_iceberg_branch_metadata_path_accepts_explicit_data_root(tmp_path):
    data_root = tmp_path / "custom-root"
    metadata_dir = data_root / "table" / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = metadata_dir / "v1.metadata.json"
    metadata_file.write_text("{}", encoding="utf-8")

    assert resolve_iceberg_branch_metadata_path(str(metadata_dir.parent), None, data_root=data_root) == str(metadata_file)


def test_resolve_iceberg_metadata_path_reports_missing_metadata_dir_race(tmp_path, monkeypatch):
    data_root = tmp_path / "custom-root"
    table_dir = data_root / "table"
    metadata_dir = table_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = metadata_dir / "v1.metadata.json"
    metadata_file.write_text("{}", encoding="utf-8")

    original_glob = Path.glob

    def raising_glob(self: Path, pattern: str):
        if self == metadata_dir and pattern == "*.metadata.json":
            raise FileNotFoundError(metadata_dir)
        return original_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", raising_glob)

    with pytest.raises(IcebergMetadataPathNotFoundError, match="Iceberg metadata_path not found"):
        resolve_iceberg_metadata_path(str(table_dir), data_root=data_root)


def test_render_template_placeholders_replaces_known_keys_and_leaves_unknown() -> None:
    rendered = render_template_placeholders(
        "Hello {{name}} from {{city}} / {{missing}}",
        {"name": "Ada", "city": "London"},
    )

    assert rendered == "Hello Ada from London / {{missing}}"
