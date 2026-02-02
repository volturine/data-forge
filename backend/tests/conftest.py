import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.database import Base, get_db
from main import app
from modules.analysis.models import Analysis, AnalysisDataSource
from modules.datasource.models import DataSource


@pytest.fixture(scope='function')
async def test_engine():
    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture(scope='function')
async def test_db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    AsyncTestingSessionLocal = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with AsyncTestingSessionLocal() as session:
        yield session


@pytest.fixture(scope='function')
async def client(test_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(scope='function')
def temp_upload_dir(tmp_path: Path) -> Path:
    upload_dir = tmp_path / 'uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


@pytest.fixture(scope='function')
def sample_csv_file(temp_upload_dir: Path) -> Path:
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
async def sample_datasource(test_db_session: AsyncSession, sample_csv_file: Path) -> DataSource:
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
    await test_db_session.commit()
    await test_db_session.refresh(datasource)

    return datasource


@pytest.fixture(scope='function')
async def sample_datasources(test_db_session: AsyncSession, sample_csv_file: Path, sample_parquet_file: Path) -> list[DataSource]:
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

    await test_db_session.commit()

    for datasource in datasources:
        await test_db_session.refresh(datasource)

    return datasources


@pytest.fixture(scope='function')
async def sample_analysis(test_db_session: AsyncSession, sample_datasource: DataSource) -> Analysis:
    analysis_id = str(uuid.uuid4())

    pipeline_definition = {
        'steps': [
            {
                'id': 'step1',
                'type': 'filter',
                'config': {'column': 'age', 'operator': '>', 'value': 30},
                'depends_on': [],
            }
        ],
        'datasource_ids': [sample_datasource.id],
        'tabs': [
            {
                'id': 'tab1',
                'name': 'Source',
                'type': 'datasource',
                'parent_id': None,
                'datasource_id': sample_datasource.id,
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

    await test_db_session.commit()
    await test_db_session.refresh(analysis)

    return analysis


@pytest.fixture(scope='function')
async def sample_analyses(test_db_session: AsyncSession, sample_datasources: list[DataSource]) -> list[Analysis]:
    analyses = []

    for idx in range(3):
        analysis_id = str(uuid.uuid4())

        pipeline_definition = {
            'steps': [
                {
                    'id': f'step{idx}',
                    'type': 'filter',
                    'config': {'column': 'id', 'operator': '>', 'value': idx},
                    'depends_on': [],
                }
            ],
            'datasource_ids': [sample_datasources[0].id],
            'tabs': [
                {
                    'id': f'tab-{idx}',
                    'name': 'Source',
                    'type': 'datasource',
                    'parent_id': None,
                    'datasource_id': sample_datasources[0].id,
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

    await test_db_session.commit()

    for analysis in analyses:
        await test_db_session.refresh(analysis)

    return analyses


@pytest.fixture(scope='function')
def mock_file_upload() -> dict[str, str | bytes]:
    content = b'id,name,age\n1,Alice,25\n2,Bob,30\n'
    return {
        'filename': 'test.csv',
        'content': content,
        'content_type': 'text/csv',
    }
