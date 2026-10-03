import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from backend_core import compute_requests_service, storage_cleanup_service
from backend_core.api_execution_budget import run_api_blocking
from backend_core.database import run_db
from backend_core.dependencies import RuntimeAvailabilityProbe
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.sqlmodel_typing import col
from dataforge_protocol import enums_pb2
from modules.compute.executor_client import execute_excel_preflight

_PREFLIGHT_TTL = storage_cleanup_service.PREFLIGHT_TTL


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('Excel metadata must contain a list of names')
    return [item for item in value if isinstance(item, str)]


@dataclass(frozen=True)
class ExcelPreflight:
    source_path: str
    sheets: list[str]
    tables: dict[str, list[str]]
    named_ranges: list[str]
    created_at: datetime
    delete_source: bool


def _load_preflight(session: Session, preflight_id: str) -> ExcelPreflight | None:
    row = session.get(ComputeRequest, preflight_id)
    if row is None or row.kind != enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT:
        return None
    if row.status != enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED:
        return None
    command = compute_requests_service.command_envelope_for_request(row).command.datasource.preflight
    if command.action != enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL:
        return None
    payload = compute_requests_service.response_payload(row)
    tables = payload.get('tables', {})
    return ExcelPreflight(
        source_path=command.source_path,
        sheets=_string_list(payload.get('sheets', [])),
        tables={name: list(value.get('columns', [])) for name, value in tables.items()} if isinstance(tables, dict) else {},
        named_ranges=_string_list(payload.get('named_ranges', [])),
        created_at=row.created_at,
        delete_source=row.artifact_path is not None and row.artifact_name == 'preflight-source',
    )


async def create_preflight(
    *,
    source_path: str,
    selection: Mapping[str, object],
    runtime_probe: RuntimeAvailabilityProbe,
    delete_source: bool,
) -> tuple[str, ExcelPreflight, dict[str, object]]:
    preflight_id = str(uuid.uuid4())
    result = await execute_excel_preflight(
        preflight_id=preflight_id,
        source_path=source_path,
        action=enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL,
        selection=selection,
        runtime_probe=runtime_probe,
        delete_source=delete_source,
    )
    preflight = await run_api_blocking(run_db, _load_preflight, preflight_id)
    if preflight is None:
        raise ValueError('Durable Excel preflight disappeared after completion')
    return preflight_id, preflight, result


async def get_preflight(preflight_id: str) -> ExcelPreflight | None:
    await _cleanup_expired()
    return await run_api_blocking(run_db, _load_preflight, preflight_id)


def _remove_preflight(session: Session, preflight_id: str, *, delete_source: bool) -> str | None:
    row = session.exec(select(ComputeRequest).where(ComputeRequest.id == preflight_id).with_for_update()).first()
    if row is None or row.kind != enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT:
        return None
    source = row.artifact_path if delete_source and row.artifact_name == 'preflight-source' else None
    if source is not None:
        if row.engine_resource_id is None:
            raise ValueError('Preflight source ownership requires its exact engine RID')
        storage_cleanup_service.register_preflight_source(session, preflight_id=preflight_id, resource_id=row.engine_resource_id, source_path=source)
    session.delete(row)
    session.commit()
    return source


async def clear_preflight(preflight_id: str, *, delete_source: bool = True) -> None:
    await run_api_blocking(run_db, _remove_preflight, preflight_id, delete_source=delete_source)


def _expire_preflights(session: Session) -> None:
    before = datetime.now(UTC) - _PREFLIGHT_TTL
    rows = session.exec(
        select(ComputeRequest)
        .where(ComputeRequest.kind == enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT)
        .where(ComputeRequest.id == ComputeRequest.engine_resource_id)
        .where(ComputeRequest.created_at < before)
        .where(col(ComputeRequest.status).in_([enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED, enums_pb2.COMPUTE_REQUEST_STATUS_FAILED]))
        .with_for_update(skip_locked=True)
        .limit(32)
    ).all()
    for row in rows:
        active = session.exec(
            select(ComputeRequest.id)
            .where(ComputeRequest.engine_resource_id == row.id)
            .where(col(ComputeRequest.status).in_([enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED, enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING]))
        ).first()
        if active is not None:
            continue
        if row.artifact_path is not None and row.artifact_name == 'preflight-source':
            if row.engine_resource_id is None:
                raise ValueError('Preflight source ownership requires its exact engine RID')
            storage_cleanup_service.register_preflight_source(session, preflight_id=row.id, resource_id=row.engine_resource_id, source_path=row.artifact_path)
        session.delete(row)
    session.commit()


async def _cleanup_expired() -> None:
    await run_api_blocking(run_db, _expire_preflights)


def preview_rows(result: Mapping[str, object]) -> list[list[str | None]]:
    rows = result.get('preview_rows', [])
    if not isinstance(rows, list):
        raise ValueError('Excel preview result must contain rows')
    return [row['cells'] for row in rows if isinstance(row, dict) and isinstance(row.get('cells'), list)]


def preview_result(result: Mapping[str, object]) -> tuple[str | None, int, int, int, int | None, list[list[str | None]]]:
    sheet_name = result.get('sheet_name')
    start_row = result.get('start_row')
    start_col = result.get('start_col')
    end_col = result.get('end_col')
    detected_end_row = result.get('detected_end_row')
    if sheet_name is not None and not isinstance(sheet_name, str):
        raise ValueError('Excel preview result has an invalid sheet name')
    if not isinstance(start_row, int) or not isinstance(start_col, int) or not isinstance(end_col, int):
        raise ValueError('Excel preview result has invalid bounds')
    if detected_end_row is not None and not isinstance(detected_end_row, int):
        raise ValueError('Excel preview result has an invalid detected end row')
    return sheet_name, start_row, start_col, end_col, detected_end_row, preview_rows(result)


def resolved_selection(result: Mapping[str, object]) -> tuple[str, int, int, int, int]:
    sheet_name, start_row, start_col, end_col, end_row, _rows = preview_result({**result, 'preview_rows': []})
    if sheet_name is None:
        raise ValueError('Excel selection result has no sheet name')
    if end_row is None:
        raise ValueError('Excel selection result has no resolved end row')
    return sheet_name, start_row, start_col, end_col, end_row


def format_excel_cell_range(sheet_name: str, start_row: int, start_col: int, end_row: int, end_col: int) -> str:
    def column_name(index: int) -> str:
        value = index + 1
        result = ''
        while value:
            value, digit = divmod(value - 1, 26)
            result = chr(65 + digit) + result
        return result

    return f'{sheet_name}!{column_name(start_col)}{start_row + 1}:{column_name(end_col)}{end_row + 1}'
