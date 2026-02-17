import logging
import os
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import polars as pl
from pyiceberg.catalog import load_catalog
from sqlalchemy import select
from sqlmodel import Session

from core.config import settings
from core.exceptions import DataSourceNotFoundError, DataSourceSnapshotError, PipelineExecutionError
from modules.analysis.models import Analysis
from modules.compute.core.exports import get_export_format
from modules.compute.manager import get_manager
from modules.compute.operations.datasource import resolve_iceberg_metadata_path
from modules.compute.utils import apply_pipeline_steps, await_engine_result, find_step_index, resolve_applied_target
from modules.datasource.models import DataSource
from modules.engine_runs import service as engine_run_service
from modules.healthcheck import service as healthcheck_service
from modules.healthcheck.models import HealthCheck, HealthCheckResult
from modules.notification.service import notification_service, render_template
from modules.udf.models import Udf

logger = logging.getLogger(__name__)


def _resolve_build_status(
    hc_results: list[HealthCheckResult],
    checks: list[HealthCheck] | None = None,
) -> tuple[str, str | None, list[dict] | None]:
    if not hc_results:
        return 'success', None, None

    name_map: dict[str, str] = {}
    if checks:
        name_map = {c.id: c.name for c in checks}

    total = len(hc_results)
    failed = [r for r in hc_results if not r.passed]

    if not failed:
        return 'success', f'{total}/{total} passed', None

    details = [
        {
            'name': name_map.get(r.healthcheck_id, r.healthcheck_id),
            'passed': r.passed,
            'message': r.message,
        }
        for r in hc_results
    ]
    return 'warning', f'{len(failed)}/{total} failed', details


def _build_subscriber_message(context: dict[str, object]) -> str:
    status = str(context.get('status', 'unknown'))
    analysis_name = str(context.get('analysis_name', ''))
    row_count = str(context.get('row_count', ''))
    duration = str(context.get('duration_ms', ''))
    hc_summary = context.get('healthcheck_summary')
    hc_details = context.get('healthcheck_details')

    if status == 'warning':
        msg = f'Build complete: {analysis_name}\nStatus: built successfully, health checks failed'
    else:
        msg = f'Build complete: {analysis_name}\nStatus: {status}'

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
            icon = '\u2713' if detail.get('passed') else '\u2717'
            name = detail.get('name', '?')
            message = detail.get('message', '')
            lines.append(f'  {icon} {name}: {message} ')
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


def _load_healthcheck_lazy(output_path: str, export_format: str) -> pl.LazyFrame | None:
    if export_format == 'parquet':
        return pl.scan_parquet(output_path)
    if export_format == 'csv':
        return pl.scan_csv(output_path)
    if export_format == 'ndjson':
        return pl.scan_ndjson(output_path)
    if export_format == 'json':
        return pl.read_json(output_path).lazy()
    return None


def _send_pipeline_notifications(
    pipeline_steps: list[dict],
    context: dict[str, object],
    output_notification: dict | None = None,
) -> None:
    failed: list[str] = []
    method = 'email'
    recipient = ''
    subject_template = 'Build Complete'
    body_template = ''

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

    for step in pipeline_steps:
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
                msg = _build_subscriber_message(context)
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


def _upsert_output_datasource(
    session: Session,
    output_datasource_id: str | None,
    name: str,
    source_type: str,
    config: dict,
    schema_cache: dict,
    analysis_id: str | None,
    is_hidden: bool | None = None,
) -> DataSource:
    """Create or update the output datasource for an export.

    If ``output_datasource_id`` points to an existing row, update it in-place.
    Otherwise create a brand-new ``DataSource``.  Returns the DB object.
    """
    if output_datasource_id:
        existing = session.get(DataSource, output_datasource_id)
        if existing:
            existing.name = name
            existing.source_type = source_type
            existing.config = config
            existing.schema_cache = schema_cache
            existing.created_by_analysis_id = analysis_id
            existing.created_by = 'analysis'
            if is_hidden is not None:
                existing.is_hidden = is_hidden
            session.add(existing)
            session.commit()
            return existing

    new_id = str(uuid.uuid4())
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


def _get_additional_datasources(
    session: Session,
    pipeline_steps: list[dict],
    analysis_pipeline: dict,
) -> dict[str, dict]:
    """Extract and fetch additional datasources referenced in pipeline steps (e.g., for joins)."""
    pipeline_steps = apply_pipeline_steps(pipeline_steps)
    additional: dict[str, dict] = {}
    pipeline_sources: dict[str, dict] | None = None
    analysis_id: str | None = None
    sources = analysis_pipeline.get('sources')
    if isinstance(sources, dict):
        pipeline_sources = {str(key): value for key, value in sources.items() if isinstance(value, dict)}
    pipeline_id = analysis_pipeline.get('analysis_id')
    if pipeline_id is not None:
        analysis_id = str(pipeline_id)

    for step in pipeline_steps:
        config = step.get('config', {})
        right_source_id = config.get('right_source') or config.get('rightDataSource')

        union_sources = config.get('sources', [])
        if isinstance(union_sources, str):
            union_sources = [union_sources]

        source_ids: list[str] = []
        if right_source_id:
            source_ids.append(str(right_source_id))
        for source_id in union_sources:
            if source_id is None:
                continue
            source_ids.append(str(source_id))

        for source_id in source_ids:
            if source_id in additional:
                continue
            config_override = None
            if pipeline_sources and source_id in pipeline_sources:
                config_override = pipeline_sources[source_id]
            if config_override is None:
                datasource = session.get(DataSource, source_id)
                if datasource:
                    config_override = {
                        'source_type': datasource.source_type,
                        **datasource.config,
                    }
            if config_override is None:
                continue
            if analysis_id and config_override.get('source_type') == 'analysis' and str(config_override.get('analysis_id')) == analysis_id:
                config_override = {**config_override, 'analysis_pipeline': analysis_pipeline}
            additional[source_id] = config_override

    return additional


def _hydrate_udfs(session: Session, pipeline_steps: list[dict]) -> list[dict]:
    next_steps: list[dict] = []
    for step in pipeline_steps:
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


def _resolve_pipeline_request(pipeline: dict, tab_id: str | None, target_step_id: str) -> dict:
    tabs = pipeline.get('tabs', [])
    if not isinstance(tabs, list) or not tabs:
        raise ValueError('analysis_pipeline missing tabs')

    selected = None
    if tab_id:
        selected = next((tab for tab in tabs if tab.get('id') == tab_id), None)
    if not selected:
        selected = next((tab for tab in tabs if tab.get('steps')), None)
    if not selected:
        selected = tabs[0]

    datasource_id = selected.get('datasource_id')
    if not datasource_id:
        raise ValueError('analysis_pipeline tab missing datasource_id')

    steps = selected.get('steps', [])
    if not isinstance(steps, list):
        raise ValueError('analysis_pipeline tab steps must be a list')

    sources = pipeline.get('sources', {})
    if not isinstance(sources, dict) or not sources:
        raise ValueError('analysis_pipeline missing datasource configs')

    datasource_config = sources.get(str(datasource_id))
    if not isinstance(datasource_config, dict):
        raise ValueError(f'analysis_pipeline missing datasource config for {datasource_id}')

    overrides = selected.get('datasource_config') or {}
    if overrides and not isinstance(overrides, dict):
        raise ValueError('analysis_pipeline tab datasource_config must be a dict')

    merged = {**datasource_config, **overrides}
    analysis_id = pipeline.get('analysis_id')
    analysis_id = str(analysis_id) if analysis_id is not None else None
    if analysis_id and merged.get('source_type') == 'analysis' and str(merged.get('analysis_id')) == analysis_id:
        merged = {**merged, 'analysis_pipeline': pipeline}

    resolved_target = resolve_applied_target(steps, target_step_id)

    return {
        'analysis_id': analysis_id,
        'datasource_id': str(datasource_id),
        'pipeline_steps': steps,
        'target_step_id': resolved_target,
        'datasource_config': merged,
    }


def build_analysis_pipeline_payload(session: Session, analysis: Analysis, datasource_id: str | None = None) -> dict:
    pipeline = analysis.pipeline_definition
    tabs = pipeline.get('tabs', []) if isinstance(pipeline, dict) else []
    if not isinstance(tabs, list) or not tabs:
        return {'analysis_id': str(analysis.id), 'tabs': [], 'sources': {}}

    sources: dict[str, dict] = {}
    for tab in tabs:
        tab_datasource_id = tab.get('datasource_id')
        if not tab_datasource_id:
            continue
        if datasource_id and str(datasource_id) != str(tab.get('output_datasource_id')) and str(datasource_id) != str(tab_datasource_id):
            continue
        datasource = session.get(DataSource, str(tab_datasource_id))
        if not datasource:
            continue
        sources[str(tab_datasource_id)] = {
            'source_type': datasource.source_type,
            **datasource.config,
        }

    return {
        'analysis_id': str(analysis.id),
        'tabs': tabs,
        'sources': sources,
    }


def preview_step(
    session: Session,
    target_step_id: str,
    analysis_pipeline: dict,
    row_limit: int = 1000,
    page: int = 1,
    timeout: int | None = None,
    analysis_id: str | None = None,
    resource_config: dict | None = None,
    datasource_config: dict | None = None,
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
    pipeline_steps = resolved['pipeline_steps']
    target_step_id = resolved['target_step_id']
    datasource_config = resolved['datasource_config']
    analysis_id_value = resolved['analysis_id'] or analysis_id

    if not isinstance(datasource_config, dict):
        raise ValueError('Preview requires datasource_config')

    if not analysis_id_value:
        analysis_id_value = f'__preview__{datasource_id}'

    config: dict = datasource_config

    run_analysis_id = analysis_id_value

    request_payload = request_json or {
        'analysis_id': run_analysis_id,
        'datasource_id': datasource_id,
        'pipeline_steps': pipeline_steps,
        'target_step_id': target_step_id,
        'row_limit': row_limit,
        'page': page,
        'resource_config': resource_config,
        'analysis_pipeline': analysis_pipeline,
        'tab_id': tab_id,
    }

    pipeline_steps = apply_pipeline_steps(pipeline_steps)

    if target_step_id == 'source':
        preview_steps = []
    else:
        step_index = find_step_index(pipeline_steps, target_step_id)
        preview_steps = pipeline_steps[: step_index + 1]
        preview_steps = _hydrate_udfs(session, preview_steps)

    manager = get_manager()
    engine = manager.get_or_create_engine(analysis_id_value, resource_config=resource_config)

    additional_datasources = _get_additional_datasources(session, preview_steps, analysis_pipeline)

    # Calculate offset for pagination
    offset = (page - 1) * row_limit

    # Use the new preview method that efficiently fetches only needed rows
    job_id = engine.preview(
        datasource_config=config,
        pipeline_steps=preview_steps,
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
        error = result_data.get('error')
        if error:
            raise PipelineExecutionError(
                f'Preview failed: {error}',
                details={'operation': 'preview', 'datasource_id': datasource_id},
            )

        data = result_data.get('data', {})
        offset = (page - 1) * row_limit
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
            status='success',
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
        )
    except Exception as exc:
        completed_at = datetime.now(UTC)
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        payload = engine_run_service.create_engine_run_payload(
            analysis_id=run_analysis_id,
            datasource_id=datasource_id,
            kind='preview',
            status='failed',
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
    target_step_id: str,
    analysis_id: str,
    analysis_pipeline: dict,
    timeout: int | None = None,
    datasource_config: dict | None = None,
    tab_id: str | None = None,
):
    """Get the output schema of a pipeline step without returning data."""
    from modules.compute.schemas import StepSchemaResponse

    if timeout is None:
        timeout = settings.job_timeout

    resolved = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id)
    datasource_id = resolved['datasource_id']
    pipeline_steps = resolved['pipeline_steps']
    target_step_id = resolved['target_step_id']
    datasource_config = resolved['datasource_config']
    analysis_id_value = resolved['analysis_id'] or analysis_id

    if not isinstance(datasource_config, dict):
        raise ValueError('Schema fetch requires datasource_config')
    if not analysis_id_value:
        raise ValueError('Schema fetch requires analysis_id')

    config: dict = datasource_config

    pipeline_steps = apply_pipeline_steps(pipeline_steps)

    if target_step_id == 'source':
        schema_steps = []
    else:
        step_index = find_step_index(pipeline_steps, target_step_id)
        schema_steps = pipeline_steps[: step_index + 1]
        schema_steps = _hydrate_udfs(session, schema_steps)

    manager = get_manager()
    engine = manager.get_engine(analysis_id_value)
    if not engine:
        engine = manager.get_or_create_engine(analysis_id_value)

    additional_datasources = _get_additional_datasources(session, schema_steps, analysis_pipeline)

    # Use the new schema command that doesn't collect full data
    job_id = engine.get_schema(
        datasource_config=config,
        pipeline_steps=schema_steps,
        additional_datasources=additional_datasources,
    )

    result_data = await_engine_result(engine, timeout, job_id=job_id)
    error = result_data.get('error')
    if error:
        raise PipelineExecutionError(
            f'Schema fetch failed: {error}',
            details={'operation': 'schema', 'datasource_id': datasource_id},
        )

    data = result_data.get('data', {})
    schema = data.get('schema', {})
    return StepSchemaResponse(
        step_id=target_step_id,
        columns=list(schema.keys()),
        column_types=schema,
    )


def export_data(
    session: Session,
    target_step_id: str,
    analysis_pipeline: dict,
    export_format: str = 'csv',
    filename: str = 'export',
    destination: str = 'download',
    datasource_type: str = 'iceberg',
    iceberg_options: dict | None = None,
    duckdb_options: dict | None = None,
    datasource_config: dict | None = None,
    timeout: int | None = None,
    analysis_id: str | None = None,
    tab_id: str | None = None,
    request_json: dict | None = None,
    triggered_by: str | None = None,
    output_datasource_id: str | None = None,
) -> tuple[bytes | None, str | None, str | None, str | None, str | None, dict | None]:
    if timeout is None:
        timeout = settings.job_timeout

    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()

    resolved = _resolve_pipeline_request(analysis_pipeline, tab_id, target_step_id)
    datasource_id = resolved['datasource_id']
    pipeline_steps = resolved['pipeline_steps']
    target_step_id = resolved['target_step_id']
    datasource_config = resolved['datasource_config']
    analysis_id_value = resolved['analysis_id'] or analysis_id

    if destination == 'datasource' and output_datasource_id is None:
        raise ValueError('Output exports require output_datasource_id')

    if not isinstance(datasource_config, dict):
        raise ValueError('Export requires datasource_config')

    config: dict = datasource_config
    run_analysis_id = analysis_id_value

    request_payload = request_json or {
        'analysis_id': run_analysis_id,
        'datasource_id': datasource_id,
        'pipeline_steps': pipeline_steps,
        'target_step_id': target_step_id,
        'format': export_format,
        'filename': filename,
        'destination': destination,
        'datasource_type': datasource_type,
        'iceberg_options': iceberg_options,
        'duckdb_options': duckdb_options,
        'datasource_config': datasource_config,
        'analysis_pipeline': analysis_pipeline,
        'tab_id': tab_id,
    }

    pipeline_steps = apply_pipeline_steps(pipeline_steps)

    if target_step_id == 'source':
        export_steps = []
    else:
        step_index = find_step_index(pipeline_steps, target_step_id)
        export_steps = pipeline_steps[: step_index + 1]
    export_steps = _hydrate_udfs(session, export_steps)

    manager = get_manager()

    temp_engine = False
    temp_engine_id = f'{datasource_id}_export'
    if analysis_id_value:
        engine = manager.get_engine(analysis_id_value)
        if not engine:
            engine = manager.get_or_create_engine(analysis_id_value)
    else:
        engine = manager.get_or_create_engine(temp_engine_id)
        temp_engine = True

    additional_datasources = _get_additional_datasources(session, export_steps, analysis_pipeline)

    if destination == 'datasource' and datasource_type == 'iceberg':
        export_format = 'parquet'
    if destination == 'datasource' and datasource_type == 'duckdb':
        export_format = 'duckdb'
    if destination == 'datasource' and datasource_type == 'file' and export_format == 'duckdb':
        raise ValueError('DuckDB format is not supported for file datasource exports')

    # Determine file extension and content type
    format_config = {
        'duckdb': ('.parquet', 'application/octet-stream'),
    }

    if export_format == 'duckdb':
        ext, content_type = format_config['duckdb']
    else:
        fmt = get_export_format(export_format)
        ext = fmt.extension
        content_type = fmt.content_type

    # For duckdb, we first export to parquet then convert
    actual_format = 'parquet' if export_format == 'duckdb' else export_format

    # Create temp file for engine to write to
    tmp_output = tempfile.mktemp(suffix=ext)
    tmp_db_path: str | None = None
    step_timings: dict = {}
    query_plan: str | None = None

    try:
        try:
            job_id = engine.export(
                datasource_config=config,
                pipeline_steps=export_steps,
                output_path=tmp_output,
                export_format=actual_format,
                additional_datasources=additional_datasources,
            )

            result_data = await_engine_result(engine, timeout, job_id=job_id)
            step_timings = result_data.get('step_timings', {}) if isinstance(result_data, dict) else {}
            query_plan = result_data.get('query_plan') if isinstance(result_data, dict) else None
            error = result_data.get('error')
            if error:
                if temp_engine:
                    manager.shutdown_engine(temp_engine_id)
                raise PipelineExecutionError(
                    f'Export failed: {error}',
                    details={'operation': 'export', 'datasource_id': datasource_id, 'export_format': export_format},
                )

            if temp_engine:
                manager.shutdown_engine(temp_engine_id)

            data = result_data.get('data', {})
            row_count = data.get('row_count', 0)
            logger.info(f'Export completed: {row_count} rows written to {export_format}')

            completed_at = datetime.now(UTC)
            duration_ms = int((time.perf_counter() - started_perf) * 1000)

            # Handle DuckDB conversion for download/filesystem/datasource
            file_bytes = None
            output_path = tmp_output
            result_format = export_format
            if export_format == 'duckdb':
                tmp_db_path = tempfile.mktemp(suffix='.duckdb')
                conn = duckdb.connect(tmp_db_path)
                try:
                    table_name = 'data'
                    if duckdb_options:
                        table_name = duckdb_options.get('table_name', 'data')
                    conn.execute(f'CREATE TABLE {table_name} AS SELECT * FROM read_parquet(?)', [tmp_output])
                finally:
                    conn.close()
                output_path = tmp_db_path
                result_format = 'duckdb'

            result_meta = _build_export_result_metadata(
                data=data,
                file_size_bytes=os.path.getsize(output_path),
            )
            hc_results: list[HealthCheckResult] = []
            hc_checks: list[HealthCheck] = []
            hc_datasource_id = datasource_id
            if destination == 'datasource' and output_datasource_id:
                hc_datasource_id = str(output_datasource_id)
            if destination != 'download':
                db_result = session.execute(
                    select(HealthCheck).where(HealthCheck.datasource_id == hc_datasource_id)  # type: ignore[arg-type]
                )
                hc_checks = [c for c in db_result.scalars().all() if c.enabled]
                logger.info(f'Health checks: found {len(hc_checks)} enabled for datasource {hc_datasource_id}')
                if hc_checks:
                    try:
                        hc_lf = _load_healthcheck_lazy(tmp_output, actual_format)
                        if hc_lf is None:
                            raise ValueError(f'Unsupported healthcheck export format: {actual_format}')
                        hc_results = healthcheck_service.run_healthchecks(session, hc_checks, hc_lf)
                        failed_count = sum(1 for r in hc_results if not r.passed)
                        logger.info(f'Health checks: {len(hc_results)} evaluated, {failed_count} failed')
                    except Exception:
                        logger.exception('Health check evaluation failed')

            status, hc_summary, hc_details = _resolve_build_status(hc_results, hc_checks)

            analysis_name = ''
            if run_analysis_id:
                analysis_obj = session.get(Analysis, run_analysis_id)
                if analysis_obj:
                    analysis_name = analysis_obj.name

            output_notification = None
            if isinstance(datasource_config, dict):
                output_cfg = datasource_config.get('output')
                if isinstance(output_cfg, dict):
                    output_notification = output_cfg.get('notification')
                    excluded = output_cfg.get('excluded_recipients')
                    if output_notification and excluded is not None:
                        output_notification = {**output_notification, 'excluded_recipients': excluded}

            _send_pipeline_notifications(
                pipeline_steps=apply_pipeline_steps(export_steps),
                context={
                    'analysis_name': analysis_name,
                    'status': status,
                    'duration_ms': str(duration_ms),
                    'row_count': str(row_count),
                    'datasource_id': hc_datasource_id,
                    'format': export_format,
                    'destination': destination,
                    'healthcheck_summary': hc_summary,
                    'healthcheck_details': hc_details,
                },
                output_notification=output_notification,
            )

            # Download - return bytes
            if destination == 'download':
                payload = engine_run_service.create_engine_run_payload(
                    analysis_id=run_analysis_id,
                    datasource_id=datasource_id,
                    kind='export',
                    status='success',
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
                with open(output_path, 'rb') as f:
                    file_bytes = f.read()
                return file_bytes, f'{filename}.{result_format}', content_type, None, None, result_meta

            # Filesystem - save in exports dir
            if destination == 'filesystem':
                payload = engine_run_service.create_engine_run_payload(
                    analysis_id=run_analysis_id,
                    datasource_id=datasource_id,
                    kind='export',
                    status='success',
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
                file_name = f'{filename}.{result_format}'
                file_path = settings.exports_dir / file_name
                with open(output_path, 'rb') as f:
                    file_bytes = f.read()
                with open(file_path, 'wb') as f:
                    f.write(file_bytes)
                return None, file_name, content_type, str(file_path.absolute()), None, result_meta

            # Datasource - create datasource entry based on type
            if destination == 'datasource':
                if datasource_type != 'iceberg':
                    raise ValueError('Output exports must use Iceberg datasources')
                iceberg_opts = iceberg_options or {}
                namespace = iceberg_opts.get('namespace', 'exports')
                if not output_datasource_id:
                    raise ValueError('Output datasource id is required for Iceberg exports')
                table_name = output_datasource_id

                iceberg_base = settings.data_dir / 'iceberg'
                warehouse_path = iceberg_base / 'warehouse'
                catalog_path = iceberg_base / 'catalog.db'

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

                arrow_table = pl.read_parquet(output_path).to_arrow()
                if catalog.table_exists(identifier):
                    iceberg_table = catalog.load_table(identifier)
                    try:
                        iceberg_table.overwrite(arrow_table)
                    except Exception as exc:
                        update = iceberg_table.update_schema()
                        update.union_by_name(arrow_table.schema)
                        update.commit()
                        try:
                            iceberg_table.overwrite(arrow_table)
                        except Exception as retry_exc:
                            raise ValueError(f'Failed to overwrite Iceberg table after schema update: {retry_exc}') from exc
                else:
                    iceberg_table = catalog.create_table(identifier, schema=arrow_table.schema)
                    iceberg_table.append(arrow_table)

                metadata_path = str(iceberg_table.metadata_location)
                resolved_metadata = resolve_iceberg_metadata_path(metadata_path)
                table_dir = str(Path(resolved_metadata).parents[1])

                iceberg_ds_config = {
                    'catalog_type': 'sql',
                    'catalog_uri': f'sqlite:///{catalog_path}',
                    'warehouse': f'file://{warehouse_path}',
                    'namespace': namespace,
                    'table': table_name,
                    'metadata_path': table_dir,
                }
                output_ds = session.get(DataSource, output_datasource_id)
                output_hidden = True
                if output_ds:
                    output_hidden = output_ds.is_hidden
                target_ds = _upsert_output_datasource(
                    session=session,
                    output_datasource_id=output_datasource_id,
                    name=iceberg_opts.get('table_name', 'exported_data'),
                    source_type='iceberg',
                    config=iceberg_ds_config,
                    schema_cache=data.get('schema', {}),
                    analysis_id=run_analysis_id,
                    is_hidden=output_hidden,
                )
                ds_id = target_ds.id
                run_kind = 'datasource_update' if output_datasource_id and target_ds.id == output_datasource_id else 'datasource_create'

                result_meta['datasource_id'] = ds_id
                result_meta['datasource_name'] = iceberg_opts.get('table_name', 'exported_data')
                payload = engine_run_service.create_engine_run_payload(
                    analysis_id=run_analysis_id,
                    datasource_id=ds_id,
                    kind=run_kind,
                    status='success',
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

                return None, iceberg_opts.get('table_name', 'exported_data'), content_type, table_dir, ds_id, result_meta

            return None, None, None, None, None, result_meta
        except Exception as exc:
            completed_at = datetime.now(UTC)
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
            if temp_engine:
                manager.shutdown_engine(temp_engine_id)
            payload = engine_run_service.create_engine_run_payload(
                analysis_id=run_analysis_id,
                datasource_id=datasource_id,
                kind='export',
                status='failed',
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
        if tmp_db_path and os.path.exists(tmp_db_path):
            os.unlink(tmp_db_path)
        if os.path.exists(tmp_output):
            os.unlink(tmp_output)


def run_analysis_build_from_payload(session: Session, pipeline: dict | None) -> dict:
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

    for tab in tabs:
        if selected_tab_id and tab.get('id') != selected_tab_id:
            continue
        tab_id = tab.get('id', 'unknown')
        tab_name = tab.get('name', 'unnamed')
        tab_datasource_id = tab.get('datasource_id')
        steps = tab.get('steps', [])
        datasource_config = tab.get('datasource_config')

        if not tab_datasource_id:
            continue

        output_config = None
        if isinstance(datasource_config, dict):
            output_config = datasource_config.get('output')

        target_step_id = 'source'
        if steps:
            target_step_id = steps[-1].get('id', 'source')

        try:
            if output_config is not None:
                datasource_type = 'iceberg'
                export_format = 'parquet'
                filename = output_config.get('filename', f'{tab_name}_out') if isinstance(output_config, dict) else f'{tab_name}_out'

                iceberg_options = None
                iceberg_cfg = output_config.get('iceberg') if isinstance(output_config, dict) else None
                if iceberg_cfg and isinstance(iceberg_cfg, dict):
                    iceberg_options = {
                        'table_name': iceberg_cfg.get('table_name', 'exported_data'),
                        'namespace': iceberg_cfg.get('namespace', 'exports'),
                    }

                export_data(
                    session=session,
                    target_step_id=target_step_id,
                    analysis_pipeline=pipeline,
                    export_format=export_format,
                    filename=filename,
                    destination='datasource',
                    datasource_type=datasource_type,
                    iceberg_options=iceberg_options,
                    duckdb_options=None,
                    datasource_config=datasource_config if isinstance(datasource_config, dict) else None,
                    analysis_id=analysis_id,
                    tab_id=str(tab_id) if tab_id else None,
                    output_datasource_id=tab.get('output_datasource_id'),
                )
            else:
                raise ValueError(f'Tab {tab_id} missing output configuration')

            tabs_built += 1
            results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': 'success'})
        except Exception as e:
            results.append({'tab_id': tab_id, 'tab_name': tab_name, 'status': 'failed', 'error': str(e)})

    return {'analysis_id': analysis_id or '', 'tabs_built': tabs_built, 'results': results}


def list_iceberg_snapshots(session: Session, datasource_id: str):
    from modules.compute.schemas import IcebergSnapshotInfo, IcebergSnapshotsResponse

    datasource = session.get(DataSource, datasource_id)

    if not datasource:
        raise DataSourceNotFoundError(datasource_id)
    if datasource.source_type != 'iceberg':
        raise ValueError('Snapshots are only available for Iceberg datasources')

    metadata_path = datasource.config.get('metadata_path')
    if not metadata_path:
        raise ValueError('Iceberg datasource missing metadata_path')

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

        resolved = resolve_iceberg_metadata_path(metadata_path)
        table = StaticTable.from_metadata(resolved)

    current_snapshot = table.current_snapshot()
    current_snapshot_id = str(current_snapshot.snapshot_id) if current_snapshot else None
    snapshots = []
    for snap in table.snapshots():
        operation = None
        if snap.summary and snap.summary.operation:
            operation = str(snap.summary.operation)
        snapshots.append(
            IcebergSnapshotInfo(
                snapshot_id=str(snap.snapshot_id),
                timestamp_ms=snap.timestamp_ms,
                parent_snapshot_id=str(snap.parent_snapshot_id) if snap.parent_snapshot_id is not None else None,
                operation=operation,
                is_current=str(snap.snapshot_id) == current_snapshot_id,
            )
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
