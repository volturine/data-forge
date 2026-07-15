from dataforge_protocol import enums_pb2
from operations.enums import CastMapType
from runtime.domain.analysis.step_types import PipelineStepType
from runtime.domain.compute.schemas import BuildEventType, BuildTabResult, BuildTabStatus
from runtime.domain.datasource.source_types import DataSourceFileType, DataSourceLoadType, DataSourceType, IcebergReader


def test_worker_compute_enums_are_protocol_descriptor_backed() -> None:
    assert BuildEventType.COMPLETE.number == enums_pb2.BUILD_EVENT_TYPE_COMPLETE
    assert BuildEventType.require(enums_pb2.BUILD_EVENT_TYPE_COMPLETE) == BuildEventType.COMPLETE
    assert BuildEventType.COMPLETE.value == "complete"
    assert BuildEventType.require(enums_pb2.BUILD_EVENT_TYPE_COMPLETE) is BuildEventType.COMPLETE
    assert BuildEventType.require("complete") is BuildEventType.COMPLETE

    result = BuildTabResult.model_validate({"tab_id": "tab-1", "tab_name": "Tab 1", "status": enums_pb2.BUILD_TAB_STATUS_SUCCESS})
    assert result.status is BuildTabStatus.SUCCESS
    assert result.model_dump(mode="json")["status"] == "success"


def test_worker_step_types_are_protocol_descriptor_backed() -> None:
    assert PipelineStepType.FILTER.number == enums_pb2.STEP_TYPE_FILTER
    assert PipelineStepType.require(enums_pb2.STEP_TYPE_FILTER) is PipelineStepType.FILTER
    assert PipelineStepType.require("filter") is PipelineStepType.FILTER
    assert PipelineStepType.FILTER == "filter"
    assert hash(PipelineStepType.FILTER) == hash("filter")


def test_worker_datasource_enums_keep_string_storage_with_protocol_numbers() -> None:
    assert DataSourceType.ICEBERG.number == enums_pb2.DATA_SOURCE_TYPE_ICEBERG
    assert DataSourceType.require(enums_pb2.DATA_SOURCE_TYPE_ICEBERG) == DataSourceType.ICEBERG
    assert DataSourceType.require("iceberg") is DataSourceType.ICEBERG
    assert [item.value for item in DataSourceFileType.members()] == ["csv", "parquet", "json", "ndjson", "excel"]
    assert DataSourceLoadType.DUCKDB.number == enums_pb2.DATA_SOURCE_LOAD_TYPE_DUCKDB
    assert DataSourceLoadType.require(enums_pb2.DATA_SOURCE_LOAD_TYPE_DATABASE) is DataSourceLoadType.DATABASE
    assert [item.value for item in DataSourceLoadType.members()] == ["file", "database", "duckdb", "iceberg"]
    assert IcebergReader.NATIVE.number == enums_pb2.ICEBERG_READER_NATIVE
    assert IcebergReader.require("native") is IcebergReader.NATIVE


def test_worker_cast_map_type_uses_generated_protocol_enum_value() -> None:
    cast_type = CastMapType.require("Int64")

    assert isinstance(cast_type, int)
    assert cast_type.number == enums_pb2.CAST_MAP_TYPE_INT64
    assert CastMapType.require(enums_pb2.CAST_MAP_TYPE_INT64) is cast_type
    assert cast_type.value == "Int64"
