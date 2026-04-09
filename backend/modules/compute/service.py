import asyncio
import concurrent.futures
import contextlib
import logging
import os
import re
import tempfile
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]
from pyiceberg.catalog import load_catalog
from pyiceberg.table import Table as IcebergTable
from sqlalchemy import select
from sqlmodel import Session, col

from core.config import settings
from core.database import get_db
from core.exceptions import DataSourceNotFoundError, DataSourceSnapshotError, PipelineExecutionError, PipelineValidationError
from core.namespace import get_namespace, namespace_paths
from modules.analysis.models import Analysis
from modules.compute import schemas as compute_schemas
from modules.compute.live import ActiveBuild
from modules.compute.manager import ProcessManager
from modules.compute.monitor import monitor_engine_resources
from modules.compute.operations.datasource import resolve_iceberg_branch_metadata_path, resolve_iceberg_metadata_path
from modules.compute.schemas import BuildStatus, BuildTabStatus, ComputeRunStatus
from modules.compute.utils import apply_steps, await_engine_result, find_step_index, resolve_applied_target
from modules.datasource.models import DataSource
from modules.datasource.source_types import DataSourceType
from modules.engine_runs import service as engine_run_service
from modules.engine_runs.schemas import EngineRunKind
from modules.healthcheck import service as healthcheck_service
from modules.healthcheck.models import HealthCheck, HealthCheckResult
from modules.notification.service import notification_service, render_template
from modules.udf.models import Udf

logger = logging.getLogger(__name__)

BuildEmitter = Callable[[dict[str, object]], Awaitable[None]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _resource_summary(engine) -> dict[str, int | None]:
    effective = engine.effective_resources if getattr(engine, 'effective_resources', None) else {}
    max_threads = effective.get('max_threads')
    max_memory_mb = effective.get('max_memory_mb')
    streaming_chunk_size = effective.get('streaming_chunk_size')
    return {
        'max_threads': int(max_threads) if isinstance(max_threads, int) else None,
        'max_memory_mb': int(max_memory_mb) if isinstance(max_memory_mb, int) else None,
        'streaming_chunk_size': int(streaming_chunk_size) if isinstance(streaming_chunk_size, int) else None,
    }


def _analysis_name(session: Session, analysis_id: str | None) -> str:
    if not analysis_id:
        return 'Build'
    analysis = session.get(Analysis, analysis_id)
    if analysis and analysis.name:
        return analysis.name
    return analysis_id


def _build_starter(user) -> compute_schemas.BuildStarter:
    if user is None:
        return compute_schemas.BuildStarter(triggered_by='user')
    return compute_schemas.BuildStarter(
        user_id=getattr(user, 'id', None),
        display_name=getattr(user, 'display_name', None),
        email=getattr(user, 'email', None),
        triggered_by='user',
    )


def _estimate_remaining(elapsed_ms: int, completed_steps: int, total_steps: int) -> int | None:
    if completed_steps <= 0 or total_steps <= completed_steps:
        return None
    avg = elapsed_ms / completed_steps
    remaining = max(total_steps - completed_steps, 0)
    return int(avg * remaining)


async def _emit_build_event(emitter: BuildEmitter | None, payload: dict[str, object]) -> None:
    if emitter is None:
        return
    await emitter(payload)


async def _emit_progress(
    emitter: BuildEmitter | None,
    *,
    progress: float,
    elapsed_ms: int,
    completed_steps: int,
    total_steps: int,
    current_step: str | None,
    current_step_index: int | None,
    tab_id: str | None,
    tab_name: str | None,
) -> None:
    await _emit_build_event(
        emitter,
        {
            'type': 'progress',
            'progress': progress,
            'elapsed_ms': elapsed_ms,
            'estimated_remaining_ms': _estimate_remaining(elapsed_ms, completed_steps, total_steps),
            'current_step': current_step,
            'current_step_index': current_step_index,
            'total_steps': total_steps,
            'tab_id': tab_id,
            'tab_name': tab_name,
        },
    )


def _result_kind(existing_output_ds: DataSource | None) -> EngineRunKind:
    return EngineRunKind.DATASOURCE_UPDATE if existing_output_ds else EngineRunKind.DATASOURCE_CREATE


@dataclass(frozen=True)
class HealthCheckDetail:
    name: str
    passed: bool
    message: str
    critical: bool


BuildContext = Mapping[str, object]


@dataclass(frozen=True)
class ExportDatasourceResult:
    datasource_id: str
    datasource_name: str
    result_meta: dict


def _resolve_build_status(
    hc_results: list[HealthCheckResult],
    checks: list[HealthCheck] | None = None,
) -> tuple[BuildStatus, str | None, list[HealthCheckDetail] | None]:
    if not hc_results:
        return BuildStatus.SUCCESS, None, None

    name_map = {c.id: c.name for c in checks} if checks else {}
    critical_map = {c.id: c.critical for c in checks} if checks else {}
    total = len(hc_results)
    failed = [r for r in hc_results if not r.passed]

    if not failed:
        return BuildStatus.SUCCESS, f'{total}/{total} passed', None

    details = [
        HealthCheckDetail(
            name=name_map.get(r.healthcheck_id, r.healthcheck_id),
            passed=r.passed,
            message=r.message,
            critical=critical_map.get(r.healthcheck_id, False),
        )
        for r in hc_results
    ]
    return BuildStatus.WARNING, f'{len(failed)}/{total} failed', details


def _coerce_build_status(status: object) -> BuildStatus:
    if isinstance(status, BuildStatus):
        return status
    # Backward-compatible aliases still sent by legacy callers/tests.
    if status == 'done':
        return BuildStatus.SUCCESS
    try:
        return BuildStatus(str(status))
    except ValueError as exc:
        raise ValueError(f'Unsupported build status: {status}') from exc


def _raise_engine_failure(
    result_data: dict,
    *,
    operation: str,
    datasource_id: str,
    failure_prefix: str,
) -> None:
    error = result_data.get('error')
    if not error:
        return

    error_text = str(error)
    error_kind = result_data.get('error_kind')
    raw_error_details = result_data.get('error_details')
    error_details = raw_error_details if isinstance(raw_error_details, dict) else {}

    if error_kind == 'pipeline_validation':
        validation_details = error_details.get('details')
        details = dict(validation_details) if isinstance(validation_details, dict) else {}
        details['operation'] = operation
        details['datasource_id'] = datasource_id
        raise PipelineValidationError(error_text, details=details)

    if error_kind == 'value_error':
        raise PipelineValidationError(
            error_text,
            details={
                'operation': operation,
                'datasource_id': datasource_id,
                **error_details,
            },
        )

    if error_kind == 'datasource_metadata_missing':
        snapshot_details: dict[str, object] = {
            'operation': operation,
            'datasource_id': datasource_id,
        }
        metadata_path = error_details.get('metadata_path')
        if isinstance(metadata_path, str):
            snapshot_details['metadata_path'] = metadata_path
        raise DataSourceSnapshotError(
            'Datasource output is not available for this branch yet. Build the producing analysis first.',
            details=snapshot_details,
        )

    raise PipelineExecutionError(
        f'{failure_prefix} failed: {error_text}',
        details={
            'operation': operation,
            'datasource_id': datasource_id,
            'error_kind': error_kind,
            **error_details,
        },
    )


def _preflight_datasource_for_compute(
    config: dict,
    *,
    operation: str,
    datasource_id: str,
) -> None:
    source_type = str(config.get('source_type') or '')
    if source_type != DataSourceType.ICEBERG and source_type != str(DataSourceType.ICEBERG):
        return

    metadata_path = config.get('metadata_path')
    if not isinstance(metadata_path, str) or not metadata_path.strip():
        raise PipelineValidationError(
            'Iceberg datasource requires metadata_path',
            details={'operation': operation, 'datasource_id': datasource_id},
        )
    branch = config.get('branch')
    branch_value = str(branch) if isinstance(branch, str) and branch else None
    try:
        resolved_metadata_path = resolve_iceberg_branch_metadata_path(metadata_path, branch_value)
    except ValueError as exc:
        message = str(exc)
        if 'Iceberg metadata_path not found' in message:
            raise DataSourceSnapshotError(
                'Datasource output is not available for this branch yet. Build the producing analysis first.',
                details={'operation': operation, 'datasource_id': datasource_id, 'metadata_path': metadata_path},
            ) from exc
        raise
    config['metadata_path'] = resolved_metadata_path


def _build_subscriber_message(context: BuildContext) -> str:
    status = _coerce_build_status(context.get('status', BuildStatus.SUCCESS))
    analysis_name = str(context.get('analysis_name', ''))
    row_count = str(context.get('row_count', ''))
    duration = str(context.get('duration_ms', ''))
    hc_summary = context.get('healthcheck_summary')
    hc_details = context.get('healthcheck_details')

    if status == BuildStatus.WARNING:
        msg = f'Build complete: {analysis_name}\nStatus: built successfully, health checks failed'
    else:
        msg = f'Build complete: {analysis_name}\nStatus: {status.value}'

    if hc_summary:
        msg += f'\nHealth checks: {hc_summary}'

    msg += f'\nRows: {row_count}\nDuration: {duration}ms'

    max_len = 3800
    if len(msg) <= max_len:
        return msg

    hc_tail = ''
    if isinstance(hc_details, list):
        lines = []
        for detail in hc_details:
            icon = '\u2713' if detail.passed else '\u2717'
            lines.append(f'  {icon} {detail.name}: {detail.message} ')
        hc_tail = '\n'.join(lines)

    if not hc_tail:
        return msg[:max_len] + '\n…(truncated)'

    header = msg
    footer = f'\nHealth check details:\n{hc_tail}'
    combined = header + footer
    if len(combined) <= max_len:
        return combined

    available = max_len - len(header) - len('\nHealth check details:\n') - len('\n…(truncated)')
    if available <= 0:
        return header[:max_len] + '\n…(truncated)'
    trimmed = hc_tail[:available]
    return f'{header}\nHealth check details:\n{trimmed}\n…(truncated)'


_HC_SCANNERS: dict[str, Callable[[str], pl.LazyFrame]] = {
    'parquet': pl.scan_parquet,
    'csv': pl.scan_csv,
    'ndjson': pl.scan_ndjson,
}


def _load_healthcheck_lazy(output_path: str, export_format: str) -> pl.LazyFrame | None:
    if scanner := _HC_SCANNERS.get(export_format):
        return scanner(output_path)
    if export_format == 'json':
        return pl.read_json(output_path).lazy()
    return None


def _send_pipeline_notifications(
    steps: list[dict],
    context: dict[str, object],
    output_notification: dict | None = None,
) -> None:
    failed: list[str] = []

    if output_notification:
        method = output_notification.get('method', 'email')
        recipient = output_notification.get('recipient', '')
        subject_template = output_notification.get('subject_template', 'Build Complete')
        body_template = output_notification.get('body_template', '')
        if recipient and method == 'email':
            subject = render_template(subject_template, context)
            body = render_template(body_template, context)
            try:
                notification_service.send_email(to=recipient, subject=subject, body=body)
                logger.info(f'Output notification email sent to {recipient}')
            except Exception as e:
                logger.warning(f'Failed to send output {method} notification to {recipient}: {e}', exc_info=True)
                failed.append(f'output:{method}')

    for step in steps:
        if step.get('type') != 'notification':
            continue
        config = step.get('config', {})
        if config.get('input_columns'):
            continue
        method = config.get('method', 'email')
        recipient = config.get('recipient', '')
        if not recipient:
            continue

        subject_template = config.get('subject_template', 'Build Complete')
        body_template = config.get('body_template', '')
        subject = render_template(subject_template, context)
        body = render_template(body_template, context)

        try:
            if method == 'email':
                notification_service.send_email(to=recipient, subject=subject, body=body)
                logger.info(f'Notification email sent to {recipient}')
            elif method == 'telegram':
                notification_service.send_telegram(chat_id=recipient, message=f'{subject}\n\n{body}')
                logger.info(f'Notification telegram sent to {recipient}')
        except Exception as e:
            logger.warning(f'Failed to send {method} notification to {recipient}: {e}', exc_info=True)
            failed.append(f'step:{method}')

    # Subscriber-based notifications (from Telegram bot /subscribe)
    datasource_id = str(context.get('datasource_id', ''))
    if datasource_id:
        try:
            from core.database import run_db
            from modules.telegram.service import get_notification_chat_ids, list_subscribers

            pairs: list[tuple[str, str]] = run_db(get_notification_chat_ids, datasource_id)
            excluded: set[str] = set()
            if output_notification and output_notification.get('method') == 'telegram':
                subs = run_db(list_subscribers)
                pairs = [(s.chat_id, s.bot_token) for s in subs if s.is_active]
                excluded_raw = output_notification.get('excluded_recipients')
                if isinstance(excluded_raw, list):
                    excluded = {str(item) for item in excluded_raw}
            if excluded:
                pairs = [(cid, token) for cid, token in pairs if cid not in excluded]
            if pairs:
                msg = _build_subscriber_message(cast(BuildContext, context))
                for cid, token in pairs:
                    if not token:
                        continue
                    try:
                        notification_service.send_telegram(chat_id=cid, message=msg, bot_token=token)
                    except Exception as e:
                        logger.warning(f'Failed to notify subscriber {cid}: {e}', exc_info=True)
                        failed.append('subscriber:telegram')
        except Exception as e:
            logger.warning(f'Failed to send subscriber notifications: {e}', exc_info=True)
            failed.append('subscriber:lookup')

    if failed:
        raise PipelineExecutionError(
            'Notification delivery failed',
            details={'failures': failed},
        )


def _sync_iceberg_schema(table: IcebergTable, new_schema: pa.Schema) -> bool:
    from modules.compute.iceberg_reader import sync_iceberg_schema

    return sync_iceberg_schema(table, new_schema)


def _upsert_output_datasource(
    session: Session,
    result_id: str,
    name: str,
    source_type: str,
    config: dict,
    schema_cache: dict,
    analysis_id: str | None,
    is_hidden: bool | None = None,
    keep_schema_cache: bool = False,
) -> DataSource:
    """Create or update the output datasource for an export.

    If ``result_id`` points to an existing row, update it in-place.
    Otherwise create a brand-new ``DataSource``.  Returns the DB object.
    """
    try:
        uuid.UUID(result_id)
    except (ValueError, AttributeError):
        raise ValueError(f'result_id must be a valid UUID, got: {result_id!r}') from None
    existing = session.get(DataSource, result_id)
    if existing:
        existing.name = name
        existing.source_type = source_type
        existing.config = config
        if not keep_schema_cache:
            existing.schema_cache = schema_cache
        existing.created_by_analysis_id = analysis_id
        existing.created_by = 'analysis'
        if is_hidden is not None:
            existing.is_hidden = is_hidden
        session.add(existing)
        session.commit()
        return existing

    new_id = result_id
    ds = DataSource(
        id=new_id,
        name=name,
        source_type=source_type,
        config=config,
        schema_cache=schema_cache,
        created_by_analysis_id=analysis_id,
        created_by='analysis',
        is_hidden=is_hidden if is_hidden is not None else True,
        created_at=datetime.now(UTC),
    )
    session.add(ds)
    session.commit()
    return ds


def _build_preview_result_metadata(
    data: dict,
    page: int,
    row_limit: int,
    offset: int,
) -> dict:
    schema = data.get('schema', {}) or {}
    rows = data.get('data', []) or []
    query_plans = data.get('query_plans')

    result: dict = {
        'schema': schema,
        'columns': list(schema.keys()),
        'row_count': data.get('row_count', 0),
        'page': page,
        'row_limit': row_limit,
        'offset': offset,
        'page_size': len(rows),
    }

    if query_plans:
        result['query_plans'] = query_plans
    if metadata := data.get('metadata'):
        result['metadata'] = metadata

    return result


def _build_export_result_metadata(
    data: dict,
    file_size_bytes: int,
) -> dict:
    query_plans = data.get('query_plans')

    result: dict = {
        'row_count': data.get('row_count', 0),
        'export_format': data.get('export_format'),
        'file_size_bytes': file_size_bytes,
    }

    if query_plans:
        result['query_plans'] = query_plans

    return result


def _resolve_branch_value(config: dict) -> str:
    branch = config.get('branch')
    if isinstance(branch, str) and branch.strip():
        return branch.strip()
    return 'master'


def _set_snapshot_metadata(config: dict, snapshot_id: str | None, snapshot_timestamp_ms: int | None) -> dict:
    if snapshot_id is None or snapshot_timestamp_ms is None:
        return config
    return {
        **config,
        'current_snapshot_id': snapshot_id,
        'current_snapshot_timestamp_ms': snapshot_timestamp_ms,
        'snapshot_id': snapshot_id,
        'snapshot_timestamp_ms': snapshot_timestamp_ms,
    }


def _ensure_request_branch(request_payload: dict, branch: str) -> dict:
    payload = dict(request_payload)
    opts = payload.get('iceberg_options')
    if isinstance(opts, dict):
        if isinstance(opts.get('branch'), str) and opts['branch'].strip():
            return payload
        payload['iceberg_options'] = {**opts, 'branch': branch}
        return payload
    payload['iceberg_options'] = {'branch': branch}
    return payload


def _get_additional_datasources(
    session: Session,
    steps: list[dict],
    analysis_pipeline: dict,
) -> dict[str, dict]:
    """Extract and fetch additional datasources referenced in pipeline steps (e.g., for joins)."""
    steps = apply_steps(steps)
    additional: dict[str, dict] = {}
    sources = analysis_pipeline.get('sources')
    pipeline_sources = {str(k): v for k, v in sources.items() if isinstance(v, dict)} if isinstance(sources, dict) else None
    pipeline_id = analysis_pipeline.get('analysis_id')
    analysis_id = str(pipeline_id) if pipeline_id is not None else None

    for step in steps:
        config = step.get('config', {})
        right_source_id = config.get('right_source') or config.get('rightDataSource')

        union_sources = config.get('sources', [])
        if isinstance(union_sources, str):
            union_sources = [union_sources]

        source_ids = ([str(right_source_id)] if right_source_id else []) + [str(s) for s in union_sources if s is not None]

        for source_id in source_ids:
            if source_id in additional:
                continue
            if pipeline_sources and source_id in pipeline_sources:
                config_override = pipeline_sources[source_id]
            else:
                datasource = session.get(DataSource, source_id)
                if not datasource:
                    continue
                config_override = {'source_type': datasource.source_type, **datasource.config}
            if analysis_id and config_override.get('source_type') == 'analysis' and str(config_override.get('analysis_id')) == analysis_id:
                config_override = {**config_override, 'analysis_pipeline': analysis_pipeline}
            additional[source_id] = config_override

    return additional


def _hydrate_udfs(session: Session, steps: list[dict]) -> list[dict]:
    next_steps: list[dict] = []
    for step in steps:
        if step.get('type') != 'with_columns':
            next_steps.append(step)
            continue
        config = step.get('config', {})
        expressions = config.get('expressions', [])
        if not isinstance(expressions, list):
            next_steps.append(step)
            continue
        updated = []
        for expr in expressions:
            if not isinstance(expr, dict) or expr.get('type') != 'udf':
                updated.append(expr)
                continue
            udf_id = expr.get('udf_id')
            if not udf_id or expr.get('code'):
                updated.append(expr)
                continue
            result = session.execute(select(Udf).where(Udf.id == udf_id))  # type: ignore[arg-type]
            udf = result.scalar_one_or_none()
            if not udf:
                raise ValueError(f'UDF {udf_id} not found')
            updated.append({**expr, 'code': udf.code})
        next_steps.append({**step, 'config': {**config, 'expressions': updated}})
    return next_steps


def _resolve_pipeline_request(
    pipeline: dict,
    tab_id: str | None,
    target_step_id: str,
) -> dict:
    tabs = pipeline.get('tabs', [])
    if not isinstance(tabs, list) or not tabs:
        raise ValueError('analysis_pipeline missing tabs')

    selected = None
    if tab_id:
        selected = next((tab for tab in tabs if tab.get('id') == tab_id), None)
    if selected and target_step_id != 'source':
        steps = selected.get('steps', []) if isinstance(selected, dict) else []
        if not any(step.get('id') == target_step_id for step in steps):
            selected = None
    if not selected and target_step_id != 'source':
        selected = next(
            (tab for tab in tabs if isinstance(tab, dict) and any(step.get('id') == target_step_id for step in tab.get('steps', []))),
            None,
        )
    if not selected:
        selected = next((tab for tab in tabs if tab.get('steps')), None)
    if not selected:
        selected = tabs[0]

    datasource = selected.get('datasource')
    if not isinstance(datasource, dict):
        raise ValueError('analysis_pipeline tab datasource must be a dict')
    datasource_id = datasource.get('id')
    if not datasource_id:
        raise ValueError('analysis_pipeline tab missing datasource.id')

    steps = selected.get('steps', [])
    if not isinstance(steps, list):
        raise ValueError('analysis_pipeline tab steps must be a list')

    sources = pipeline.get('sources', {})
    if not isinstance(sources, dict) or not sources:
        raise ValueError('analysis_pipeline missing datasource configs')

    datasource_config = sources.get(str(datasource_id))
    if not isinstance(datasource_config, dict):
        raise ValueError(f'analysis_pipeline missing datasource config for {datasource_id}')

    overrides = datasource.get('config') or {}
    if not isinstance(overrides, dict):
        raise ValueError('analysis_pipeline tab datasource.config must be a dict')
    branch = overrides.get('branch')
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError('analysis_pipeline tab datasource.config.branch is required')

    merged = {**datasource_config, **overrides}
    analysis_id = pipeline.get('analysis_id')
    analysis_id = str(analysis_id) if analysis_id is not None else None
    if analysis_id and merged.get('source_type') == 'analysis' and str(merged.get('analysis_id')) == analysis_id:
        merged = {**merged, 'analysis_pipeline': pipeline}

    resolved_target = resolve_applied_target(steps, target_step_id)

    return {
        'analysis_id': analysis_id,
        'datasource_id': str(datasource_id),
        'steps': steps,
        'target_step_id': resolved_target,
        'datasource_config': merged,
    }


def build_analysis_pipeline_payload(session: Session, analysis: Analysis, datasource_id: str | None = None) -> dict:
    pipeline = analysis.pipeline_definition
    tabs = pipeline.get('tabs', []) if isinstance(pipeline, dict) else []
    if not isinstance(tabs, list) or not tabs:
        return {'analysis_id': str(analysis.id), 'tabs': [], 'sources': {}}

    sources: dict[str, dict] = {}
    output_map: dict[str, str] = {}
    for tab in tabs:
        tab_id = tab.get('id')
        output = tab.get('output') if isinstance(tab, dict) else None
        if not isinstance(output, dict):
            raise ValueError('Analysis pipeline tab missing output configuration')
        output_id = output.get('result_id')
        if not output_id:
            raise ValueError('Analysis pipeline tab missing output.result_id')
        output_id = str(output_id)
        if output_id and tab_id:
            output_map[str(tab_id)] = str(output_id)
            sources[str(output_id)] = {
                'source_type': 'analysis',
                'analysis_id': str(analysis.id),
                'analysis_tab_id': str(tab_id),
            }

    next_tabs: list[dict] = []
    for tab in tabs:
        datasource = tab.get('datasource') if isinstance(tab, dict) else None
        if not isinstance(datasource, dict):
            raise ValueError('Analysis pipeline tab datasource must be a dict')
        output = tab.get('output') if isinstance(tab, dict) else None
        if not isinstance(output, dict):
            raise ValueError('Analysis pipeline tab missing output configuration')
        output_id = output.get('result_id')
        if not output_id:
            raise ValueError('Analysis pipeline tab missing output.result_id')
        config = datasource.get('config')
        if not isinstance(config, dict):
            raise ValueError('Analysis pipeline tab datasource.config must be a dict')
        branch = config.get('branch')
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError('Analysis pipeline tab datasource.config.branch is required')
        tab_datasource_id = datasource.get('id')

        if not tab_datasource_id:
            raise ValueError('Analysis pipeline tab missing datasource.id')
        if datasource_id and str(datasource_id) != output_id and str(datasource_id) != str(tab_datasource_id):
            next_tabs.append({**tab, 'datasource': {**datasource, 'id': tab_datasource_id, 'config': config}})
            continue
        if str(tab_datasource_id) not in sources:
            datasource_model = session.get(DataSource, str(tab_datasource_id))
            if datasource_model:
                sources[str(tab_datasource_id)] = {
                    'source_type': datasource_model.source_type,
                    **datasource_model.config,
                }
        next_tabs.append({**tab, 'datasource': {**datasource, 'id': tab_datasource_id, 'config': config}})

    return {
        'analysis_id': str(analysis.id),
        'tabs': next_tabs,
        'sources': sources,
    }


def preview_step(
    session: Session,
    manager: ProcessManager,
    target_step_id: str,
    analysis_pipeline: dict,
    row_limit: int = 1000,
    page: int = 1,
    timeout: int | None = None,
    analysis_id: str | None = None,
    resource_config: dict | None = None,
    tab_id: str | None = None,
    request_json: dict | None = None,
    triggered_by: str | None = None,
):
    """Preview the result of executing pipeline up to a specific step with pagination."""
    from modules.compute.schemas import StepPreviewResponse

    if timeout is None:
        timeout = settings.job_timeout

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()
    resolved = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id)
    datasource_id = resolved['datasource_id']
    steps = resolved['steps']
    target_step_id = resolved['target_step_id']
    datasource_config = resolved['datasource_config']
    analysis_id_value = resolved['analysis_id'] or analysis_id

    if not isinstance(datasource_config, dict):
        raise ValueError('Preview requires datasource_config')

    if not analysis_id_value:
        analysis_id_value = f'__preview__{datasource_id}'

    config: dict = datasource_config
    _preflight_datasource_for_compute(
        config,
        operation='preview',
        datasource_id=datasource_id,
    )

    run_analysis_id = analysis_id_value

    branch = _resolve_branch_value(config)
    request_payload = _ensure_request_branch(
        request_json
        or {
            'analysis_id': run_analysis_id,
            'datasource_id': datasource_id,
            'steps': steps,
            'target_step_id': target_step_id,
            'row_limit': row_limit,
            'page': page,
            'resource_config': resource_config,
            'analysis_pipeline': analysis_pipeline,
            'tab_id': tab_id,
            'iceberg_options': {'branch': branch},
        },
        branch,
    )

    steps = apply_steps(steps)

    if target_step_id == 'source':
        preview_steps = []
    else:
        step_index = find_step_index(steps, target_step_id)
        preview_steps = steps[: step_index + 1]
        preview_steps = _hydrate_udfs(session, preview_steps)

    engine = manager.get_or_create_engine(analysis_id_value, resource_config=resource_config)

    additional_datasources = _get_additional_datasources(session, preview_steps, analysis_pipeline)

    # Calculate offset for pagination
    offset = (page - 1) * row_limit

    # Use the new preview method that efficiently fetches only needed rows
    job_id = engine.preview(
        datasource_config=config,
        steps=preview_steps,
        row_limit=row_limit,
        offset=offset,
        additional_datasources=additional_datasources,
    )

    step_timings: dict = {}
    current_step_id: str | None = None
    query_plan: str | None = None
    try:
        result_data = await_engine_result(engine, timeout, job_id=job_id)
        step_timings = result_data.get('step_timings', {}) if isinstance(result_data, dict) else {}
        query_plan = result_data.get('query_plan') if isinstance(result_data, dict) else None
        _raise_engine_failure(
            result_data,
            operation='preview',
            datasource_id=datasource_id,
            failure_prefix='Preview',
        )

        data = result_data.get('data', {})
        result_meta = _build_preview_result_metadata(
            data=data,
            page=page,
            row_limit=row_limit,
            offset=offset,
        )

        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=run_analysis_id,
            datasource_id=datasource_id,
            kind='preview',
            status=ComputeRunStatus.SUCCESS,
            request_json=request_payload,
            result_json=result_meta,
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            step_timings=step_timings,
            query_plan=query_plan,
            progress=1.0,
            current_step=current_step_id,
            triggered_by=triggered_by,
        )
        engine_run_service.create_engine_run(session, payload)

        return StepPreviewResponse(
            step_id=target_step_id,
            columns=list(data.get('schema', {}).keys()),
            column_types=data.get('schema', {}),
            data=data.get('data', []),
            total_rows=data.get('row_count', 0),
            page=page,
            page_size=len(data.get('data', [])),
            metadata=data.get('metadata'),
        )
    except Exception as exc:
        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=run_analysis_id,
            datasource_id=datasource_id,
            kind='preview',
            status=ComputeRunStatus.FAILED,
            request_json=request_payload,
            error_message=str(exc),
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            step_timings=step_timings,
            progress=0.0,
            current_step=current_step_id,
            triggered_by=triggered_by,
        )
        engine_run_service.create_engine_run(session, payload)
        raise


def get_step_schema(
    session: Session,
    manager: ProcessManager,
    target_step_id: str,
    analysis_id: str,
    analysis_pipeline: dict,
    timeout: int | None = None,
    tab_id: str | None = None,
):
    """Get the output schema of a pipeline step without returning data."""
    from modules.compute.schemas import StepSchemaResponse

    if timeout is None:
        timeout = settings.job_timeout

    resolved = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id)
    datasource_id = resolved['datasource_id']
    steps = resolved['steps']
    target_step_id = resolved['target_step_id']
    datasource_config = resolved['datasource_config']
    analysis_id_value = resolved['analysis_id'] or analysis_id

    if not isinstance(datasource_config, dict):
        raise ValueError('Schema fetch requires datasource_config')
    if not analysis_id_value:
        raise ValueError('Schema fetch requires analysis_id')

    config: dict = datasource_config
    _preflight_datasource_for_compute(
        config,
        operation='schema',
        datasource_id=datasource_id,
    )

    steps = apply_steps(steps)

    if target_step_id == 'source':
        schema_steps = []
    else:
        step_index = find_step_index(steps, target_step_id)
        schema_steps = steps[: step_index + 1]
        schema_steps = _hydrate_udfs(session, schema_steps)

    engine = manager.get_engine(analysis_id_value) or manager.get_or_create_engine(analysis_id_value)

    additional_datasources = _get_additional_datasources(session, schema_steps, analysis_pipeline)

    # Use the new schema command that doesn't collect full data
    job_id = engine.get_schema(
        datasource_config=config,
        steps=schema_steps,
        additional_datasources=additional_datasources,
    )

    result_data = await_engine_result(engine, timeout, job_id=job_id)
    _raise_engine_failure(
        result_data,
        operation='schema',
        datasource_id=datasource_id,
        failure_prefix='Schema fetch',
    )

    data = result_data.get('data', {})
    schema = data.get('schema', {})
    return StepSchemaResponse(
        step_id=target_step_id,
        columns=list(schema.keys()),
        column_types=schema,
    )


def get_step_row_count(
    session: Session,
    manager: ProcessManager,
    target_step_id: str,
    analysis_id: str,
    analysis_pipeline: dict,
    timeout: int | None = None,
    tab_id: str | None = None,
    request_json: dict | None = None,
    triggered_by: str | None = None,
):
    """Get the row count of a pipeline step without collecting full data."""
    from modules.compute.schemas import StepRowCountResponse

    if timeout is None:
        timeout = settings.job_timeout

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()

    resolved = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id)
    datasource_id = resolved['datasource_id']
    steps = resolved['steps']
    target_step_id = resolved['target_step_id']
    datasource_config = resolved['datasource_config']
    analysis_id_value = resolved['analysis_id'] or analysis_id

    if not isinstance(datasource_config, dict):
        raise ValueError('Row count requires datasource_config')
    if not analysis_id_value:
        analysis_id_value = f'__row_count__{datasource_id}'

    config: dict = datasource_config
    _preflight_datasource_for_compute(
        config,
        operation='row_count',
        datasource_id=datasource_id,
    )
    branch = _resolve_branch_value(config)

    request_payload = _ensure_request_branch(
        request_json
        or {
            'analysis_id': analysis_id_value,
            'datasource_id': datasource_id,
            'steps': steps,
            'target_step_id': target_step_id,
            'analysis_pipeline': analysis_pipeline,
            'tab_id': tab_id,
        },
        branch,
    )

    steps = apply_steps(steps)

    if target_step_id == 'source':
        count_steps = []
    else:
        step_index = find_step_index(steps, target_step_id)
        count_steps = steps[: step_index + 1]
        count_steps = _hydrate_udfs(session, count_steps)

    engine = manager.get_engine(analysis_id_value) or manager.get_or_create_engine(analysis_id_value)

    additional_datasources = _get_additional_datasources(session, count_steps, analysis_pipeline)

    job_id = engine.get_row_count(
        datasource_config=config,
        steps=count_steps,
        additional_datasources=additional_datasources,
    )

    step_timings: dict = {}
    current_step_id: str | None = None
    query_plan: str | None = None
    try:
        result_data = await_engine_result(engine, timeout, job_id=job_id)
        step_timings = result_data.get('step_timings', {}) if isinstance(result_data, dict) else {}
        query_plan = result_data.get('query_plan') if isinstance(result_data, dict) else None
        _raise_engine_failure(
            result_data,
            operation='row_count',
            datasource_id=datasource_id,
            failure_prefix='Row count',
        )

        data = result_data.get('data', {})
        row_count = data.get('row_count', 0)

        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=analysis_id_value,
            datasource_id=datasource_id,
            kind='row_count',
            status=ComputeRunStatus.SUCCESS,
            request_json=request_payload,
            result_json={'row_count': row_count},
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            step_timings=step_timings,
            query_plan=query_plan,
            progress=1.0,
            current_step=current_step_id,
            triggered_by=triggered_by,
        )
        engine_run_service.create_engine_run(session, payload)

        return StepRowCountResponse(step_id=target_step_id, row_count=row_count)
    except Exception as exc:
        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=analysis_id_value,
            datasource_id=datasource_id,
            kind='row_count',
            status=ComputeRunStatus.FAILED,
            request_json=request_payload,
            error_message=str(exc),
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            step_timings=step_timings,
            progress=0.0,
            current_step=current_step_id,
            triggered_by=triggered_by,
        )
        engine_run_service.create_engine_run(session, payload)
        raise


def export_data(
    session: Session,
    manager: ProcessManager,
    target_step_id: str,
    analysis_pipeline: dict,
    filename: str = 'export',
    iceberg_options: dict | None = None,
    timeout: int | None = None,
    analysis_id: str | None = None,
    tab_id: str | None = None,
    request_json: dict | None = None,
    triggered_by: str | None = None,
    result_id: str | None = None,
    build_mode: str = 'full',
    job_started: Callable[[dict[str, object]], None] | None = None,
) -> ExportDatasourceResult:
    if result_id is None:
        raise ValueError('Output exports require result_id')
    if not iceberg_options or not isinstance(iceberg_options.get('branch'), str):
        raise ValueError('Iceberg exports require iceberg_options with an explicit branch')
    if timeout is None:
        timeout = settings.job_timeout

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()

    resolved = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id)
    datasource_id = resolved['datasource_id']
    steps = resolved['steps']
    target_step_id = resolved['target_step_id']
    datasource_config = resolved['datasource_config']
    analysis_id_value = resolved['analysis_id'] or analysis_id

    if not isinstance(datasource_config, dict):
        raise ValueError('Export requires datasource_config')
    _preflight_datasource_for_compute(
        datasource_config,
        operation='export',
        datasource_id=datasource_id,
    )

    branch = _resolve_branch_value(datasource_config)
    existing_output_ds = session.get(DataSource, result_id)
    run_kind = _result_kind(existing_output_ds)

    request_payload = _ensure_request_branch(
        request_json
        or {
            'analysis_id': analysis_id_value,
            'datasource_id': datasource_id,
            'steps': steps,
            'target_step_id': target_step_id,
            'format': 'parquet',
            'filename': filename,
            'destination': 'datasource',
            'iceberg_options': iceberg_options,
            'analysis_pipeline': analysis_pipeline,
            'tab_id': tab_id,
            'build_mode': build_mode,
        },
        branch,
    )

    steps = apply_steps(steps)

    if target_step_id == 'source':
        export_steps = []
    else:
        step_index = find_step_index(steps, target_step_id)
        export_steps = steps[: step_index + 1]
    export_steps = _hydrate_udfs(session, export_steps)

    temp_engine = False
    temp_engine_id = f'{datasource_id}_export'
    if analysis_id_value:
        engine = manager.get_engine(analysis_id_value) or manager.get_or_create_engine(analysis_id_value)
    else:
        engine = manager.get_or_create_engine(temp_engine_id)
        temp_engine = True

    additional_datasources = _get_additional_datasources(session, export_steps, analysis_pipeline)

    tmp_output = tempfile.mktemp(suffix='.parquet')
    step_timings: dict = {}
    query_plan: str | None = None

    try:
        job_id = engine.export(
            datasource_config=datasource_config,
            steps=export_steps,
            output_path=tmp_output,
            export_format='parquet',
            additional_datasources=additional_datasources,
        )
        if job_started is not None:
            job_started(
                {
                    'job_id': job_id,
                    'engine': engine,
                    'steps': export_steps,
                    'tab_id': tab_id,
                }
            )

        result_data = await_engine_result(engine, timeout, job_id=job_id)
        step_timings = result_data.get('step_timings', {}) if isinstance(result_data, dict) else {}
        query_plan = result_data.get('query_plan') if isinstance(result_data, dict) else None
        _raise_engine_failure(
            result_data,
            operation='export',
            datasource_id=datasource_id,
            failure_prefix='Export',
        )

        data = result_data.get('data', {})
        row_count = data.get('row_count', 0)
        logger.info(f'Export completed: {row_count} rows written to parquet')

        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)

        result_meta = _build_export_result_metadata(
            data=data,
            file_size_bytes=os.path.getsize(tmp_output),
        )

        hc_datasource_id = str(result_id)
        db_result = session.execute(
            select(HealthCheck).where(col(HealthCheck.datasource_id) == hc_datasource_id),  # type: ignore[arg-type]
        )
        hc_checks = [c for c in db_result.scalars().all() if c.enabled]
        hc_results: list[HealthCheckResult] = []
        logger.info(f'Health checks: found {len(hc_checks)} enabled for datasource {hc_datasource_id}')
        if hc_checks:
            hc_lf = _load_healthcheck_lazy(tmp_output, 'parquet')
            if hc_lf is None:
                raise ValueError('Unsupported healthcheck export format: parquet')
            try:
                hc_results = healthcheck_service.run_healthchecks(session, hc_checks, hc_lf)
            except Exception as exc:
                if any(check.critical for check in hc_checks):
                    raise PipelineExecutionError(
                        'Critical health checks failed to run',
                        details={'datasource_id': hc_datasource_id, 'error': str(exc)},
                    ) from exc
                logger.exception('Health check evaluation failed')
            else:
                critical_ids = {check.id for check in hc_checks if check.critical}
                critical_failed = [result for result in hc_results if not result.passed and result.healthcheck_id in critical_ids]
                if critical_failed:
                    raise PipelineExecutionError(
                        'Critical health checks failed',
                        details={
                            'datasource_id': hc_datasource_id,
                            'failed': [
                                {
                                    'healthcheck_id': result.healthcheck_id,
                                    'message': result.message,
                                }
                                for result in critical_failed
                            ],
                        },
                    )
                failed_count = sum(1 for r in hc_results if not r.passed)
                logger.info(f'Health checks: {len(hc_results)} evaluated, {failed_count} failed')

        status, hc_summary, hc_details = _resolve_build_status(hc_results, hc_checks)

        analysis_obj = session.get(Analysis, analysis_id_value) if analysis_id_value else None
        analysis_name = analysis_obj.name if analysis_obj else ''

        output_notification = datasource_config.get('notification')
        excluded = datasource_config.get('excluded_recipients')
        if output_notification and excluded is not None:
            output_notification = {**output_notification, 'excluded_recipients': excluded}

        _send_pipeline_notifications(
            steps=apply_steps(export_steps),
            context={
                'analysis_name': analysis_name,
                'status': status,
                'duration_ms': str(duration_ms),
                'row_count': str(row_count),
                'datasource_id': hc_datasource_id,
                'format': 'parquet',
                'destination': 'datasource',
                'healthcheck_summary': hc_summary,
                'healthcheck_details': hc_details,
            },
            output_notification=output_notification,
        )

        namespace = iceberg_options.get('namespace', 'outputs')
        branch_name = iceberg_options['branch']
        safe_branch = re.sub(r'[^a-zA-Z0-9_]+', '_', branch_name).strip('_')
        table_name = f'{result_id}_{safe_branch}'
        export_base = namespace_paths().exports_dir / str(result_id)
        table_path = export_base / branch_name
        warehouse_path = namespace_paths().exports_dir
        catalog_path = export_base / 'catalog.db'

        export_base.mkdir(parents=True, exist_ok=True)
        table_path.mkdir(parents=True, exist_ok=True)
        warehouse_path.mkdir(parents=True, exist_ok=True)
        if not catalog_path.exists():
            catalog_path.touch()

        catalog_config = {
            'type': 'sql',
            'uri': f'sqlite:///{catalog_path}',
            'warehouse': f'file://{warehouse_path}',
        }

        catalog = load_catalog('local', **catalog_config)
        catalog.create_namespace_if_not_exists(namespace)

        identifier = f'{namespace}.{table_name}'

        arrow_table = pl.read_parquet(tmp_output).to_arrow()
        if build_mode == 'recreate' and catalog.table_exists(identifier):
            catalog.drop_table(identifier)

        if catalog.table_exists(identifier):
            iceberg_table = catalog.load_table(identifier)
            if build_mode == 'incremental':
                iceberg_table.append(arrow_table)
            else:
                _sync_iceberg_schema(iceberg_table, arrow_table.schema)
                iceberg_table.overwrite(arrow_table)
        else:
            iceberg_table = catalog.create_table(identifier, schema=arrow_table.schema, location=str(table_path))
            iceberg_table.append(arrow_table)

        snapshot_id = None
        snapshot_timestamp_ms = None
        current_snapshot = iceberg_table.current_snapshot()
        if current_snapshot:
            snapshot_id = str(current_snapshot.snapshot_id)
            snapshot_timestamp_ms = int(current_snapshot.timestamp_ms)

        datasource_name = iceberg_options.get('table_name', 'exported_data')
        iceberg_ds_config = {
            'catalog_type': 'sql',
            'catalog_uri': f'sqlite:///{catalog_path}',
            'warehouse': f'file://{warehouse_path}',
            'namespace': namespace,
            'table': table_name,
            'table_name': datasource_name,
            'metadata_path': str(export_base),
            'branch': branch_name,
            'namespace_name': get_namespace(),
        }
        if tab_id:
            iceberg_ds_config['analysis_tab_id'] = str(tab_id)
        iceberg_ds_config = _set_snapshot_metadata(iceberg_ds_config, snapshot_id, snapshot_timestamp_ms)
        output_hidden = existing_output_ds.is_hidden if existing_output_ds else True
        schema_cache = data.get('schema', {})
        target_ds = _upsert_output_datasource(
            session=session,
            result_id=result_id,
            name=datasource_name,
            source_type=DataSourceType.ICEBERG,
            config=iceberg_ds_config,
            schema_cache=schema_cache,
            analysis_id=analysis_id_value,
            is_hidden=output_hidden,
            keep_schema_cache=build_mode == 'incremental',
        )
        ds_id = target_ds.id
        result_meta['datasource_id'] = ds_id
        result_meta['datasource_name'] = datasource_name
        if snapshot_id:
            result_meta['snapshot_id'] = snapshot_id
        if snapshot_timestamp_ms is not None:
            result_meta['snapshot_timestamp_ms'] = snapshot_timestamp_ms
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=analysis_id_value,
            datasource_id=ds_id,
            kind=run_kind,
            status=ComputeRunStatus.SUCCESS,
            request_json=request_payload,
            result_json=result_meta,
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            step_timings=step_timings,
            query_plan=query_plan,
            progress=1.0,
            triggered_by=triggered_by,
        )
        engine_run_service.create_engine_run(session, payload)

        return ExportDatasourceResult(datasource_id=ds_id, datasource_name=datasource_name, result_meta=result_meta)
    except Exception as exc:
        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=analysis_id_value,
            datasource_id=datasource_id,
            kind=run_kind,
            status=ComputeRunStatus.FAILED,
            request_json=request_payload,
            error_message=str(exc),
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            step_timings=step_timings,
            query_plan=query_plan,
            progress=0.0,
            triggered_by=triggered_by,
        )
        engine_run_service.create_engine_run(session, payload)
        raise
    finally:
        if temp_engine:
            manager.shutdown_engine(temp_engine_id)
        if os.path.exists(tmp_output):
            os.unlink(tmp_output)


def download_step(
    session: Session,
    manager: ProcessManager,
    target_step_id: str,
    analysis_pipeline: dict,
    export_format: str = 'csv',
    filename: str = 'download',
    timeout: int | None = None,
    analysis_id: str | None = None,
    tab_id: str | None = None,
):
    """Download the result of a pipeline step in a specific format."""
    from modules.compute.core.exports import get_export_format

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()

    if timeout is None:
        timeout = settings.job_timeout

    resolved = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id)
    datasource_id = resolved['datasource_id']
    steps = resolved['steps']
    target_step_id = resolved['target_step_id']
    datasource_config = resolved['datasource_config']
    analysis_id_value = resolved['analysis_id'] or analysis_id

    if not isinstance(datasource_config, dict):
        raise ValueError('Download requires datasource_config')
    _preflight_datasource_for_compute(
        datasource_config,
        operation='download',
        datasource_id=datasource_id,
    )

    if not analysis_id_value:
        analysis_id_value = f'__download__{datasource_id}'

    download_steps = [step for step in steps if step.get('type') != 'download']
    target_step = next((step for step in steps if step.get('id') == target_step_id), None)
    if target_step and target_step.get('type') == 'download':
        depends_on = target_step.get('depends_on') or []
        parent_id = str(depends_on[0]) if depends_on and depends_on[0] else None
        if parent_id:
            target_step_id = parent_id
        elif download_steps:
            target_step_id = str(download_steps[-1].get('id') or 'source')
        else:
            target_step_id = 'source'

    steps = apply_steps(download_steps)

    if target_step_id == 'source':
        download_steps = []
    else:
        step_index = find_step_index(steps, target_step_id)
        download_steps = steps[: step_index + 1]
        download_steps = _hydrate_udfs(session, download_steps)

    engine = manager.get_or_create_engine(analysis_id_value)
    branch = _resolve_branch_value(datasource_config)
    request_payload = _ensure_request_branch(
        {
            'analysis_id': analysis_id_value,
            'datasource_id': datasource_id,
            'steps': download_steps,
            'target_step_id': target_step_id,
            'format': export_format,
            'filename': filename,
            'tab_id': tab_id,
            'analysis_pipeline': analysis_pipeline,
        },
        branch,
    )

    additional_datasources = _get_additional_datasources(session, download_steps, analysis_pipeline)

    export_fmt = get_export_format(export_format)
    ext = export_fmt.extension
    content_type = export_fmt.content_type

    tmp_output = tempfile.mktemp(suffix=ext)

    step_timings: dict = {}
    query_plan: str | None = None
    try:
        job_id = engine.preview(
            datasource_config=datasource_config,
            steps=download_steps,
            row_limit=10_000_000,  # Large limit to get all data for download
            offset=0,
            additional_datasources=additional_datasources,
        )

        result_data = await_engine_result(engine, timeout, job_id=job_id)
        step_timings = result_data.get('step_timings', {}) if isinstance(result_data, dict) else {}
        query_plan = result_data.get('query_plan') if isinstance(result_data, dict) else None
        _raise_engine_failure(
            result_data,
            operation='download',
            datasource_id=datasource_id,
            failure_prefix='Download',
        )

        data = result_data.get('data', {})
        df_data = data.get('data', [])
        schema = data.get('schema', {})

        if not schema:
            raise ValueError('No data to download')

        from modules.compute.operations.fill_null import get_polars_type

        schema_types = {name: get_polars_type(dtype) or pl.Utf8() for name, dtype in schema.items()}
        df = pl.DataFrame(df_data, schema=schema_types)
        export_fmt.writer(df, tmp_output)

        with open(tmp_output, 'rb') as f:
            file_bytes = f.read()

        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=analysis_id_value,
            datasource_id=datasource_id,
            kind='download',
            status=ComputeRunStatus.SUCCESS,
            request_json=request_payload,
            result_json={'filename': f'{filename}{ext}', 'format': export_format},
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            step_timings=step_timings,
            query_plan=query_plan,
            progress=1.0,
        )
        engine_run_service.create_engine_run(session, payload)

        return file_bytes, f'{filename}{ext}', content_type
    except Exception as exc:
        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=analysis_id_value,
            datasource_id=datasource_id,
            kind='download',
            status=ComputeRunStatus.FAILED,
            request_json=request_payload,
            error_message=str(exc),
            created_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            step_timings=step_timings,
            query_plan=query_plan,
            progress=0.0,
        )
        engine_run_service.create_engine_run(session, payload)
        raise
    finally:
        if os.path.exists(tmp_output):
            os.remove(tmp_output)


def _resolve_upstream_tabs(tabs: list[dict], target_tab_id: str) -> set[str]:
    """Find all tab IDs that the target tab depends on via lazyframe inputs (including itself)."""
    output_to_tab: dict[str, str] = {}
    tab_input: dict[str, str] = {}

    for tab in tabs:
        tid = tab.get('id')
        output = tab.get('output') if isinstance(tab, dict) else None
        output_id = output.get('result_id') if isinstance(output, dict) else None
        datasource = tab.get('datasource') if isinstance(tab, dict) else None
        input_id = datasource.get('id') if isinstance(datasource, dict) else None
        if tid and output_id:
            output_to_tab[str(output_id)] = str(tid)
        if tid and input_id:
            tab_input[str(tid)] = str(input_id)

    required: set[str] = set()
    queue: deque[str] = deque([target_tab_id])
    while queue:
        current = queue.popleft()
        if current in required:
            continue
        required.add(current)
        input_ds = tab_input.get(current)
        if input_ds and input_ds in output_to_tab:
            upstream = output_to_tab[input_ds]
            if upstream not in required:
                queue.append(upstream)

    return required


def _build_execution_tabs(pipeline: dict) -> tuple[list[dict], str | None]:
    tabs = pipeline.get('tabs', [])
    if not isinstance(tabs, list) or not tabs:
        raise ValueError('analysis_pipeline missing tabs')

    selected_tab_id = pipeline.get('tab_id')
    required_tabs: set[str] | None = None
    if selected_tab_id:
        required_tabs = _resolve_upstream_tabs(tabs, str(selected_tab_id))

    execution_tabs: list[dict] = []
    for tab in tabs:
        if required_tabs and tab.get('id') not in required_tabs:
            continue
        execution_tabs.append(tab)
    return execution_tabs, str(selected_tab_id) if selected_tab_id is not None else None


def _count_total_build_steps(tabs: list[dict], selected_tab_id: str | None) -> int:
    total = 0
    for tab in tabs:
        output_config = tab.get('output') if isinstance(tab, dict) else None
        steps = tab.get('steps', []) if isinstance(tab, dict) else []
        if not isinstance(steps, list):
            continue
        if not isinstance(output_config, dict) or 'filename' not in output_config:
            if selected_tab_id and str(tab.get('id')) != selected_tab_id:
                continue
            total += max(len(steps), 1)
            continue
        total += max(len(steps), 1)
    return total


async def _stream_engine_events(
    *,
    engine,
    job_id: str,
    build_step_base: int,
    total_steps: int,
    started_perf: float,
    tab_id: str | None,
    tab_name: str | None,
    emitter: BuildEmitter | None,
) -> None:
    completed_steps = build_step_base
    draining = False
    drain_deadline: float | None = None
    while True:
        poll_timeout = 0.2 if not draining else 0.05
        event = await asyncio.to_thread(engine.get_progress_event, poll_timeout, job_id)
        if event is None:
            if draining:
                if drain_deadline is None:
                    drain_deadline = time.monotonic() + 0.5
                if time.monotonic() >= drain_deadline:
                    return
                continue
            if engine.current_job_id != job_id:
                draining = True
                drain_deadline = time.monotonic() + 0.5
                continue
            continue

        payload = dict(event.event)
        emitted_type = str(payload.get('type') or '')
        step_index = payload.get('step_index')
        if isinstance(step_index, int):
            payload['build_step_index'] = build_step_base + step_index
        payload['tab_id'] = tab_id
        payload['tab_name'] = tab_name
        await _emit_build_event(emitter, payload)

        if emitted_type == 'step_complete':
            completed_steps += 1
            step_name = payload.get('step_name') if isinstance(payload.get('step_name'), str) else None
            step_index_value = payload.get('build_step_index') if isinstance(payload.get('build_step_index'), int) else None
            elapsed_ms = int((time.perf_counter() - started_perf) * 1000)
            await _emit_progress(
                emitter,
                progress=(completed_steps / total_steps) if total_steps else 1.0,
                elapsed_ms=elapsed_ms,
                completed_steps=completed_steps,
                total_steps=total_steps,
                current_step=step_name,
                current_step_index=step_index_value,
                tab_id=tab_id,
                tab_name=tab_name,
            )
        if emitted_type == 'step_failed':
            elapsed_ms = int((time.perf_counter() - started_perf) * 1000)
            step_name = payload.get('step_name') if isinstance(payload.get('step_name'), str) else None
            step_index_value = payload.get('build_step_index') if isinstance(payload.get('build_step_index'), int) else None
            await _emit_progress(
                emitter,
                progress=(completed_steps / total_steps) if total_steps else 0.0,
                elapsed_ms=elapsed_ms,
                completed_steps=completed_steps,
                total_steps=total_steps,
                current_step=step_name,
                current_step_index=step_index_value,
                tab_id=tab_id,
                tab_name=tab_name,
            )
            return


async def _stream_resource_events(
    *,
    engine,
    emitter: BuildEmitter | None,
    tab_id: str | None,
    tab_name: str | None,
) -> None:
    async for resource in monitor_engine_resources(engine):
        await _emit_build_event(
            emitter,
            {
                'type': 'resources',
                'tab_id': tab_id,
                'tab_name': tab_name,
                **resource,
            },
        )


def _schedule_stream_tasks(
    loop: asyncio.AbstractEventLoop,
    *,
    engine,
    job_id: str,
    build_step_base: int,
    total_steps: int,
    started_perf: float,
    tab_id: str | None,
    tab_name: str | None,
    emitter: BuildEmitter | None,
) -> tuple[asyncio.Task, asyncio.Task]:
    progress_task = loop.create_task(
        _stream_engine_events(
            engine=engine,
            job_id=job_id,
            build_step_base=build_step_base,
            total_steps=total_steps,
            started_perf=started_perf,
            tab_id=tab_id,
            tab_name=tab_name,
            emitter=emitter,
        )
    )
    resource_task = loop.create_task(
        _stream_resource_events(
            engine=engine,
            emitter=emitter,
            tab_id=tab_id,
            tab_name=tab_name,
        )
    )
    return progress_task, resource_task


def _start_stream_tasks(
    loop: asyncio.AbstractEventLoop,
    *,
    engine,
    job_id: str,
    build_step_base: int,
    total_steps: int,
    started_perf: float,
    tab_id: str | None,
    tab_name: str | None,
    emitter: BuildEmitter | None,
    build: ActiveBuild,
) -> tuple[asyncio.Task | None, asyncio.Task | None]:
    build.resource_config = compute_schemas.BuildResourceConfigSummary.model_validate(_resource_summary(engine))
    if loop.is_closed() or not loop.is_running():
        logger.warning('Skipping build stream tasks for job %s because the event loop is unavailable', job_id)
        return None, None

    future: concurrent.futures.Future[tuple[asyncio.Task, asyncio.Task]] = concurrent.futures.Future()

    def assign() -> None:
        try:
            future.set_result(
                _schedule_stream_tasks(
                    loop,
                    engine=engine,
                    job_id=job_id,
                    build_step_base=build_step_base,
                    total_steps=total_steps,
                    started_perf=started_perf,
                    tab_id=tab_id,
                    tab_name=tab_name,
                    emitter=emitter,
                )
            )
        except Exception as exc:
            future.set_exception(exc)

    try:
        loop.call_soon_threadsafe(assign)
    except RuntimeError as exc:
        logger.warning('Skipping build stream tasks for job %s because the event loop rejected scheduling: %s', job_id, exc)
        return None, None

    try:
        return future.result(timeout=5)
    except (concurrent.futures.TimeoutError, RuntimeError) as exc:
        logger.warning('Skipping build stream tasks for job %s because scheduling did not complete: %s', job_id, exc)
        return None, None


async def _stop_stream_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def run_analysis_build_from_payload(session: Session, manager: ProcessManager, pipeline: dict | None) -> dict:
    if not isinstance(pipeline, dict):
        raise ValueError('analysis_pipeline is required')

    tabs = pipeline.get('tabs', [])
    if not isinstance(tabs, list) or not tabs:
        raise ValueError('analysis_pipeline missing tabs')

    analysis_id = pipeline.get('analysis_id')
    analysis_id = str(analysis_id) if analysis_id is not None else None

    results: list[dict] = []
    tabs_built = 0
    selected_tab_id = pipeline.get('tab_id')
    required_tabs: set[str] | None = None
    if selected_tab_id:
        required_tabs = _resolve_upstream_tabs(tabs, str(selected_tab_id))

    for tab in tabs:
        if required_tabs and tab.get('id') not in required_tabs:
            continue
        tab_id = tab.get('id', 'unknown')
        tab_name = tab.get('name', 'unnamed')
        datasource = tab.get('datasource') if isinstance(tab, dict) else None
        tab_datasource_id = datasource.get('id') if isinstance(datasource, dict) else None
        steps = tab.get('steps', [])

        if not tab_datasource_id:
            continue

        output_config = tab.get('output') if isinstance(tab, dict) else None
        if not isinstance(output_config, dict) or 'filename' not in output_config:
            output_config = None

        target_step_id = steps[-1].get('id', 'source') if steps else 'source'

        try:
            if output_config is not None:
                filename = output_config.get('filename', f'{tab_name}_out')

                iceberg_cfg = output_config.get('iceberg')
                iceberg_options = (
                    {
                        'table_name': iceberg_cfg.get('table_name', 'exported_data'),
                        'namespace': iceberg_cfg.get('namespace', 'outputs'),
                        'branch': iceberg_cfg.get('branch', 'master'),
                    }
                    if isinstance(iceberg_cfg, dict)
                    else None
                )

                tab_build_mode = output_config.get('build_mode', 'full')

                export_data(
                    session=session,
                    manager=manager,
                    target_step_id=target_step_id,
                    analysis_pipeline=pipeline,
                    filename=filename,
                    iceberg_options=iceberg_options,
                    analysis_id=analysis_id,
                    tab_id=str(tab_id) if tab_id else None,
                    result_id=output_config.get('result_id'),
                    build_mode=tab_build_mode,
                )
            else:
                if required_tabs and str(tab_id) != str(selected_tab_id):
                    tabs_built += 1
                    results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': BuildTabStatus.SUCCESS})
                    continue
                raise ValueError(f'Tab {tab_id} missing output configuration')

            tabs_built += 1
            results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': BuildTabStatus.SUCCESS})
        except Exception as e:
            results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': BuildTabStatus.FAILED, 'error': str(e)})

    return {'analysis_id': analysis_id or '', 'tabs_built': tabs_built, 'results': results}


async def run_analysis_build_stream(
    session: Session,
    manager: ProcessManager,
    pipeline: dict | None,
    *,
    build: ActiveBuild,
    emitter: BuildEmitter | None,
    triggered_by: str | None = None,
) -> dict:
    if not isinstance(pipeline, dict):
        raise ValueError('analysis_pipeline is required')

    execution_tabs, selected_tab_id = _build_execution_tabs(pipeline)
    analysis_id = pipeline.get('analysis_id')
    analysis_id_value = str(analysis_id) if analysis_id is not None else ''
    total_steps = _count_total_build_steps(execution_tabs, selected_tab_id)
    build.total_steps = total_steps
    build.total_tabs = len(execution_tabs)
    started_perf = time.perf_counter()

    await _emit_build_event(
        emitter,
        {
            'type': 'log',
            'level': compute_schemas.BuildLogLevel.INFO.value,
            'message': f'Starting build for {build.analysis_name}',
        },
    )
    await _emit_progress(
        emitter,
        progress=0.0,
        elapsed_ms=0,
        completed_steps=0,
        total_steps=total_steps,
        current_step=None,
        current_step_index=None,
        tab_id=None,
        tab_name=None,
    )

    results: list[dict] = []
    tabs_built = 0
    build_step_base = 0
    has_failures = False
    loop = asyncio.get_running_loop()

    for tab in execution_tabs:
        tab_id = str(tab.get('id', 'unknown'))
        tab_name = str(tab.get('name', 'unnamed'))
        datasource = tab.get('datasource') if isinstance(tab, dict) else None
        tab_datasource_id = datasource.get('id') if isinstance(datasource, dict) else None
        steps = tab.get('steps', []) if isinstance(tab, dict) else []
        output_config = tab.get('output') if isinstance(tab, dict) else None

        if not tab_datasource_id:
            continue

        if not isinstance(steps, list):
            steps = []

        target_step_id = steps[-1].get('id', 'source') if steps else 'source'
        step_count = max(len(steps), 1)
        build.current_tab_id = tab_id
        build.current_tab_name = tab_name

        if not isinstance(output_config, dict) or 'filename' not in output_config:
            if selected_tab_id and tab_id != selected_tab_id:
                tabs_built += 1
                results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': BuildTabStatus.SUCCESS})
                build_step_base += step_count
                continue
            error = f'Tab {tab_id} missing output configuration'
            has_failures = True
            results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': BuildTabStatus.FAILED, 'error': error})
            await _emit_build_event(
                emitter,
                {
                    'type': 'log',
                    'level': compute_schemas.BuildLogLevel.ERROR.value,
                    'message': error,
                    'tab_id': tab_id,
                    'tab_name': tab_name,
                },
            )
            build_step_base += step_count
            continue

        filename = output_config.get('filename', f'{tab_name}_out')
        result_id = output_config.get('result_id') if isinstance(output_config.get('result_id'), str) else None
        iceberg_cfg = output_config.get('iceberg')
        iceberg_options = (
            {
                'table_name': iceberg_cfg.get('table_name', 'exported_data'),
                'namespace': iceberg_cfg.get('namespace', 'outputs'),
                'branch': iceberg_cfg.get('branch', 'master'),
            }
            if isinstance(iceberg_cfg, dict)
            else None
        )
        tab_build_mode = output_config.get('build_mode', 'full')

        progress_task: asyncio.Task | None = None
        resource_task: asyncio.Task | None = None
        source_step_started_at: float | None = None

        try:
            await _emit_build_event(
                emitter,
                {
                    'type': 'log',
                    'level': compute_schemas.BuildLogLevel.INFO.value,
                    'message': f'Starting tab {tab_name}',
                    'tab_id': tab_id,
                    'tab_name': tab_name,
                },
            )
            if not steps:
                source_step_started_at = time.perf_counter()
                await _emit_build_event(
                    emitter,
                    {
                        'type': 'step_start',
                        'build_step_index': build_step_base,
                        'step_index': 0,
                        'step_id': 'source',
                        'step_name': 'Source',
                        'step_type': 'source',
                        'total_steps': total_steps,
                        'tab_id': tab_id,
                        'tab_name': tab_name,
                    },
                )

            def handle_job_started(
                info: dict[str, object],
                *,
                current_build_step_base: int = build_step_base,
                current_tab_id: str = tab_id,
                current_tab_name: str = tab_name,
            ) -> None:
                nonlocal progress_task, resource_task
                job_id = info.get('job_id')
                engine = info.get('engine')
                if not isinstance(job_id, str) or engine is None:
                    return
                next_progress_task, next_resource_task = _start_stream_tasks(
                    loop,
                    engine=engine,
                    job_id=job_id,
                    build_step_base=current_build_step_base,
                    total_steps=total_steps,
                    started_perf=started_perf,
                    tab_id=current_tab_id,
                    tab_name=current_tab_name,
                    emitter=emitter,
                    build=build,
                )
                progress_task = next_progress_task
                resource_task = next_resource_task

            def run_export_job(
                *,
                current_target_step_id: str = target_step_id,
                current_filename: str = filename,
                current_iceberg_options: dict | None = iceberg_options,
                current_tab_id: str = tab_id,
                current_result_id: str | None = result_id,
                current_build_mode: str = tab_build_mode,
            ) -> None:
                session_gen = get_db()
                thread_session = next(session_gen)
                try:
                    export_data(
                        session=thread_session,
                        manager=manager,
                        target_step_id=current_target_step_id,
                        analysis_pipeline=pipeline,
                        filename=current_filename,
                        iceberg_options=current_iceberg_options,
                        analysis_id=analysis_id_value,
                        tab_id=current_tab_id,
                        triggered_by=triggered_by,
                        result_id=current_result_id,
                        build_mode=current_build_mode,
                        job_started=handle_job_started,
                    )
                finally:
                    thread_session.close()
                    session_gen.close()

            await asyncio.to_thread(run_export_job)

            if progress_task is not None:
                await progress_task
            await _stop_stream_task(resource_task)
            if not steps:
                duration_ms = int((time.perf_counter() - (source_step_started_at or started_perf)) * 1000)
                await _emit_build_event(
                    emitter,
                    {
                        'type': 'step_complete',
                        'build_step_index': build_step_base,
                        'step_index': 0,
                        'step_id': 'source',
                        'step_name': 'Source',
                        'step_type': 'source',
                        'duration_ms': duration_ms,
                        'row_count': None,
                        'total_steps': total_steps,
                        'tab_id': tab_id,
                        'tab_name': tab_name,
                    },
                )
                elapsed_ms = int((time.perf_counter() - started_perf) * 1000)
                await _emit_progress(
                    emitter,
                    progress=((build_step_base + 1) / total_steps) if total_steps else 1.0,
                    elapsed_ms=elapsed_ms,
                    completed_steps=build_step_base + 1,
                    total_steps=total_steps,
                    current_step='Source',
                    current_step_index=build_step_base,
                    tab_id=tab_id,
                    tab_name=tab_name,
                )

            tabs_built += 1
            build_step_base += step_count
            results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': BuildTabStatus.SUCCESS})
        except Exception as exc:
            has_failures = True
            if progress_task is not None:
                with contextlib.suppress(Exception):
                    await progress_task
            await _stop_stream_task(resource_task)
            results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': BuildTabStatus.FAILED, 'error': str(exc)})
            elapsed_ms = int((time.perf_counter() - started_perf) * 1000)
            if not steps:
                await _emit_build_event(
                    emitter,
                    {
                        'type': 'step_failed',
                        'build_step_index': build_step_base,
                        'step_index': 0,
                        'step_id': 'source',
                        'step_name': 'Source',
                        'step_type': 'source',
                        'error': str(exc),
                        'total_steps': total_steps,
                        'tab_id': tab_id,
                        'tab_name': tab_name,
                    },
                )
            await _emit_build_event(
                emitter,
                {
                    'type': 'log',
                    'level': compute_schemas.BuildLogLevel.ERROR.value,
                    'message': str(exc),
                    'tab_id': tab_id,
                    'tab_name': tab_name,
                },
            )
            build_step_base += step_count
            continue

    elapsed_ms = int((time.perf_counter() - started_perf) * 1000)
    if has_failures:
        await _emit_build_event(
            emitter,
            {
                'type': 'failed',
                'progress': build.progress,
                'elapsed_ms': elapsed_ms,
                'total_steps': total_steps,
                'tabs_built': tabs_built,
                'results': results,
                'duration_ms': elapsed_ms,
                'error': 'One or more tabs failed',
            },
        )
    else:
        await _emit_build_event(
            emitter,
            {
                'type': 'complete',
                'elapsed_ms': elapsed_ms,
                'total_steps': total_steps,
                'tabs_built': tabs_built,
                'results': results,
                'duration_ms': elapsed_ms,
            },
        )
    return {'analysis_id': analysis_id_value, 'tabs_built': tabs_built, 'results': results}


def list_iceberg_snapshots(session: Session, datasource_id: str, branch: str | None = None):
    from modules.compute.schemas import IcebergSnapshotInfo, IcebergSnapshotsResponse

    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)
    if datasource.source_type != 'iceberg':
        raise ValueError('Snapshots are only available for Iceberg datasources')

    metadata_path = datasource.config.get('metadata_path')
    if not metadata_path:
        raise ValueError('Iceberg datasource missing metadata_path')
    branch_name = branch or datasource.config.get('branch')

    catalog_type = datasource.config.get('catalog_type')
    catalog_uri = datasource.config.get('catalog_uri')
    namespace = datasource.config.get('namespace')
    table_name = datasource.config.get('table')
    warehouse = datasource.config.get('warehouse')

    if catalog_type and catalog_uri and namespace and table_name:
        catalog_config = {
            'type': catalog_type,
            'uri': catalog_uri,
        }
        if warehouse:
            catalog_config['warehouse'] = warehouse
        catalog = load_catalog('local', **catalog_config)
        identifier = f'{namespace}.{table_name}'
        table = catalog.load_table(identifier)
        resolved = resolve_iceberg_metadata_path(str(table.metadata_location))
    else:
        from pyiceberg.table import StaticTable

        resolved = resolve_iceberg_branch_metadata_path(metadata_path, branch_name)
        table = StaticTable.from_metadata(resolved)

    current_snapshot = table.current_snapshot()
    current_snapshot_id = str(current_snapshot.snapshot_id) if current_snapshot else None
    snapshots = []
    for snap in table.snapshots():
        operation = str(snap.summary.operation) if snap.summary and snap.summary.operation else None
        snapshots.append(
            IcebergSnapshotInfo(
                snapshot_id=str(snap.snapshot_id),
                timestamp_ms=snap.timestamp_ms,
                parent_snapshot_id=str(snap.parent_snapshot_id) if snap.parent_snapshot_id is not None else None,
                operation=operation,
                is_current=str(snap.snapshot_id) == current_snapshot_id,
            ),
        )

    snapshots.sort(key=lambda s: s.timestamp_ms, reverse=True)

    return IcebergSnapshotsResponse(
        datasource_id=datasource_id,
        table_path=str(Path(resolved).parents[1]),
        snapshots=snapshots,
    )


def delete_iceberg_snapshot(session: Session, datasource_id: str, snapshot_id: str):
    from modules.compute.schemas import IcebergSnapshotDeleteResponse

    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)
    if datasource.source_type != 'iceberg':
        raise ValueError('Snapshots are only available for Iceberg datasources')

    try:
        snapshot_value = int(snapshot_id)
    except (TypeError, ValueError) as exc:
        raise DataSourceSnapshotError('Snapshot ID must be an integer', details={'snapshot_id': snapshot_id}) from exc

    catalog_type = datasource.config.get('catalog_type')
    catalog_uri = datasource.config.get('catalog_uri')
    namespace = datasource.config.get('namespace')
    table_name = datasource.config.get('table')
    warehouse = datasource.config.get('warehouse')
    if catalog_type and catalog_uri and namespace and table_name:
        catalog_config = {
            'type': catalog_type,
            'uri': catalog_uri,
        }
        if warehouse:
            catalog_config['warehouse'] = warehouse
        catalog = load_catalog('local', **catalog_config)
        identifier = f'{namespace}.{table_name}'
        table = catalog.load_table(identifier)
    else:
        raise DataSourceSnapshotError(
            'Snapshot deletion requires a catalog-backed Iceberg datasource',
            details={'snapshot_id': snapshot_id},
        )

    if not hasattr(table, 'maintenance'):
        raise DataSourceSnapshotError(
            'Snapshot deletion is not supported by the current Iceberg runtime',
            details={'snapshot_id': snapshot_id},
        )
    maintenance = table.maintenance
    if not hasattr(maintenance, 'expire_snapshots'):
        raise DataSourceSnapshotError(
            'Snapshot deletion is not supported by the current Iceberg runtime',
            details={'snapshot_id': snapshot_id},
        )

    try:
        current = table.current_snapshot()
        if current and current.snapshot_id == snapshot_value:
            raise DataSourceSnapshotError(
                'Cannot delete the current snapshot',
                details={'snapshot_id': snapshot_id},
            )
        available_ids = [snap.snapshot_id for snap in table.snapshots()]
        if snapshot_value not in available_ids:
            raise DataSourceSnapshotError(
                f'Snapshot with snapshot id {snapshot_value} does not exist',
                details={'snapshot_id': snapshot_id, 'available_snapshot_ids': available_ids},
            )
        maintenance.expire_snapshots().by_id(snapshot_value).commit()
    except ValueError as exc:
        raise DataSourceSnapshotError(str(exc), details={'snapshot_id': snapshot_id}) from exc
    except NotImplementedError as exc:
        raise DataSourceSnapshotError(
            'Snapshot deletion is not supported by the current Iceberg catalog',
            details={'snapshot_id': snapshot_id},
        ) from exc

    return IcebergSnapshotDeleteResponse(
        datasource_id=datasource_id,
        snapshot_id=snapshot_id,
    )
