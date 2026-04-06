import uuid
from unittest.mock import MagicMock, patch

import pyarrow as pa  # type: ignore[import-untyped]
from pyiceberg.schema import Schema as IcebergSchema
from pyiceberg.types import NestedField, StringType
from sqlmodel import Session

from core.namespace import namespace_paths
from modules.compute.service import _sync_iceberg_schema, export_data
from modules.datasource.models import DataSource


class TestSyncIcebergSchema:
    def _make_table(self, iceberg_fields: list[NestedField]) -> tuple[MagicMock, MagicMock]:
        schema = IcebergSchema(*iceberg_fields)
        mock_table = MagicMock()
        mock_table.schema.return_value = schema
        mock_update = MagicMock()
        mock_table.update_schema.return_value = mock_update
        return mock_table, mock_update

    def test_no_changes_returns_false(self):
        table, update = self._make_table(
            [
                NestedField(1, 'a', StringType()),
                NestedField(2, 'b', StringType()),
            ],
        )
        new_schema = pa.schema([pa.field('a', pa.string()), pa.field('b', pa.string())])

        result = _sync_iceberg_schema(table, new_schema)

        assert result is False
        table.update_schema.assert_not_called()

    def test_delete_removed_columns(self):
        table, update = self._make_table(
            [
                NestedField(1, 'a', StringType()),
                NestedField(2, 'b', StringType()),
                NestedField(3, 'c', StringType()),
            ],
        )
        new_schema = pa.schema([pa.field('a', pa.string())])

        result = _sync_iceberg_schema(table, new_schema)

        assert result is True
        update.delete_column.assert_any_call('b')
        update.delete_column.assert_any_call('c')
        assert update.delete_column.call_count == 2
        update.commit.assert_called_once()

    def test_add_new_columns(self):
        table, update = self._make_table(
            [
                NestedField(1, 'a', StringType()),
            ],
        )
        new_schema = pa.schema([pa.field('a', pa.string()), pa.field('b', pa.int64()), pa.field('c', pa.float64())])

        result = _sync_iceberg_schema(table, new_schema)

        assert result is True
        update.union_by_name.assert_called_once_with(new_schema)
        update.commit.assert_called_once()

    def test_delete_and_add_combined(self):
        table, update = self._make_table(
            [
                NestedField(1, 'keep', StringType()),
                NestedField(2, 'remove', StringType()),
            ],
        )
        new_schema = pa.schema(
            [
                pa.field('keep', pa.string()),
                pa.field('new_col', pa.float64()),
            ],
        )

        result = _sync_iceberg_schema(table, new_schema)

        assert result is True
        update.delete_column.assert_called_once_with('remove')
        update.union_by_name.assert_called_once_with(new_schema)
        update.commit.assert_called_once()

    def test_only_deletions_no_union_call(self):
        table, update = self._make_table(
            [
                NestedField(1, 'a', StringType()),
                NestedField(2, 'b', StringType()),
            ],
        )
        new_schema = pa.schema([pa.field('a', pa.string())])

        _sync_iceberg_schema(table, new_schema)

        update.delete_column.assert_called_once_with('b')
        update.union_by_name.assert_not_called()
        update.commit.assert_called_once()


class TestBuildModeWiring:
    def _make_pipeline(self, datasource: DataSource, output_ds_id: str, build_mode: str = 'full') -> dict:
        return {
            'analysis_id': str(uuid.uuid4()),
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Test Tab',
                    'parent_id': None,
                    'datasource': {
                        'id': datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': output_ds_id,
                        'format': 'parquet',
                        'filename': 'test_out',
                        'iceberg': {'namespace': 'ns', 'table_name': 'tbl'},
                        'build_mode': build_mode,
                    },
                    'steps': [],
                },
            ],
            'sources': {
                datasource.id: {
                    'source_type': datasource.source_type,
                    **datasource.config,
                },
            },
        }

    def _make_engine_mock(self) -> MagicMock:
        engine = MagicMock()
        engine.is_process_alive.return_value = True
        engine.export.return_value = 'job-1'
        engine.get_result.return_value = {
            'data': {'row_count': 1},
            'error': None,
            'step_timings': {},
        }
        return engine

    def _make_manager_mock(self) -> MagicMock:
        manager = MagicMock()
        engine = self._make_engine_mock()
        manager.get_engine.return_value = engine
        manager.get_or_create_engine.return_value = engine
        return manager

    def _setup_mocks(self, table_exists: bool = True):
        mock_catalog = MagicMock()
        mock_table = MagicMock()
        mock_catalog.table_exists.return_value = table_exists
        mock_catalog.load_table.return_value = mock_table
        mock_catalog.create_table.return_value = mock_table
        mock_table.current_snapshot.return_value = MagicMock(snapshot_id=123, timestamp_ms=1000)
        mock_table.metadata_location = str(namespace_paths().exports_dir / 'ns' / 'tbl' / 'metadata' / 'v1.metadata.json')
        mock_arrow = MagicMock(schema=pa.schema([pa.field('id', pa.int64())]))
        return mock_catalog, mock_table, mock_arrow

    def test_full_mode_calls_overwrite(self, test_db_session: Session, sample_datasource: DataSource):
        output_ds_id = str(uuid.uuid4())
        pipeline = self._make_pipeline(sample_datasource, output_ds_id, build_mode='full')
        mock_catalog, mock_table, mock_arrow = self._setup_mocks(table_exists=True)

        with (
            patch('modules.compute.service.load_catalog', return_value=mock_catalog),
            patch('modules.compute.service.pl.read_parquet') as mock_read,
            patch('modules.compute.service._sync_iceberg_schema', return_value=False) as mock_sync,
            patch('modules.compute.service.os.path.getsize', return_value=100),
        ):
            mock_read.return_value.to_arrow.return_value = mock_arrow
            export_data(
                session=test_db_session,
                manager=self._make_manager_mock(),
                target_step_id='source',
                analysis_pipeline=pipeline,
                filename='test_out',
                iceberg_options={'namespace': 'ns', 'table_name': 'tbl', 'branch': 'master'},
                result_id=output_ds_id,
                build_mode='full',
            )

        mock_sync.assert_called_once_with(mock_table, mock_arrow.schema)
        mock_table.overwrite.assert_called_once_with(mock_arrow)
        mock_table.append.assert_not_called()

    def test_incremental_mode_calls_append(self, test_db_session: Session, sample_datasource: DataSource):
        output_ds_id = str(uuid.uuid4())
        pipeline = self._make_pipeline(sample_datasource, output_ds_id, build_mode='incremental')
        mock_catalog, mock_table, mock_arrow = self._setup_mocks(table_exists=True)

        with (
            patch('modules.compute.service.load_catalog', return_value=mock_catalog),
            patch('modules.compute.service.pl.read_parquet') as mock_read,
            patch('modules.compute.service._sync_iceberg_schema') as mock_sync,
            patch('modules.compute.service.os.path.getsize', return_value=100),
        ):
            mock_read.return_value.to_arrow.return_value = mock_arrow
            export_data(
                session=test_db_session,
                manager=self._make_manager_mock(),
                target_step_id='source',
                analysis_pipeline=pipeline,
                filename='test_out',
                iceberg_options={'namespace': 'ns', 'table_name': 'tbl', 'branch': 'master'},
                result_id=output_ds_id,
                build_mode='incremental',
            )

        mock_sync.assert_not_called()
        mock_table.append.assert_called_once_with(mock_arrow)
        mock_table.overwrite.assert_not_called()

    def test_new_table_always_creates_and_appends(self, test_db_session: Session, sample_datasource: DataSource):
        output_ds_id = str(uuid.uuid4())
        pipeline = self._make_pipeline(sample_datasource, output_ds_id, build_mode='full')
        mock_catalog, mock_table, mock_arrow = self._setup_mocks(table_exists=False)

        with (
            patch('modules.compute.service.load_catalog', return_value=mock_catalog),
            patch('modules.compute.service.pl.read_parquet') as mock_read,
            patch('modules.compute.service.os.path.getsize', return_value=100),
        ):
            mock_read.return_value.to_arrow.return_value = mock_arrow
            export_data(
                session=test_db_session,
                manager=self._make_manager_mock(),
                target_step_id='source',
                analysis_pipeline=pipeline,
                filename='test_out',
                iceberg_options={'namespace': 'ns', 'table_name': 'tbl', 'branch': 'master'},
                result_id=output_ds_id,
                build_mode='full',
            )

        mock_catalog.create_table.assert_called_once()
        mock_table.append.assert_called_once_with(mock_arrow)

    def test_recreate_mode_drops_and_creates(self, test_db_session: Session, sample_datasource: DataSource):
        output_ds_id = str(uuid.uuid4())
        pipeline = self._make_pipeline(sample_datasource, output_ds_id, build_mode='recreate')
        mock_catalog, mock_table, mock_arrow = self._setup_mocks(table_exists=True)
        mock_catalog.table_exists.side_effect = [True, False]

        with (
            patch('modules.compute.service.load_catalog', return_value=mock_catalog),
            patch('modules.compute.service.pl.read_parquet') as mock_read,
            patch('modules.compute.service.os.path.getsize', return_value=100),
        ):
            mock_read.return_value.to_arrow.return_value = mock_arrow
            export_data(
                session=test_db_session,
                manager=self._make_manager_mock(),
                target_step_id='source',
                analysis_pipeline=pipeline,
                filename='test_out',
                iceberg_options={'namespace': 'ns', 'table_name': 'tbl', 'branch': 'master'},
                result_id=output_ds_id,
                build_mode='recreate',
            )

        mock_catalog.drop_table.assert_called_once_with(f'ns.{output_ds_id}_master')
        mock_catalog.create_table.assert_called_once()
        mock_table.append.assert_called_once_with(mock_arrow)
        mock_table.overwrite.assert_not_called()

    def test_recreate_mode_no_table_skips_drop(self, test_db_session: Session, sample_datasource: DataSource):
        output_ds_id = str(uuid.uuid4())
        pipeline = self._make_pipeline(sample_datasource, output_ds_id, build_mode='recreate')
        mock_catalog, mock_table, mock_arrow = self._setup_mocks(table_exists=False)

        with (
            patch('modules.compute.service.load_catalog', return_value=mock_catalog),
            patch('modules.compute.service.pl.read_parquet') as mock_read,
            patch('modules.compute.service.os.path.getsize', return_value=100),
        ):
            mock_read.return_value.to_arrow.return_value = mock_arrow
            export_data(
                session=test_db_session,
                manager=self._make_manager_mock(),
                target_step_id='source',
                analysis_pipeline=pipeline,
                filename='test_out',
                iceberg_options={'namespace': 'ns', 'table_name': 'tbl', 'branch': 'master'},
                result_id=output_ds_id,
                build_mode='recreate',
            )

        mock_catalog.drop_table.assert_not_called()
        mock_catalog.create_table.assert_called_once()
        mock_table.append.assert_called_once_with(mock_arrow)

    def test_default_build_mode_is_full(self, test_db_session: Session, sample_datasource: DataSource):
        output_ds_id = str(uuid.uuid4())
        pipeline = self._make_pipeline(sample_datasource, output_ds_id)
        del pipeline['tabs'][0]['output']['build_mode']
        mock_catalog, mock_table, mock_arrow = self._setup_mocks(table_exists=True)

        with (
            patch('modules.compute.service.load_catalog', return_value=mock_catalog),
            patch('modules.compute.service.pl.read_parquet') as mock_read,
            patch(
                'modules.compute.service.resolve_iceberg_metadata_path',
                return_value='/tmp/iceberg/warehouse/ns/tbl/metadata/v1.metadata.json',
            ),
            patch('modules.compute.service._sync_iceberg_schema', return_value=False) as mock_sync,
            patch('modules.compute.service.os.path.getsize', return_value=100),
        ):
            mock_read.return_value.to_arrow.return_value = mock_arrow
            export_data(
                session=test_db_session,
                manager=self._make_manager_mock(),
                target_step_id='source',
                analysis_pipeline=pipeline,
                filename='test_out',
                iceberg_options={'namespace': 'ns', 'table_name': 'tbl', 'branch': 'master'},
                result_id=output_ds_id,
            )

        mock_sync.assert_called_once()
        mock_table.overwrite.assert_called_once()
