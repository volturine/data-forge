from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
from sqlmodel import Session

from core.exceptions import AnalysisNotFoundError
from modules.analysis import schemas
from modules.analysis.dashboard_utils import (
    collect_dashboard_dependencies,
    resolve_pipeline_variables,
    stable_variable_state_key,
    validate_analysis_pipeline_extensions,
)
from modules.analysis.models import Analysis
from modules.compute import service as compute_service
from modules.compute.manager import ProcessManager


def _get_analysis_row(session: Session, analysis_id: str) -> Analysis:
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise AnalysisNotFoundError(analysis_id)
    return analysis


def _find_dashboard(pipeline: dict[str, Any], dashboard_id: str) -> dict[str, Any]:
    dashboards = pipeline.get('dashboards', [])
    if not isinstance(dashboards, list):
        raise ValueError('Analysis dashboards are invalid')
    for dashboard in dashboards:
        if isinstance(dashboard, dict) and dashboard.get('id') == dashboard_id:
            return dashboard
    raise ValueError(f"Dashboard '{dashboard_id}' not found")


def _find_tab(pipeline: dict[str, Any], tab_id: str) -> dict[str, Any]:
    tabs = pipeline.get('tabs', [])
    if not isinstance(tabs, list):
        raise ValueError('Analysis tabs are invalid')
    for tab in tabs:
        if isinstance(tab, dict) and tab.get('id') == tab_id:
            return tab
    raise ValueError(f"Tab '{tab_id}' not found")


def _build_pipeline_payload(session: Session, analysis: Analysis) -> dict[str, Any]:
    pipeline = compute_service.build_analysis_pipeline_payload(session, analysis)
    raw = analysis.pipeline_definition if isinstance(analysis.pipeline_definition, dict) else {}
    variables = raw.get('variables', [])
    dashboards = raw.get('dashboards', [])
    if isinstance(variables, list):
        pipeline['variables'] = deepcopy(variables)
    if isinstance(dashboards, list):
        pipeline['dashboards'] = deepcopy(dashboards)
    return pipeline


def _resolve_variable_options(
    session: Session,
    manager: ProcessManager,
    analysis: Analysis,
    pipeline: dict[str, Any],
    variable: dict[str, Any],
) -> list[dict[str, Any]]:
    options = variable.get('options')
    if isinstance(options, list) and options:
        return deepcopy([option for option in options if isinstance(option, dict)])

    option_source = variable.get('option_source')
    if not isinstance(option_source, dict):
        return []

    tab_id = str(option_source.get('tab_id') or '').strip()
    column = str(option_source.get('column') or '').strip()
    limit = int(option_source.get('limit') or 100)
    if not tab_id or not column:
        return []

    source_pipeline = deepcopy(pipeline)
    source_tab = _find_tab(source_pipeline, tab_id)
    steps = list(source_tab.get('steps') or [])
    select_id = f'option-select-{variable.get("id")}'
    dedupe_id = f'option-dedupe-{variable.get("id")}'
    sort_id = f'option-sort-{variable.get("id")}'
    steps.append(
        {
            'id': select_id,
            'type': 'select',
            'config': {'columns': [column]},
            'depends_on': [steps[-1]['id']] if steps else [],
            'is_applied': True,
        },
    )
    steps.append(
        {
            'id': dedupe_id,
            'type': 'deduplicate',
            'config': {'subset': [column], 'keep': 'first'},
            'depends_on': [select_id],
            'is_applied': True,
        },
    )
    steps.append(
        {
            'id': sort_id,
            'type': 'sort',
            'config': {'columns': [column], 'descending': [False]},
            'depends_on': [dedupe_id],
            'is_applied': True,
        },
    )
    source_tab['steps'] = steps
    preview = compute_service.preview_step(
        session=session,
        manager=manager,
        target_step_id=sort_id,
        analysis_pipeline=source_pipeline,
        row_limit=limit,
        page=1,
        analysis_id=str(analysis.id),
        tab_id=tab_id,
        triggered_by='dashboard_options',
    )
    values: list[dict[str, Any]] = []
    for row in preview.data:
        value = row.get(column)
        if value is None:
            continue
        values.append({'label': str(value), 'value': value})
    return values


def get_dashboard_detail(
    session: Session,
    manager: ProcessManager,
    analysis_id: str,
    dashboard_id: str,
) -> schemas.DashboardDetailResponseSchema:
    analysis = _get_analysis_row(session, analysis_id)
    pipeline = analysis.pipeline_definition if isinstance(analysis.pipeline_definition, dict) else {}
    validate_analysis_pipeline_extensions(pipeline)
    dashboard = _find_dashboard(pipeline, dashboard_id)
    runtime_pipeline = _build_pipeline_payload(session, analysis)
    variables = pipeline.get('variables', [])
    if not isinstance(variables, list):
        variables = []
    resolved_variables: list[dict[str, Any]] = []
    for variable in variables:
        if not isinstance(variable, dict):
            continue
        resolved_variables.append(
            {
                **deepcopy(variable),
                'options': _resolve_variable_options(session, manager, analysis, runtime_pipeline, variable),
            },
        )
    return schemas.DashboardDetailResponseSchema(
        analysis_id=analysis_id,
        dashboard=schemas.DashboardDefinitionSchema.model_validate(dashboard),
        variables=[schemas.VariableDefinitionSchema.model_validate(variable) for variable in resolved_variables],
        widget_dependencies=collect_dashboard_dependencies(pipeline, dashboard),
    )


def validate_dashboard_payload(
    session: Session,
    request: schemas.DashboardValidateRequestSchema,
) -> dict[str, Any]:
    del session
    pipeline = {
        'tabs': [tab.model_dump(mode='json') for tab in request.tabs],
        'variables': [variable.model_dump(mode='json') for variable in request.variables],
        'dashboards': [dashboard.model_dump(mode='json') for dashboard in request.dashboards],
    }
    validate_analysis_pipeline_extensions(pipeline)
    dependencies = {
        dashboard['id']: collect_dashboard_dependencies(pipeline, dashboard)
        for dashboard in pipeline['dashboards']
        if isinstance(dashboard, dict)
    }
    return {'valid': True, 'widget_dependencies': dependencies}


def _target_step_id(tab: dict[str, Any]) -> str:
    steps = tab.get('steps', [])
    if not isinstance(steps, list) or not steps:
        return 'source'
    last = steps[-1]
    if not isinstance(last, dict):
        return 'source'
    return str(last.get('id') or 'source')


def _infer_filter_value_type(values: list[str | int | float | bool]) -> str:
    if not values:
        return 'string'
    if all(isinstance(value, bool) for value in values):
        return 'boolean'
    if all(not isinstance(value, bool) and isinstance(value, (int, float)) for value in values):
        return 'number'
    string_values = [value for value in values if isinstance(value, str)]
    if len(string_values) == len(values):
        with_date_values = True
        for value in string_values:
            try:
                if len(value.strip()) != 10:
                    with_date_values = False
                    break
                date.fromisoformat(value.strip())
            except ValueError:
                with_date_values = False
                break
        if with_date_values:
            return 'date'
    return 'string'


def _widget_map(dashboard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    widgets = dashboard.get('widgets', [])
    if not isinstance(widgets, list):
        return {}
    return {
        str(widget.get('id')): widget
        for widget in widgets
        if isinstance(widget, dict) and isinstance(widget.get('id'), str) and str(widget.get('id')).strip()
    }


def _chart_params_config(config: dict[str, Any]) -> dict[str, Any]:
    from modules.compute.operations.plot import ChartParams

    allowed = set(ChartParams.model_fields)
    return {key: deepcopy(value) for key, value in config.items() if key in allowed}


def _selection_filters_for_widget(
    widget: dict[str, Any],
    widget_map: dict[str, dict[str, Any]],
    request_filters: dict[str, schemas.DashboardSelectionFilterSchema],
) -> list[dict[str, Any]]:
    widget_id = str(widget.get('id') or '').strip()
    source_tab_id = str(widget.get('source_tab_id') or '').strip()
    if not widget_id or not source_tab_id:
        return []

    filters: list[dict[str, Any]] = []
    for source_widget_id, selection in request_filters.items():
        if source_widget_id == widget_id:
            continue
        source_widget = widget_map.get(source_widget_id)
        if source_widget is None:
            continue
        source_config = source_widget.get('config') or {}
        if not isinstance(source_config, dict):
            continue
        if str(source_widget.get('type') or '') != schemas.DashboardWidgetType.CHART:
            continue
        if not bool(source_config.get('selection_filters_widgets')):
            continue
        if str(source_widget.get('source_tab_id') or '').strip() != source_tab_id:
            continue
        values = list(selection.values)
        if not values:
            continue
        filters.append(
            {
                'source_widget_id': source_widget_id,
                'column': selection.column,
                'values': values,
            },
        )
    return sorted(filters, key=lambda item: str(item['source_widget_id']))


def _apply_selection_filters(
    pipeline: dict[str, Any],
    widget: dict[str, Any],
    selection_filters: list[dict[str, Any]],
) -> dict[str, Any]:
    if not selection_filters:
        return pipeline

    source_tab_id = str(widget.get('source_tab_id') or '').strip()
    if not source_tab_id:
        return pipeline

    filtered_pipeline = deepcopy(pipeline)
    source_tab = _find_tab(filtered_pipeline, source_tab_id)
    steps = list(source_tab.get('steps') or [])
    depends_on = [steps[-1]['id']] if steps else []
    for index, selection_filter in enumerate(selection_filters):
        values = selection_filter['values']
        if not isinstance(values, list) or not values:
            continue
        step_id = f'dashboard-selection-{widget.get("id")}-{index}'
        steps.append(
            {
                'id': step_id,
                'type': 'filter',
                'config': {
                    'conditions': [
                        {
                            'column': str(selection_filter['column']),
                            'operator': 'in',
                            'value': values,
                            'value_type': _infer_filter_value_type(values),
                        },
                    ],
                    'logic': 'AND',
                },
                'depends_on': depends_on,
                'is_applied': True,
            },
        )
        depends_on = [step_id]
    source_tab['steps'] = steps
    return filtered_pipeline


def _build_dataset_result(
    session: Session,
    manager: ProcessManager,
    analysis: Analysis,
    widget: dict[str, Any],
    pipeline: dict[str, Any],
    variable_state: dict[str, Any],
    page: dict[str, int],
    variable_ids: list[str],
    selection_state: dict[str, Any] | None,
    preview_cache: dict[str, Any],
) -> schemas.DashboardWidgetRunResultSchema:
    source_tab_id = str(widget.get('source_tab_id') or '')
    selection_key = stable_variable_state_key(selection_state or {})
    preview_key = f'{source_tab_id}|{stable_variable_state_key(variable_state)}|{selection_key}|{page["page"]}|{page["page_size"]}'
    preview = preview_cache.get(preview_key)
    if preview is None:
        preview = compute_service.preview_step(
            session=session,
            manager=manager,
            target_step_id=_target_step_id(_find_tab(pipeline, source_tab_id)),
            analysis_pipeline={**deepcopy(pipeline), 'variable_values': variable_state},
            row_limit=page['page_size'],
            page=page['page'],
            analysis_id=str(analysis.id),
            tab_id=source_tab_id,
            triggered_by='dashboard_widget',
        )
        preview_cache[preview_key] = preview
    result = schemas.DashboardWidgetRunResultSchema(
        widget_id=str(widget.get('id')),
        type=schemas.DashboardWidgetType.DATASET_PREVIEW,
        title=str(widget.get('title') or ''),
        source_tab_id=source_tab_id,
        variable_ids=variable_ids,
        status='empty' if not preview.data else 'success',
        last_refresh_at=datetime.now(UTC),
        variable_state=variable_state,
        dataset=schemas.DatasetPreviewResultSchema(
            columns=preview.columns,
            column_types=preview.column_types or {},
            rows=preview.data,
            row_count=len(preview.data),
            page=page['page'],
            page_size=page['page_size'],
        ),
    )
    return result


def _build_chart_result(
    session: Session,
    manager: ProcessManager,
    analysis: Analysis,
    widget: dict[str, Any],
    pipeline: dict[str, Any],
    variable_state: dict[str, Any],
    variable_ids: list[str],
    selection_state: dict[str, Any] | None,
    preview_cache: dict[str, Any],
) -> schemas.DashboardWidgetRunResultSchema:
    source_tab_id = str(widget.get('source_tab_id') or '')
    selection_key = stable_variable_state_key(selection_state or {})
    preview_key = f'{source_tab_id}|{stable_variable_state_key(variable_state)}|{selection_key}|1|500'
    preview = preview_cache.get(preview_key)
    if preview is None:
        fallback_key = f'{source_tab_id}|{stable_variable_state_key(variable_state)}|{selection_key}|1|25'
        preview = preview_cache.get(fallback_key)
    if preview is None:
        preview = compute_service.preview_step(
            session=session,
            manager=manager,
            target_step_id=_target_step_id(_find_tab(pipeline, source_tab_id)),
            analysis_pipeline={**deepcopy(pipeline), 'variable_values': variable_state},
            row_limit=500,
            page=1,
            analysis_id=str(analysis.id),
            tab_id=source_tab_id,
            triggered_by='dashboard_widget',
        )
        preview_cache[preview_key] = preview

    chart_config = deepcopy(widget.get('config') or {})
    chart_params = _chart_params_config(chart_config) if isinstance(chart_config, dict) else {}
    chart_data = preview.data
    chart_metadata: dict[str, Any] = dict(preview.metadata or {})

    if chart_data:
        from modules.compute.operations.plot import ChartParams, compute_chart_data, compute_overlay_datasets

        raw_lf = pl.LazyFrame(chart_data)
        chart_model = ChartParams.model_validate(chart_params)
        chart_lf = compute_chart_data(raw_lf, chart_params)
        chart_data = chart_lf.collect().to_dicts()
        chart_metadata.update(
            {
                'y_axis_scale': chart_model.y_axis_scale,
                'y_axis_min': chart_model.y_axis_min,
                'y_axis_max': chart_model.y_axis_max,
                'display_units': chart_model.display_units,
                'decimal_places': chart_model.decimal_places,
                'legend_position': chart_model.legend_position,
                'title': chart_model.title,
                'overlays': compute_overlay_datasets(
                    raw_lf,
                    chart_model,
                    row_limit=500,
                    offset=0,
                ),
                'reference_lines': [line.model_dump() for line in chart_model.reference_lines],
            }
        )

    chart_schema = {}
    if chart_data:
        chart_schema = {col: str(dtype) for col, dtype in pl.DataFrame(chart_data).schema.items()}

    result = schemas.DashboardWidgetRunResultSchema(
        widget_id=str(widget.get('id')),
        type=schemas.DashboardWidgetType.CHART,
        title=str(widget.get('title') or ''),
        source_tab_id=source_tab_id,
        variable_ids=variable_ids,
        status='empty' if not chart_data else 'success',
        last_refresh_at=datetime.now(UTC),
        variable_state=variable_state,
        chart=schemas.ChartResultSchema(
            schema_map=chart_schema,
            data=chart_data,
            config=chart_config,
            metadata=chart_metadata,
        ),
    )
    return result


def _build_metric_step(widget: dict[str, Any], target_id: str) -> tuple[str, dict[str, Any]]:
    config = widget.get('config') or {}
    if not isinstance(config, dict):
        raise ValueError('Metric widget config is invalid')
    aggregation = str(config.get('aggregation') or '')
    column = str(config.get('column') or '').strip()
    comparison = config.get('comparison')
    aggregations: list[dict[str, Any]] = []
    if aggregation == 'count' and not column:
        return target_id, {}
    aggregations.append({'column': column, 'function': aggregation, 'alias': 'primary_value'})
    if isinstance(comparison, dict):
        comparison_aggregation = str(comparison.get('aggregation') or '').strip()
        comparison_column = str(comparison.get('column') or column).strip()
        if comparison_aggregation == 'count' and not comparison_column:
            comparison_column = column
        aggregations.append(
            {
                'column': comparison_column,
                'function': comparison_aggregation,
                'alias': 'comparison_value',
            },
        )
    return f'dashboard-metric-{widget.get("id")}', {'group_by': [], 'aggregations': aggregations}


def _build_metric_result(
    session: Session,
    manager: ProcessManager,
    analysis: Analysis,
    widget: dict[str, Any],
    pipeline: dict[str, Any],
    variable_state: dict[str, Any],
    variable_ids: list[str],
    selection_state: dict[str, Any] | None,
    preview_cache: dict[str, Any],
) -> schemas.DashboardWidgetRunResultSchema:
    source_tab_id = str(widget.get('source_tab_id') or '')
    metric_pipeline = {**deepcopy(pipeline), 'variable_values': variable_state}
    source_tab = _find_tab(metric_pipeline, source_tab_id)
    steps = list(source_tab.get('steps') or [])
    metric_step_id, metric_config = _build_metric_step(widget, _target_step_id(source_tab))
    metric_value: int | float | str
    comparison_value: int | float | str | None = None
    if metric_config:
        steps.append(
            {
                'id': metric_step_id,
                'type': 'groupby',
                'config': metric_config,
                'depends_on': [steps[-1]['id']] if steps else [],
                'is_applied': True,
            },
        )
        source_tab['steps'] = steps
        preview = compute_service.preview_step(
            session=session,
            manager=manager,
            target_step_id=metric_step_id,
            analysis_pipeline=metric_pipeline,
            row_limit=1,
            page=1,
            analysis_id=str(analysis.id),
            tab_id=source_tab_id,
            triggered_by='dashboard_widget',
        )
        row = preview.data[0] if preview.data else {}
        metric_value = row.get('primary_value', 0)
        comparison_value = row.get('comparison_value')
    else:
        selection_key = stable_variable_state_key(selection_state or {})
        preview_key = f'{source_tab_id}|{stable_variable_state_key(variable_state)}|{selection_key}|1|10000'
        preview = preview_cache.get(preview_key)
        if preview is None:
            preview = compute_service.preview_step(
                session=session,
                manager=manager,
                target_step_id=_target_step_id(source_tab),
                analysis_id=str(analysis.id),
                analysis_pipeline=metric_pipeline,
                row_limit=10_000,
                page=1,
                tab_id=source_tab_id,
                triggered_by='dashboard_widget',
            )
            preview_cache[preview_key] = preview
        metric_value = len(preview.data)
    config = widget.get('config') or {}
    result = schemas.DashboardWidgetRunResultSchema(
        widget_id=str(widget.get('id')),
        type=schemas.DashboardWidgetType.METRIC_KPI,
        title=str(widget.get('title') or ''),
        source_tab_id=source_tab_id,
        variable_ids=variable_ids,
        status='success',
        last_refresh_at=datetime.now(UTC),
        variable_state=variable_state,
        metric=schemas.MetricResultSchema(
            label=str(config.get('label') or ''),
            value=metric_value,
            comparison=comparison_value,
        ),
    )
    return result


def _build_text_result(
    widget: dict[str, Any],
    variable_state: dict[str, Any],
) -> schemas.DashboardWidgetRunResultSchema:
    config = widget.get('config') or {}
    result = schemas.DashboardWidgetRunResultSchema(
        widget_id=str(widget.get('id')),
        type=schemas.DashboardWidgetType.TEXT_HEADER,
        title=str(widget.get('title') or ''),
        source_tab_id=None,
        variable_ids=[],
        status='success',
        last_refresh_at=datetime.now(UTC),
        variable_state=variable_state,
        header=schemas.TextHeaderResultSchema(
            text=str(config.get('text') or ''),
            level=int(config.get('level') or 2),
        ),
    )
    return result


def run_dashboard(
    session: Session,
    manager: ProcessManager,
    analysis_id: str,
    dashboard_id: str,
    request: schemas.DashboardRunRequestSchema,
) -> schemas.DashboardRunResponseSchema:
    analysis = _get_analysis_row(session, analysis_id)
    pipeline = analysis.pipeline_definition if isinstance(analysis.pipeline_definition, dict) else {}
    validate_analysis_pipeline_extensions(pipeline)
    dashboard = _find_dashboard(pipeline, dashboard_id)
    widget_dependencies = collect_dashboard_dependencies(pipeline, dashboard)
    widget_map = _widget_map(dashboard)
    runtime_pipeline = _build_pipeline_payload(session, analysis)
    resolved_pipeline, variable_state = resolve_pipeline_variables(runtime_pipeline, request.variable_values)

    widgets = dashboard.get('widgets', [])
    if not isinstance(widgets, list):
        widgets = []
    selected_ids = set(request.widget_ids) if request.widget_ids else None
    results: list[schemas.DashboardWidgetRunResultSchema] = []
    preview_cache: dict[str, Any] = {}
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        widget_id = str(widget.get('id') or '').strip()
        if selected_ids is not None and widget_id not in selected_ids:
            continue
        variable_ids = widget_dependencies.get(widget_id, [])
        selection_filters = _selection_filters_for_widget(widget, widget_map, request.selection_filters)
        selection_state = {'selection_filters': selection_filters} if selection_filters else None
        widget_pipeline = _apply_selection_filters(resolved_pipeline, widget, selection_filters)
        try:
            widget_type = str(widget.get('type') or '')
            if widget_type == schemas.DashboardWidgetType.DATASET_PREVIEW:
                config = widget.get('config') or {}
                default_page_size = int(config.get('page_size') or 25) if isinstance(config, dict) else 25
                page = request.widget_page.get(widget_id)
                page_state = {
                    'page': page.page if page else 1,
                    'page_size': page.page_size if page else default_page_size,
                }
                result = _build_dataset_result(
                    session,
                    manager,
                    analysis,
                    widget,
                    widget_pipeline,
                    variable_state,
                    page_state,
                    variable_ids,
                    selection_state,
                    preview_cache,
                )
            elif widget_type == schemas.DashboardWidgetType.CHART:
                result = _build_chart_result(
                    session,
                    manager,
                    analysis,
                    widget,
                    widget_pipeline,
                    variable_state,
                    variable_ids,
                    selection_state,
                    preview_cache,
                )
            elif widget_type == schemas.DashboardWidgetType.METRIC_KPI:
                result = _build_metric_result(
                    session,
                    manager,
                    analysis,
                    widget,
                    widget_pipeline,
                    variable_state,
                    variable_ids,
                    selection_state,
                    preview_cache,
                )
            else:
                result = _build_text_result(widget, variable_state)
            results.append(result)
        except Exception as exc:
            results.append(
                schemas.DashboardWidgetRunResultSchema(
                    widget_id=widget_id,
                    type=schemas.DashboardWidgetType(str(widget.get('type') or 'text_header')),
                    title=str(widget.get('title') or ''),
                    source_tab_id=widget.get('source_tab_id'),
                    variable_ids=variable_ids,
                    status='error',
                    last_refresh_at=datetime.now(UTC),
                    variable_state=variable_state,
                    error=str(exc),
                ),
            )

    return schemas.DashboardRunResponseSchema(
        analysis_id=analysis_id,
        dashboard_id=dashboard_id,
        variable_state=variable_state,
        widget_dependencies=widget_dependencies,
        widgets=results,
    )
