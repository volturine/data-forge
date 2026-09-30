from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from openpyxl.utils.cell import range_boundaries
from sqlmodel import Session

from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.persistence.datasource.models import DataSource
from dataforge_protocol import datasource_pb2
from modules.datasource.schema_protocol import schema_info_payload


class FauxDatasourceRuntime:
    def __init__(self) -> None:
        self.preflights: dict[str, Any] = {}
        self.preflight_calls: list[tuple[str, dict[str, object]]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from modules.datasource import preflight, routes

        monkeypatch.setattr(routes, 'create_remote_file_datasource', self.create_file_datasource)
        monkeypatch.setattr(routes, 'create_remote_database_datasource', self.create_database_datasource)
        monkeypatch.setattr(routes, 'create_remote_iceberg_datasource', self.create_iceberg_datasource)
        monkeypatch.setattr(routes, 'get_remote_datasource_schema', self.get_datasource_schema)
        monkeypatch.setattr(routes, 'ingest_remote_datasource', self.ingest_datasource)
        monkeypatch.setattr(routes, 'get_remote_column_stats', self.get_column_stats)
        monkeypatch.setattr(preflight, 'create_preflight', self.create_preflight)
        monkeypatch.setattr(preflight, 'get_preflight', self.get_preflight)
        monkeypatch.setattr(preflight, 'clear_preflight', self.clear_preflight)
        monkeypatch.setattr(preflight, 'execute_excel_preflight', self.execute_excel_preflight)
        monkeypatch.setattr(routes, 'create_preflight', self.create_preflight)
        monkeypatch.setattr(routes, 'get_preflight', self.get_preflight)
        monkeypatch.setattr(routes, 'clear_preflight', self.clear_preflight)
        monkeypatch.setattr(routes, 'execute_excel_preflight', self.execute_excel_preflight)

    async def create_preflight(
        self,
        *,
        source_path: str,
        selection: dict[str, object],
        runtime_probe: object,
        delete_source: bool,
    ) -> tuple[str, Any, dict[str, object]]:
        from modules.datasource.preflight import ExcelPreflight

        del runtime_probe
        preflight_id = str(uuid.uuid4())
        self.preflight_calls.append(('initial', dict(selection)))
        preflight = ExcelPreflight(
            source_path=source_path,
            sheets=['Sheet1'],
            tables={},
            named_ranges=[],
            created_at=datetime.now(UTC).replace(tzinfo=None),
            delete_source=delete_source,
        )
        self.preflights[preflight_id] = preflight
        return preflight_id, preflight, self._preflight_result(selection)

    async def get_preflight(self, preflight_id: str) -> Any | None:
        return self.preflights.get(preflight_id)

    async def clear_preflight(self, preflight_id: str, *, delete_source: bool = True) -> None:
        del delete_source
        self.preflights.pop(preflight_id, None)

    async def execute_excel_preflight(
        self,
        *,
        preflight_id: str,
        source_path: str,
        action: int,
        selection: dict[str, object],
        runtime_probe: object,
        delete_source: bool = False,
        datasource_id: str | None = None,
    ) -> dict[str, object]:
        del preflight_id, source_path, runtime_probe, delete_source, datasource_id
        self.preflight_calls.append((str(action), dict(selection)))
        return self._preflight_result(selection)

    @staticmethod
    def _preflight_result(selection: dict[str, object]) -> dict[str, object]:
        def selection_int(key: str, default: int) -> int:
            value = selection.get(key)
            return value if isinstance(value, int) else default

        cell_range = selection.get('cell_range')
        if isinstance(cell_range, str) and cell_range:
            bounds_text = cell_range.rsplit('!', 1)[-1]
            min_col, min_row, max_col, max_row = range_boundaries(bounds_text)
            min_col = min_col or 1
            min_row = min_row or 1
            max_col = max_col or min_col
            max_row = max_row or min_row
            start_row, start_col = min_row - 1, min_col - 1
            end_row, end_col = max_row - 1, max_col - 1
        else:
            start_row = selection_int('start_row', 0)
            start_col = selection_int('start_col', 0)
            end_col = selection_int('end_col', 1)
            end_row = selection_int('end_row', 2)
        return {
            'sheet_name': selection.get('sheet_name') or 'Sheet1',
            'start_row': start_row,
            'start_col': start_col,
            'end_col': end_col,
            'detected_end_row': end_row,
            'preview_rows': [
                {'cells': ['id', 'name']},
                {'cells': ['1', 'A']},
                {'cells': ['2', 'B']},
            ],
        }

    async def create_file_datasource(
        self,
        *,
        name: str,
        description: str | None,
        file_path: str,
        file_type: str,
        options: dict[str, Any] | None = None,
        csv_options: dict[str, object] | None = None,
        owner_id: str | None = None,
        **kwargs: Any,
    ):
        from backend_core.database import run_db

        def _work(session: Session):
            from backend_core.data_plane_client import client_from_settings
            from backend_core.namespace import get_namespace

            data_plane = client_from_settings()
            metadata_root = data_plane.build_object_url('clean', uuid.uuid4().hex, 'master', namespace=get_namespace())
            data_plane.upload_object_bytes(
                b'{"metadata":"placeholder"}',
                data_plane.join_object_url(metadata_root, 'metadata', '00000-placeholder.metadata.json'),
            )

            datasource = DataSource(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                source_type=DataSourceType.ICEBERG,
                config={
                    'metadata_path': metadata_root,
                    'branch': 'master',
                    'source': {
                        'source_type': 'file',
                        'file_path': file_path,
                        'file_type': file_type,
                        'options': options or csv_options or {},
                        **{key: value for key, value in kwargs.items() if value is not None and key not in {'runtime_probe', 'branch'}},
                    },
                },
                owner_id=owner_id,
                created_by='import',
                created_at=datetime.now(UTC),
            )
            datasource.schema_cache = schema_info_payload(self._schema_for(datasource))
            session.add(datasource)
            session.commit()
            session.refresh(datasource)
            return self._response(datasource)

        return await asyncio.to_thread(run_db, _work)

    async def create_database_datasource(
        self,
        *,
        name: str,
        description: str | None,
        connection_string: str,
        query: str,
        branch: str,
        owner_id: str | None = None,
        **kwargs: Any,
    ):
        from backend_core.database import run_db

        def _work(session: Session):
            datasource = DataSource(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                source_type=DataSourceType.DATABASE,
                config={
                    'connection_string': connection_string,
                    'query': query,
                    'branch': branch,
                },
                owner_id=owner_id,
                created_by='import',
                created_at=datetime.now(UTC),
            )
            session.add(datasource)
            session.commit()
            session.refresh(datasource)
            return self._response(datasource)

        return await asyncio.to_thread(run_db, _work)

    async def create_iceberg_datasource(
        self,
        *,
        name: str,
        description: str | None,
        source: dict[str, object],
        branch: str,
        owner_id: str | None = None,
        **kwargs: Any,
    ):
        return await self.create_file_datasource(
            name=name,
            description=description,
            file_path=str(source.get('file_path')),
            file_type=str(source.get('file_type', 'csv')),
            options=self._source_options(source),
            owner_id=owner_id,
            branch=branch,
            **kwargs,
        )

    async def get_datasource_schema(self, *, datasource_id: str, **kwargs: Any):
        from backend_core.database import run_db

        def _work(session: Session):
            datasource = self._get_datasource(session, datasource_id)
            schema = self._schema_for(datasource)
            datasource.schema_cache = schema_info_payload(schema)
            session.add(datasource)
            session.commit()
            return schema

        return await asyncio.to_thread(run_db, _work)

    async def ingest_datasource(self, *, datasource_id: str, **kwargs: Any):
        from backend_core.database import run_db

        def _work(session: Session):
            datasource = self._get_datasource(session, datasource_id)
            datasource.schema_cache = schema_info_payload(self._schema_for(datasource))
            session.add(datasource)
            session.commit()
            session.refresh(datasource)
            return self._response(datasource)

        return await asyncio.to_thread(run_db, _work)

    async def get_column_stats(self, *, datasource_id: str, column_name: str, **kwargs: Any):
        from backend_core.database import run_db

        def _work(session: Session):
            from modules.datasource import schemas

            datasource = self._get_datasource(session, datasource_id)
            series = self._read_dataframe(datasource)[column_name]
            count = len(series)
            null_count = series.null_count()
            return schemas.ColumnStatsResponse(
                column=column_name,
                dtype=str(series.dtype),
                count=count,
                null_count=null_count,
                null_percentage=(null_count / count * 100) if count else 0,
                unique=series.n_unique(),
                min=self._stat_value(series.min()),
                max=self._stat_value(series.max()),
            )

        return await asyncio.to_thread(run_db, _work)

    def _source_options(self, source: dict[str, object]) -> dict[str, Any]:
        options = source.get('options')
        return options if isinstance(options, dict) else {}

    def _stat_value(self, value: object) -> float | str | None:
        if value is None or isinstance(value, (float, str)):
            return value
        if isinstance(value, int):
            return float(value)
        return str(value)

    def _get_datasource(self, session: Session, datasource_id: str) -> DataSource:
        datasource = session.get(DataSource, datasource_id)
        if datasource is None:
            from backend_core.exceptions import datasource_not_found

            raise datasource_not_found(datasource_id)
        return datasource

    def _schema_for(self, datasource: DataSource) -> datasource_pb2.SchemaInfo:
        df = self._read_dataframe(datasource)
        schema = datasource_pb2.SchemaInfo(row_count=df.height)
        for name, dtype in zip(df.columns, df.dtypes, strict=True):
            column = schema.columns.add(name=name, dtype=str(dtype), nullable=True)
            if df.height > 0:
                column.sample_value = str(df[name][0])
        return schema

    def _response(self, datasource: DataSource):
        from modules.datasource import schemas

        response = schemas.DataSourceResponse.model_validate(datasource)
        response.output_of_tab_id = datasource.config.get('analysis_tab_id') if isinstance(datasource.config, dict) else None
        return response

    @contextlib.contextmanager
    def _materialized_source_path(self, file_path: str):
        from backend_core.data_plane_client import client_from_settings

        data_plane = client_from_settings()
        if not data_plane.classify_object_url(file_path).is_object_store:
            yield file_path
            return
        suffix = Path(file_path).suffix or '.dat'
        fd, temp_name = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_bytes(data_plane.download_object_bytes(file_path))
            yield str(temp_path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temp_path.unlink()

    def _read_dataframe(self, datasource: DataSource) -> pl.DataFrame:
        config = datasource.config if isinstance(datasource.config, dict) else {}
        source = config.get('source') if datasource.source_type == DataSourceType.ICEBERG else config
        if not isinstance(source, dict):
            source = config
        file_path = source.get('file_path')
        file_type = source.get('file_type')
        if not isinstance(file_path, str):
            return pl.DataFrame()
        with self._materialized_source_path(file_path) as local_file_path:
            if file_type == 'parquet':
                return pl.read_parquet(local_file_path)
            if file_type == 'json':
                return pl.read_json(local_file_path)
            if file_type == 'ndjson':
                return pl.read_ndjson(local_file_path)
            if file_type == 'excel':
                return pl.read_excel(local_file_path)
            return pl.read_csv(local_file_path)
