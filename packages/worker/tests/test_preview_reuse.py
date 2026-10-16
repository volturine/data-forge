from __future__ import annotations

from collections import Counter
from pathlib import Path

import polars as pl
import pytest

from runtime import polars_compute
from runtime.preview_cache import PreviewCache


def _source_config(tmp_path: Path, name: str = "source") -> dict[str, object]:
    file_path = tmp_path / f"{name}.csv"
    file_path.write_text("value\n0\n", encoding="utf-8")
    return {"source_type": "file", "file_path": str(file_path), "file_type": "csv", "options": {}}


def _step(step_id: str, step_type: str, config: dict[str, object], depends_on: list[str] | None = None) -> dict[str, object]:
    return {"id": step_id, "type": step_type, "config": config, "depends_on": depends_on or []}


def _view(step_id: str, depends_on: list[str] | None = None, row_limit: int | None = None) -> dict[str, object]:
    config: dict[str, object] = {} if row_limit is None else {"row_limit": row_limit}
    return _step(step_id, "view", config, depends_on)


def _filter(step_id: str, threshold: int, depends_on: list[str] | None = None) -> dict[str, object]:
    return _step(
        step_id,
        "filter",
        {
            "conditions": [{"column": "value", "operator": ">", "value": threshold, "value_type": "number"}],
            "logic": "AND",
        },
        depends_on,
    )


def _install_cache(monkeypatch: pytest.MonkeyPatch, *, max_rows: int = 100_000) -> PreviewCache:
    cache = PreviewCache(max_bytes=8 * 1024 * 1024, max_rows=max_rows, max_entries=16)
    monkeypatch.setattr(polars_compute, "_PREVIEW_CACHE", cache)
    return cache


def _count_steps(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    counts: Counter[str] = Counter()
    original_apply_step = polars_compute.apply_step

    def apply_step(lf, step, step_id, right_sources=None, right_lf=None):
        counts[step.operation] += 1
        return original_apply_step(lf, step, step_id, right_sources=right_sources, right_lf=right_lf)

    monkeypatch.setattr(polars_compute, "apply_step", apply_step)
    return counts


def test_appended_filter_reuses_source_view_prefix_and_only_applies_new_transform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    frame = pl.DataFrame({"value": range(20)})
    load_calls: list[str] = []
    step_calls = _count_steps(monkeypatch)
    _install_cache(monkeypatch)

    def load_datasource(config: dict[str, object]) -> pl.LazyFrame:
        load_calls.append(str(config["file_path"]))
        return frame.lazy()

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)

    first = polars_compute.execute_preview(source_config, [_view("input-view")], 2, 0, "first")
    second = polars_compute.execute_preview(
        source_config,
        [
            _view("input-view"),
            _filter("filter", 5, ["input-view"]),
            _view("output-view", ["filter"]),
        ],
        3,
        3,
        "second",
    )

    assert [row["value"] for row in first["data"]] == [0, 1]
    assert [row["value"] for row in second["data"]] == [9, 10, 11]
    assert load_calls == [source_config["file_path"]]
    assert step_calls["filter"] == 1


def test_iceberg_preview_reuses_materialized_prefix_and_refreshes_after_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pyarrow as pa  # type: ignore[import-untyped]  # PyArrow ships no type stubs.
    from pyiceberg.catalog.memory import InMemoryCatalog

    from runtime.config import settings
    from runtime.namespace import namespace_paths

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _install_cache(monkeypatch)
    location = namespace_paths().clean_dir / "preview-source"
    catalog = InMemoryCatalog("preview-cache", warehouse=(tmp_path / "warehouse").as_uri())
    catalog.create_namespace("clean")
    rows = pa.table({"value": list(range(20))})
    table = catalog.create_table("clean.preview_source", schema=rows.schema, location=location.as_uri())
    table.append(rows)
    source_config = {"source_type": "iceberg", "metadata_path": str(location), "reader": "pyiceberg"}
    load_calls = 0
    original_load = polars_compute.load_datasource

    def load_datasource(config: dict) -> pl.LazyFrame:
        nonlocal load_calls
        load_calls += 1
        return original_load(config)

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)
    first = polars_compute.execute_preview(source_config, [_view("input-view")], 2, 0, "iceberg-first")
    steps = [_view("input-view"), _filter("filter", 5, ["input-view"]), _view("output-view", ["filter"])]
    second = polars_compute.execute_preview(source_config, steps, 3, 3, "iceberg-second")

    assert [row["value"] for row in first["data"]] == [0, 1]
    assert [row["value"] for row in second["data"]] == [9, 10, 11]
    assert load_calls == 1

    table.append(pa.table({"value": [99]}))
    refreshed = polars_compute.execute_preview(source_config, steps, 100, 0, "iceberg-refreshed")
    assert sorted(row["value"] for row in refreshed["data"]) == [*range(6, 20), 99]
    assert load_calls == 2


def test_changed_transparent_view_reuses_cached_filter_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    frame = pl.DataFrame({"value": range(20)})
    load_calls: list[str] = []
    step_calls = _count_steps(monkeypatch)
    _install_cache(monkeypatch)

    def load_datasource(config: dict[str, object]) -> pl.LazyFrame:
        load_calls.append(str(config["file_path"]))
        return frame.lazy()

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)

    first = polars_compute.execute_preview(source_config, [_filter("filter", 5)], 2, 0, "first")
    second = polars_compute.execute_preview(
        source_config,
        [_filter("filter", 5), _view("changed-view", ["filter"], row_limit=17)],
        2,
        3,
        "second",
    )

    assert [row["value"] for row in first["data"]] == [6, 7]
    assert [row["value"] for row in second["data"]] == [9, 10]
    assert load_calls == [source_config["file_path"]]
    assert step_calls["filter"] == 1


def test_changed_local_source_version_invalidates_cached_descendants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    versions = [pl.DataFrame({"value": range(5)}), pl.DataFrame({"value": range(100, 105)})]
    load_calls = 0
    step_calls = _count_steps(monkeypatch)
    _install_cache(monkeypatch)

    def load_datasource(_config: dict[str, object]) -> pl.LazyFrame:
        nonlocal load_calls
        frame = versions[load_calls]
        load_calls += 1
        return frame.lazy()

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)

    first = polars_compute.execute_preview(source_config, [_filter("filter", 1)], 10, 0, "first")
    Path(str(source_config["file_path"])).write_text("value\n100\n", encoding="utf-8")
    second = polars_compute.execute_preview(source_config, [_filter("filter", 1)], 10, 0, "second")

    assert [row["value"] for row in first["data"]] == [2, 3, 4]
    assert [row["value"] for row in second["data"]] == list(range(100, 105))
    assert load_calls == 2
    assert step_calls["filter"] == 2


def test_changed_transform_parameters_invalidate_cached_descendants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    frame = pl.DataFrame({"value": range(10)})
    load_calls = 0
    step_calls = _count_steps(monkeypatch)
    _install_cache(monkeypatch)

    def load_datasource(_config: dict[str, object]) -> pl.LazyFrame:
        nonlocal load_calls
        load_calls += 1
        return frame.lazy()

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)

    first = polars_compute.execute_preview(source_config, [_filter("filter", 2)], 10, 0, "first")
    second = polars_compute.execute_preview(source_config, [_filter("filter", 7)], 10, 0, "second")

    assert [row["value"] for row in first["data"]] == list(range(3, 10))
    assert [row["value"] for row in second["data"]] == [8, 9]
    assert load_calls == 2
    assert step_calls["filter"] == 2


def test_changed_join_source_recomputes_join_but_reuses_cached_input_view(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path, "left")
    right_config = _source_config(tmp_path, "right")
    left = pl.DataFrame({"id": [1, 2, 3], "value": [10, 20, 30]})
    right_versions = [
        pl.DataFrame({"id": [1, 2, 3], "extra": ["old-1", "old-2", "old-3"]}),
        pl.DataFrame({"id": [1, 2, 3], "extra": ["new-1", "new-2", "new-3"]}),
    ]
    load_calls: Counter[str] = Counter()
    step_calls = _count_steps(monkeypatch)
    _install_cache(monkeypatch)

    def load_datasource(config: dict[str, object]) -> pl.LazyFrame:
        path = str(config["file_path"])
        load_calls[path] += 1
        if path == source_config["file_path"]:
            return left.lazy()
        return right_versions[load_calls[path] - 1].lazy()

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)
    additional_datasources = {"right": right_config}
    polars_compute.execute_preview(source_config, [_view("input-view")], 2, 0, "prefix", additional_datasources)
    join = _step(
        "join",
        "join",
        {
            "right_source": "right",
            "join_columns": [{"left_column": "id", "right_column": "id"}],
            "right_columns": ["extra"],
            "how": "inner",
        },
        ["input-view"],
    )
    first = polars_compute.execute_preview(source_config, [_view("input-view"), join], 10, 0, "first", additional_datasources)
    Path(str(right_config["file_path"])).write_text("value\nright-version-two\n", encoding="utf-8")
    second = polars_compute.execute_preview(source_config, [_view("input-view"), join], 10, 0, "second", additional_datasources)

    assert [row["extra"] for row in first["data"]] == ["old-1", "old-2", "old-3"]
    assert [row["extra"] for row in second["data"]] == ["new-1", "new-2", "new-3"]
    assert load_calls[str(source_config["file_path"])] == 1
    assert load_calls[str(right_config["file_path"])] == 2
    assert step_calls["join"] == 2


def test_incomplete_large_preview_does_not_truncate_later_filter_and_groupby(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    frame = pl.DataFrame({"value": range(100), "kind": ["all"] * 100})
    load_calls = 0
    _install_cache(monkeypatch, max_rows=5)

    def load_datasource(_config: dict[str, object]) -> pl.LazyFrame:
        nonlocal load_calls
        load_calls += 1
        return frame.lazy()

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)

    first = polars_compute.execute_preview(source_config, [_view("input-view")], 2, 0, "first")
    second = polars_compute.execute_preview(
        source_config,
        [
            _view("input-view"),
            _filter("filter", 90, ["input-view"]),
            _step(
                "groupby",
                "groupby",
                {"group_by": ["kind"], "aggregations": [{"column": "value", "function": "sum", "alias": "total"}]},
                ["filter"],
            ),
        ],
        10,
        0,
        "second",
    )

    assert [row["value"] for row in first["data"]] == [0, 1]
    assert second["data"] == [{"kind": "all", "total": 855}]
    assert load_calls == 2


def test_failing_first_page_is_never_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    cache = _install_cache(monkeypatch)

    def load_datasource(_config: dict[str, object]) -> pl.LazyFrame:
        return pl.DataFrame({"value": ["bad"]}).lazy().with_columns(pl.col("value").cast(pl.Int64))

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)
    _pinned_config, source_key = cache.source(source_config)

    with pytest.raises(pl.exceptions.PolarsError):
        polars_compute.execute_preview(source_config, [], 1, 0, "failure")

    assert source_key is not None
    assert cache.get(source_key) is None


def test_cached_view_does_not_skip_sibling_notification_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    frame = pl.DataFrame({"value": range(5)})
    notification_calls: list[str] = []
    _install_cache(monkeypatch)
    original_apply_step = polars_compute.apply_step

    def load_datasource(_config: dict[str, object]) -> pl.LazyFrame:
        return frame.lazy()

    def apply_step(lf, step, step_id, right_sources=None, right_lf=None):
        if step.operation == "notification":
            notification_calls.append(step_id)
            return lf.with_columns(pl.lit("staged").alias(str(step.params["output_column"])))
        return original_apply_step(lf, step, step_id, right_sources=right_sources, right_lf=right_lf)

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)
    monkeypatch.setattr(polars_compute, "apply_step", apply_step)
    steps = [
        _step(
            "notification",
            "notification",
            {
                "method": "email",
                "recipient": "person@example.test",
                "input_columns": ["value"],
                "message_template": "{{value}}",
            },
        ),
        _view("cached-view"),
    ]

    polars_compute.execute_preview(source_config, steps, 2, 0, "first")
    polars_compute.execute_preview(source_config, steps, 2, 1, "second")

    assert notification_calls == ["notification", "notification"]


def test_chart_metadata_paginates_after_cached_preview_and_export_stays_full(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    frame = pl.DataFrame({"category": ["A", "A", "B", "B"], "value": [1, 2, 10, 20]})
    load_calls = 0
    _install_cache(monkeypatch)

    def load_datasource(_config: dict[str, object]) -> pl.LazyFrame:
        nonlocal load_calls
        load_calls += 1
        return frame.lazy()

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)
    filter_step = _step(
        "filter",
        "filter",
        {"conditions": [{"column": "value", "operator": ">", "value": 0, "value_type": "number"}], "logic": "AND"},
    )

    first = polars_compute.execute_preview(source_config, [filter_step], 1, 0, "first")
    chart = _step(
        "chart",
        "chart",
        {"chart_type": "bar", "x_column": "category", "y_column": "value", "aggregation": "sum", "title": "Cached chart"},
        ["filter"],
    )
    chart_result = polars_compute.execute_preview(source_config, [filter_step, chart], 1, 1, "chart")
    export_path = tmp_path / "full.csv"
    export_result = polars_compute.execute_export(source_config, [filter_step], str(export_path), "csv", "export")

    assert first["row_count"] == 1
    assert chart_result["row_count"] == 1
    assert chart_result["data"][0]["x"] == "B"
    assert chart_result["metadata"]["title"] == "Cached chart"
    assert load_calls == 2
    assert export_result["row_count"] == 4
    assert pl.read_csv(export_path).height == 4
