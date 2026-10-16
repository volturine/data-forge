from __future__ import annotations

import glob
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import polars as pl

from operations.enums import WithColumnsExprType
from operations.step_converter import BackendStep
from runtime.domain.datasource.source_types import DataSourceType
from runtime.iceberg_metadata import resolve_iceberg_branch_metadata_path

_DEFAULT_MAX_ENTRIES = 16
_DEFAULT_MAX_ROWS = 100_000
_DEFAULT_MAX_BYTES = 64 * 1024 * 1024
_BATCH_SIZE = 4096
_MAX_CACHE_FILL_SECONDS = 0.25
_CACHEABLE_OPERATIONS = frozenset(
    {
        "deduplicate",
        "drop",
        "explode",
        "fill_null",
        "filter",
        "groupby",
        "join",
        "limit",
        "pivot",
        "rename",
        "sample",
        "select",
        "sort",
        "string_transform",
        "timeseries",
        "topk",
        "union_by_name",
        "unpivot",
        "with_columns",
    }
)
_TRANSPARENT_OPERATIONS = frozenset({"chart", "download", "export", "view"})


@dataclass(slots=True)
class _CacheEntry:
    frame: pl.DataFrame
    size_bytes: int


def _cgroup_memory_limit_bytes() -> int | None:
    for path in (Path("/sys/fs/cgroup/memory.max"), Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")):
        try:
            value = path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            continue
        if value == "max":
            continue
        limit = int(value)
        if limit >= 1 << 60:
            continue
        return limit
    return None


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PreviewCache:
    """A bounded process-local cache of complete raw preview frames."""

    def __init__(self, *, max_bytes: int | None = None, max_rows: int = _DEFAULT_MAX_ROWS, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        if (max_bytes is not None and max_bytes < 0) or max_rows < 0 or max_entries < 0:
            raise ValueError("Preview cache budgets must be non-negative")
        memory_limit = _cgroup_memory_limit_bytes() if max_bytes is None else None
        self.max_bytes = min(_DEFAULT_MAX_BYTES, memory_limit // 8) if memory_limit is not None else (_DEFAULT_MAX_BYTES if max_bytes is None else max_bytes)
        self.max_rows = max_rows
        self.max_entries = max_entries
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._total_bytes = 0

    def source(self, config: Mapping[str, object]) -> tuple[dict[str, object], str | None]:
        """Return a pinned copy and a stable key for cacheable datasource configs."""
        copied_config = dict(config)
        source_type = config.get("source_type")

        if source_type == DataSourceType.ICEBERG.value:
            metadata_path = config.get("metadata_path")
            if not isinstance(metadata_path, str):
                return copied_config, None
            branch = config.get("branch")
            namespace_name = config.get("namespace_name")
            metadata_file = config.get("metadata_file")
            resolved_path = resolve_iceberg_branch_metadata_path(
                metadata_path,
                branch if isinstance(branch, str) else None,
                namespace_name=namespace_name if isinstance(namespace_name, str) else None,
                fallback_file=metadata_file if isinstance(metadata_file, str) else None,
            )
            copied_config["metadata_path"] = resolved_path
            return copied_config, _canonical_hash(copied_config)

        if source_type != DataSourceType.FILE.value:
            return copied_config, None

        file_path = config.get("file_path")
        if not isinstance(file_path, str):
            return copied_config, None

        parsed_path = urlparse(file_path)
        if parsed_path.scheme and parsed_path.scheme.lower() != "file":
            return copied_config, None
        if parsed_path.scheme.lower() == "file":
            if parsed_path.netloc not in {"", "localhost"}:
                return copied_config, None
            local_path = Path(unquote(parsed_path.path))
        else:
            if glob.has_magic(file_path):
                return copied_config, None
            local_path = Path(file_path)
        if glob.has_magic(str(local_path)) or not local_path.is_file():
            return copied_config, None

        stat = local_path.stat()
        file_identity = {
            "st_mtime_ns": stat.st_mtime_ns,
            "st_ctime_ns": stat.st_ctime_ns,
            "st_size": stat.st_size,
            "st_ino": stat.st_ino,
            "st_dev": stat.st_dev,
        }
        return copied_config, _canonical_hash({"config": copied_config, "file": file_identity})

    def step_key(self, parent_key: str | None, step: BackendStep, source_keys: dict[str, str | None]) -> str | None:
        operation = step.operation
        if operation in _TRANSPARENT_OPERATIONS:
            return parent_key
        if parent_key is None or operation not in _CACHEABLE_OPERATIONS:
            return None
        if operation == "with_columns":
            expressions = step.params.get("expressions")
            allowed_types = {WithColumnsExprType.LITERAL.value, WithColumnsExprType.COLUMN.value}
            if not isinstance(expressions, list) or not all(
                isinstance(expression, dict) and expression.get("type") in allowed_types for expression in expressions
            ):
                return None

        referenced_sources: set[str] = set()
        right_source = step.params.get("right_source")
        if right_source is not None:
            if not isinstance(right_source, str):
                return None
            referenced_sources.add(right_source)

        if operation == "union_by_name":
            sources = step.params.get("sources")
            if not isinstance(sources, list) or not all(isinstance(source_id, str) for source_id in sources):
                return None
            referenced_sources.update(sources)

        referenced_keys: dict[str, str] = {}
        for source_id in referenced_sources:
            source_key = source_keys.get(source_id)
            if source_key is None:
                return None
            referenced_keys[source_id] = source_key

        return _canonical_hash(
            {
                "operation": operation,
                "params": step.params,
                "parent": parent_key,
                "sources": referenced_keys,
            }
        )

    def get(self, key: str | None) -> pl.DataFrame | None:
        if key is None:
            return None
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry.frame.clone()

    def collect(self, key: str | None, lf: pl.LazyFrame, offset: int, row_limit: int) -> pl.DataFrame:
        if key is None or self.max_bytes <= 0 or self.max_rows <= 0 or self.max_entries <= 0 or offset < 0 or row_limit < 0:
            return lf.slice(offset, row_limit).collect()

        cached = self.get(key)
        if cached is not None:
            return cached.slice(offset, row_limit).clone()
        if offset >= self.max_rows:
            return lf.slice(offset, row_limit).collect()

        schema = lf.collect_schema()
        cached_chunks: list[pl.DataFrame] = []
        page_chunks: list[pl.DataFrame] = []
        candidate_bytes = 0
        candidate_rows = 0
        total_rows = 0
        candidate_complete = True
        page_end = offset + row_limit
        sink_started_at = time.perf_counter()

        def receive_batch(batch: pl.DataFrame) -> bool:
            nonlocal candidate_bytes, candidate_rows, candidate_complete, total_rows

            batch_start = total_rows
            batch_end = batch_start + batch.height
            batch_size = int(batch.estimated_size())

            if candidate_complete:
                if candidate_rows + batch.height > self.max_rows or candidate_bytes + batch_size > self.max_bytes:
                    candidate_complete = False
                    cached_chunks.clear()
                    candidate_bytes = 0
                    candidate_rows = 0
                else:
                    cached_chunks.append(batch.clone())
                    candidate_bytes += batch_size
                    candidate_rows += batch.height

            page_start = max(offset, batch_start)
            page_stop = min(page_end, batch_end)
            if page_stop > page_start:
                page_chunks.append(batch.slice(page_start - batch_start, page_stop - page_start).clone())
            total_rows = batch_end

            page_satisfied = row_limit == 0 or total_rows >= page_end
            if candidate_complete and page_satisfied and time.perf_counter() - sink_started_at > _MAX_CACHE_FILL_SECONDS:
                candidate_complete = False
                cached_chunks.clear()
                candidate_bytes = 0
                candidate_rows = 0
            return not candidate_complete and page_satisfied

        try:
            lf.sink_batches(receive_batch, chunk_size=min(_BATCH_SIZE, max(1, row_limit)), maintain_order=True, lazy=False)
        except pl.exceptions.PolarsError:
            return lf.slice(offset, row_limit).collect()

        empty = pl.DataFrame(schema=schema)
        if candidate_complete:
            complete_frame = pl.concat(cached_chunks, how="vertical") if cached_chunks else empty
            self._store(key, complete_frame)
            return complete_frame.slice(offset, row_limit).clone()

        if not page_chunks:
            return empty
        return page_chunks[0] if len(page_chunks) == 1 else pl.concat(page_chunks, how="vertical")

    def _store(self, key: str, frame: pl.DataFrame) -> None:
        size_bytes = int(frame.estimated_size())
        if size_bytes > self.max_bytes:
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._total_bytes -= previous.size_bytes
        while self._entries and (len(self._entries) >= self.max_entries or self._total_bytes + size_bytes > self.max_bytes):
            _, evicted = self._entries.popitem(last=False)
            self._total_bytes -= evicted.size_bytes
        self._entries[key] = _CacheEntry(frame.clone(), size_bytes)
        self._total_bytes += size_bytes
