from datetime import UTC, datetime

from contracts.analysis.step_types import STEP_TYPES
from contracts.build_jobs.models import BuildJob, BuildJobStatus
from contracts.build_runs.models import BuildRun, BuildRunStatus
from contracts.compute import schemas as compute_schemas
from contracts.datasource.models import DataSource, DataSourceCreatedBy, DataSourceTargetKind
from contracts.datasource.source_types import DataSourceFileType, DataSourceType
from contracts.engine_instances.models import EngineInstanceStatus
from contracts.engine_runs.schemas import EngineRunExecutionCategory, EngineRunStatus
from contracts.healthcheck_models import HealthCheck, HealthCheckType
from contracts.runtime.ipc import RuntimePayloadKind
from contracts.step_config_enums import (
    AIProvider,
    ChartAggregation,
    FillNullStrategy,
    FilterOperator,
    GroupByAggregationFunction,
    JoinHow,
    PivotAggregateFunction,
    RecipientSource,
    SortBy,
)


def test_datasource_type_owns_ingestion_classification() -> None:
    assert DataSourceType.FILE.supports_external_ingestion is True
    assert DataSourceType.DATABASE.supports_external_ingestion is True
    assert DataSourceType.ICEBERG.supports_external_ingestion is False
    assert DataSourceType.DATABASE.ingestion_error_message == 'Failed to query database datasource'
    assert DataSourceType.FILE.ingestion_error_message == 'Failed to read file datasource'


def test_datasource_file_type_owns_upload_and_path_rules(tmp_path) -> None:
    parquet_dir = tmp_path / 'table'
    parquet_dir.mkdir()
    csv_file = tmp_path / 'data.csv'
    csv_file.write_text('id\n1\n')

    assert DataSourceFileType.from_upload_filename('sample.jsonl') == DataSourceFileType.NDJSON
    assert DataSourceFileType.NDJSON.upload_suffixes == ('.ndjson', '.jsonl')
    assert DataSourceFileType.CSV.uses_csv_options is True
    assert DataSourceFileType.PARQUET.requires_regular_file is False
    assert DataSourceFileType.PARQUET.matches_magic_number(b'PAR1rest') is True
    assert DataSourceFileType.EXCEL.matches_magic_number(b'PK\x03\x04rest') is True
    DataSourceFileType.CSV.validate_local_path(csv_file)
    DataSourceFileType.PARQUET.validate_local_path(parquet_dir)


def test_datasource_target_kind_is_model_owned() -> None:
    analysis_output = DataSource(
        id='ds-analysis',
        name='Analysis Output',
        source_type=DataSourceType.ICEBERG.value,
        config={'analysis_tab_id': 'tab-1'},
        created_by=DataSourceCreatedBy.ANALYSIS.value,
        created_by_analysis_id='analysis-1',
        created_at='2024-01-01T00:00:00Z',
    )
    raw_import = DataSource(
        id='ds-raw',
        name='Raw Import',
        source_type=DataSourceType.ICEBERG.value,
        config={'source': {'source_type': DataSourceType.FILE.value}},
        created_by=DataSourceCreatedBy.IMPORT.value,
        created_at='2024-01-01T00:00:00Z',
    )
    derived = DataSource(
        id='ds-derived',
        name='Derived',
        source_type=DataSourceType.ICEBERG.value,
        config={},
        created_by=DataSourceCreatedBy.IMPORT.value,
        created_at='2024-01-01T00:00:00Z',
    )

    assert analysis_output.target_kind() == DataSourceTargetKind.ANALYSIS
    assert raw_import.external_source_type() == DataSourceType.FILE
    assert raw_import.is_refreshable_external is True
    assert raw_import.query_and_connection() == (None, None)
    assert raw_import.target_kind() == DataSourceTargetKind.RAW
    assert derived.target_kind() == DataSourceTargetKind.DATASOURCE


def test_datasource_model_owns_query_and_connection_normalization() -> None:
    direct = DataSource(
        id='ds-direct',
        name='Direct DB',
        source_type=DataSourceType.DATABASE.value,
        config={
            'query': 'select * from public.users',
            'connection_string': 'postgresql+psycopg://example/db',
        },
        created_by=DataSourceCreatedBy.IMPORT.value,
        created_at='2024-01-01T00:00:00Z',
    )
    nested = DataSource(
        id='ds-nested',
        name='Nested DB',
        source_type=DataSourceType.ICEBERG.value,
        config={
            'source': {
                'query': 'select * from public.orders',
                'connection_string': 'postgresql+asyncpg://example/db',
            }
        },
        created_by=DataSourceCreatedBy.IMPORT.value,
        created_at='2024-01-01T00:00:00Z',
    )

    assert direct.query_and_connection() == ('select * from public.users', 'postgresql://example/db')
    assert nested.query_and_connection() == ('select * from public.orders', 'postgresql://example/db')


def test_healthcheck_type_owns_uniqueness_rule() -> None:
    assert HealthCheckType.ROW_COUNT.requires_unique_per_datasource is True
    assert HealthCheckType.COLUMN_NULL.requires_unique_per_datasource is False
    assert HealthCheckType.COLUMN_RANGE.requires_column is True
    assert HealthCheckType.ROW_COUNT.requires_column is False


def test_healthcheck_model_owns_metric_aliases_and_details() -> None:
    row_count_check = HealthCheck(
        id='hc-row-count',
        datasource_id='ds-1',
        name='Row Count',
        check_type=HealthCheckType.ROW_COUNT.value,
        config={'min_rows': 1},
        enabled=True,
        critical=False,
        created_at='2024-01-01T00:00:00Z',
    )
    column_check = HealthCheck(
        id='hc-column-null',
        datasource_id='ds-1',
        name='Column Null',
        check_type=HealthCheckType.COLUMN_NULL.value,
        config={'column': 'name', 'threshold': 10},
        enabled=True,
        critical=False,
        created_at='2024-01-01T00:00:00Z',
    )

    assert row_count_check.metric_alias('count') == 'row_count__count'
    assert column_check.metric_alias('null_pct') == 'hc-column-null__null_pct'
    assert column_check.column_name() == 'name'
    assert column_check.result_details(actual_percentage=12.5) == {'column': 'name', 'threshold': 10, 'actual_percentage': 12.5}


def test_runtime_payload_kind_is_model_owned() -> None:
    assert RuntimePayloadKind.from_payload({'kind': RuntimePayloadKind.BUILD.value}) == RuntimePayloadKind.BUILD
    assert RuntimePayloadKind.from_payload({'kind': 'unknown'}) is None
    assert RuntimePayloadKind.from_payload({}) is None


def test_fill_null_strategy_owns_special_modes() -> None:
    assert FillNullStrategy.LITERAL.uses_literal_value is True
    assert FillNullStrategy.ZERO.uses_literal_value is False
    assert FillNullStrategy.DROP_ROWS.drops_rows is True
    assert FillNullStrategy.MEAN.drops_rows is False


def test_step_types_own_dependency_config_keys() -> None:
    assert STEP_TYPES.dependency_values(STEP_TYPES.join.value, {'right_source': 'tab-2'}) == ('tab-2',)
    assert STEP_TYPES.dependency_values(STEP_TYPES.union_by_name.value, {'sources': ['tab-2', 'tab-3', None]}) == ('tab-2', 'tab-3')
    assert STEP_TYPES.dependency_values(STEP_TYPES.filter.value, {'right_source': 'ignored'}) == ()


def test_filter_operator_owns_error_and_list_semantics() -> None:
    assert FilterOperator.unsupported_message('nope') == 'Unsupported filter operator: nope'
    assert FilterOperator.NOT_IN.empty_list_result is True
    assert FilterOperator.IN.empty_list_result is False
    assert FilterOperator.NOT_CONTAINS.folds_list_with_all is True
    assert FilterOperator.CONTAINS.folds_list_with_all is False


def test_join_how_owns_backend_and_export_tokens() -> None:
    assert JoinHow.OUTER.polars_how == 'full'
    assert JoinHow.CROSS.polars_how == 'cross'
    assert JoinHow.OUTER.sql_join_type == 'FULL OUTER JOIN'
    assert JoinHow.CROSS.requires_join_keys is False
    assert JoinHow.LEFT.requires_join_keys is True


def test_build_job_owns_activity_and_orphan_rules() -> None:
    now = datetime.now(UTC)
    job = BuildJob(
        id='job-1',
        build_id='build-1',
        namespace='default',
        status=BuildJobStatus.RUNNING,
        priority=0,
        lease_owner='dead-worker',
        available_at=now,
        created_at=now,
        updated_at=now,
    )

    assert BuildJobStatus.RUNNING.is_active is True
    assert BuildJobStatus.COMPLETED.is_active is False
    assert BuildJobStatus.LEASED.is_reclaimable is True
    assert job.is_orphaned({'dead-worker'}) is True
    job.clear_lease()
    assert job.lease_owner is None
    assert job.lease_expires_at is None
    assert job.age_seconds(now=now) == 0.0


def test_engine_run_status_owns_terminal_rules() -> None:
    assert EngineRunStatus.RUNNING.is_terminal is False
    assert EngineRunStatus.SUCCESS.is_terminal is True
    assert EngineRunStatus.SUCCESS.blocks_transition_to(EngineRunStatus.FAILED) is True
    assert EngineRunStatus.SUCCESS.blocks_transition_to(EngineRunStatus.SUCCESS) is False


def test_engine_run_execution_category_owns_plan_and_step_defaults() -> None:
    assert EngineRunExecutionCategory.PLAN.is_query_plan is True
    assert EngineRunExecutionCategory.STEP.is_query_plan is False
    assert EngineRunExecutionCategory.READ.default_step_type == 'read'
    assert EngineRunExecutionCategory.WRITE.default_step_type == 'write'
    assert EngineRunExecutionCategory.STEP.default_step_type == 'unknown'


def test_engine_instance_status_owns_projection_flags() -> None:
    assert EngineInstanceStatus.RUNNING.is_active is True
    assert EngineInstanceStatus.STOPPED.is_active is False
    assert EngineInstanceStatus.STARTING.overview_status == 'healthy'
    assert EngineInstanceStatus.FAILED.overview_status == 'terminated'


def test_build_run_owns_terminal_event_updates() -> None:
    run = BuildRun(
        id='build-1',
        namespace='default',
        analysis_id='analysis-1',
        analysis_name='Analysis 1',
        status=BuildRunStatus.RUNNING,
        request_json={},
        starter_json={},
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    event = compute_schemas.BuildCancelledEvent(
        build_id='build-1',
        analysis_id='analysis-1',
        emitted_at=datetime.now(UTC),
        progress=0.5,
        elapsed_ms=100,
        total_steps=4,
        tabs_built=1,
        results=[],
        duration_ms=100,
        cancelled_at=datetime.now(UTC),
        cancelled_by='user-1',
    )

    assert BuildRun.terminal_status_for_event(event) == BuildRunStatus.CANCELLED
    assert BuildRun.terminal_update_values(event) is not None
    assert run.apply_terminal_event(event) is True
    assert run.status == BuildRunStatus.CANCELLED
    assert run.error_message == 'Build cancelled'


def test_groupby_aggregation_function_owns_alias_and_export_rendering() -> None:
    assert GroupByAggregationFunction.N_UNIQUE.default_alias('city') == 'city_n_unique'
    assert GroupByAggregationFunction.N_UNIQUE.polars_method_name == 'n_unique'
    assert GroupByAggregationFunction.STD.sql_function_name == 'STDDEV_POP'
    assert (
        GroupByAggregationFunction.COLLECT_SET.render_polars_export('pl.col("city")', '"city_values"')
        == 'pl.col("city").implode().list.unique().alias("city_values")'
    )
    assert GroupByAggregationFunction.N_UNIQUE.render_sql_export('"city"', '"city_count"') == 'COUNT(DISTINCT "city") AS "city_count"'


def test_pivot_aggregate_function_owns_polars_mapping() -> None:
    assert PivotAggregateFunction.COUNT.polars_aggregate_function == 'len'
    assert PivotAggregateFunction.MAX.polars_aggregate_function == 'max'


def test_chart_aggregation_is_contract_owned() -> None:
    assert ChartAggregation.require('sum') == ChartAggregation.SUM
    assert ChartAggregation.require('unique_count') == ChartAggregation.UNIQUE_COUNT


def test_shared_step_config_enums_cover_ai_and_notification_contracts() -> None:
    assert AIProvider.require('openrouter') == AIProvider.OPENROUTER
    assert RecipientSource.require('column') == RecipientSource.COLUMN
    assert SortBy.require('custom') == SortBy.CUSTOM
