from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import pytest

from operations.step_converter import BackendStep
from runtime.config import settings
from runtime.domain.datasource.source_types import DataSourceLoadType
from runtime.namespace import namespace_paths
from runtime.preview_cache import PreviewCache


def _frame(row_count: int = 12) -> pl.DataFrame:
    return pl.DataFrame({"row": range(row_count), "label": [f"row-{row}" for row in range(row_count)]})


def test_collect_materializes_full_result_and_serves_later_pages() -> None:
    cache = PreviewCache()
    source = _frame()

    first_page = cache.collect("source", source.lazy(), 2, 3)
    cached = cache.get("source")
    second_page = cache.collect("source", _frame(1).lazy(), 8, 2)

    assert first_page["row"].to_list() == [2, 3, 4]
    assert cached is not None
    assert cached["row"].to_list() == list(range(12))
    assert second_page["row"].to_list() == [8, 9]


def test_collect_caches_result_over_former_row_and_byte_limits() -> None:
    row_count = 100_001
    payload = "x" * 1024
    source = pl.DataFrame(
        {
            "row": range(row_count),
            "payload": pl.Series("payload", [payload] * row_count, dtype=pl.String),
        }
    )
    cache = PreviewCache()

    page = cache.collect("large", source.lazy(), 100_000, 1, owner_id="large-preview")
    cached = cache.get("large")

    assert page["row"].to_list() == [100_000]
    assert cached is not None
    assert cached.height == 100_001
    assert cached.estimated_size() > 64 * 1024 * 1024
    assert len(cached["payload"][0]) == 1024


def test_cache_retains_more_than_sixteen_owned_checkpoints() -> None:
    cache = PreviewCache()

    for index in range(20):
        cache.put(f"preview-{index}", f"key-{index}", pl.DataFrame({"value": [index]}))

    assert len(cache._frames) == 20
    for index in range(20):
        cached = cache.get(f"key-{index}")
        assert cached is not None
        assert cached["value"][0] == index


def test_owners_share_frames_and_replacement_prunes_only_unowned_frames() -> None:
    cache = PreviewCache()
    shared = pl.DataFrame({"value": [1, 2]})
    replacement = pl.DataFrame({"value": [3, 4]})
    cache.put("preview-a", "shared", shared)
    cache.put("preview-b", "shared", shared)

    cache.put("preview-a", "replacement", replacement)

    shared_result = cache.get("shared")
    replacement_result = cache.get("replacement")
    assert shared_result is not None
    assert replacement_result is not None
    assert shared_result["value"].to_list() == [1, 2]
    assert replacement_result["value"].to_list() == [3, 4]
    assert cache._owners == {"preview-b": "shared", "preview-a": "replacement"}

    cache.invalidate("preview-a", "replacement")
    assert cache.get("replacement") is not None
    cache.invalidate("preview-a", "changed-key")

    assert cache.get("replacement") is None
    assert cache.get("shared") is not None
    cache.discard("preview-b")
    assert cache.get("shared") is None


def test_discard_and_invalidate_preserve_frames_owned_by_another_preview() -> None:
    cache = PreviewCache()
    frame = pl.DataFrame({"value": [1]})
    cache.put("preview-a", "same", frame)
    cache.put("preview-b", "same", frame)

    cache.discard("preview-a")
    assert cache.get("same") is not None

    cache.invalidate("preview-b", None)
    assert cache.get("same") is None


def test_materialize_uses_shared_full_frame_and_associates_each_owner() -> None:
    cache = PreviewCache()
    source = _frame()

    materialized = cache.materialize("frame", source.lazy(), owner_id="preview-a")
    shared = cache.materialize("frame", _frame(1).lazy(), owner_id="preview-b")

    assert materialized.collect()["row"].to_list() == list(range(12))
    assert shared.collect()["row"].to_list() == list(range(12))
    assert cache._owners == {"preview-a": "frame", "preview-b": "frame"}


def test_materialize_falls_back_to_original_lazy_frame_after_polars_error() -> None:
    source = pl.DataFrame({"value": ["1", "2", "bad"]}).lazy().with_columns(pl.col("value").cast(pl.Int64))
    cache = PreviewCache()

    materialized = cache.materialize("cast", source, owner_id="preview")

    assert materialized is source
    assert materialized.slice(0, 2).collect()["value"].to_list() == [1, 2]
    assert cache.get("cast") is None
    assert cache._owners == {}


def test_materialize_falls_back_to_original_lazy_frame_after_os_error(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _frame().lazy()
    cache = PreviewCache()

    def raise_os_error(self, **kwargs):
        raise OSError("source unavailable")

    with monkeypatch.context() as context:
        context.setattr(pl.LazyFrame, "collect", raise_os_error)
        materialized = cache.materialize("io-error", source, owner_id="preview")

    assert materialized is source
    assert cache.get("io-error") is None
    assert cache._owners == {}


def test_keyless_collect_slices_without_changing_checkpoint_ownership() -> None:
    cache = PreviewCache()
    cached_frame = pl.DataFrame({"row": [1, 2, 3]})
    cache.put("preview", "checkpoint", cached_frame)

    page = cache.collect(None, pl.DataFrame({"row": [8, 9, 10]}).lazy(), 1, 1, owner_id="preview")

    assert page["row"].to_list() == [9]
    checkpoint = cache.get("checkpoint")
    assert checkpoint is not None
    assert checkpoint["row"].to_list() == [1, 2, 3]
    assert cache._owners == {"preview": "checkpoint"}


def test_source_fingerprints_same_size_local_rewrite_and_preserves_config(tmp_path: Path) -> None:
    file_path = tmp_path / "source.csv"
    file_path.write_text("row\n1\n", encoding="utf-8")
    original_stat = file_path.stat()
    config = {"source_type": DataSourceLoadType.FILE.value, "file_path": str(file_path), "file_type": "csv", "options": {"delimiter": ","}}
    cache = PreviewCache()

    copied_config, first_key = cache.source(config)
    file_path.write_text("row\n2\n", encoding="utf-8")
    os.utime(file_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000_000))
    _updated_config, second_key = cache.source(config)

    assert copied_config == config
    assert config["file_path"] == str(file_path)
    assert first_key is not None
    assert second_key is not None
    assert file_path.stat().st_size == original_stat.st_size
    assert first_key != second_key


def test_distinct_sources_and_namespace_config_have_distinct_keys(tmp_path: Path) -> None:
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    first_path.write_text("row\n1\n", encoding="utf-8")
    second_path.write_text("row\n1\n", encoding="utf-8")
    cache = PreviewCache()
    first_config = {"source_type": "file", "file_path": str(first_path), "file_type": "csv", "namespace_name": "alpha"}
    second_config = {"source_type": "file", "file_path": str(second_path), "file_type": "csv", "namespace_name": "alpha"}
    other_namespace_config = {**first_config, "namespace_name": "beta"}

    _first_copy, first_key = cache.source(first_config)
    _second_copy, second_key = cache.source(second_config)
    _namespace_copy, namespace_key = cache.source(other_namespace_config)

    assert first_key is not None and second_key is not None and namespace_key is not None
    assert first_key != second_key
    assert first_key != namespace_key


def test_source_bypasses_globs_directories_and_remote_file_urls(tmp_path: Path) -> None:
    cache = PreviewCache()
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

    copied_config, key = PreviewCache().source(config)

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
    cache = PreviewCache()
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


def test_step_keys_cover_transparent_and_deterministic_operations() -> None:
    cache = PreviewCache()
    filter_step = BackendStep(name="Filter", operation="filter", params={"conditions": [], "logic": "AND"})
    other_filter_step = BackendStep(name="Filter", operation="filter", params={"conditions": [{"column": "x"}], "logic": "AND"})

    assert cache.step_key("parent", BackendStep(name="View", operation="view", params={"row_limit": 2}), {}) == "parent"
    assert cache.step_key("parent", BackendStep(name="Chart", operation="chart", params={}), {}) == "parent"
    assert cache.step_key(None, BackendStep(name="View", operation="view", params={}), {}) is None
    assert cache.step_key("parent", filter_step, {}) != cache.step_key("different-parent", filter_step, {})
    assert cache.step_key("parent", filter_step, {}) != cache.step_key("parent", other_filter_step, {})
    assert cache.step_key("parent", filter_step, {}) is not None


def test_step_keys_include_only_referenced_additional_sources() -> None:
    cache = PreviewCache()
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
    cache = PreviewCache()
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
