from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import boto3  # type: ignore[import-untyped]
import pytest
from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from tests.harness.postgres_harness import (
    ExternalPostgres,
    PostgresContainer,
    RustfsContainer,
    cleanup_stale_test_postgres,
    cleanup_stale_test_rustfs,
    docker_available,
    require_docker,
)

if TYPE_CHECKING:
    from backend_core.persistence.analysis.models import Analysis
    from backend_core.persistence.datasource.models import DataSource


def pytest_sessionstart(session: pytest.Session) -> None:
    os.environ.pop('POLARS_MAX_THREADS', None)
    os.environ.pop('POLARS_STREAMING_CHUNK_SIZE', None)
    os.environ.setdefault('ENV_FILE', '')
    os.environ.setdefault('SETTINGS_ENCRYPTION_KEY', 'test-key')
    os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg://dataforge:dataforge@127.0.0.1:5432/dataforge')
    if os.environ.get('TEST_POSTGRES_URL'):
        return
    if docker_available():
        cleanup_stale_test_postgres()
        cleanup_stale_test_rustfs()


def _settings():
    from backend_core.config import settings

    return settings


def _filter_config(column: str, operator: str, value: object) -> dict[str, object]:
    return {
        'conditions': [
            {
                'column': column,
                'operator': operator,
                'value': value,
            }
        ],
        'logic': 'AND',
    }


def _register_sqlmodel_metadata() -> None:
    from backend_core.persistence.analysis.models import Analysis, AnalysisDataSource, AnalysisFavorite
    from backend_core.persistence.analysis_versions.models import AnalysisVersion
    from backend_core.persistence.build_jobs.models import BuildJob
    from backend_core.persistence.build_runs.models import BuildEvent, BuildRun
    from backend_core.persistence.datasource.models import DataSource, DataSourceColumnMetadata
    from backend_core.persistence.engine_instances.models import EngineInstance
    from backend_core.persistence.engine_runs.models import EngineRun
    from backend_core.persistence.healthchecks.models import HealthCheck, HealthCheckResult
    from backend_core.persistence.locks.models import ResourceLock
    from backend_core.persistence.namespaces.models import RuntimeNamespace
    from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent
    from backend_core.persistence.runtime_workers.models import RuntimeWorker
    from backend_core.persistence.scheduler.models import Schedule
    from backend_core.persistence.settings.models import AppSettings
    from backend_core.persistence.telegram.models import TelegramListener, TelegramSubscriber
    from backend_core.persistence.udfs.models import Udf

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
    del RuntimeOutboxEvent
    del RuntimeWorker
    del Schedule
    del TelegramListener
    del TelegramSubscriber
    del Udf


def _settings_tables() -> list[Any]:
    from backend_core.persistence.engine_instances.models import EngineInstance
    from backend_core.persistence.namespaces.models import RuntimeNamespace
    from backend_core.persistence.runtime_workers.models import RuntimeWorker
    from backend_core.persistence.settings.models import AppSettings

    table_names = {AppSettings.__tablename__, EngineInstance.__tablename__, RuntimeWorker.__tablename__, RuntimeNamespace.__tablename__}
    return [table for table in AppSettings.metadata.sorted_tables if table.name in table_names]


def _reset_settings_state(engine: Engine) -> None:
    from backend_core.settings_projection import invalidate_resolved_settings_cache

    with engine.begin() as conn:
        for table in reversed(_settings_tables()):
            conn.execute(table.delete())

    invalidate_resolved_settings_cache()


@pytest.fixture(scope='session')
def rustfs_container() -> Generator[RustfsContainer]:
    require_docker()
    with RustfsContainer() as container:
        yield container


@pytest.fixture(scope='session')
def postgres_container() -> Generator[ExternalPostgres | PostgresContainer]:
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
    from backend_core import database

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
    from backend_core.database import clear_engine_override, set_engine_override

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
def isolate_data_dir(tmp_path: Path, monkeypatch, postgres_container: PostgresContainer, rustfs_container: RustfsContainer):
    settings = _settings()
    data_dir = tmp_path / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('ENV_FILE', '')
    monkeypatch.setenv('SETTINGS_ENCRYPTION_KEY', 'test-key')
    monkeypatch.setenv('DATA_DIR', str(data_dir))
    monkeypatch.setenv('DATABASE_URL', postgres_container.url)
    monkeypatch.setenv('OBJECT_STORE_ENDPOINT', rustfs_container.endpoint)
    monkeypatch.setenv('OBJECT_STORE_REGION', 'us-east-1')
    monkeypatch.setenv('OBJECT_STORE_ACCESS_KEY', rustfs_container.access_key)
    monkeypatch.setenv('OBJECT_STORE_SECRET_KEY', rustfs_container.secret_key)
    monkeypatch.setenv('OBJECT_STORE_BUCKET', rustfs_container.bucket)
    monkeypatch.setenv('OBJECT_STORE_PREFIX', 'dataforge-tests')
    monkeypatch.setattr(settings, 'settings_encryption_key', 'test-key', raising=False)
    monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
    monkeypatch.setattr(settings, 'database_url', postgres_container.url, raising=False)
    monkeypatch.setattr(settings, 'object_store_endpoint', rustfs_container.endpoint, raising=False)
    monkeypatch.setattr(settings, 'object_store_region', 'us-east-1', raising=False)
    monkeypatch.setattr(settings, 'object_store_access_key', rustfs_container.access_key, raising=False)
    monkeypatch.setattr(settings, 'object_store_secret_key', rustfs_container.secret_key, raising=False)
    monkeypatch.setattr(settings, 'object_store_bucket', rustfs_container.bucket, raising=False)
    monkeypatch.setattr(settings, 'object_store_prefix', 'dataforge-tests', raising=False)


class _TestWorkerDataPlaneClient:
    def __init__(self) -> None:
        self._client = None

    def _settings(self):
        return _settings()

    def _s3(self):
        if self._client is None:
            settings = self._settings()
            self._client = boto3.client(
                's3',
                endpoint_url=settings.object_store_endpoint,
                region_name=settings.object_store_region,
                aws_access_key_id=settings.object_store_access_key,
                aws_secret_access_key=settings.object_store_secret_key,
                config=BotoConfig(s3={'addressing_style': 'path'}),
            )
        return self._client

    def _ensure_bucket_exists(self) -> None:
        settings = self._settings()
        try:
            self._s3().head_bucket(Bucket=settings.object_store_bucket)
        except ClientError as exc:
            error = exc.response.get('Error', {}) if isinstance(exc.response, dict) else {}
            code = str(error.get('Code') or '')
            if code not in {'404', 'NoSuchBucket', 'NotFound'}:
                raise
            self._s3().create_bucket(Bucket=settings.object_store_bucket)

    @staticmethod
    def _parse_object_url(url: str) -> tuple[str, str]:
        parsed = urlparse(url)
        if parsed.scheme.lower() != 's3' or not parsed.netloc or not parsed.path.lstrip('/'):
            raise ValueError(f'Object storage URL must be s3://bucket/key, got: {url}')
        return parsed.netloc, parsed.path.lstrip('/')

    def classify_object_url(self, value: str) -> Any:
        from backend_core.data_plane_client import ObjectStoreUrlClassification

        try:
            bucket, key = self._parse_object_url(value)
        except ValueError:
            return ObjectStoreUrlClassification(is_object_store=False, is_managed=False, object_url=None)
        settings = self._settings()
        prefix = settings.object_store_prefix.strip('/').strip()
        is_managed = bucket == settings.object_store_bucket and (key == prefix or key.startswith(prefix + '/'))
        return ObjectStoreUrlClassification(is_object_store=True, is_managed=is_managed, object_url=value)

    def build_object_url(self, *parts: str, bucket: str | None = None) -> str:
        settings = self._settings()
        cleaned = [settings.object_store_prefix.strip('/').strip(), *(part.strip('/') for part in parts if part.strip('/'))]
        key = '/'.join(part for part in cleaned if part)
        return f's3://{bucket or settings.object_store_bucket}/{key}'

    def join_object_url(self, base_url: str, *parts: str) -> str:
        bucket, key = self._parse_object_url(base_url)
        suffix = '/'.join(part.strip('/') for part in parts if part.strip('/'))
        return f's3://{bucket}/{"/".join(part for part in (key.rstrip("/"), suffix) if part)}'

    def read_object_store_storage_options(self) -> dict[str, object]:
        settings = self._settings()
        return {
            's3.endpoint': settings.object_store_endpoint,
            's3.access-key-id': settings.object_store_access_key,
            's3.secret-access-key': settings.object_store_secret_key,
            's3.region': settings.object_store_region,
            's3.force-virtual-addressing': False,
            'py-io-impl': 'pyiceberg.io.pyarrow.PyArrowFileIO',
        }

    def upload_object_bytes(self, data: bytes, target_url: str, *, content_type: str | None = None) -> str:
        self._ensure_bucket_exists()
        bucket, key = self._parse_object_url(target_url)
        kwargs: dict[str, object] = {'Bucket': bucket, 'Key': key, 'Body': data}
        if content_type is not None:
            kwargs['ContentType'] = content_type
        self._s3().put_object(**kwargs)
        return target_url

    def download_object_bytes(self, source_url: str) -> bytes:
        bucket, key = self._parse_object_url(source_url)
        response = self._s3().get_object(Bucket=bucket, Key=key)
        return response['Body'].read()

    def delete_object(self, source_url: str) -> None:
        bucket, key = self._parse_object_url(source_url)
        self._s3().delete_object(Bucket=bucket, Key=key)

    def object_exists(self, source_url: str) -> bool:
        bucket, key = self._parse_object_url(source_url)
        try:
            self._s3().head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            error = exc.response.get('Error', {}) if isinstance(exc.response, dict) else {}
            code = str(error.get('Code') or '')
            if code in {'404', 'NoSuchKey', 'NotFound'}:
                return False
            raise
        return True

    def list_prefixes(self, prefix_url: str) -> list[str]:
        bucket, key = self._parse_object_url(prefix_url)
        prefix = key.rstrip('/')
        if prefix:
            prefix = prefix + '/'
        response = self._s3().list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter='/')
        names: list[str] = []
        for item in response.get('CommonPrefixes') or []:
            value = item.get('Prefix') if isinstance(item, dict) else None
            if not isinstance(value, str):
                continue
            suffix = value[len(prefix) :].strip('/')
            if suffix:
                names.append(suffix)
        return sorted(names)

    def list_metadata_files(self, base_url: str) -> list[str]:
        bucket, key = self._parse_object_url(base_url)
        prefix = key.rstrip('/')
        if prefix and not prefix.endswith('/metadata') and '/metadata/' not in prefix:
            prefix = prefix + '/metadata'
        prefix = prefix.rstrip('/') + '/'
        paginator = self._s3().get_paginator('list_objects_v2')
        results: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get('Contents') or []:
                object_key = item.get('Key') if isinstance(item, dict) else None
                if isinstance(object_key, str) and object_key.endswith('.metadata.json'):
                    results.append(f's3://{bucket}/{object_key}')
        return sorted(results)

    def delete_managed_prefix(self, prefix_url: str) -> None:
        bucket, key = self._parse_object_url(prefix_url)
        prefix = key.rstrip('/')
        if prefix:
            prefix = prefix + '/'
        paginator = self._s3().get_paginator('list_objects_v2')
        batch: list[dict[str, str]] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get('Contents') or []:
                object_key = item.get('Key') if isinstance(item, dict) else None
                if not isinstance(object_key, str):
                    continue
                batch.append({'Key': object_key})
                if len(batch) == 1000:
                    self._s3().delete_objects(Bucket=bucket, Delete={'Objects': batch})
                    batch = []
        if batch:
            self._s3().delete_objects(Bucket=bucket, Delete={'Objects': batch})

    def resolve_metadata_path(self, *, namespace: str, metadata_path: str, datasource_id: str | None = None) -> str:
        del namespace, datasource_id
        if metadata_path.endswith('.metadata.json'):
            if not self.object_exists(metadata_path):
                raise ValueError(f'Iceberg metadata_path not found: {metadata_path}')
            return metadata_path
        files = self.list_metadata_files(metadata_path)
        if not files:
            raise ValueError(f'Iceberg metadata_path not found: {metadata_path}')
        return files[-1]

    def resolve_branch_metadata_path(
        self,
        *,
        namespace: str,
        metadata_path: str,
        datasource_id: str | None = None,
        branch: str | None = None,
    ) -> str:
        del namespace, datasource_id
        if metadata_path.endswith('.metadata.json'):
            return self.resolve_metadata_path(metadata_path=metadata_path, namespace='test')
        if branch:
            branch_url = self.join_object_url(metadata_path, branch)
            if self.list_metadata_files(branch_url):
                return self.resolve_metadata_path(metadata_path=branch_url, namespace='test')
        return self.resolve_metadata_path(metadata_path=metadata_path, namespace='test')

    def scan_snapshot(self, *, metadata_path: str, snapshot_id: str, limit: int | None = None) -> list[dict[str, object]]:
        import polars as pl
        from pyiceberg.table import StaticTable

        table = StaticTable.from_metadata(metadata_path, properties=self.read_object_store_storage_options())
        frame = pl.from_arrow(table.scan(snapshot_id=int(snapshot_id)).to_arrow())
        if isinstance(frame, pl.Series):
            frame = frame.to_frame()
        if limit is not None:
            frame = frame.head(limit)
        return frame.to_dicts()

    def sync_table_schema(self, *, metadata_path: str, schema_payload: dict[str, object]) -> None:
        del metadata_path, schema_payload

    def list_snapshots(self, *, namespace: str, datasource_id: str, branch: str | None = None):
        from backend_core.data_plane_client import IcebergSnapshots

        del namespace, branch
        return IcebergSnapshots(datasource_id=datasource_id, table_path='', snapshots=[])

    def delete_snapshot(self, *, namespace: str, datasource_id: str, snapshot_id: str) -> str:
        del namespace, datasource_id
        return snapshot_id


@pytest.fixture(autouse=True, scope='function')
def use_test_worker_data_plane(monkeypatch, isolate_data_dir) -> Generator[None]:
    client = _TestWorkerDataPlaneClient()
    from backend_core import data_plane_client

    monkeypatch.setattr(data_plane_client, 'WorkerDataPlaneClient', lambda: client)
    yield


@pytest.fixture(autouse=True, scope='function')
def isolate_settings_engine(
    request: pytest.FixtureRequest, tmp_path: Path, isolate_data_dir, postgres_container: PostgresContainer
) -> Generator[Engine | None]:
    if '/backend/tests/' in request.node.path.as_posix():
        yield None
        return

    from backend_core import database
    from backend_core.persistence.settings.models import AppSettings

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
    from backend_core import database

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


def _upload_test_object(local_path: Path) -> str:
    from backend_core.data_plane_client import client_from_settings

    data_plane = client_from_settings()
    target_url = data_plane.build_object_url('tests', uuid.uuid4().hex, local_path.name)
    data_plane.upload_object_bytes(local_path.read_bytes(), target_url)
    return target_url


@pytest.fixture(scope='function')
def sample_csv_object_url(sample_csv_file: Path) -> str:
    return _upload_test_object(sample_csv_file)


@pytest.fixture(scope='function')
def sample_parquet_object_url(sample_parquet_file: Path) -> str:
    return _upload_test_object(sample_parquet_file)


@pytest.fixture(scope='function')
def sample_ndjson_object_url(sample_ndjson_file: Path) -> str:
    return _upload_test_object(sample_ndjson_file)


@pytest.fixture(scope='function')
def sample_json_object_url(sample_json_file: Path) -> str:
    return _upload_test_object(sample_json_file)


@pytest.fixture(scope='function')
def sample_datasource(test_db_session: Session, sample_csv_object_url: str) -> DataSource:
    from backend_core.persistence.datasource.models import DataSource

    datasource_id = str(uuid.uuid4())
    config = {'file_path': sample_csv_object_url, 'file_type': 'csv', 'options': {}}

    datasource = DataSource(
        id=datasource_id, name='Test DataSource', description='Fixture datasource description', source_type='file', config=config, created_at=datetime.now(UTC)
    )

    test_db_session.add(datasource)
    test_db_session.commit()
    test_db_session.refresh(datasource)

    return datasource


@pytest.fixture(scope='function')
def sample_datasources(test_db_session: Session, sample_csv_object_url: str, sample_parquet_object_url: str) -> list[DataSource]:
    from backend_core.persistence.datasource.models import DataSource

    datasources = []

    for file_path, file_type, name in [(sample_csv_object_url, 'csv', 'CSV DataSource'), (sample_parquet_object_url, 'parquet', 'Parquet DataSource')]:
        datasource_id = str(uuid.uuid4())
        config = {'file_path': file_path, 'file_type': file_type, 'options': {}}

        datasource = DataSource(id=datasource_id, name=name, description=f'{name} description', source_type='file', config=config, created_at=datetime.now(UTC))

        test_db_session.add(datasource)
        datasources.append(datasource)

    test_db_session.commit()

    for datasource in datasources:
        test_db_session.refresh(datasource)

    return datasources


@pytest.fixture(scope='function')
def sample_analysis(test_db_session: Session, sample_datasource: DataSource) -> Analysis:
    from backend_core.domain.analysis.models import AnalysisStatus
    from backend_core.persistence.analysis.models import Analysis, AnalysisDataSource

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
                'steps': [{'id': 'step1', 'type': 'filter', 'config': _filter_config('age', '>', 30), 'depends_on': []}],
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
    from backend_core.domain.analysis.models import AnalysisStatus
    from backend_core.persistence.analysis.models import Analysis, AnalysisDataSource

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
                    'steps': [{'id': f'step{idx}', 'type': 'filter', 'config': _filter_config('id', '>', idx), 'depends_on': []}],
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
