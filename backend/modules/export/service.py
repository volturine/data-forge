from __future__ import annotations

import re
from dataclasses import dataclass

from sqlmodel import Session

from core.exceptions import AnalysisNotFoundError
from modules.analysis.models import Analysis
from modules.datasource.models import DataSource
from modules.export.generators import generate_polars_code, generate_sql_code, select_tabs


@dataclass(frozen=True)
class CodeExportResult:
    code: str
    warnings: list[str]
    filename: str
    tab_id: str | None
    format: str


def _slug(value: str) -> str:
    base = re.sub(r'[^a-z0-9]+', '_', value.strip().lower()).strip('_')
    return base or 'analysis'


def _build_filename(analysis_name: str, tab_name: str | None, format_name: str) -> str:
    extension = 'py' if format_name == 'polars' else 'sql'
    if tab_name:
        return f'{_slug(analysis_name)}_{_slug(tab_name)}.{extension}'
    return f'{_slug(analysis_name)}_pipeline.{extension}'


def export_analysis_code(
    session: Session,
    analysis_id: str,
    *,
    format_name: str,
    tab_id: str | None = None,
) -> CodeExportResult:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    selection = select_tabs(analysis.pipeline, tab_id)

    datasource_ids = {tab.datasource.id for tab in selection.ordered_tabs if tab.datasource.id and tab.datasource.analysis_tab_id is None}
    datasources_by_id = {
        datasource_id: datasource for datasource_id in datasource_ids if (datasource := session.get(DataSource, datasource_id)) is not None
    }

    if format_name == 'polars':
        code, warnings = generate_polars_code(selection, datasources_by_id)
    elif format_name == 'sql':
        code, warnings = generate_sql_code(selection, datasources_by_id)
    else:
        raise ValueError(f"Unsupported export format '{format_name}'")

    filename = _build_filename(
        analysis_name=analysis.name,
        tab_name=selection.target_tab.name if tab_id else None,
        format_name=format_name,
    )
    return CodeExportResult(
        code=code,
        warnings=warnings,
        filename=filename,
        tab_id=tab_id,
        format=format_name,
    )
