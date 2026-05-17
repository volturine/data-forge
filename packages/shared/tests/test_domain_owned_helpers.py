from contracts.analysis.step_types import STEP_TYPES
from contracts.datasource.models import DataSource, DataSourceCreatedBy, DataSourceTargetKind
from contracts.datasource.source_types import DataSourceType
from contracts.healthcheck_models import HealthCheckType
from contracts.runtime.ipc import RuntimePayloadKind
from contracts.step_config_enums import FillNullStrategy, FilterOperator


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
    assert raw_import.target_kind() == DataSourceTargetKind.RAW
    assert derived.target_kind() == DataSourceTargetKind.DATASOURCE


def test_healthcheck_type_owns_uniqueness_rule() -> None:
    assert HealthCheckType.ROW_COUNT.requires_unique_per_datasource is True
    assert HealthCheckType.COLUMN_NULL.requires_unique_per_datasource is False


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
