import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlmodel import Session

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


def create_analysis(
    session: Session,  # type: ignore[type-arg]
    data: AnalysisCreateSchema,
) -> AnalysisResponseSchema:
    analysis_id = str(uuid.uuid4())

    for datasource_id in data.datasource_ids:
        result = session.execute(select(DataSource).where(DataSource.id == datasource_id))  # type: ignore[arg-type]
        datasource = result.scalar_one_or_none()
        if not datasource:
            raise DataSourceNotFoundError(datasource_id)
        if datasource.source_type == 'analysis':
            source_id = _get_analysis_source_id(datasource)
            _ensure_no_cycle(session, analysis_id, source_id)

    pipeline_definition = {
        'steps': [step.model_dump() for step in data.pipeline_steps],
        'datasource_ids': data.datasource_ids,
        'tabs': [tab.model_dump() for tab in data.tabs],
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

        for datasource_id in data.datasource_ids:
            link = AnalysisDataSource(
                analysis_id=analysis_id,
                datasource_id=datasource_id,
            )
            session.add(link)

        version_service.create_version(session, analysis, commit=False)

    session.refresh(analysis)

    response = AnalysisResponseSchema.model_validate(analysis)
    response.tabs = [TabSchema.model_validate(tab) for tab in analysis.pipeline_definition.get('tabs', [])]
    return response


def get_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
) -> AnalysisResponseSchema:
    analysis = session.get(Analysis, analysis_id)

    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    response = AnalysisResponseSchema.model_validate(analysis)
    response.tabs = [TabSchema.model_validate(tab) for tab in analysis.pipeline_definition.get('tabs', [])]
    return response


def list_analyses(
    session: Session,  # type: ignore[type-arg]
) -> list[AnalysisGalleryItemSchema]:
    result = session.execute(select(Analysis))
    analyses = result.scalars().all()

    return [AnalysisGalleryItemSchema.model_validate(a) for a in analyses]


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

    if data.pipeline_steps is not None or data.tabs is not None:
        tabs_payload = [tab.model_dump() for tab in data.tabs] if data.tabs is not None else analysis.pipeline_definition.get('tabs', [])
        if data.tabs is not None:
            from modules.datasource import service as datasource_service

            for tab in tabs_payload:
                config = tab.get('datasource_config') or {}
                source_analysis_id = config.get('analysis_id')

                # Cross-analysis source tabs: validate and auto-create analysis datasource
                if source_analysis_id:
                    if str(source_analysis_id) == analysis_id and not config.get('analysis_tab_id'):
                        raise ValueError('Analysis cannot use itself as a datasource')
                    datasource_id = tab.get('datasource_id')
                    if not (datasource_id and session.get(DataSource, datasource_id)):
                        created = datasource_service.create_analysis_datasource(
                            session=session,
                            name=tab.get('name') or 'Analysis Source',
                            analysis_id=str(source_analysis_id),
                            analysis_tab_id=(str(config.get('analysis_tab_id')) if config.get('analysis_tab_id') else None),
                        )
                        tab['datasource_id'] = created.id
                else:
                    # All other tabs: ensure they have an input datasource_id.
                    # Derived tabs without a datasource get a hidden analysis datasource.
                    datasource_id = tab.get('datasource_id')
                    if not (datasource_id and session.get(DataSource, datasource_id)):
                        tab_id = tab.get('id', '')
                        created = datasource_service.create_analysis_datasource(
                            session=session,
                            name=tab.get('name') or f'Tab {tab_id}',
                            analysis_id=analysis_id,
                            analysis_tab_id=tab_id or None,
                            is_hidden=True,
                        )
                        tab['datasource_id'] = created.id

                # Every tab always gets an output datasource for builds,
                # timetravel, healthchecks, and scheduling.
                output_ds_id = tab.get('output_datasource_id')
                if not (output_ds_id and session.get(DataSource, output_ds_id)):
                    tab_id = tab.get('id', '')
                    output_ds = datasource_service.create_analysis_datasource(
                        session=session,
                        name=f'{tab.get("name") or "Tab"} Output',
                        analysis_id=analysis_id,
                        analysis_tab_id=tab_id or None,
                        is_hidden=True,
                        source_type='iceberg',
                    )
                    tab['output_datasource_id'] = output_ds.id
                output_config = tab.get('datasource_config')
                if not isinstance(output_config, dict):
                    output_config = {}
                if 'output' not in output_config:
                    base_name = tab.get('name') or 'export'
                    table_name = base_name.replace(' ', '_').lower() or 'export'
                    output_config['output'] = {
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': base_name,
                        'iceberg': {
                            'namespace': 'exports',
                            'table_name': table_name,
                        },
                    }
                    tab['datasource_config'] = output_config
        datasource_ids = analysis.pipeline_definition.get('datasource_ids', [])
        if data.tabs is not None:
            datasource_ids = [tab.get('datasource_id') for tab in tabs_payload if tab.get('datasource_id')]
        pipeline_definition = {
            'steps': (
                [step.model_dump() for step in data.pipeline_steps]
                if data.pipeline_steps is not None
                else analysis.pipeline_definition.get('steps', [])
            ),
            'datasource_ids': datasource_ids,
            'tabs': tabs_payload,
        }
        analysis.pipeline_definition = pipeline_definition

        datasource_ids = analysis.pipeline_definition.get('datasource_ids', [])
        session.execute(
            delete(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id)  # type: ignore[arg-type]
        )
        for datasource_id in datasource_ids:
            datasource = session.get(DataSource, datasource_id)
            if not datasource:
                raise DataSourceNotFoundError(datasource_id)
            if datasource.source_type == 'analysis':
                source_id = _get_analysis_source_id(datasource)
                if source_id == analysis_id and datasource.config.get('analysis_tab_id'):
                    continue
                _ensure_no_cycle(session, analysis_id, source_id)
            session.add(
                AnalysisDataSource(
                    analysis_id=analysis_id,
                    datasource_id=datasource_id,
                )
            )

    if data.status is not None:
        analysis.status = data.status

    analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.commit()
    session.refresh(analysis)

    response = AnalysisResponseSchema.model_validate(analysis)
    response.tabs = [TabSchema.model_validate(tab) for tab in analysis.pipeline_definition.get('tabs', [])]
    return response


def delete_analysis(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
) -> None:
    analysis = session.get(Analysis, analysis_id)

    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    session.execute(
        delete(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id)  # type: ignore[arg-type]
    )

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

    result = session.execute(select(DataSource).where(DataSource.id == datasource_id))  # type: ignore[arg-type]
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    result = session.execute(
        select(AnalysisDataSource).where(
            AnalysisDataSource.analysis_id == analysis_id,  # type: ignore[arg-type]
            AnalysisDataSource.datasource_id == datasource_id,  # type: ignore[arg-type]
        )  # type: ignore[arg-type]
    )
    existing = result.scalar_one_or_none()
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

    if datasource_id not in analysis.pipeline_definition.get('datasource_ids', []):
        analysis.pipeline_definition['datasource_ids'] = analysis.pipeline_definition.get('datasource_ids', []) + [datasource_id]
        analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)

    tabs = analysis.pipeline_definition.get('tabs', [])
    if not any(tab.get('datasource_id') == datasource_id for tab in tabs):
        tabs.append(
            {
                'id': f'tab-{datasource_id}',
                'name': f'Source {len(tabs) + 1}',
                'type': 'datasource',
                'parent_id': None,
                'datasource_id': datasource_id,
                'steps': [],
            }
        )
        analysis.pipeline_definition['tabs'] = tabs
        analysis.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.commit()


def _get_analysis_source_id(datasource: DataSource) -> str:
    analysis_id = datasource.config.get('analysis_id')
    if not analysis_id:
        raise ValueError(f'Analysis datasource {datasource.id} missing analysis_id')
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
                select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == target_id)  # type: ignore[arg-type]
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
            next_id = datasource.config.get('analysis_id')
            if not next_id:
                continue
            if visit(str(next_id)):
                return True
        return False

    return visit(source_analysis_id)


def unlink_datasource(
    session: Session,  # type: ignore[type-arg]
    analysis_id: str,
    datasource_id: str,
) -> None:
    result = session.execute(select(Analysis).where(Analysis.id == analysis_id))  # type: ignore[arg-type]
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise AnalysisNotFoundError(analysis_id)

    result = session.execute(select(DataSource).where(DataSource.id == datasource_id))  # type: ignore[arg-type]
    datasource = result.scalar_one_or_none()
    if not datasource:
        raise DataSourceNotFoundError(datasource_id)

    session.execute(
        delete(AnalysisDataSource).where(
            AnalysisDataSource.analysis_id == analysis_id,  # type: ignore[arg-type]
            AnalysisDataSource.datasource_id == datasource_id,  # type: ignore[arg-type]
        )  # type: ignore[arg-type]
    )

    datasource_ids = analysis.pipeline_definition.get('datasource_ids', [])
    if datasource_id in datasource_ids:
        datasource_ids.remove(datasource_id)
        analysis.pipeline_definition['datasource_ids'] = datasource_ids
        analysis.updated_at = datetime.now(UTC)

    tabs = analysis.pipeline_definition.get('tabs', [])
    next_tabs = [tab for tab in tabs if tab.get('datasource_id') != datasource_id]
    if len(next_tabs) != len(tabs):
        analysis.pipeline_definition['tabs'] = next_tabs
        analysis.updated_at = datetime.now(UTC)

    session.commit()
