from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

if TYPE_CHECKING:
    from modules.analysis.models import Analysis
    from modules.auth.models import User
    from modules.datasource.models import DataSource


def pytest_sessionstart(session: pytest.Session) -> None:
    os.environ.pop('POLARS_MAX_THREADS', None)
    os.environ.pop('POLARS_STREAMING_CHUNK_SIZE', None)
    os.environ.setdefault('ENV_FILE', '')


def _settings():
    from core.config import settings

    return settings


@pytest.fixture(scope='function')
def test_engine():
    from modules.udf.models import Udf

    del Udf
    engine = create_engine(
        'sqlite:///:memory:',
        echo=False,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture(scope='function')
def test_db_session(test_engine):
    from core.database import clear_engine_override, set_engine_override

    # Set the engine override so run_db uses the test engine
    set_engine_override(test_engine)
    with Session(test_engine) as session:
        yield session
    # Clear the override after the test
    clear_engine_override()


@pytest.fixture(scope='function')
def test_user() -> User:
    from modules.auth.models import User

    now = datetime.now(UTC)
    return User(
        id=uuid.uuid4().hex,
        email='test@example.com',
        display_name='Test User',
        status='active',
        email_verified=True,
        has_password=True,
        preferences={},
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(scope='function')
def client(test_db_session, test_user):
    from core.database import get_db
    from main import app
    from modules.auth.dependencies import get_current_user

    def override_get_db():
        yield test_db_session

    if hasattr(app.state, 'mcp_registry'):
        del app.state.mcp_registry
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    with TestClient(app) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(scope='function')
def temp_upload_dir(tmp_path: Path) -> Path:
    upload_dir = tmp_path / 'uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


@pytest.fixture(autouse=True, scope='function')
def isolate_data_dir(tmp_path: Path, monkeypatch):
    settings = _settings()
    data_dir = tmp_path / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir = data_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('ENV_FILE', '')
    monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
    monkeypatch.setattr(settings, 'settings_encryption_key', 'test-key', raising=False)
    monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
    monkeypatch.setattr(settings, 'database_url', f'sqlite:///{data_dir / "app.db"}', raising=False)
    monkeypatch.setattr(settings, 'log_sqlite_path', log_dir, raising=False)


@pytest.fixture(autouse=True, scope='function')
def isolate_settings_engine(isolate_data_dir, monkeypatch):
    from core import database
    from core.database import _run_settings_migrations
    from modules.settings.models import AppSettings

    settings = _settings()
    settings_db_path = settings.data_dir / 'app.db'
    settings_url = f'sqlite:///{settings_db_path}'
    engine = create_engine(
        settings_url,
        echo=False,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    AppSettings.metadata.create_all(engine)

    from modules.chat.sessions import ChatSession

    ChatSession.metadata.create_all(engine)
    _run_settings_migrations(engine)
    monkeypatch.setattr(settings, 'database_url', settings_url, raising=False)
    monkeypatch.setattr(database, 'settings_engine', engine, raising=False)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True, scope='function')
def cleanup_namespace_engines():
    from core import database

    yield
    for engine in database._namespace_engines.values():
        engine.dispose()
    database._namespace_engines.clear()


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
        {
            'product_id': [101, 102, 103],
            'product_name': ['Widget A', 'Widget B', 'Widget C'],
            'price': [10.99, 20.99, 30.99],
            'stock': [100, 50, 75],
        }
    )
    df.write_parquet(parquet_path)
    return parquet_path


@pytest.fixture(scope='function')
def sample_ndjson_file(temp_upload_dir: Path) -> Path:
    import polars as pl

    ndjson_path = temp_upload_dir / 'sample.ndjson'
    df = pl.DataFrame(
        {
            'user_id': [1, 2, 3],
            'username': ['user1', 'user2', 'user3'],
            'email': ['user1@test.com', 'user2@test.com', 'user3@test.com'],
        }
    )
    df.write_ndjson(ndjson_path)
    return ndjson_path


@pytest.fixture(scope='function')
def sample_json_file(temp_upload_dir: Path) -> Path:
    import polars as pl

    json_path = temp_upload_dir / 'sample.json'
    df = pl.DataFrame(
        {
            'user_id': [1, 2, 3],
            'username': ['user1', 'user2', 'user3'],
            'email': ['user1@test.com', 'user2@test.com', 'user3@test.com'],
        }
    )
    df.write_json(json_path)
    return json_path


@pytest.fixture(scope='function')
def sample_datasource(test_db_session: Session, sample_csv_file: Path) -> DataSource:
    from modules.datasource.models import DataSource

    datasource_id = str(uuid.uuid4())

    config = {
        'file_path': str(sample_csv_file),
        'file_type': 'csv',
        'options': {},
    }

    datasource = DataSource(
        id=datasource_id,
        name='Test DataSource',
        source_type='file',
        config=config,
        created_at=datetime.now(UTC),
    )

    test_db_session.add(datasource)
    test_db_session.commit()
    test_db_session.refresh(datasource)

    return datasource


@pytest.fixture(scope='function')
def sample_datasources(test_db_session: Session, sample_csv_file: Path, sample_parquet_file: Path) -> list[DataSource]:
    from modules.datasource.models import DataSource

    datasources = []

    for _idx, (file_path, file_type, name) in enumerate(
        [
            (sample_csv_file, 'csv', 'CSV DataSource'),
            (sample_parquet_file, 'parquet', 'Parquet DataSource'),
        ]
    ):
        datasource_id = str(uuid.uuid4())
        config = {
            'file_path': str(file_path),
            'file_type': file_type,
            'options': {},
        }

        datasource = DataSource(
            id=datasource_id,
            name=name,
            source_type='file',
            config=config,
            created_at=datetime.now(UTC),
        )

        test_db_session.add(datasource)
        datasources.append(datasource)

    test_db_session.commit()

    for datasource in datasources:
        test_db_session.refresh(datasource)

    return datasources


@pytest.fixture(scope='function')
def sample_analysis(test_db_session: Session, sample_datasource: DataSource) -> Analysis:
    from modules.analysis.models import Analysis, AnalysisDataSource

    analysis_id = str(uuid.uuid4())
    tab1_result_id = str(uuid.uuid4())

    pipeline_definition = {
        'tabs': [
            {
                'id': 'tab1',
                'name': 'Source',
                'parent_id': None,
                'datasource': {
                    'id': sample_datasource.id,
                    'analysis_tab_id': None,
                    'config': {'branch': 'master'},
                },
                'output': {
                    'result_id': tab1_result_id,
                    'datasource_type': 'iceberg',
                    'format': 'parquet',
                    'filename': 'fixture_output',
                },
                'steps': [
                    {
                        'id': 'step1',
                        'type': 'filter',
                        'config': {'column': 'age', 'operator': '>', 'value': 30},
                        'depends_on': [],
                    }
                ],
            }
        ],
    }

    now = datetime.now(UTC)
    analysis = Analysis(
        id=analysis_id,
        name='Test Analysis',
        description='Test analysis description',
        pipeline_definition=pipeline_definition,
        status='draft',
        created_at=now,
        updated_at=now,
    )

    test_db_session.add(analysis)

    link = AnalysisDataSource(
        analysis_id=analysis_id,
        datasource_id=sample_datasource.id,
    )
    test_db_session.add(link)

    test_db_session.commit()
    test_db_session.refresh(analysis)

    return analysis


@pytest.fixture(scope='function')
def sample_analyses(test_db_session: Session, sample_datasources: list[DataSource]) -> list[Analysis]:
    from modules.analysis.models import Analysis, AnalysisDataSource

    analyses = []

    for idx in range(3):
        analysis_id = str(uuid.uuid4())

        pipeline_definition = {
            'tabs': [
                {
                    'id': f'tab-{idx}',
                    'name': 'Source',
                    'parent_id': None,
                    'datasource': {
                        'id': sample_datasources[0].id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'fixture_output',
                    },
                    'steps': [
                        {
                            'id': f'step{idx}',
                            'type': 'filter',
                            'config': {'column': 'id', 'operator': '>', 'value': idx},
                            'depends_on': [],
                        }
                    ],
                }
            ],
        }

        now = datetime.now(UTC)
        analysis = Analysis(
            id=analysis_id,
            name=f'Analysis {idx + 1}',
            description=f'Analysis {idx + 1} description',
            pipeline_definition=pipeline_definition,
            status='draft',
            created_at=now,
            updated_at=now,
        )

        test_db_session.add(analysis)

        link = AnalysisDataSource(
            analysis_id=analysis_id,
            datasource_id=sample_datasources[0].id,
        )
        test_db_session.add(link)

        analyses.append(analysis)

    test_db_session.commit()

    for analysis in analyses:
        test_db_session.refresh(analysis)

    return analyses


@pytest.fixture(scope='function')
def mock_file_upload() -> dict[str, str | bytes]:
    content = b'id,name,age\n1,Alice,25\n2,Bob,30\n'
    return {
        'filename': 'test.csv',
        'content': content,
        'content_type': 'text/csv',
    }
