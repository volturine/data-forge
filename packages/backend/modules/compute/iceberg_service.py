from datetime import UTC
from pathlib import Path

from contracts.build_runs.models import BuildRun, BuildRunStatus
from contracts.compute import schemas
from contracts.datasource.models import DataSource
from contracts.engine_runs.models import EngineRun
from contracts.engine_runs.schemas import EngineRunKind, EngineRunStatus
from core.exceptions import DataSourceNotFoundError, DataSourceSnapshotError
from core.iceberg_catalog import load_runtime_catalog
from core.iceberg_metadata import (
    resolve_iceberg_branch_metadata_path,
    resolve_iceberg_metadata_path,
)
from sqlalchemy import or_, select
from sqlmodel import Session


def _read_snapshot_id(payload: dict[str, object] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    snapshot_id = payload.get("snapshot_id")
    if isinstance(snapshot_id, str) and snapshot_id:
        return snapshot_id
    if isinstance(snapshot_id, int):
        return str(snapshot_id)
    return None


def _matches_branch(payload: dict[str, object] | None, branch: str | None) -> bool:
    if branch is None:
        return True
    if not isinstance(payload, dict):
        return False
    run_branch = payload.get("branch")
    return isinstance(run_branch, str) and run_branch == branch


def _engine_run_end_ms(run: EngineRun) -> int:
    completed_at = run.completed_at or run.created_at
    marker = completed_at if completed_at.tzinfo is not None else completed_at.replace(tzinfo=UTC)
    return int(marker.timestamp() * 1000)


def _build_run_snapshot_ids(
    session: Session,
    *,
    datasource_id: str,
    branch: str | None,
) -> set[str]:
    stmt = (
        select(BuildRun)
        .where(
            or_(
                BuildRun.current_datasource_id == datasource_id,  # type: ignore[arg-type]
                BuildRun.current_output_id == datasource_id,  # type: ignore[arg-type]
            )
        )
        .where(BuildRun.status == BuildRunStatus.COMPLETED)  # type: ignore[arg-type]
    )
    runs = session.execute(stmt).scalars().all()
    snapshot_ids: set[str] = set()
    for run in runs:
        result_json = run.result_json if isinstance(run.result_json, dict) else None
        if not _matches_branch(result_json, branch):
            continue
        snapshot_id = _read_snapshot_id(result_json)
        if snapshot_id is not None:
            snapshot_ids.add(snapshot_id)
    return snapshot_ids


def _ingest_run_snapshot_ids(
    session: Session,
    *,
    datasource_id: str,
    branch: str | None,
    snapshots: list[schemas.IcebergSnapshotInfo],
) -> set[str]:
    stmt = (
        select(EngineRun)
        .where(EngineRun.datasource_id == datasource_id)  # type: ignore[arg-type]
        .where(EngineRun.kind == EngineRunKind.INGEST.value)  # type: ignore[arg-type]
        .where(EngineRun.status == EngineRunStatus.SUCCESS.value)  # type: ignore[arg-type]
    )
    runs = session.execute(stmt).scalars().all()
    direct_snapshot_ids: set[str] = set()
    unresolved_runs: list[EngineRun] = []
    for run in runs:
        request_json = run.request_json if isinstance(run.request_json, dict) else None
        result_json = run.result_json if isinstance(run.result_json, dict) else None
        if not _matches_branch(result_json, branch) and not _matches_branch(request_json, branch):
            continue
        snapshot_id = _read_snapshot_id(result_json)
        if snapshot_id is not None:
            direct_snapshot_ids.add(snapshot_id)
            continue
        unresolved_runs.append(run)
    if not unresolved_runs:
        return direct_snapshot_ids

    claimed_snapshot_ids = set(direct_snapshot_ids)
    ordered_snapshots = sorted(
        enumerate(snapshots),
        key=lambda item: (item[1].timestamp_ms, item[0]),
    )
    snapshot_index = 0
    latest_candidate: schemas.IcebergSnapshotInfo | None = None
    ordered_runs = sorted(unresolved_runs, key=lambda run: (_engine_run_end_ms(run), run.id))
    for run in ordered_runs:
        run_end_ms = _engine_run_end_ms(run)
        while snapshot_index < len(ordered_snapshots):
            snapshot = ordered_snapshots[snapshot_index][1]
            if snapshot.timestamp_ms > run_end_ms:
                break
            snapshot_index += 1
            if snapshot.snapshot_id in claimed_snapshot_ids:
                continue
            latest_candidate = snapshot
        if latest_candidate is None:
            continue
        direct_snapshot_ids.add(latest_candidate.snapshot_id)
        claimed_snapshot_ids.add(latest_candidate.snapshot_id)
        latest_candidate = None
    return direct_snapshot_ids


def _build_result_snapshot_ids(
    session: Session,
    *,
    datasource_id: str,
    branch: str | None,
    snapshots: list[schemas.IcebergSnapshotInfo],
) -> set[str]:
    snapshot_ids = _build_run_snapshot_ids(
        session,
        datasource_id=datasource_id,
        branch=branch,
    )
    snapshot_ids.update(
        _ingest_run_snapshot_ids(
            session,
            datasource_id=datasource_id,
            branch=branch,
            snapshots=snapshots,
        )
    )
    return snapshot_ids


def list_iceberg_snapshots(
    session: Session,
    datasource_id: str,
    branch: str | None = None,
    build_results_only: bool = False,
) -> schemas.IcebergSnapshotsResponse:
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
        catalog = load_runtime_catalog("local", **catalog_config)
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
    if build_results_only:
        allowed_snapshot_ids = _build_result_snapshot_ids(
            session,
            datasource_id=datasource_id,
            branch=branch_name if isinstance(branch_name, str) else None,
            snapshots=snapshots,
        )
        snapshots = [snapshot for snapshot in snapshots if snapshot.snapshot_id in allowed_snapshot_ids]
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
    catalog = load_runtime_catalog("local", **catalog_config)
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
