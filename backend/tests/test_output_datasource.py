import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from sqlmodel import Session

from core.namespace import namespace_paths
from modules.analysis.models import Analysis
from modules.analysis.schemas import AnalysisUpdateSchema, TabDatasourceConfig, TabDatasourceSchema, TabOutputSchema, TabSchema
from modules.analysis.service import update_analysis
from modules.compute.service import _upsert_output_datasource, export_data
from modules.datasource.models import DataSource
from modules.datasource.service import create_analysis_datasource
from modules.datasource.source_types import DataSourceType

# ---------------------------------------------------------------------------
# TabSchema
# ---------------------------------------------------------------------------


class TestTabSchemaOutputDatasourceId:
    """TabSchema requires output_datasource_id for pipeline output routing."""

    def test_accepts_string(self):
        tab = TabSchema(
            id='t1',
            name='Tab 1',
            datasource=TabDatasourceSchema(
                id='ds-1',
                analysis_tab_id=None,
                config=TabDatasourceConfig(branch='master'),
            ),
            output=TabOutputSchema(
                output_datasource_id='ds-abc',
                datasource_type='iceberg',
                format='parquet',
                filename='tab_output',
            ),
            steps=[],
        )
        assert tab.output.output_datasource_id == 'ds-abc'

    def test_round_trips_through_model_dump(self):
        tab = TabSchema(
            id='t1',
            name='Tab 1',
            datasource=TabDatasourceSchema(
                id='ds-1',
                analysis_tab_id=None,
                config=TabDatasourceConfig(branch='master'),
            ),
            output=TabOutputSchema(
                output_datasource_id='ds-xyz',
                datasource_type='iceberg',
                format='parquet',
                filename='tab_output',
            ),
            steps=[],
        )
        dumped = tab.model_dump()
        assert dumped['output']['output_datasource_id'] == 'ds-xyz'
        restored = TabSchema.model_validate(dumped)
        assert restored.output.output_datasource_id == 'ds-xyz'


# ---------------------------------------------------------------------------
# create_analysis_datasource with is_hidden
# ---------------------------------------------------------------------------


class TestCreateAnalysisDatasourceHidden:
    """create_analysis_datasource honours the is_hidden flag."""

    def test_creates_hidden_datasource(self, test_db_session: Session, sample_analysis: Analysis):
        result = create_analysis_datasource(
            session=test_db_session,
            name='Hidden Output',
            analysis_id=sample_analysis.id,
            analysis_tab_id='tab1',
            is_hidden=True,
        )
        ds = test_db_session.get(DataSource, result.id)
        assert ds is not None
        assert ds.is_hidden is True
        assert ds.source_type == 'analysis'
        assert ds.created_by == 'analysis'
        assert ds.created_by_analysis_id == sample_analysis.id

    def test_creates_visible_by_default(self, test_db_session: Session, sample_analysis: Analysis):
        result = create_analysis_datasource(
            session=test_db_session,
            name='Visible Source',
            analysis_id=sample_analysis.id,
        )
        ds = test_db_session.get(DataSource, result.id)
        assert ds is not None
        assert ds.is_hidden is False


# ---------------------------------------------------------------------------
# _upsert_output_datasource
# ---------------------------------------------------------------------------


class TestUpsertOutputDatasource:
    """_upsert_output_datasource creates or updates a DataSource."""

    def test_creates_new_when_no_id(self, test_db_session: Session):
        ds = _upsert_output_datasource(
            session=test_db_session,
            output_datasource_id=None,
            name='brand-new',
            source_type='file',
            config={'file_path': '/tmp/test.csv', 'file_type': 'csv'},
            schema_cache={'col': 'Utf8'},
            analysis_id='a1',
        )
        assert ds.id is not None
        assert ds.name == 'brand-new'
        assert ds.source_type == 'file'
        assert ds.created_by_analysis_id == 'a1'
        assert ds.created_by == 'analysis'
        assert ds.is_hidden is True

    def test_creates_new_when_id_not_found(self, test_db_session: Session):
        ds = _upsert_output_datasource(
            session=test_db_session,
            output_datasource_id='nonexistent-id',
            name='fallback',
            source_type='file',
            config={'file_path': '/tmp/x.csv', 'file_type': 'csv'},
            schema_cache={},
            analysis_id=None,
        )
        assert ds.id == 'nonexistent-id'
        assert ds.name == 'fallback'
        assert ds.is_hidden is True

    def test_updates_existing(self, test_db_session: Session):
        existing_id = str(uuid.uuid4())
        existing = DataSource(
            id=existing_id,
            name='old-name',
            source_type='file',
            config={'file_path': '/tmp/old.csv', 'file_type': 'csv'},
            schema_cache={'a': 'Int64'},
            created_at=datetime.now(UTC),
        )
        test_db_session.add(existing)
        test_db_session.commit()

        ds = _upsert_output_datasource(
            session=test_db_session,
            output_datasource_id=existing_id,
            name='new-name',
            source_type='iceberg',
            config={'table': 't1'},
            schema_cache={'b': 'Utf8'},
            analysis_id='a2',
            keep_schema_cache=True,
        )
        assert ds.id == existing_id  # Same row
        assert ds.name == 'new-name'
        assert ds.source_type == 'iceberg'
        assert ds.config == {'table': 't1'}
        assert ds.schema_cache == {'a': 'Int64'}
        assert ds.created_by_analysis_id == 'a2'
        assert ds.created_by == 'analysis'


# ---------------------------------------------------------------------------
# update_analysis — output_datasource_id required
# ---------------------------------------------------------------------------


class TestUpdateAnalysisOutputDatasource:
    """update_analysis requires output_datasource_id and does not create datasources."""

    def test_keeps_output_id_without_creating_datasource(
        self, test_db_session: Session, sample_analysis: Analysis, sample_datasource: DataSource
    ):
        tabs = [
            TabSchema(
                id='tab1',
                name='Source',
                datasource=TabDatasourceSchema(
                    id=sample_datasource.id,
                    analysis_tab_id=None,
                    config=TabDatasourceConfig(branch='master'),
                ),
                output=TabOutputSchema(
                    output_datasource_id='out-1',
                    datasource_type='iceberg',
                    format='parquet',
                    filename='tab_output',
                ),
                steps=[],
            ),
        ]
        update = AnalysisUpdateSchema(
            tabs=tabs,
            pipeline_steps=[],
        )
        result = update_analysis(test_db_session, sample_analysis.id, update)
        assert len(result.tabs) == 1
        tab = result.tabs[0]
        assert tab.output.output_datasource_id == 'out-1'
        output_ds = test_db_session.get(DataSource, tab.output.output_datasource_id)
        assert output_ds is None

    def test_reuses_existing_output_id(self, test_db_session: Session, sample_analysis: Analysis, sample_datasource: DataSource):
        tabs = [
            TabSchema(
                id='tab1',
                name='Source',
                datasource=TabDatasourceSchema(
                    id=sample_datasource.id,
                    analysis_tab_id=None,
                    config=TabDatasourceConfig(branch='master'),
                ),
                output=TabOutputSchema(
                    output_datasource_id='out-1',
                    datasource_type='iceberg',
                    format='parquet',
                    filename='tab_output',
                ),
                steps=[],
            ),
        ]
        update = AnalysisUpdateSchema(tabs=tabs, pipeline_steps=[])

        result1 = update_analysis(test_db_session, sample_analysis.id, update)
        output_id_1 = result1.tabs[0].output.output_datasource_id

        tabs2 = [
            TabSchema(
                id='tab1',
                name='Source',
                datasource=TabDatasourceSchema(
                    id=sample_datasource.id,
                    analysis_tab_id=None,
                    config=TabDatasourceConfig(branch='master'),
                ),
                output=TabOutputSchema(
                    output_datasource_id=output_id_1,
                    datasource_type='iceberg',
                    format='parquet',
                    filename='tab_output',
                ),
                steps=[],
            ),
        ]
        update2 = AnalysisUpdateSchema(tabs=tabs2, pipeline_steps=[])
        result2 = update_analysis(test_db_session, sample_analysis.id, update2)
        output_id_2 = result2.tabs[0].output.output_datasource_id

        assert output_id_2 == output_id_1

    def test_multiple_tabs_each_get_output_id(self, test_db_session: Session, sample_analysis: Analysis, sample_datasource: DataSource):
        tabs = [
            TabSchema(
                id='tab-a',
                name='Tab A',
                datasource=TabDatasourceSchema(
                    id=sample_datasource.id,
                    analysis_tab_id=None,
                    config=TabDatasourceConfig(branch='master'),
                ),
                output=TabOutputSchema(
                    output_datasource_id='out-a',
                    datasource_type='iceberg',
                    format='parquet',
                    filename='tab_output',
                ),
                steps=[],
            ),
            TabSchema(
                id='tab-b',
                name='Tab B',
                parent_id='tab-a',
                datasource=TabDatasourceSchema(
                    id='out-a',
                    analysis_tab_id='tab-a',
                    config=TabDatasourceConfig(branch='master'),
                ),
                output=TabOutputSchema(
                    output_datasource_id='out-b',
                    datasource_type='iceberg',
                    format='parquet',
                    filename='tab_output',
                ),
                steps=[],
            ),
        ]
        update = AnalysisUpdateSchema(tabs=tabs, pipeline_steps=[])
        result = update_analysis(test_db_session, sample_analysis.id, update)

        assert len(result.tabs) == 2
        ids = [t.output.output_datasource_id for t in result.tabs]
        assert all(i is not None for i in ids)
        assert ids[0] != ids[1]
        assert result.tabs[1].datasource.id == 'out-a'


# ---------------------------------------------------------------------------
# run_analysis_build passes output_datasource_id
# ---------------------------------------------------------------------------


class TestRunAnalysisBuildOutputDatasource:
    """Scheduler's run_analysis_build passes output_datasource_id to export_data."""

    def test_passes_output_datasource_id(self, test_db_session: Session, sample_datasource: DataSource):
        """run_analysis_build should forward output_datasource_id from the tab."""
        output_ds_id = str(uuid.uuid4())
        analysis_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        analysis = Analysis(
            id=analysis_id,
            name='Build Test',
            description='',
            pipeline_definition={
                'steps': [],
                'tabs': [
                    {
                        'id': 'tab1',
                        'name': 'Main',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'steps': [
                            {'id': 's1', 'type': 'filter', 'config': {'column': 'age', 'operator': '>', 'value': 30}, 'depends_on': []}
                        ],
                        'output': {
                            'output_datasource_id': output_ds_id,
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'test_out',
                            'iceberg': {'namespace': 'ns', 'table_name': 'tbl'},
                        },
                    }
                ],
            },
            status='draft',
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(analysis)
        test_db_session.commit()

        mock_export = MagicMock()
        mock_preview = MagicMock()
        mock_notify = MagicMock()
        with (
            patch('modules.compute.service.export_data', mock_export),
            patch('modules.compute.service.preview_step', mock_preview),
            patch('modules.compute.service._send_pipeline_notifications', mock_notify),
        ):
            from modules.scheduler.service import run_analysis_build

            run_analysis_build(test_db_session, analysis_id)

            mock_export.assert_called_once()
            call_kwargs = mock_export.call_args
            assert call_kwargs.kwargs.get('output_datasource_id') == output_ds_id
            assert call_kwargs.kwargs.get('triggered_by') == 'schedule'
            mock_preview.assert_not_called()

    def test_export_uses_output_datasource_id_for_table_name(self, test_db_session: Session, sample_datasource: DataSource):
        output_ds_id = str(uuid.uuid4())
        analysis_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        analysis = Analysis(
            id=analysis_id,
            name='Output Test',
            description='',
            pipeline_definition={
                'steps': [],
                'tabs': [
                    {
                        'id': 'tab1',
                        'name': 'Main',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'steps': [],
                        'output': {
                            'output_datasource_id': output_ds_id,
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'test_out',
                            'iceberg': {'namespace': 'ns', 'table_name': 'tbl'},
                        },
                    }
                ],
            },
            status='draft',
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(analysis)
        test_db_session.commit()

        mock_catalog = MagicMock()
        mock_table = MagicMock()
        mock_catalog.table_exists.return_value = False
        mock_catalog.create_table.return_value = mock_table

        with (
            patch('modules.compute.service.load_catalog', return_value=mock_catalog),
            patch('modules.compute.service.pl.read_parquet') as mock_read,
        ):
            mock_read.return_value.to_arrow.return_value = MagicMock(schema=MagicMock())
            _, _, _, _, created_ds_id, _ = export_data(
                session=test_db_session,
                target_step_id='source',
                analysis_pipeline={
                    'analysis_id': analysis_id,
                    'tabs': [
                        {
                            'id': 'tab1',
                            'datasource': {
                                'id': sample_datasource.id,
                                'analysis_tab_id': None,
                                'config': {'branch': 'master'},
                            },
                            'output': {
                                'output_datasource_id': output_ds_id,
                                'datasource_type': 'iceberg',
                                'format': 'parquet',
                                'filename': 'test_out',
                                'iceberg': {'namespace': 'ns', 'table_name': 'tbl'},
                            },
                            'steps': [],
                        }
                    ],
                    'sources': {
                        sample_datasource.id: {
                            'source_type': sample_datasource.source_type,
                            **sample_datasource.config,
                        }
                    },
                },
                export_format='parquet',
                filename='test_out',
                destination='datasource',
                datasource_type='iceberg',
                iceberg_options={'namespace': 'ns', 'table_name': 'tbl', 'branch': 'master'},
                output_datasource_id=output_ds_id,
            )

        identifier = mock_catalog.create_table.call_args.args[0]
        assert identifier == f'ns.{output_ds_id}_master'

        output_ds = test_db_session.get(DataSource, created_ds_id)
        assert output_ds is not None
        expected_path = str(namespace_paths().exports_dir / output_ds_id)
        assert output_ds.config['metadata_path'] == expected_path
        assert output_ds.config['table'] == f'{output_ds_id}_master'

    def test_tab_without_output_config_fails(self, test_db_session: Session, sample_datasource: DataSource):
        """Tabs without output config should fail."""
        analysis_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        analysis = Analysis(
            id=analysis_id,
            name='Preview Test',
            description='',
            pipeline_definition={
                'steps': [],
                'tabs': [
                    {
                        'id': 'tab1',
                        'name': 'No Output',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'output_datasource_id': 'some-output-id',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'missing_output',
                        },
                        'steps': [],
                    }
                ],
            },
            status='draft',
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(analysis)
        test_db_session.commit()

        mock_export = MagicMock()
        mock_preview = MagicMock()
        mock_notify = MagicMock()
        with (
            patch('modules.compute.service.export_data', mock_export),
            patch('modules.compute.service.preview_step', mock_preview),
            patch('modules.compute.service._send_pipeline_notifications', mock_notify),
        ):
            from modules.scheduler.service import run_analysis_build

            result = run_analysis_build(test_db_session, analysis_id)

            mock_export.assert_not_called()
            mock_preview.assert_not_called()
            assert result['tabs_built'] == 0
            assert result['results'][0]['status'] == 'failed'

    def test_tab_missing_output_filename_fails(self, test_db_session: Session, sample_datasource: DataSource):
        analysis_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        analysis = Analysis(
            id=analysis_id,
            name='Missing Output Fields',
            description='',
            pipeline_definition={
                'steps': [],
                'tabs': [
                    {
                        'id': 'tab1',
                        'name': 'No Filename',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'output_datasource_id': 'some-output-id',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                        },
                        'steps': [],
                    }
                ],
            },
            status='draft',
            created_at=now,
            updated_at=now,
        )
        test_db_session.add(analysis)
        test_db_session.commit()

        with patch('modules.compute.service.export_data') as mock_export:
            from modules.scheduler.service import run_analysis_build

            result = run_analysis_build(test_db_session, analysis_id)

            mock_export.assert_not_called()
            assert result['tabs_built'] == 0
            assert result['results'][0]['status'] == 'failed'


# ---------------------------------------------------------------------------
# is_hidden semantics — output vs input
# ---------------------------------------------------------------------------


class TestIsHiddenSemantics:
    """is_hidden is for OUTPUT datasources, not input datasources."""

    def test_input_datasource_not_hidden(self, test_db_session: Session, sample_datasource: DataSource):
        """The input/source datasource should NOT be is_hidden."""
        assert sample_datasource.is_hidden is False

    def test_datasource_model_is_hidden_default(self, test_db_session: Session):
        """DataSource.is_hidden defaults to False."""
        ds = DataSource(
            id=str(uuid.uuid4()),
            name='test',
            source_type='file',
            config={'file_path': '/tmp/t.csv', 'file_type': 'csv'},
            created_at=datetime.now(UTC),
        )
        test_db_session.add(ds)
        test_db_session.commit()
        test_db_session.refresh(ds)
        assert ds.is_hidden is False
        assert ds.created_by == 'import'


# ---------------------------------------------------------------------------
# source_type + created_by semantics
# ---------------------------------------------------------------------------


class TestSourceTypeCreatedBy:
    """source_type reflects data format; created_by tracks origin."""

    def test_input_analysis_datasource_keeps_source_type_analysis(self, test_db_session: Session, sample_analysis: Analysis):
        """INPUT analysis datasources keep source_type='analysis' for engine dispatch."""
        result = create_analysis_datasource(
            session=test_db_session,
            name='Input Ref',
            analysis_id=sample_analysis.id,
        )
        ds = test_db_session.get(DataSource, result.id)
        assert ds is not None
        assert ds.source_type == DataSourceType.ANALYSIS
        assert ds.created_by == 'analysis'

    def test_output_datasource_uses_iceberg_source_type(self, test_db_session: Session, sample_analysis: Analysis):
        """OUTPUT analysis datasources use source_type='iceberg'."""
        result = create_analysis_datasource(
            session=test_db_session,
            name='Output',
            analysis_id=sample_analysis.id,
            analysis_tab_id='tab1',
            is_hidden=True,
            source_type=DataSourceType.ICEBERG,
        )
        ds = test_db_session.get(DataSource, result.id)
        assert ds is not None
        assert ds.source_type == DataSourceType.ICEBERG
        assert ds.created_by == 'analysis'
        assert ds.is_hidden is True

    def test_imported_file_datasource_created_by_import(self, test_db_session: Session):
        """File datasources default to created_by='import'."""
        ds = DataSource(
            id=str(uuid.uuid4()),
            name='uploaded',
            source_type='file',
            config={'file_path': '/tmp/data.csv', 'file_type': 'csv'},
            created_at=datetime.now(UTC),
        )
        test_db_session.add(ds)
        test_db_session.commit()
        test_db_session.refresh(ds)
        assert ds.created_by == 'import'

    def test_update_analysis_does_not_create_output_datasource(
        self, test_db_session: Session, sample_analysis: Analysis, sample_datasource: DataSource
    ):
        """update_analysis does not create output datasources."""
        tabs = [
            TabSchema(
                id='tab1',
                name='Source',
                datasource=TabDatasourceSchema(
                    id=sample_datasource.id,
                    analysis_tab_id=None,
                    config=TabDatasourceConfig(branch='master'),
                ),
                output=TabOutputSchema(
                    output_datasource_id='out-1',
                    datasource_type='iceberg',
                    format='parquet',
                    filename='tab_output',
                ),
                steps=[],
            ),
        ]
        update = AnalysisUpdateSchema(tabs=tabs, pipeline_steps=[])
        result = update_analysis(test_db_session, sample_analysis.id, update)
        output_ds = test_db_session.get(DataSource, result.tabs[0].output.output_datasource_id)
        assert output_ds is None

    def test_upsert_output_sets_created_by_analysis(self, test_db_session: Session):
        """_upsert_output_datasource sets created_by='analysis'."""
        ds = _upsert_output_datasource(
            session=test_db_session,
            output_datasource_id=None,
            name='upserted',
            source_type='iceberg',
            config={'metadata_path': '/tmp/iceberg'},
            schema_cache={},
            analysis_id='a1',
        )
        assert ds.created_by == 'analysis'
        assert ds.source_type == 'iceberg'
