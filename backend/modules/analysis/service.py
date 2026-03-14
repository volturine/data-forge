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
    TabSchema,
)
from modules.analysis_versions import service as version_service
from modules.datasource.models import DataSource
from modules.locks import service as lock_service


def _validate_analysis_payload(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema,
    analysis_id: str | None = None,
) -> tuple[list[dict], list[str]]:
    if not data.tabs:
        raise ValueError('Analysis requires at least one tab')
    tabs_payload = [tab.model_dump() for tab in data.tabs]
    output_map: dict[str, str] = {}
    for tab in tabs_payload:
        output = tab.get('output')
        if not isinstance(output, dict):
            raise ValueError('Analysis tab missing output configuration')
        output_id = output.get('output_datasource_id')
        if not output_id:
            raise ValueError('Analysis tab missing output.output_datasource_id')
        if not output.get('filename'):
            raise ValueError('Analysis tab missing output.filename')
        if not output.get('format'):
            raise ValueError('Analysis tab missing output.format')
        output_id = str(output_id)
        tab_id = tab.get('id')
        if tab_id:
            output_map[str(tab_id)] = output_id

    datasource_ids = []
    output_ids = set(output_map.values())
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
        datasource_row = session.get(DataSource, datasource_id)
        if datasource_row:
            datasource_ids.append(str(datasource_id))
            if datasource_row.source_type == 'analysis' and analysis_id:
                source_id = _get_analysis_source_id(datasource_row)
                _ensure_no_cycle(session, analysis_id, source_id)
            continue
        if str(datasource_id) in output_ids:
            datasource_ids.append(str(datasource_id))
            continue
        raise DataSourceNotFoundError(str(datasource_id))

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

    response = AnalysisResponseSchema.model_validate(analysis)
    tabs = analysis.pipeline_definition.get('tabs', [])
    if not isinstance(tabs, list):
        tabs = []
    response.tabs = [TabSchema.model_validate(tab) for tab in tabs if isinstance(tab, dict)]
    return response


def get_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
) -> AnalysisResponseSchema:
    analysis = session.get(Analysis, analysis_id)

    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    response = AnalysisResponseSchema.model_validate(analysis)
    tabs = analysis.pipeline_definition.get('tabs', [])
    response.tabs = [TabSchema.model_validate(tab) for tab in tabs if isinstance(tab, dict)]
    return response


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
        tabs_payload = [tab.model_dump() for tab in data.tabs]
        output_map: dict[str, str] = {}
        if not data.tabs:
            raise ValueError('Analysis requires at least one tab')
        for tab in tabs_payload:
            tab_id = tab.get('id')
            output = tab.get('output')
            if not isinstance(output, dict):
                raise ValueError('Analysis tab missing output configuration')
            output_id = output.get('output_datasource_id')
            if not output_id:
                raise ValueError('Analysis tab missing output.output_datasource_id')
            if not output.get('filename'):
                raise ValueError('Analysis tab missing output.filename')
            if not output.get('format'):
                raise ValueError('Analysis tab missing output.format')
            output_id = str(output_id)
            if tab_id and output_id:
                output_map[str(tab_id)] = output_id

        output_ids = set(output_map.values())
        for tab in tabs_payload:
            datasource = tab.get('datasource')
            if not isinstance(datasource, dict):
                raise ValueError('Analysis tab datasource must be a dict')
            datasource_id = datasource.get('id')
            config = datasource.get('config')
            if not isinstance(config, dict):
                raise ValueError('Analysis tab datasource.config must be a dict')

            if not datasource_id:
                raise ValueError('Analysis tab missing datasource.id')
            if not session.get(DataSource, datasource_id) and str(datasource_id) not in output_ids:
                raise DataSourceNotFoundError(str(datasource_id))

            branch = config.get('branch')
            if not isinstance(branch, str) or not branch.strip():
                raise ValueError('Analysis tab datasource.config.branch is required')
            config['branch'] = branch.strip()
            datasource['config'] = config
            tab['datasource'] = datasource
        pipeline_definition: dict[str, object] = {
            'tabs': tabs_payload,
        }
        analysis.pipeline_definition = pipeline_definition

        datasource_ids: set[str] = set()
        session.execute(delete(AnalysisDataSource).where(col(AnalysisDataSource.analysis_id) == analysis_id))
        for tab in tabs_payload:
            datasource = tab.get('datasource')
            if not isinstance(datasource, dict):
                raise ValueError('Analysis tab datasource must be a dict')
            ds_id = datasource.get('id')
            if not ds_id:
                raise ValueError('Analysis tab missing datasource.id')
            ds_id_value = str(ds_id)
            datasource_model = session.get(DataSource, ds_id)
            if not datasource_model and ds_id_value not in output_ids:
                raise DataSourceNotFoundError(ds_id_value)
            if ds_id_value in datasource_ids:
                continue
            datasource_ids.add(ds_id_value)
            if datasource_model and datasource_model.source_type == 'analysis':
                source_id = _get_analysis_source_id(datasource_model)
                _ensure_no_cycle(session, analysis_id, source_id)
            session.add(
                AnalysisDataSource(
                    analysis_id=analysis_id,
                    datasource_id=ds_id_value,
                )
            )

    if data.status is not None:
        analysis.status = data.status

    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.commit()
    session.refresh(analysis)

    response = AnalysisResponseSchema.model_validate(analysis)
    tabs = analysis.pipeline_definition.get('tabs', [])
    if not isinstance(tabs, list):
        tabs = []
    response.tabs = [TabSchema.model_validate(tab) for tab in tabs if isinstance(tab, dict)]
    return response


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


def link_datasource(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    datasource_id: str,
) -> None:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    datasource = session.execute(select(DataSource).where(col(DataSource.id) == datasource_id)).scalar_one_or_none()  # type: ignore[arg-type]
    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    existing = session.execute(
        select(AnalysisDataSource).where(  # type: ignore[arg-type]
            col(AnalysisDataSource.analysis_id) == analysis_id,
            col(AnalysisDataSource.datasource_id) == datasource_id,
        )
    ).scalar_one_or_none()
    if existing:
        return

    if datasource.source_type == 'analysis':
        source_id = _get_analysis_source_id(datasource)
        _ensure_no_cycle(session, analysis_id, source_id)

    link = AnalysisDataSource(
        analysis_id=analysis_id,
        datasource_id=datasource_id,
    )
    session.add(link)

    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)

    tabs = analysis.pipeline_definition.get('tabs', [])
    if not any((tab.get('datasource') or {}).get('id') == datasource_id for tab in tabs):
        tabs.append(
            {
                'id': f'tab-{datasource_id}',
                'name': f'Source {len(tabs) + 1}',
                'parent_id': None,
                'datasource': {
                    'id': datasource_id,
                    'analysis_tab_id': None,
                    'config': {'branch': 'master'},
                },
                'output': {
                    'output_datasource_id': str(uuid.uuid4()),
                    'format': 'parquet',
                    'filename': f'Source {len(tabs) + 1}',
                    'iceberg': {
                        'namespace': 'outputs',
                        'table_name': f'source_{len(tabs) + 1}',
                        'branch': 'master',
                    },
                },
                'steps': [],
            }
        )
        analysis.pipeline_definition['tabs'] = tabs

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
    tab = next((t for t in tabs if t.get('id') == tab_id), None)
    if not tab:
        raise ValueError(f'Tab {tab_id} not found')

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
    tab = next((t for t in tabs if t.get('id') == tab_id), None)
    if not tab:
        raise ValueError(f'Tab {tab_id} not found')

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
    tab = next((t for t in tabs if t.get('id') == tab_id), None)
    if not tab:
        raise ValueError(f'Tab {tab_id} not found')

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


def unlink_datasource(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    datasource_id: str,
) -> None:
    analysis = session.execute(select(Analysis).where(col(Analysis.id) == analysis_id)).scalar_one_or_none()  # type: ignore[arg-type]
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    datasource = session.execute(select(DataSource).where(col(DataSource.id) == datasource_id)).scalar_one_or_none()  # type: ignore[arg-type]
    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    session.execute(
        delete(AnalysisDataSource).where(  # type: ignore[arg-type]
            col(AnalysisDataSource.analysis_id) == analysis_id,
            col(AnalysisDataSource.datasource_id) == datasource_id,
        )
    )

    tabs = analysis.pipeline_definition.get('tabs', [])
    next_tabs = [tab for tab in tabs if (tab.get('datasource') or {}).get('id') != datasource_id]
    if len(next_tabs) != len(tabs):
        analysis.pipeline_definition['tabs'] = next_tabs
        analysis.updated_at = datetime.now(UTC)

    session.commit()
