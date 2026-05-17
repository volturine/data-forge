from pathlib import Path

from contracts.compute import schemas
from contracts.datasource.models import DataSource
from core.exceptions import DataSourceNotFoundError, DataSourceSnapshotError
from core.iceberg_metadata import (
    resolve_iceberg_branch_metadata_path,
    resolve_iceberg_metadata_path,
)
from pyiceberg.catalog import load_catalog
from sqlmodel import Session


def list_iceberg_snapshots(session: Session, datasource_id: str, branch: str | None = None) -> schemas.IcebergSnapshotsResponse:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise DataSourceNotFoundError(datasource_id)
    if not datasource.is_iceberg:
        raise ValueError("Snapshots are only available for Iceberg datasources")

    metadata_path = datasource.config.get("metadata_path")
    if not metadata_path:
        raise ValueError("Iceberg datasource missing metadata_path")
    branch_name = branch or datasource.config.get("branch")

    catalog_type = datasource.config.get("catalog_type")
    catalog_uri = datasource.config.get("catalog_uri")
    namespace = datasource.config.get("namespace")
    table_name = datasource.config.get("table")
    warehouse = datasource.config.get("warehouse")

    if catalog_type and catalog_uri and namespace and table_name:
        catalog_config = {"type": catalog_type, "uri": catalog_uri}
        if warehouse:
            catalog_config["warehouse"] = warehouse
        catalog = load_catalog("local", **catalog_config)
        identifier = f"{namespace}.{table_name}"
        table = catalog.load_table(identifier)
        resolved = resolve_iceberg_metadata_path(str(table.metadata_location))
    else:
        from pyiceberg.table import StaticTable

        resolved = resolve_iceberg_branch_metadata_path(metadata_path, branch_name)
        table = StaticTable.from_metadata(resolved)

    current_snapshot = table.current_snapshot()
    current_snapshot_id = str(current_snapshot.snapshot_id) if current_snapshot else None
    snapshots = [
        schemas.IcebergSnapshotInfo(
            snapshot_id=str(snapshot.snapshot_id),
            timestamp_ms=snapshot.timestamp_ms,
            parent_snapshot_id=(str(snapshot.parent_snapshot_id) if snapshot.parent_snapshot_id is not None else None),
            operation=(str(snapshot.summary.operation) if snapshot.summary and snapshot.summary.operation else None),
            is_current=str(snapshot.snapshot_id) == current_snapshot_id,
        )
        for snapshot in table.snapshots()
    ]
    snapshots.sort(key=lambda snapshot: snapshot.timestamp_ms, reverse=True)
    return schemas.IcebergSnapshotsResponse(
        datasource_id=datasource_id,
        table_path=str(Path(resolved).parents[1]),
        snapshots=snapshots,
    )


def delete_iceberg_snapshot(session: Session, datasource_id: str, snapshot_id: str) -> schemas.IcebergSnapshotDeleteResponse:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise DataSourceNotFoundError(datasource_id)
    if not datasource.is_iceberg:
        raise ValueError("Snapshots are only available for Iceberg datasources")

    try:
        snapshot_value = int(snapshot_id)
    except (TypeError, ValueError) as exc:
        raise DataSourceSnapshotError("Snapshot ID must be an integer", details={"snapshot_id": snapshot_id}) from exc

    catalog_type = datasource.config.get("catalog_type")
    catalog_uri = datasource.config.get("catalog_uri")
    namespace = datasource.config.get("namespace")
    table_name = datasource.config.get("table")
    warehouse = datasource.config.get("warehouse")
    if not (catalog_type and catalog_uri and namespace and table_name):
        raise DataSourceSnapshotError(
            "Snapshot deletion requires a catalog-backed Iceberg datasource",
            details={"snapshot_id": snapshot_id},
        )

    catalog_config = {"type": catalog_type, "uri": catalog_uri}
    if warehouse:
        catalog_config["warehouse"] = warehouse
    catalog = load_catalog("local", **catalog_config)
    table = catalog.load_table(f"{namespace}.{table_name}")

    if not hasattr(table, "maintenance"):
        raise DataSourceSnapshotError(
            "Snapshot deletion is not supported by the current Iceberg runtime",
            details={"snapshot_id": snapshot_id},
        )
    maintenance = table.maintenance
    if not hasattr(maintenance, "expire_snapshots"):
        raise DataSourceSnapshotError(
            "Snapshot deletion is not supported by the current Iceberg runtime",
            details={"snapshot_id": snapshot_id},
        )

    try:
        current = table.current_snapshot()
        if current and current.snapshot_id == snapshot_value:
            raise DataSourceSnapshotError(
                "Cannot delete the current snapshot",
                details={"snapshot_id": snapshot_id},
            )
        available_ids = [snapshot.snapshot_id for snapshot in table.snapshots()]
        if snapshot_value not in available_ids:
            raise DataSourceSnapshotError(
                f"Snapshot with snapshot id {snapshot_value} does not exist",
                details={
                    "snapshot_id": snapshot_id,
                    "available_snapshot_ids": available_ids,
                },
            )
        maintenance.expire_snapshots().by_id(snapshot_value).commit()
    except ValueError as exc:
        raise DataSourceSnapshotError(str(exc), details={"snapshot_id": snapshot_id}) from exc
    except NotImplementedError as exc:
        raise DataSourceSnapshotError(
            "Snapshot deletion is not supported by the current Iceberg catalog",
            details={"snapshot_id": snapshot_id},
        ) from exc

    return schemas.IcebergSnapshotDeleteResponse(datasource_id=datasource_id, snapshot_id=snapshot_id)
