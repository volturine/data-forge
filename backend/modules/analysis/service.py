import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import defer
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, col

from core.exceptions import AnalysisNotFoundError, DataSourceNotFoundError
from modules.analysis.models import Analysis, AnalysisDataSource, AnalysisStatus
from modules.analysis.pipeline_types import PipelineDefinition, PipelineStep, PipelineTab, TabDatasource, TabOutput
from modules.analysis.schemas import (
    AnalysisCreateSchema,
    AnalysisGalleryItemSchema,
    AnalysisResponseSchema,
    AnalysisUpdateSchema,
)
from modules.analysis.step_schemas import validate_step
from modules.analysis_versions import service as version_service
from modules.datasource.models import DataSource


def _to_response(analysis: Analysis) -> AnalysisResponseSchema:
    return AnalysisResponseSchema.model_validate(analysis)


def _validate_analysis_payload(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema | AnalysisUpdateSchema,
    analysis_id: str | None = None,
) -> tuple[list[PipelineTab], list[str]]:
    if not data.tabs:
        raise ValueError('Analysis requires at least one tab')
    tabs_payload = [PipelineTab.from_dict(tab.model_dump()) for tab in data.tabs]
    for tab in tabs_payload:
        if not tab.output.result_id:
            raise ValueError('Analysis tab missing output.result_id')
        if not tab.output.filename:
            raise ValueError('Analysis tab missing output.filename')
        if not tab.output.format:
            raise ValueError('Analysis tab missing output.format')

    tab_output_map: dict[str, str] = {}
    for tab in tabs_payload:
        if tab.id and tab.output.result_id:
            tab_output_map[tab.id] = tab.output.result_id

    datasource_ids: list[str] = []
    for tab in tabs_payload:
        ds = tab.datasource
        branch = ds.config.get('branch')
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError('Analysis tab datasource.config.branch is required')
        ds.config['branch'] = branch.strip()

        if not ds.id:
            raise ValueError('Analysis tab missing datasource.id')

        if ds.analysis_tab_id is not None:
            expected = tab_output_map.get(str(ds.analysis_tab_id))
            if expected != ds.id:
                raise ValueError(f"Datasource id '{ds.id}' does not match output.result_id of tab '{ds.analysis_tab_id}'")
            continue
        datasource_row = session.get(DataSource, ds.id)
        if datasource_row:
            datasource_ids.append(ds.id)
            if datasource_row.source_type == 'analysis' and analysis_id:
                source_id = _get_analysis_source_id(datasource_row)
                _ensure_no_cycle(session, analysis_id, source_id)
            continue
        raise DataSourceNotFoundError(ds.id)

    tab_ids = {tab.id for tab in tabs_payload if tab.id}

    referenced_source_ids: set[str] = set()
    for tab in tabs_payload:
        for step in tab.steps:
            cfg = step.config
            rs = cfg.get('right_source')
            if isinstance(rs, str) and rs:
                referenced_source_ids.add(rs)
            sources = cfg.get('sources')
            if isinstance(sources, list):
                for src in sources:
                    if isinstance(src, str) and src:
                        referenced_source_ids.add(src)

    unknown = referenced_source_ids - tab_ids
    for src_id in unknown:
        if not session.get(DataSource, src_id):
            raise ValueError(f"Step references unknown source '{src_id}'")
        datasource_ids.append(src_id)

    for tab in tabs_payload:
        step_ids: set[str] = set()
        for step in tab.steps:
            validate_step(step.type, step.config)
            if step.id:
                step_ids.add(step.id)
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    raise ValueError(f"Step depends on unknown step '{dep_id}'")

    return tabs_payload, datasource_ids


def validate_analysis(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema,
) -> dict[str, Any]:
    """Validate analysis payload without persisting."""
    tabs_payload, _ = _validate_analysis_payload(session, data)
    return {'valid': True, 'payload': {'tabs': [t.to_dict() for t in tabs_payload]}}


def create_analysis(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema,
    owner_id: str | None = None,
) -> AnalysisResponseSchema:
    analysis_id = str(uuid.uuid4())

    tabs_payload, datasource_ids = _validate_analysis_payload(session, data, analysis_id)

    pipeline_definition = PipelineDefinition(tabs=tabs_payload).to_dict()

    now = datetime.now(UTC).replace(tzinfo=None)
    analysis = Analysis(
        id=analysis_id,
        name=data.name,
        description=data.description,
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=now,
        updated_at=now,
        owner_id=owner_id,
    )

    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    with transaction:
        session.add(analysis)

        seen: set[str] = set()
        for datasource_id in datasource_ids:
            if datasource_id in seen:
                continue
            seen.add(datasource_id)
            link = AnalysisDataSource(
                analysis_id=analysis_id,
                datasource_id=datasource_id,
            )
            session.add(link)

        version_service.create_version(session, analysis, commit=False)

    session.refresh(analysis)
    return _to_response(analysis)


def get_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
) -> AnalysisResponseSchema:
    analysis = session.get(Analysis, analysis_id)

    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    return _to_response(analysis)


def list_analyses(
    session: Session,  # type: ignore[type-arg]
) -> list[AnalysisGalleryItemSchema]:
    stmt = select(Analysis).options(
        defer(Analysis.pipeline_definition),  # type: ignore[arg-type]
        defer(Analysis.description),  # type: ignore[arg-type]
        defer(Analysis.status),  # type: ignore[arg-type]
        defer(Analysis.result_path),  # type: ignore[arg-type]
        defer(Analysis.owner_id),  # type: ignore[arg-type]
    )
    return [AnalysisGalleryItemSchema.model_validate(a) for a in session.execute(stmt).scalars()]


def update_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    data: AnalysisUpdateSchema,
) -> AnalysisResponseSchema:
    analysis = session.get(Analysis, analysis_id)

    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    if data.name is not None:
        analysis.name = data.name

    if data.description is not None:
        analysis.description = data.description

    if data.tabs is not None:
        tabs_payload, datasource_ids = _validate_analysis_payload(session, data, analysis_id)
        analysis.pipeline_definition = PipelineDefinition(tabs=tabs_payload).to_dict()

        session.execute(delete(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == analysis_id))
        for ds_id in set(datasource_ids):
            session.add(
                AnalysisDataSource(
                    analysis_id=analysis_id,
                    datasource_id=ds_id,
                ),
            )

    if data.status is not None:
        analysis.status = data.status

    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.commit()
    session.refresh(analysis)
    return _to_response(analysis)


def delete_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
) -> None:
    from modules.datasource.service import _delete_datasource_files

    analysis = session.get(Analysis, analysis_id)

    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    created_datasources = (
        session.execute(
            select(DataSource).where(col(DataSource.created_by_analysis_id) == analysis_id),  # type: ignore[arg-type]
        )
        .scalars()
        .all()
    )

    for ds in created_datasources:
        if ds.is_hidden:
            _delete_datasource_files(ds)
            session.delete(ds)

    session.execute(delete(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == analysis_id))  # type: ignore[arg-type]

    session.delete(analysis)
    session.commit()


def _get_analysis_source_id(datasource: DataSource) -> str:
    analysis_id = datasource.created_by_analysis_id
    if not analysis_id:
        raise ValueError(f'Analysis datasource {datasource.id} missing created_by_analysis_id')
    return str(analysis_id)


def _ensure_no_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> None:
    if analysis_id == source_analysis_id:
        raise ValueError('Analysis cannot use itself as a datasource')
    if _detect_cycle(session, analysis_id, source_analysis_id):
        raise ValueError('Analysis datasource introduces a cycle')


def _detect_cycle(session: Session, analysis_id: str, source_analysis_id: str) -> bool:
    visited: set[str] = set()

    def visit(target_id: str) -> bool:
        if target_id == analysis_id:
            return True
        if target_id in visited:
            return False
        visited.add(target_id)
        links = (
            session.execute(
                select(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == target_id),  # type: ignore[arg-type]
            )
            .scalars()
            .all()
        )
        datasources = [session.get(DataSource, link.datasource_id) for link in links]
        for datasource in datasources:
            if not datasource:
                continue
            if datasource.source_type != 'analysis':
                continue
            next_id = datasource.created_by_analysis_id
            if not next_id:
                continue
            if visit(str(next_id)):
                return True
        return False

    return visit(source_analysis_id)


def add_step(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    step_type: str,
    config: dict[str, object],
    position: int | None = None,
    depends_on: list[str] | None = None,
) -> PipelineStep:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    pipeline = analysis.pipeline
    tab = pipeline.find_tab(tab_id)

    existing_step_ids = {s.id for s in tab.steps if s.id}
    for dep_id in depends_on or []:
        if dep_id not in existing_step_ids:
            raise ValueError(f"depends_on references unknown step '{dep_id}'")

    tab_ids = {t.id for t in pipeline.tabs if t.id}
    ds_ids = {t.datasource.id for t in pipeline.tabs if t.datasource.id}
    valid_source_ids = tab_ids | ds_ids

    def _is_valid_source(src_id: str) -> bool:
        if src_id in valid_source_ids:
            return True
        return session.get(DataSource, src_id) is not None

    right_source = config.get('right_source')
    if right_source and not _is_valid_source(str(right_source)):
        raise ValueError(f"Step references unknown source '{right_source}'")
    sources = config.get('sources')
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, str) and not _is_valid_source(src):
                raise ValueError(f"Step references unknown source '{src}'")

    step = PipelineStep(
        id=str(uuid.uuid4()),
        type=step_type,
        config=config,
        depends_on=depends_on or [],
        is_applied=True,
    )

    if position is None:
        tab.steps.append(step)
    else:
        pos = max(0, min(position, len(tab.steps)))
        tab.steps.insert(pos, step)

    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()
    session.refresh(analysis)
    return step


def get_step(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    step_id: str,
) -> PipelineStep:
    """Get a step by ID from an analysis tab."""
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)
    pipeline = analysis.pipeline
    tab = pipeline.find_tab(tab_id)
    step = next((s for s in tab.steps if s.id == step_id), None)
    if not step:
        raise ValueError(f'Step {step_id} not found')
    return step


def update_step(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    step_id: str,
    config: dict[str, object] | None = None,
    step_type: str | None = None,
) -> PipelineStep:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    pipeline = analysis.pipeline
    tab = pipeline.find_tab(tab_id)

    step = next((s for s in tab.steps if s.id == step_id), None)
    if not step:
        raise ValueError(f'Step {step_id} not found')

    if step_type is not None:
        step.type = step_type
    if config is not None:
        step.config = config

    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()
    session.refresh(analysis)
    return step


def remove_step(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    step_id: str,
) -> None:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    pipeline = analysis.pipeline
    tab = pipeline.find_tab(tab_id)

    idx = next((i for i, s in enumerate(tab.steps) if s.id == step_id), None)
    if idx is None:
        raise ValueError(f'Step {step_id} not found')

    tab.steps.pop(idx)

    for s in tab.steps:
        if step_id in s.depends_on:
            s.depends_on.remove(step_id)

    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()


def derive_tab(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    name: str | None = None,
) -> PipelineTab:
    """Create a new tab whose datasource is the given tab's output result_id."""
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    pipeline = analysis.pipeline
    source = pipeline.find_tab(tab_id)

    if not source.output.result_id:
        raise ValueError(f'Tab {tab_id} has no output.result_id')

    tab_name = name or f'Derived {len(pipeline.tabs) + 1}'
    new_tab_id = f'tab-{uuid.uuid4()!s}'

    derived_step = PipelineStep(
        id=str(uuid.uuid4()),
        type='view',
        config={'rowLimit': 100},
        depends_on=[],
        is_applied=True,
    )

    new_tab = PipelineTab(
        id=new_tab_id,
        name=tab_name,
        parent_id=tab_id,
        datasource=TabDatasource(
            id=source.output.result_id,
            config={'branch': 'master'},
            analysis_tab_id=tab_id,
        ),
        output=TabOutput(
            result_id=str(uuid.uuid4()),
            format=source.output.format or 'parquet',
            filename=tab_name,
        ),
        steps=[derived_step],
    )

    pipeline.tabs.append(new_tab)
    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()
    session.refresh(analysis)
    return new_tab


def _slugify_output_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        return 'export'
    return re.sub(r'\s+', '_', stripped).lower()


def _next_duplicate_tab_name(tabs: list[PipelineTab], source_name: str) -> str:
    base = f'{source_name} Copy'
    existing = {tab.name for tab in tabs}
    if base not in existing:
        return base

    suffix = 2
    while True:
        candidate = f'{base} {suffix}'
        if candidate not in existing:
            return candidate
        suffix += 1


def duplicate_tab(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    name: str | None = None,
) -> PipelineTab:
    """Duplicate an existing tab in-place with fresh tab/step/output identities."""
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    pipeline = analysis.pipeline
    source = pipeline.find_tab(tab_id)

    new_tab_id = f'tab-{uuid.uuid4()!s}'
    next_name = name.strip() if isinstance(name, str) and name.strip() else _next_duplicate_tab_name(pipeline.tabs, source.name)

    step_id_map: dict[str, str] = {}
    duplicated_steps: list[PipelineStep] = []
    for step in source.steps:
        next_step_id = str(uuid.uuid4())
        step_id_map[step.id] = next_step_id
        duplicated_steps.append(
            PipelineStep(
                id=next_step_id,
                type=step.type,
                config=deepcopy(step.config),
                depends_on=[],
                is_applied=step.is_applied,
            )
        )

    for duplicated_step, source_step in zip(duplicated_steps, source.steps, strict=True):
        rewritten_deps: list[str] = []
        for dep_id in source_step.depends_on:
            mapped = step_id_map.get(dep_id)
            if not mapped:
                raise ValueError(f"Unable to rewrite dependency '{dep_id}' while duplicating tab '{tab_id}'")
            rewritten_deps.append(mapped)
        duplicated_step.depends_on = rewritten_deps

    duplicated_output = TabOutput.from_dict(source.output.to_dict())
    duplicated_output.result_id = str(uuid.uuid4())
    duplicated_output.filename = _slugify_output_name(next_name)

    iceberg = duplicated_output.extra.get('iceberg')
    if isinstance(iceberg, dict):
        duplicated_output.extra['iceberg'] = {
            **iceberg,
            'table_name': duplicated_output.filename,
        }

    duplicated_tab = PipelineTab(
        id=new_tab_id,
        name=next_name,
        parent_id=source.parent_id,
        datasource=TabDatasource(
            id=source.datasource.id,
            config=deepcopy(source.datasource.config),
            analysis_tab_id=source.datasource.analysis_tab_id,
        ),
        output=duplicated_output,
        steps=duplicated_steps,
    )

    source_idx = next((idx for idx, tab in enumerate(pipeline.tabs) if tab.id == tab_id), -1)
    if source_idx < 0:
        raise ValueError(f'Tab {tab_id} not found')

    pipeline.tabs.insert(source_idx + 1, duplicated_tab)
    analysis.pipeline_definition = pipeline.to_dict()
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()
    session.refresh(analysis)
    return duplicated_tab
