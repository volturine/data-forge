from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session

from backend_core.exceptions import analysis_not_found
from backend_core.persistence.analysis.models import Analysis
from backend_core.persistence.datasource.models import DataSource
from modules.export.generators import export_slug, generate_code, select_tabs
from modules.export.models import CodeExportFormat


@dataclass(frozen=True)
class CodeExportResult:
    code: str
    warnings: list[str]
    filename: str
    tab_id: str | None
    format: CodeExportFormat


def export_analysis_code(
    session: Session,
    analysis_id: str,
    *,
    format_name: CodeExportFormat,
    tab_id: str | None = None,
) -> CodeExportResult:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise analysis_not_found(analysis_id)

    selection = select_tabs(analysis.pipeline, tab_id)

    datasource_ids = {tab.datasource.id for tab in selection.ordered_tabs if tab.datasource.id and tab.datasource.analysis_tab_id is None}
    datasources_by_id = {datasource_id: datasource for datasource_id in datasource_ids if (datasource := session.get(DataSource, datasource_id)) is not None}

    code, warnings = generate_code(format_name, selection, datasources_by_id)

    tab_suffix = export_slug(selection.target_tab.name, fallback='item') if tab_id and selection.target_tab.name else 'pipeline'
    filename = f'{export_slug(analysis.name, fallback="analysis")}_{tab_suffix}.{format_name.file_extension}'
    return CodeExportResult(
        code=code,
        warnings=warnings,
        filename=filename,
        tab_id=tab_id,
        format=format_name,
    )
