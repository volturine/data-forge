from __future__ import annotations

from dataclasses import dataclass

from contracts.analysis.models import Analysis
from contracts.datasource.models import DataSource
from core.exceptions import AnalysisNotFoundError
from sqlmodel import Session

from modules.export.generators import generate_code, select_tabs
from modules.export.models import CodeExportFormat
from modules.export.utils import build_export_filename


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
    format_name: CodeExportFormat | str,
    tab_id: str | None = None,
) -> CodeExportResult:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    export_format = CodeExportFormat.require(format_name)
    selection = select_tabs(analysis.pipeline, tab_id)

    datasource_ids = {tab.datasource.id for tab in selection.ordered_tabs if tab.datasource.id and tab.datasource.analysis_tab_id is None}
    datasources_by_id = {datasource_id: datasource for datasource_id in datasource_ids if (datasource := session.get(DataSource, datasource_id)) is not None}

    code, warnings = generate_code(export_format, selection, datasources_by_id)

    filename = build_export_filename(
        analysis_name=analysis.name,
        tab_name=selection.target_tab.name if tab_id else None,
        format_name=export_format,
    )
    return CodeExportResult(
        code=code,
        warnings=warnings,
        filename=filename,
        tab_id=tab_id,
        format=export_format,
    )
