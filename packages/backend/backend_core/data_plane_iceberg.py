from __future__ import annotations

import base64
from typing import Any

import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]

from backend_core.data_plane_client import client_from_settings
from backend_core.namespace import get_namespace


def resolve_iceberg_metadata_path(metadata_path: str, *, namespace_name: str | None = None) -> str:
    return client_from_settings().resolve_iceberg_metadata_path(
        namespace=namespace_name or get_namespace(),
        metadata_path=metadata_path,
    )


def resolve_iceberg_branch_metadata_path(metadata_path: str, branch: str | None, *, namespace_name: str | None = None) -> str:
    return client_from_settings().resolve_iceberg_branch_metadata_path(
        namespace=namespace_name or get_namespace(),
        metadata_path=metadata_path,
        branch=branch,
    )


def scan_iceberg_snapshot(metadata_path: str, snapshot_id: int, limit: int | None = None) -> pl.LazyFrame:
    rows = client_from_settings().scan_iceberg_snapshot(
        metadata_path=metadata_path,
        snapshot_id=str(snapshot_id),
        limit=limit,
    )
    return pl.DataFrame(rows).lazy()


def sync_iceberg_schema(metadata_path: str, schema: pa.Schema, *, namespace_name: str | None = None) -> None:
    del namespace_name
    client_from_settings().sync_iceberg_schema(
        metadata_path=metadata_path,
        schema_payload=_arrow_schema_payload(schema),
    )


def _arrow_schema_payload(schema: Any) -> dict[str, object]:
    if not isinstance(schema, pa.Schema):
        raise TypeError('Iceberg schema sync requires a pyarrow.Schema')
    encoded = base64.b64encode(schema.serialize().to_pybytes()).decode('ascii')
    return {'arrow_schema_ipc_base64': encoded}
