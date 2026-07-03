from datetime import UTC

from sqlalchemy import or_, select
from sqlmodel import Session

from backend_core.data_plane_client import client_from_settings
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.compute import schemas
from backend_core.domain.engine_runs.schemas import EngineRunKind, EngineRunStatus
from backend_core.exceptions import DataSourceSnapshotError, datasource_not_found
from backend_core.namespace import get_namespace
from backend_core.persistence.build_runs.models import BuildRun
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.engine_runs.models import EngineRun
from backend_core.sqlmodel_typing import sa


def _read_snapshot_id(payload: dict[str, object] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    snapshot_id = payload.get('snapshot_id')
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
    run_branch = payload.get('branch')
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
                sa(BuildRun.current_datasource_id == datasource_id),
                sa(BuildRun.current_output_id == datasource_id),
            )
        )
        .where(sa(BuildRun.status == BuildRunStatus.COMPLETED))
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
        .where(sa(EngineRun.datasource_id == datasource_id))
        .where(sa(EngineRun.kind == EngineRunKind.INGEST.value))
        .where(sa(EngineRun.status == EngineRunStatus.SUCCESS.value))
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
        raise datasource_not_found(datasource_id)
    if not datasource.is_iceberg:
        raise ValueError('Snapshots are only available for Iceberg datasources')

    metadata_path = datasource.config.get('metadata_path')
    if not metadata_path:
        raise ValueError('Iceberg datasource missing metadata_path')
    branch_name = branch or datasource.config.get('branch')

    worker_response = client_from_settings().list_snapshots(
        namespace=get_namespace(),
        datasource_id=datasource_id,
        branch=branch_name if isinstance(branch_name, str) else None,
    )
    snapshots = [
        schemas.IcebergSnapshotInfo(
            snapshot_id=snapshot.snapshot_id,
            timestamp_ms=snapshot.timestamp_ms,
            parent_snapshot_id=snapshot.parent_snapshot_id,
            operation=snapshot.operation,
            is_current=snapshot.is_current,
        )
        for snapshot in worker_response.snapshots
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
        table_path=worker_response.table_path,
        snapshots=snapshots,
    )


def delete_iceberg_snapshot(session: Session, datasource_id: str, snapshot_id: str) -> schemas.IcebergSnapshotDeleteResponse:
    datasource = session.get(DataSource, datasource_id)
    if datasource is None:
        raise datasource_not_found(datasource_id)
    if not datasource.is_iceberg:
        raise ValueError('Snapshots are only available for Iceberg datasources')

    try:
        int(snapshot_id)
    except (TypeError, ValueError) as exc:
        raise DataSourceSnapshotError('Snapshot ID must be an integer', details={'snapshot_id': snapshot_id}) from exc

    deleted_snapshot_id = client_from_settings().delete_snapshot(namespace=get_namespace(), datasource_id=datasource_id, snapshot_id=snapshot_id)
    return schemas.IcebergSnapshotDeleteResponse(datasource_id=datasource_id, snapshot_id=deleted_snapshot_id)
