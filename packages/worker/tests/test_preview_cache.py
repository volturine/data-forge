from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from operations.step_converter import BackendStep
from runtime import preview_cache as preview_cache_module
from runtime.config import settings
from runtime.domain.datasource.source_types import DataSourceLoadType
from runtime.namespace import namespace_paths
from runtime.preview_cache import PreviewCache


def _frame(row_count: int = 12) -> pl.DataFrame:
    return pl.DataFrame({"row": range(row_count), "label": [f"row-{row}" for row in range(row_count)]})


def test_collect_caches_complete_frame_and_serves_later_pages() -> None:
    cache = PreviewCache(max_bytes=1_000_000, max_rows=100, max_entries=4)
    source = _frame()

    first_page = cache.collect("source", source.lazy(), 2, 3)
    cached = cache.get("source")
    second_page = cache.collect("source", _frame(1).lazy(), 8, 2)

    assert first_page["row"].to_list() == [2, 3, 4]
    assert cached is not None
    assert cached["row"].to_list() == list(range(12))
    assert second_page["row"].to_list() == [8, 9]


def test_collect_uses_native_slice_for_pages_beyond_cache_row_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _frame(100)
    cache = PreviewCache(max_bytes=1_000_000, max_rows=5, max_entries=4)

    def unexpected_probe(*_args, **_kwargs):
        pytest.fail("Deep pagination must preserve Polars slice pushdown")

    monkeypatch.setattr(pl.LazyFrame, "sink_batches", unexpected_probe)
    page = cache.collect("large", source.lazy(), 50, 4)

    assert page["row"].to_list() == [50, 51, 52, 53]
    assert cache.get("large") is None


def test_collect_stops_opportunistic_fill_after_time_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _frame(100)
    cache = PreviewCache(max_bytes=1_000_000, max_rows=1_000, max_entries=4)
    elapsed_times = iter((0.0, 0.1, 0.3))

    with monkeypatch.context() as context:
        context.setattr(preview_cache_module.time, "perf_counter", lambda: next(elapsed_times))
        first_page = cache.collect("slow-fill", source.lazy(), 0, 2)

    assert cache.get("slow-fill") is None
    next_page = cache.collect("slow-fill", source.lazy(), 20, 3)

    assert first_page["row"].to_list() == [0, 1]
    assert next_page["row"].to_list() == [20, 21, 22]


def test_collect_does_not_store_a_page_as_a_complete_frame() -> None:
    source = _frame(100)
    cache = PreviewCache(max_bytes=1_000_000, max_rows=5, max_entries=4)

    page = cache.collect("incomplete", source.lazy(), 10, 3)
    next_result = cache.collect("incomplete", source.filter(pl.col("row") > 90).lazy(), 0, 20)

    assert page["row"].to_list() == [10, 11, 12]
    assert next_result["row"].to_list() == list(range(91, 100))
    assert cache.get("incomplete") is None


def test_collect_respects_byte_and_entry_budgets_with_lru_promotion() -> None:
    source = pl.DataFrame({"value": range(8)})
    size_bytes = int(source.estimated_size())
    cache = PreviewCache(max_bytes=size_bytes * 2 - 1, max_rows=100, max_entries=2)

    cache.collect("first", source.lazy(), 0, 1)
    cache.collect("second", source.lazy(), 0, 1)

    assert cache.get("first") is None
    assert cache.get("second") is not None
    assert cache._total_bytes <= cache.max_bytes

    entry_limited = PreviewCache(max_bytes=1_000_000, max_rows=100, max_entries=2)
    entry_limited.collect("first", source.lazy(), 0, 1)
    entry_limited.collect("second", source.lazy(), 0, 1)
    assert entry_limited.get("first") is not None
    entry_limited.collect("third", source.lazy(), 0, 1)

    assert entry_limited.get("first") is not None
    assert entry_limited.get("second") is None
    assert entry_limited.get("third") is not None


def test_collect_preserves_schema_for_empty_complete_frame() -> None:
    source = pl.DataFrame(schema={"row": pl.Int64, "label": pl.String})
    cache = PreviewCache(max_bytes=1_000_000, max_rows=100, max_entries=4)

    page = cache.collect("empty", source.lazy(), 0, 10)
    cached = cache.get("empty")

    assert page.is_empty()
    assert page.schema == source.schema
    assert cached is not None
    assert cached.schema == source.schema


def test_collect_never_caches_candidate_frames_when_sink_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = PreviewCache(max_bytes=1_000_000, max_rows=100, max_entries=4)

    def fail_after_partial_batch(self, callback, **kwargs):
        callback(pl.DataFrame({"row": [0, 1]}))
        raise RuntimeError("stream failed")

    monkeypatch.setattr(pl.LazyFrame, "sink_batches", fail_after_partial_batch)

    with pytest.raises(RuntimeError, match="stream failed"):
        cache.collect("failed", _frame().lazy(), 0, 2)

    assert cache.get("failed") is None


def test_collect_falls_back_to_original_page_when_cache_probe_hits_later_bad_row() -> None:
    source = pl.DataFrame({"value": ["1", "2", "bad"]}).lazy().with_columns(pl.col("value").cast(pl.Int64))
    cache = PreviewCache(max_bytes=1_000_000, max_rows=100, max_entries=4)

    first_page = cache.collect("cast", source, 0, 2)

    assert first_page["value"].to_list() == [1, 2]
    assert cache.get("cast") is None
    with pytest.raises(pl.exceptions.PolarsError):
        cache.collect("cast", source, 2, 1)


def test_collect_with_disabled_cache_uses_requested_slice() -> None:
    source = _frame()
    cache = PreviewCache(max_bytes=0, max_rows=100, max_entries=4)

    page = cache.collect("disabled", source.lazy(), 4, 3)

    assert page["row"].to_list() == [4, 5, 6]
    assert cache.get("disabled") is None


def test_source_fingerprints_regular_local_files_without_mutating_config(tmp_path: Path) -> None:
    file_path = tmp_path / "source.csv"
    file_path.write_text("row\n1\n", encoding="utf-8")
    config = {"source_type": DataSourceLoadType.FILE.value, "file_path": str(file_path), "file_type": "csv", "options": {"delimiter": ","}}
    cache = PreviewCache(max_bytes=1_000_000)

    copied_config, first_key = cache.source(config)
    file_path.write_text("row\n10\n", encoding="utf-8")
    _updated_config, second_key = cache.source(config)

    assert copied_config == config
    assert config["file_path"] == str(file_path)
    assert first_key is not None
    assert second_key is not None
    assert first_key != second_key


def test_source_bypasses_globs_directories_and_remote_file_urls(tmp_path: Path) -> None:
    cache = PreviewCache(max_bytes=1_000_000)
    directory = tmp_path / "parts"
    directory.mkdir()

    for file_path in (str(tmp_path / "*.csv"), str(directory), "s3://bucket/file.csv", "https://example.test/file.csv"):
        copied_config, key = cache.source({"source_type": "file", "file_path": file_path, "file_type": "csv"})

        assert copied_config["file_path"] == file_path
        assert key is None


def test_source_fingerprints_file_uri_using_local_path(tmp_path: Path) -> None:
    file_path = tmp_path / "source.csv"
    file_path.write_text("row\n1\n", encoding="utf-8")
    config = {"source_type": "file", "file_path": file_path.as_uri(), "file_type": "csv"}

    copied_config, key = PreviewCache(max_bytes=1_000_000).source(config)

    assert copied_config == config
    assert key is not None


def test_iceberg_source_pins_branch_metadata_and_invalidates_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data", raising=False)
    table_path = namespace_paths().exports_dir / "table"
    first_metadata = table_path / "main" / "metadata" / "v1.metadata.json"
    second_metadata = table_path / "experiment" / "metadata" / "v2.metadata.json"
    first_metadata.parent.mkdir(parents=True)
    second_metadata.parent.mkdir(parents=True)
    first_metadata.write_text("{}", encoding="utf-8")
    second_metadata.write_text("{}", encoding="utf-8")
    cache = PreviewCache(max_bytes=1_000_000)
    original = {
        "source_type": DataSourceLoadType.ICEBERG.value,
        "metadata_path": str(table_path),
        "branch": "main",
        "snapshot_id": "1",
        "storage_options": {"token": "secret"},
    }

    pinned_main, main_key = cache.source(original)
    pinned_branch, branch_key = cache.source({**original, "branch": "experiment"})
    _pinned_snapshot, snapshot_key = cache.source({**original, "snapshot_id": "2"})

    assert pinned_main["metadata_path"] == str(first_metadata)
    assert pinned_branch["metadata_path"] == str(second_metadata)
    assert original["metadata_path"] == str(table_path)
    assert main_key is not None and branch_key is not None and snapshot_key is not None
    assert main_key != branch_key
    assert main_key != snapshot_key
    assert "secret" not in main_key


def test_default_memory_budget_uses_finite_cgroup_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_read_text(path: Path, *, encoding: str | None = None) -> str:
        if str(path) == "/sys/fs/cgroup/memory.max":
            return str(32 * 1024 * 1024)
        raise FileNotFoundError(path)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    assert PreviewCache().max_bytes == 4 * 1024 * 1024


def test_step_keys_cover_transparent_and_deterministic_operations() -> None:
    cache = PreviewCache(max_bytes=1_000_000)
    filter_step = BackendStep(name="Filter", operation="filter", params={"conditions": [], "logic": "AND"})
    other_filter_step = BackendStep(name="Filter", operation="filter", params={"conditions": [{"column": "x"}], "logic": "AND"})

    assert cache.step_key("parent", BackendStep(name="View", operation="view", params={"row_limit": 2}), {}) == "parent"
    assert cache.step_key("parent", BackendStep(name="Chart", operation="chart", params={}), {}) == "parent"
    assert cache.step_key(None, BackendStep(name="View", operation="view", params={}), {}) is None
    assert cache.step_key("parent", filter_step, {}) != cache.step_key("different-parent", filter_step, {})
    assert cache.step_key("parent", filter_step, {}) != cache.step_key("parent", other_filter_step, {})
    assert cache.step_key("parent", filter_step, {}) is not None


def test_step_keys_include_only_referenced_additional_sources() -> None:
    cache = PreviewCache(max_bytes=1_000_000)
    join = BackendStep(name="Join", operation="join", params={"right_source": "right", "how": "inner"})
    union = BackendStep(name="Union", operation="union_by_name", params={"sources": ["right"], "allow_missing": True})

    join_key = cache.step_key("parent", join, {"right": "right-v1", "unused": "unused-v1"})
    assert join_key is not None
    assert cache.step_key("parent", join, {"right": "right-v2", "unused": "unused-v1"}) != join_key
    assert cache.step_key("parent", join, {"right": "right-v1", "unused": "unused-v2"}) == join_key
    assert cache.step_key("parent", join, {}) is None

    union_key = cache.step_key("parent", union, {"right": "right-v1", "unused": "unused-v1"})
    assert union_key is not None
    assert cache.step_key("parent", union, {"right": "right-v2"}) != union_key


def test_step_keys_reject_unsafe_barriers_and_udf_expressions() -> None:
    cache = PreviewCache(max_bytes=1_000_000)
    for operation in ("ai", "notification", "datasource", "expression", "unknown"):
        step = BackendStep(name=operation, operation=operation, params={})
        assert cache.step_key("parent", step, {}) is None

    literal = BackendStep(
        name="Columns",
        operation="with_columns",
        params={"expressions": [{"name": "constant", "type": "literal", "value": 2}]},
    )
    column = BackendStep(
        name="Columns",
        operation="with_columns",
        params={"expressions": [{"name": "copy", "type": "column", "column": "value"}]},
    )
    udf = BackendStep(
        name="Columns",
        operation="with_columns",
        params={"expressions": [{"name": "computed", "type": "udf", "code": "def udf(): return 1"}]},
    )

    assert cache.step_key("parent", literal, {}) is not None
    assert cache.step_key("parent", column, {}) is not None
    assert cache.step_key("parent", udf, {}) is None
