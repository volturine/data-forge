import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, col

from core.exceptions import AnalysisNotFoundError, DataSourceNotFoundError
from modules.analysis.models import Analysis, AnalysisDataSource
from modules.analysis.schemas import (
    AnalysisCreateSchema,
    AnalysisGalleryItemSchema,
    AnalysisResponseSchema,
    AnalysisUpdateSchema,
)
from modules.analysis.step_schemas import validate_step
from modules.analysis_versions import service as version_service
from modules.datasource.models import DataSource
from modules.locks import service as lock_service


def _to_response(analysis: Analysis) -> AnalysisResponseSchema:
    return AnalysisResponseSchema.model_validate(analysis)


def _find_tab(tabs: list[dict], tab_id: str) -> dict:
    """Find a tab by ID or raise ValueError."""
    tab = next((t for t in tabs if t.get('id') == tab_id), None)
    if not tab:
        raise ValueError(f'Tab {tab_id} not found')
    return tab


def _validate_analysis_payload(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema | AnalysisUpdateSchema,
    analysis_id: str | None = None,
) -> tuple[list[dict], list[str]]:
    if not data.tabs:
        raise ValueError('Analysis requires at least one tab')
    tabs_payload = [tab.model_dump() for tab in data.tabs]
    for tab in tabs_payload:
        output = tab.get('output')
        if not isinstance(output, dict):
            raise ValueError('Analysis tab missing output configuration')
        output_id = output.get('result_id')
        if not output_id:
            raise ValueError('Analysis tab missing output.result_id')
        if not output.get('filename'):
            raise ValueError('Analysis tab missing output.filename')
        if not output.get('format'):
            raise ValueError('Analysis tab missing output.format')

    tab_output_map = {
        str(tab.get('id')): str((tab.get('output') or {}).get('result_id') or '')
        for tab in tabs_payload
        if tab.get('id') and (tab.get('output') or {}).get('result_id')
    }

    datasource_ids = []
    for tab in tabs_payload:
        datasource = tab.get('datasource')
        if not isinstance(datasource, dict):
            raise ValueError('Analysis tab datasource must be a dict')
        config = datasource.get('config')
        if not isinstance(config, dict):
            raise ValueError('Analysis tab datasource.config must be a dict')
        branch = config.get('branch')
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError('Analysis tab datasource.config.branch is required')
        config['branch'] = branch.strip()
        datasource['config'] = config
        tab['datasource'] = datasource
        datasource_id = datasource.get('id')
        if not datasource_id:
            raise ValueError('Analysis tab missing datasource.id')
        analysis_tab_id = datasource.get('analysis_tab_id')
        if analysis_tab_id is not None:
            expected = tab_output_map.get(str(analysis_tab_id))
            if expected != str(datasource_id):
                raise ValueError(f"Datasource id '{datasource_id}' does not match output.result_id of tab '{analysis_tab_id}'")
            datasource_ids.append(str(datasource_id))
            continue
        datasource_row = session.get(DataSource, datasource_id)
        if datasource_row:
            datasource_ids.append(str(datasource_id))
            if datasource_row.source_type == 'analysis' and analysis_id:
                source_id = _get_analysis_source_id(datasource_row)
                _ensure_no_cycle(session, analysis_id, source_id)
            continue
        raise DataSourceNotFoundError(str(datasource_id))

    tab_ids = {str(tab.get('id')) for tab in tabs_payload if tab.get('id')}
    for tab in tabs_payload:
        steps = tab.get('steps')
        if not isinstance(steps, list):
            continue
        step_ids: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError('Each step must be a dict')
            step_type = step.get('type')
            if not step_type:
                raise ValueError('Step missing type')
            config = step.get('config')
            if not isinstance(config, dict):
                config = {}
            validate_step(step_type, config)

            step_id = step.get('id')
            if step_id:
                step_ids.add(str(step_id))

            for dep_id in step.get('depends_on') or []:
                if str(dep_id) not in step_ids:
                    raise ValueError(f"Step depends on unknown step '{dep_id}'")

            right_source = config.get('right_source')
            if right_source and str(right_source) not in tab_ids:
                raise ValueError(f"Step references unknown tab '{right_source}'")

            sources = config.get('sources')
            if isinstance(sources, list):
                for src in sources:
                    if isinstance(src, str) and src not in tab_ids:
                        raise ValueError(f"Step references unknown tab '{src}'")

    return tabs_payload, datasource_ids


def validate_analysis(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema,
) -> dict:
    """Validate analysis payload without persisting."""
    tabs_payload, _ = _validate_analysis_payload(session, data)
    return {'valid': True, 'payload': {'tabs': tabs_payload}}


def create_analysis(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema,
) -> AnalysisResponseSchema:
    analysis_id = str(uuid.uuid4())

    tabs_payload, datasource_ids = _validate_analysis_payload(session, data, analysis_id)

    pipeline_definition: dict[str, object] = {
        'tabs': tabs_payload,
    }

    now = datetime.now(UTC).replace(tzinfo=None)
    analysis = Analysis(
        id=analysis_id,
        name=data.name,
        description=data.description,
        pipeline_definition=pipeline_definition,
        status='draft',
        created_at=now,
        updated_at=now,
    )

    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    with transaction:
        session.add(analysis)

        for datasource_id in datasource_ids:
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
    return [AnalysisGalleryItemSchema.model_validate(a) for a in session.execute(select(Analysis)).scalars()]


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
        analysis.pipeline_definition = {'tabs': tabs_payload}

        session.execute(delete(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == analysis_id))
        for ds_id in set(datasource_ids):
            session.add(
                AnalysisDataSource(
                    analysis_id=analysis_id,
                    datasource_id=ds_id,
                )
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
            select(DataSource).where(col(DataSource.created_by_analysis_id) == analysis_id)  # type: ignore[arg-type]
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

    lock_service.clear_lock(session, analysis_id)


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
                select(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == target_id)  # type: ignore[arg-type]
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
    config: dict,
    position: int | None = None,
    depends_on: list[str] | None = None,
) -> dict:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    tabs = analysis.pipeline_definition.get('tabs', [])
    tab = _find_tab(tabs, tab_id)

    existing_step_ids = {str(s.get('id')) for s in tab.get('steps', []) if s.get('id')}
    for dep_id in depends_on or []:
        if str(dep_id) not in existing_step_ids:
            raise ValueError(f"depends_on references unknown step '{dep_id}'")

    tab_ids = {str(t.get('id')) for t in tabs if t.get('id')}
    right_source = config.get('right_source')
    if right_source and str(right_source) not in tab_ids:
        raise ValueError(f"Step references unknown tab '{right_source}'")
    sources = config.get('sources')
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, str) and src not in tab_ids:
                raise ValueError(f"Step references unknown tab '{src}'")

    step_id = str(uuid.uuid4())
    step: dict = {
        'id': step_id,
        'type': step_type,
        'config': config,
        'depends_on': depends_on or [],
        'is_applied': True,
    }

    steps = tab.setdefault('steps', [])
    if position is None:
        steps.append(step)
    else:
        pos = max(0, min(position, len(steps)))
        steps.insert(pos, step)

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
) -> dict:
    """Get a step by ID from an analysis tab."""
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)
    tabs = analysis.pipeline_definition.get('tabs', [])
    tab = _find_tab(tabs, tab_id)
    step = next((s for s in tab.get('steps', []) if s.get('id') == step_id), None)
    if not step:
        raise ValueError(f'Step {step_id} not found')
    return step


def update_step(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    step_id: str,
    config: dict | None = None,
    step_type: str | None = None,
) -> dict:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    version_service.create_version(session, analysis, commit=False)

    tabs = analysis.pipeline_definition.get('tabs', [])
    tab = _find_tab(tabs, tab_id)

    step = next((s for s in tab.get('steps', []) if s.get('id') == step_id), None)
    if not step:
        raise ValueError(f'Step {step_id} not found')

    if step_type is not None:
        step['type'] = step_type
    if config is not None:
        step['config'] = config

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

    tabs = analysis.pipeline_definition.get('tabs', [])
    tab = _find_tab(tabs, tab_id)

    steps = tab.get('steps', [])
    idx = next((i for i, s in enumerate(steps) if s.get('id') == step_id), None)
    if idx is None:
        raise ValueError(f'Step {step_id} not found')

    steps.pop(idx)

    for s in steps:
        deps = s.get('depends_on', [])
        if step_id in deps:
            deps.remove(step_id)

    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()


def derive_tab(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    tab_id: str,
    name: str | None = None,
) -> dict:
    """Create a new tab whose datasource is the given tab's output result_id."""
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    tabs = analysis.pipeline_definition.get('tabs', [])
    source = _find_tab(tabs, tab_id)

    output = source.get('output') or {}
    result_id = output.get('result_id')
    if not result_id:
        raise ValueError(f'Tab {tab_id} has no output.result_id')

    tab_name = name or f'Derived {len(tabs) + 1}'
    new_tab_id = f'tab-{str(uuid.uuid4())}'
    new_result_id = str(uuid.uuid4())
    new_tab = {
        'id': new_tab_id,
        'name': tab_name,
        'parent_id': tab_id,
        'datasource': {
            'id': result_id,
            'analysis_tab_id': tab_id,
            'config': {'branch': 'master'},
        },
        'output': {
            'result_id': new_result_id,
            'format': output.get('format', 'parquet'),
            'filename': tab_name,
        },
        'steps': [
            {
                'id': str(uuid.uuid4()),
                'type': 'view',
                'config': {'rowLimit': 100},
                'depends_on': [],
                'is_applied': True,
            }
        ],
    }

    tabs.append(new_tab)
    analysis.pipeline_definition['tabs'] = tabs
    flag_modified(analysis, 'pipeline_definition')
    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()
    session.refresh(analysis)
    return new_tab
