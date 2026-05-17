from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from harness.postgres_harness import ExternalPostgres, PostgresContainer, require_docker

if TYPE_CHECKING:
    from contracts.analysis.models import Analysis
    from contracts.datasource.models import DataSource


def pytest_sessionstart(session: pytest.Session) -> None:
    os.environ.pop('POLARS_MAX_THREADS', None)
    os.environ.pop('POLARS_STREAMING_CHUNK_SIZE', None)
    os.environ.setdefault('ENV_FILE', '')
    os.environ.setdefault('SETTINGS_ENCRYPTION_KEY', 'test-key')
    os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg://dataforge:dataforge@127.0.0.1:5432/dataforge')


def _settings():
    from core.config import settings

    return settings


def _register_sqlmodel_metadata() -> None:
    from contracts.analysis.models import Analysis, AnalysisDataSource, AnalysisFavorite
    from contracts.analysis_versions.models import AnalysisVersion
    from contracts.build_jobs.models import BuildJob
    from contracts.build_runs.models import BuildEvent, BuildRun
    from contracts.datasource.models import DataSource, DataSourceColumnMetadata
    from contracts.engine_instances.models import EngineInstance
    from contracts.engine_runs.models import EngineRun
    from contracts.healthcheck_models import HealthCheck, HealthCheckResult
    from contracts.locks.models import ResourceLock
    from contracts.namespaces.models import RuntimeNamespace
    from contracts.runtime_workers.models import RuntimeWorker
    from contracts.scheduler.models import Schedule
    from contracts.settings_models import AppSettings
    from contracts.telegram_models import TelegramListener, TelegramSubscriber
    from contracts.udf_models import Udf

    del Analysis
    del AnalysisDataSource
    del AnalysisFavorite
    del AnalysisVersion
    del AppSettings
    del BuildEvent
    del BuildJob
    del BuildRun
    del DataSource
    del DataSourceColumnMetadata
    del EngineInstance
    del EngineRun
    del HealthCheck
    del HealthCheckResult
    del ResourceLock
    del RuntimeNamespace
    del RuntimeWorker
    del Schedule
    del TelegramListener
    del TelegramSubscriber
    del Udf


def _settings_tables() -> list[Any]:
    from contracts.engine_instances.models import EngineInstance
    from contracts.namespaces.models import RuntimeNamespace
    from contracts.runtime_workers.models import RuntimeWorker
    from contracts.settings_models import AppSettings

    table_names = {AppSettings.__tablename__, EngineInstance.__tablename__, RuntimeWorker.__tablename__, RuntimeNamespace.__tablename__}
    return [table for table in AppSettings.metadata.sorted_tables if table.name in table_names]


def _reset_settings_state(engine: Engine) -> None:
    from core.settings_projection import invalidate_resolved_settings_cache

    with engine.begin() as conn:
        for table in reversed(_settings_tables()):
            conn.execute(table.delete())

    invalidate_resolved_settings_cache()


@pytest.fixture(scope='session')
def postgres_container() -> Generator[ExternalPostgres | PostgresContainer, None, None]:
    external_url = os.environ.get('TEST_POSTGRES_URL')
    if external_url:
        yield ExternalPostgres(external_url)
        return

    require_docker()
    with PostgresContainer() as container:
        os.environ['TEST_POSTGRES_URL'] = container.url
        yield container
        os.environ.pop('TEST_POSTGRES_URL', None)


def _schema_engine(database_url: str, schema: str) -> Engine:
    engine = create_engine(database_url, echo=False, pool_pre_ping=True, connect_args={'options': f'-c search_path={schema},public'})
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    return engine


@pytest.fixture(scope='function')
def test_engine(postgres_container: PostgresContainer):
    schema = f'test_{uuid.uuid4().hex}'
    engine = _schema_engine(postgres_container.url, schema)
    _register_sqlmodel_metadata()
    from core import database

    with engine.begin() as connection:
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        tenant_tables = database._tenant_tables()
        tenant_metadata = tenant_tables[0].metadata if tenant_tables else None
        if tenant_metadata is not None:
            tenant_metadata.create_all(connection, tables=tenant_tables)
    try:
        yield engine
    finally:
        with postgres_container.connect() as pg_connection, pg_connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


@pytest.fixture(scope='function')
def test_db_session(test_engine):
    from core.database import clear_engine_override, set_engine_override

    set_engine_override(test_engine)
    with Session(test_engine) as session:
        yield session
    clear_engine_override()


@pytest.fixture(scope='function')
def temp_upload_dir(tmp_path: Path) -> Path:
    upload_dir = tmp_path / 'uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


@pytest.fixture(autouse=True, scope='function')
def isolate_data_dir(tmp_path: Path, monkeypatch, postgres_container: PostgresContainer):
    settings = _settings()
    data_dir = tmp_path / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('ENV_FILE', '')
    monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
    monkeypatch.setattr(settings, 'settings_encryption_key', 'test-key', raising=False)
    monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
    monkeypatch.setattr(settings, 'database_url', postgres_container.url, raising=False)


@pytest.fixture(autouse=True, scope='function')
def isolate_settings_engine(
    request: pytest.FixtureRequest, tmp_path: Path, isolate_data_dir, postgres_container: PostgresContainer
) -> Generator[Engine | None, None, None]:
    if '/backend/tests/' in request.node.path.as_posix():
        yield None
        return

    from contracts.settings_models import AppSettings
    from core import database

    schema = f'settings_{uuid.uuid4().hex}'
    engine = _schema_engine(postgres_container.url, schema)
    AppSettings.metadata.create_all(engine, tables=_settings_tables())
    original = database.settings_engine
    database.settings_engine = engine
    database.clear_settings_engine_override()
    try:
        yield engine
    finally:
        database.clear_settings_engine_override()
        _reset_settings_state(engine)
        database.settings_engine = original
        with postgres_container.connect() as pg_connection, pg_connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


@pytest.fixture(autouse=True, scope='function')
def cleanup_namespace_engines():
    from core import database

    yield
    database.clear_namespace_init_cache()
    if database.tenant_engine is not None:
        database.tenant_engine.dispose()
        database.tenant_engine = None


@pytest.fixture(scope='function')
def sample_csv_file(temp_upload_dir: Path) -> Path:
    import polars as pl

    csv_path = temp_upload_dir / 'sample.csv'
    df = pl.DataFrame(
        {
            'id': [1, 2, 3, 4, 5],
            'name': ['Alice', 'Bob', 'Charlie', 'David', 'Eve'],
            'age': [25, 30, 35, 40, 45],
            'city': ['NYC', 'LA', 'Chicago', 'Houston', 'Phoenix'],
        }
    )
    df.write_csv(csv_path)
    return csv_path


@pytest.fixture(scope='function')
def sample_parquet_file(temp_upload_dir: Path) -> Path:
    import polars as pl

    parquet_path = temp_upload_dir / 'sample.parquet'
    df = pl.DataFrame(
        {'product_id': [101, 102, 103], 'product_name': ['Widget A', 'Widget B', 'Widget C'], 'price': [10.99, 20.99, 30.99], 'stock': [100, 50, 75]}
    )
    df.write_parquet(parquet_path)
    return parquet_path


@pytest.fixture(scope='function')
def sample_ndjson_file(temp_upload_dir: Path) -> Path:
    import polars as pl

    ndjson_path = temp_upload_dir / 'sample.ndjson'
    df = pl.DataFrame({'user_id': [1, 2, 3], 'username': ['user1', 'user2', 'user3'], 'email': ['user1@test.com', 'user2@test.com', 'user3@test.com']})
    df.write_ndjson(ndjson_path)
    return ndjson_path


@pytest.fixture(scope='function')
def sample_json_file(temp_upload_dir: Path) -> Path:
    import polars as pl

    json_path = temp_upload_dir / 'sample.json'
    df = pl.DataFrame({'user_id': [1, 2, 3], 'username': ['user1', 'user2', 'user3'], 'email': ['user1@test.com', 'user2@test.com', 'user3@test.com']})
    df.write_json(json_path)
    return json_path


@pytest.fixture(scope='function')
def sample_datasource(test_db_session: Session, sample_csv_file: Path) -> DataSource:
    from contracts.datasource.models import DataSource

    datasource_id = str(uuid.uuid4())
    config = {'file_path': str(sample_csv_file), 'file_type': 'csv', 'options': {}}

    datasource = DataSource(
        id=datasource_id, name='Test DataSource', description='Fixture datasource description', source_type='file', config=config, created_at=datetime.now(UTC)
    )

    test_db_session.add(datasource)
    test_db_session.commit()
    test_db_session.refresh(datasource)

    return datasource


@pytest.fixture(scope='function')
def sample_datasources(test_db_session: Session, sample_csv_file: Path, sample_parquet_file: Path) -> list[DataSource]:
    from contracts.datasource.models import DataSource

    datasources = []

    for file_path, file_type, name in [(sample_csv_file, 'csv', 'CSV DataSource'), (sample_parquet_file, 'parquet', 'Parquet DataSource')]:
        datasource_id = str(uuid.uuid4())
        config = {'file_path': str(file_path), 'file_type': file_type, 'options': {}}

        datasource = DataSource(id=datasource_id, name=name, description=f'{name} description', source_type='file', config=config, created_at=datetime.now(UTC))

        test_db_session.add(datasource)
        datasources.append(datasource)

    test_db_session.commit()

    for datasource in datasources:
        test_db_session.refresh(datasource)

    return datasources


@pytest.fixture(scope='function')
def sample_analysis(test_db_session: Session, sample_datasource: DataSource) -> Analysis:
    from contracts.analysis.models import Analysis, AnalysisDataSource, AnalysisStatus

    analysis_id = str(uuid.uuid4())
    tab1_result_id = str(uuid.uuid4())

    pipeline_definition = {
        'tabs': [
            {
                'id': 'tab1',
                'name': 'Source',
                'parent_id': None,
                'datasource': {'id': sample_datasource.id, 'analysis_tab_id': None, 'config': {'branch': 'master'}},
                'output': {'result_id': tab1_result_id, 'datasource_type': 'iceberg', 'format': 'parquet', 'filename': 'fixture_output'},
                'steps': [{'id': 'step1', 'type': 'filter', 'config': {'column': 'age', 'operator': '>', 'value': 30}, 'depends_on': []}],
            }
        ]
    }

    now = datetime.now(UTC)
    analysis = Analysis(
        id=analysis_id,
        name='Test Analysis',
        description='Test analysis description',
        pipeline_definition=pipeline_definition,
        status=AnalysisStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )

    test_db_session.add(analysis)
    test_db_session.add(AnalysisDataSource(analysis_id=analysis_id, datasource_id=sample_datasource.id))
    test_db_session.commit()
    test_db_session.refresh(analysis)

    return analysis


@pytest.fixture(scope='function')
def sample_analyses(test_db_session: Session, sample_datasources: list[DataSource]) -> list[Analysis]:
    from contracts.analysis.models import Analysis, AnalysisDataSource, AnalysisStatus

    analyses = []

    for idx in range(3):
        analysis_id = str(uuid.uuid4())
        pipeline_definition = {
            'tabs': [
                {
                    'id': f'tab-{idx}',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {'id': sample_datasources[0].id, 'analysis_tab_id': None, 'config': {'branch': 'master'}},
                    'output': {'result_id': str(uuid.uuid4()), 'datasource_type': 'iceberg', 'format': 'parquet', 'filename': 'fixture_output'},
                    'steps': [{'id': f'step{idx}', 'type': 'filter', 'config': {'column': 'id', 'operator': '>', 'value': idx}, 'depends_on': []}],
                }
            ]
        }

        now = datetime.now(UTC)
        analysis = Analysis(
            id=analysis_id,
            name=f'Analysis {idx + 1}',
            description=f'Analysis {idx + 1} description',
            pipeline_definition=pipeline_definition,
            status=AnalysisStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )

        test_db_session.add(analysis)
        test_db_session.add(AnalysisDataSource(analysis_id=analysis_id, datasource_id=sample_datasources[0].id))
        analyses.append(analysis)

    test_db_session.commit()

    for analysis in analyses:
        test_db_session.refresh(analysis)

    return analyses


@pytest.fixture(scope='function')
def mock_file_upload() -> dict[str, str | bytes]:
    content = b'id,name,age\n1,Alice,25\n2,Bob,30\n'
    return {'filename': 'test.csv', 'content': content, 'content_type': 'text/csv'}
