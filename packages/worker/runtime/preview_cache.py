from __future__ import annotations

import glob
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import unquote, urlparse

import polars as pl

from operations.enums import WithColumnsExprType
from operations.step_converter import BackendStep
from runtime.domain.datasource.source_types import DataSourceType
from runtime.iceberg_metadata import resolve_iceberg_branch_metadata_path

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


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PreviewCache:
    """Process-local full-frame cache with explicit checkpoint ownership."""

    def __init__(self) -> None:
        self._frames: dict[str, pl.DataFrame] = {}
        self._owners: dict[str, str] = {}

    def source(self, config: Mapping[str, object]) -> tuple[dict[str, object], str | None]:
        """Return a pinned copy and a stable key for cacheable datasource configs."""
        original_config = dict(config)
        copied_config = dict(original_config)
        source_type = config.get("source_type")

        try:
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
        except OSError, TypeError, ValueError:
            return original_config, None

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

        try:
            return _canonical_hash(
                {
                    "operation": operation,
                    "params": step.params,
                    "parent": parent_key,
                    "sources": referenced_keys,
                }
            )
        except OSError, TypeError, ValueError:
            return None

    def get(self, key: str | None) -> pl.DataFrame | None:
        if key is None:
            return None
        frame = self._frames.get(key)
        return frame.clone() if frame is not None else None

    def put(self, owner_id: str, key: str, frame: pl.DataFrame) -> None:
        previous_key = self._owners.get(owner_id)
        if previous_key is not None and previous_key != key:
            self._owners.pop(owner_id)
            self._remove_unowned_frame(previous_key)
        self._frames[key] = frame.clone()
        self._owners[owner_id] = key

    def discard(self, owner_id: str) -> None:
        previous_key = self._owners.pop(owner_id, None)
        if previous_key is not None:
            self._remove_unowned_frame(previous_key)

    def invalidate(self, owner_id: str, key: str | None) -> None:
        if key is None or self._owners.get(owner_id) != key:
            self.discard(owner_id)

    def materialize(self, key: str | None, lf: pl.LazyFrame, *, owner_id: str) -> pl.LazyFrame:
        if key is None:
            return lf

        cached = self.get(key)
        if cached is not None:
            self.put(owner_id, key, cached)
            return cached.lazy()

        try:
            frame = lf.collect(engine="streaming")
        except pl.exceptions.PolarsError, OSError:
            return lf

        self.put(owner_id, key, frame)
        return frame.lazy()

    def collect(
        self,
        key: str | None,
        lf: pl.LazyFrame,
        offset: int,
        row_limit: int,
        *,
        owner_id: str | None = None,
    ) -> pl.DataFrame:
        if key is None:
            return lf.slice(offset, row_limit).collect()
        result = self.materialize(key, lf, owner_id=owner_id if owner_id is not None else key)
        return result.slice(offset, row_limit).collect()

    def _remove_unowned_frame(self, key: str) -> None:
        if key not in self._owners.values():
            self._frames.pop(key, None)
