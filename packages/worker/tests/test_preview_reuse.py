from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import polars as pl
import pytest

from runtime import polars_compute
from runtime.exceptions import PipelineValidationError
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


def _install_cache(monkeypatch: pytest.MonkeyPatch) -> PreviewCache:
    cache = PreviewCache()
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
    events: list[dict[str, object]] = []
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
        progress_callback=events.append,
    )

    assert [row["value"] for row in first["data"]] == [0, 1]
    assert [row["value"] for row in second["data"]] == [9, 10, 11]
    assert load_calls == [source_config["file_path"]]
    assert step_calls["filter"] == 1
    assert [event["step_id"] for event in events if event["type"] == "step_start"] == ["filter", "output-view"]


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
    file_path = Path(str(source_config["file_path"]))
    file_path.write_text("value\n100\n", encoding="utf-8")
    original_stat = file_path.stat()
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
    file_path.write_text("value\n200\n", encoding="utf-8")
    os.utime(file_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000_000))
    assert file_path.stat().st_size == original_stat.st_size
    second = polars_compute.execute_preview(source_config, [_filter("filter", 1)], 10, 0, "second")

    assert [row["value"] for row in first["data"]] == [2, 3, 4]
    assert [row["value"] for row in second["data"]] == list(range(100, 105))
    assert load_calls == 2
    assert step_calls["filter"] == 2


def test_distinct_sources_and_namespaces_with_identical_steps_never_share_cached_preview(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first_config = {**_source_config(tmp_path, "first"), "namespace_name": "alpha"}
    second_config = {**_source_config(tmp_path, "second"), "namespace_name": "alpha"}
    beta_config = {**first_config, "namespace_name": "beta"}
    Path(str(first_config["file_path"])).write_text("value\n10\n", encoding="utf-8")
    Path(str(second_config["file_path"])).write_text("value\n20\n", encoding="utf-8")
    _install_cache(monkeypatch)
    load_calls = 0
    original_load = polars_compute.load_datasource

    def load_datasource(config: dict) -> pl.LazyFrame:
        nonlocal load_calls
        load_calls += 1
        return original_load(config)

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)
    steps = [_filter("filter", 0), _view("preview", ["filter"])]

    first = polars_compute.execute_preview(first_config, steps, 10, 0, "first")
    second = polars_compute.execute_preview(second_config, steps, 10, 0, "second")
    beta = polars_compute.execute_preview(beta_config, steps, 10, 0, "beta")

    assert [row["value"] for row in first["data"]] == [10]
    assert [row["value"] for row in second["data"]] == [20]
    assert [row["value"] for row in beta["data"]] == [10]
    assert load_calls == 3


def test_eviction_through_execute_preview_recomputes_when_returning_to_previous_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    frame = pl.DataFrame({"value": range(10)})
    load_calls = 0
    step_calls = _count_steps(monkeypatch)
    cache = _install_cache(monkeypatch)

    def load_datasource(_config: dict[str, object]) -> pl.LazyFrame:
        nonlocal load_calls
        load_calls += 1
        return frame.lazy()

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)

    first = polars_compute.execute_preview(source_config, [_filter("filter", 2), _view("preview", ["filter"])], 10, 0, "first")
    first_key = cache._owners["preview"]
    assert cache.get(first_key) is not None

    second = polars_compute.execute_preview(source_config, [_filter("filter", 7), _view("preview", ["filter"])], 10, 0, "second")
    assert cache.get(first_key) is None
    assert load_calls == 2
    assert step_calls["filter"] == 2

    third = polars_compute.execute_preview(source_config, [_filter("filter", 2), _view("preview", ["filter"])], 10, 0, "third")

    assert [row["value"] for row in first["data"]] == list(range(3, 10))
    assert [row["value"] for row in second["data"]] == [8, 9]
    assert [row["value"] for row in third["data"]] == list(range(3, 10))
    assert load_calls == 3
    assert step_calls["filter"] == 3


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

    assert {row["id"]: row["extra"] for row in first["data"]} == {1: "old-1", 2: "old-2", 3: "old-3"}
    assert {row["id"]: row["extra"] for row in second["data"]} == {1: "new-1", 2: "new-2", 3: "new-3"}
    assert load_calls[str(source_config["file_path"])] == 1
    assert load_calls[str(right_config["file_path"])] == 2
    assert step_calls["join"] == 2


def test_cache_toggle_discards_view_checkpoint_and_reenable_recomputes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    versions = [pl.DataFrame({"value": range(start, start + 4)}) for start in (0, 10, 20)]
    load_calls = 0
    step_calls = _count_steps(monkeypatch)
    _install_cache(monkeypatch)

    def load_datasource(_config: dict[str, object]) -> pl.LazyFrame:
        nonlocal load_calls
        frame = versions[load_calls]
        load_calls += 1
        return frame.lazy()

    monkeypatch.setattr(polars_compute, "load_datasource", load_datasource)
    cached_view = _view("preview", ["filter"])
    uncached_view = _view("preview", ["filter"])
    uncached_view["config"] = {"cache_enabled": False}

    first = polars_compute.execute_preview(source_config, [_filter("filter", -1), cached_view], 2, 0, "first")
    uncached = polars_compute.execute_preview(source_config, [_filter("filter", -1), uncached_view], 2, 0, "uncached")
    recomputed = polars_compute.execute_preview(source_config, [_filter("filter", -1), cached_view], 2, 0, "recomputed")
    reused = polars_compute.execute_preview(source_config, [_filter("filter", -1), cached_view], 2, 2, "reused")

    assert [row["value"] for row in first["data"]] == [0, 1]
    assert [row["value"] for row in uncached["data"]] == [10, 11]
    assert [row["value"] for row in recomputed["data"]] == [20, 21]
    assert [row["value"] for row in reused["data"]] == [22, 23]
    assert load_calls == 3
    assert step_calls["filter"] == 3


def test_cache_hit_emits_no_step_progress_or_timings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    frame = pl.DataFrame({"value": range(5)})
    _install_cache(monkeypatch)
    monkeypatch.setattr(polars_compute, "load_datasource", lambda _config: frame.lazy())
    steps = [_filter("filter", -1), _view("preview", ["filter"])]
    first_events: list[dict[str, object]] = []
    cached_events: list[dict[str, object]] = []

    first = polars_compute.execute_preview(source_config, steps, 2, 0, "first", progress_callback=first_events.append)
    cached = polars_compute.execute_preview(source_config, steps, 2, 1, "cached", progress_callback=cached_events.append)

    assert first["step_timings"]
    assert cached["step_timings"] == {}
    assert any(event.get("type") == "step_start" for event in first_events)
    assert not any(event.get("type") in {"step_start", "step_complete"} for event in cached_events)


@pytest.mark.parametrize("method", ("source", "step_key"))
@pytest.mark.parametrize("error_type", (OSError, TypeError, ValueError))
def test_fingerprint_errors_disable_preview_cache_without_failing(
    method: str,
    error_type: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_config = _source_config(tmp_path)
    frame = pl.DataFrame({"value": range(3)})
    cache = _install_cache(monkeypatch)

    def fail_fingerprint(*_args, **_kwargs):
        raise error_type("fingerprint failed")

    monkeypatch.setattr(cache, method, fail_fingerprint)
    monkeypatch.setattr(polars_compute, "load_datasource", lambda _config: frame.lazy())

    result = polars_compute.execute_preview(source_config, [_filter("filter", 0), _view("preview", ["filter"])], 3, 0, "fingerprint-error")

    assert [row["value"] for row in result["data"]] == [1, 2]
    assert cache._owners == {}


def test_additional_source_fingerprint_error_uses_normal_loader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path, "left")
    right_config = _source_config(tmp_path, "right")
    Path(str(source_config["file_path"])).write_text("id,value\n1,10\n2,20\n", encoding="utf-8")
    Path(str(right_config["file_path"])).write_text("id,extra\n2,matched\n", encoding="utf-8")
    cache = _install_cache(monkeypatch)
    source_key = cache.source

    def fingerprint(config: dict):
        if config["file_path"] == right_config["file_path"]:
            raise TypeError("Cannot fingerprint additional source")
        return source_key(config)

    monkeypatch.setattr(cache, "source", fingerprint)
    join = _step(
        "join",
        "join",
        {"right_source": "right", "join_columns": [{"left_column": "id", "right_column": "id"}], "right_columns": ["extra"], "how": "inner"},
    )
    result = polars_compute.execute_preview(source_config, [join, _view("preview", ["join"])], 10, 0, "right-key-error", {"right": right_config})

    assert result["data"] == [{"id": 2, "value": 20, "extra": "matched"}]
    assert cache._owners == {}


def test_invalid_step_config_reports_validation_before_execution(tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    events: list[dict[str, object]] = []

    with pytest.raises(PipelineValidationError) as error:
        polars_compute.execute_preview(
            source_config, [_step("invalid", "select", {"columns": "not-a-list"})], 10, 0, "invalid", progress_callback=events.append
        )

    assert error.value.details["step_id"] == "invalid"
    assert events == []


def test_invalid_downstream_step_config_raises_mid_run_after_upstream_progress(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_config = _source_config(tmp_path)
    _install_cache(monkeypatch)
    events: list[dict[str, object]] = []

    with pytest.raises(PipelineValidationError) as error:
        polars_compute.execute_preview(
            source_config,
            [
                _filter("valid-filter", -1),
                _step("invalid", "select", {"columns": "not-a-list"}, ["valid-filter"]),
            ],
            10,
            0,
            "invalid-mid-run",
            progress_callback=events.append,
        )

    assert error.value.details["step_id"] == "invalid"
    assert [(event["type"], event["step_id"]) for event in events if "step_id" in event] == [
        ("step_start", "valid-filter"),
        ("step_complete", "valid-filter"),
    ]


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

    view = _view("chart-input", ["filter"])
    first = polars_compute.execute_preview(source_config, [filter_step, view], 1, 0, "first")
    chart = _step(
        "chart",
        "chart",
        {"chart_type": "bar", "x_column": "category", "y_column": "value", "aggregation": "sum", "title": "Cached chart"},
        ["chart-input"],
    )
    chart_result = polars_compute.execute_preview(source_config, [filter_step, view, chart], 1, 1, "chart")
    export_path = tmp_path / "full.csv"
    export_result = polars_compute.execute_export(source_config, [filter_step], str(export_path), "csv", "export")

    assert first["row_count"] == 1
    assert chart_result["row_count"] == 1
    assert chart_result["data"][0]["x"] == "B"
    assert chart_result["metadata"]["title"] == "Cached chart"
    assert load_calls == 2
    assert export_result["row_count"] == 4
    assert pl.read_csv(export_path).height == 4
