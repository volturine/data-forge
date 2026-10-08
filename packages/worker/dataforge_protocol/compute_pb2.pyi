import datetime

from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import analysis_pb2 as _analysis_pb2
from dataforge_protocol import datasource_pb2 as _datasource_pb2
from dataforge_protocol import enums_pb2 as _enums_pb2
from dataforge_protocol import errors_pb2 as _errors_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ComputeWorkerIdentity(_message.Message):
    __slots__ = ("scope", "reuse_policy", "analysis_id", "datasource_id", "build_id", "resource_id")
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    REUSE_POLICY_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    scope: _enums_pb2.ComputeWorkerScope
    reuse_policy: _enums_pb2.ComputeWorkerReusePolicy
    analysis_id: str
    datasource_id: str
    build_id: str
    resource_id: str
    def __init__(self, scope: _Optional[_Union[_enums_pb2.ComputeWorkerScope, str]] = ..., reuse_policy: _Optional[_Union[_enums_pb2.ComputeWorkerReusePolicy, str]] = ..., analysis_id: _Optional[str] = ..., datasource_id: _Optional[str] = ..., build_id: _Optional[str] = ..., resource_id: _Optional[str] = ...) -> None: ...

class ComputeWorkerResourceConfig(_message.Message):
    __slots__ = ("max_threads", "max_memory_mb", "streaming_chunk_size")
    MAX_THREADS_FIELD_NUMBER: _ClassVar[int]
    MAX_MEMORY_MB_FIELD_NUMBER: _ClassVar[int]
    STREAMING_CHUNK_SIZE_FIELD_NUMBER: _ClassVar[int]
    max_threads: int
    max_memory_mb: int
    streaming_chunk_size: int
    def __init__(self, max_threads: _Optional[int] = ..., max_memory_mb: _Optional[int] = ..., streaming_chunk_size: _Optional[int] = ...) -> None: ...

class StepPreviewCommand(_message.Message):
    __slots__ = ("analysis_id", "engine_identity", "target_step_id", "analysis_pipeline", "tab_id", "row_limit", "page", "resource_config")
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    ENGINE_IDENTITY_FIELD_NUMBER: _ClassVar[int]
    TARGET_STEP_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_PIPELINE_FIELD_NUMBER: _ClassVar[int]
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    ROW_LIMIT_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    analysis_id: str
    engine_identity: ComputeWorkerIdentity
    target_step_id: str
    analysis_pipeline: _analysis_pb2.AnalysisPipelinePayload
    tab_id: str
    row_limit: int
    page: int
    resource_config: ComputeWorkerResourceConfig
    def __init__(self, analysis_id: _Optional[str] = ..., engine_identity: _Optional[_Union[ComputeWorkerIdentity, _Mapping]] = ..., target_step_id: _Optional[str] = ..., analysis_pipeline: _Optional[_Union[_analysis_pb2.AnalysisPipelinePayload, _Mapping]] = ..., tab_id: _Optional[str] = ..., row_limit: _Optional[int] = ..., page: _Optional[int] = ..., resource_config: _Optional[_Union[ComputeWorkerResourceConfig, _Mapping]] = ...) -> None: ...

class StepSchemaCommand(_message.Message):
    __slots__ = ("analysis_id", "target_step_id", "analysis_pipeline", "tab_id")
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_STEP_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_PIPELINE_FIELD_NUMBER: _ClassVar[int]
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    analysis_id: str
    target_step_id: str
    analysis_pipeline: _analysis_pb2.AnalysisPipelinePayload
    tab_id: str
    def __init__(self, analysis_id: _Optional[str] = ..., target_step_id: _Optional[str] = ..., analysis_pipeline: _Optional[_Union[_analysis_pb2.AnalysisPipelinePayload, _Mapping]] = ..., tab_id: _Optional[str] = ...) -> None: ...

class StepRowCountCommand(_message.Message):
    __slots__ = ("analysis_id", "target_step_id", "analysis_pipeline", "tab_id")
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_STEP_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_PIPELINE_FIELD_NUMBER: _ClassVar[int]
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    analysis_id: str
    target_step_id: str
    analysis_pipeline: _analysis_pb2.AnalysisPipelinePayload
    tab_id: str
    def __init__(self, analysis_id: _Optional[str] = ..., target_step_id: _Optional[str] = ..., analysis_pipeline: _Optional[_Union[_analysis_pb2.AnalysisPipelinePayload, _Mapping]] = ..., tab_id: _Optional[str] = ...) -> None: ...

class DownloadCommand(_message.Message):
    __slots__ = ("analysis_id", "target_step_id", "analysis_pipeline", "tab_id", "format", "filename")
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_STEP_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_PIPELINE_FIELD_NUMBER: _ClassVar[int]
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    analysis_id: str
    target_step_id: str
    analysis_pipeline: _analysis_pb2.AnalysisPipelinePayload
    tab_id: str
    format: _enums_pb2.ExportFormat
    filename: str
    def __init__(self, analysis_id: _Optional[str] = ..., target_step_id: _Optional[str] = ..., analysis_pipeline: _Optional[_Union[_analysis_pb2.AnalysisPipelinePayload, _Mapping]] = ..., tab_id: _Optional[str] = ..., format: _Optional[_Union[_enums_pb2.ExportFormat, str]] = ..., filename: _Optional[str] = ...) -> None: ...

class IcebergExportOptions(_message.Message):
    __slots__ = ("table_name", "namespace", "branch")
    TABLE_NAME_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    BRANCH_FIELD_NUMBER: _ClassVar[int]
    table_name: str
    namespace: str
    branch: str
    def __init__(self, table_name: _Optional[str] = ..., namespace: _Optional[str] = ..., branch: _Optional[str] = ...) -> None: ...

class ExportCommand(_message.Message):
    __slots__ = ("analysis_id", "target_step_id", "analysis_pipeline", "tab_id", "format", "filename", "destination", "iceberg_options", "result_id")
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_STEP_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_PIPELINE_FIELD_NUMBER: _ClassVar[int]
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_FIELD_NUMBER: _ClassVar[int]
    ICEBERG_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    RESULT_ID_FIELD_NUMBER: _ClassVar[int]
    analysis_id: str
    target_step_id: str
    analysis_pipeline: _analysis_pb2.AnalysisPipelinePayload
    tab_id: str
    format: _enums_pb2.ExportFormat
    filename: str
    destination: _enums_pb2.ExportDestination
    iceberg_options: IcebergExportOptions
    result_id: str
    def __init__(self, analysis_id: _Optional[str] = ..., target_step_id: _Optional[str] = ..., analysis_pipeline: _Optional[_Union[_analysis_pb2.AnalysisPipelinePayload, _Mapping]] = ..., tab_id: _Optional[str] = ..., format: _Optional[_Union[_enums_pb2.ExportFormat, str]] = ..., filename: _Optional[str] = ..., destination: _Optional[_Union[_enums_pb2.ExportDestination, str]] = ..., iceberg_options: _Optional[_Union[IcebergExportOptions, _Mapping]] = ..., result_id: _Optional[str] = ...) -> None: ...

class ComputeWorkerLifecycleCommand(_message.Message):
    __slots__ = ("engine_identity", "resource_config")
    ENGINE_IDENTITY_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    engine_identity: ComputeWorkerIdentity
    resource_config: ComputeWorkerResourceConfig
    def __init__(self, engine_identity: _Optional[_Union[ComputeWorkerIdentity, _Mapping]] = ..., resource_config: _Optional[_Union[ComputeWorkerResourceConfig, _Mapping]] = ...) -> None: ...

class ComputeCommand(_message.Message):
    __slots__ = ("input_revisions", "preview", "schema", "row_count", "download", "export", "spawn_engine", "configure_engine", "shutdown_engine", "datasource")
    INPUT_REVISIONS_FIELD_NUMBER: _ClassVar[int]
    PREVIEW_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_FIELD_NUMBER: _ClassVar[int]
    EXPORT_FIELD_NUMBER: _ClassVar[int]
    SPAWN_ENGINE_FIELD_NUMBER: _ClassVar[int]
    CONFIGURE_ENGINE_FIELD_NUMBER: _ClassVar[int]
    SHUTDOWN_ENGINE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_FIELD_NUMBER: _ClassVar[int]
    input_revisions: _containers.RepeatedCompositeFieldContainer[_datasource_pb2.DatasourceInputRevision]
    preview: StepPreviewCommand
    schema: StepSchemaCommand
    row_count: StepRowCountCommand
    download: DownloadCommand
    export: ExportCommand
    spawn_engine: ComputeWorkerLifecycleCommand
    configure_engine: ComputeWorkerLifecycleCommand
    shutdown_engine: ComputeWorkerLifecycleCommand
    datasource: _datasource_pb2.DatasourceCommand
    def __init__(self, input_revisions: _Optional[_Iterable[_Union[_datasource_pb2.DatasourceInputRevision, _Mapping]]] = ..., preview: _Optional[_Union[StepPreviewCommand, _Mapping]] = ..., schema: _Optional[_Union[StepSchemaCommand, _Mapping]] = ..., row_count: _Optional[_Union[StepRowCountCommand, _Mapping]] = ..., download: _Optional[_Union[DownloadCommand, _Mapping]] = ..., export: _Optional[_Union[ExportCommand, _Mapping]] = ..., spawn_engine: _Optional[_Union[ComputeWorkerLifecycleCommand, _Mapping]] = ..., configure_engine: _Optional[_Union[ComputeWorkerLifecycleCommand, _Mapping]] = ..., shutdown_engine: _Optional[_Union[ComputeWorkerLifecycleCommand, _Mapping]] = ..., datasource: _Optional[_Union[_datasource_pb2.DatasourceCommand, _Mapping]] = ...) -> None: ...

class StepPreviewResult(_message.Message):
    __slots__ = ("step_id", "columns", "column_types", "rows", "total_rows", "page", "page_size", "metadata")
    class ColumnTypesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    COLUMN_TYPES_FIELD_NUMBER: _ClassVar[int]
    ROWS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_ROWS_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    step_id: str
    columns: _containers.RepeatedScalarFieldContainer[str]
    column_types: _containers.ScalarMap[str, str]
    rows: _containers.RepeatedCompositeFieldContainer[_struct_pb2.Struct]
    total_rows: int
    page: int
    page_size: int
    metadata: _struct_pb2.Struct
    def __init__(self, step_id: _Optional[str] = ..., columns: _Optional[_Iterable[str]] = ..., column_types: _Optional[_Mapping[str, str]] = ..., rows: _Optional[_Iterable[_Union[_struct_pb2.Struct, _Mapping]]] = ..., total_rows: _Optional[int] = ..., page: _Optional[int] = ..., page_size: _Optional[int] = ..., metadata: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class StepSchemaResult(_message.Message):
    __slots__ = ("step_id", "columns", "column_types")
    class ColumnTypesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    COLUMN_TYPES_FIELD_NUMBER: _ClassVar[int]
    step_id: str
    columns: _containers.RepeatedScalarFieldContainer[str]
    column_types: _containers.ScalarMap[str, str]
    def __init__(self, step_id: _Optional[str] = ..., columns: _Optional[_Iterable[str]] = ..., column_types: _Optional[_Mapping[str, str]] = ...) -> None: ...

class StepRowCountResult(_message.Message):
    __slots__ = ("step_id", "row_count")
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_FIELD_NUMBER: _ClassVar[int]
    step_id: str
    row_count: int
    def __init__(self, step_id: _Optional[str] = ..., row_count: _Optional[int] = ...) -> None: ...

class ExportResult(_message.Message):
    __slots__ = ("success", "filename", "format", "destination", "message", "datasource_id", "datasource_name")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_NAME_FIELD_NUMBER: _ClassVar[int]
    success: bool
    filename: str
    format: _enums_pb2.ExportFormat
    destination: _enums_pb2.ExportDestination
    message: str
    datasource_id: str
    datasource_name: str
    def __init__(self, success: _Optional[bool] = ..., filename: _Optional[str] = ..., format: _Optional[_Union[_enums_pb2.ExportFormat, str]] = ..., destination: _Optional[_Union[_enums_pb2.ExportDestination, str]] = ..., message: _Optional[str] = ..., datasource_id: _Optional[str] = ..., datasource_name: _Optional[str] = ...) -> None: ...

class ComputeWorkerDefaults(_message.Message):
    __slots__ = ("max_threads", "max_memory_mb", "streaming_chunk_size")
    MAX_THREADS_FIELD_NUMBER: _ClassVar[int]
    MAX_MEMORY_MB_FIELD_NUMBER: _ClassVar[int]
    STREAMING_CHUNK_SIZE_FIELD_NUMBER: _ClassVar[int]
    max_threads: int
    max_memory_mb: int
    streaming_chunk_size: int
    def __init__(self, max_threads: _Optional[int] = ..., max_memory_mb: _Optional[int] = ..., streaming_chunk_size: _Optional[int] = ...) -> None: ...

class ComputeWorkerStatusResult(_message.Message):
    __slots__ = ("analysis_id", "resource_id", "status", "last_activity", "current_job_id", "resource_config", "effective_resources", "defaults", "scope", "reuse_policy", "datasource_id", "build_id", "current_build_id", "current_engine_run_id", "container_id", "image_digest", "lifecycle_status", "termination_reason", "exit_code", "oom_killed", "supervisor_id", "owner_id")
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    LAST_ACTIVITY_FIELD_NUMBER: _ClassVar[int]
    CURRENT_JOB_ID_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_RESOURCES_FIELD_NUMBER: _ClassVar[int]
    DEFAULTS_FIELD_NUMBER: _ClassVar[int]
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    REUSE_POLICY_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_ENGINE_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    CONTAINER_ID_FIELD_NUMBER: _ClassVar[int]
    IMAGE_DIGEST_FIELD_NUMBER: _ClassVar[int]
    LIFECYCLE_STATUS_FIELD_NUMBER: _ClassVar[int]
    TERMINATION_REASON_FIELD_NUMBER: _ClassVar[int]
    EXIT_CODE_FIELD_NUMBER: _ClassVar[int]
    OOM_KILLED_FIELD_NUMBER: _ClassVar[int]
    SUPERVISOR_ID_FIELD_NUMBER: _ClassVar[int]
    OWNER_ID_FIELD_NUMBER: _ClassVar[int]
    analysis_id: str
    resource_id: str
    status: _enums_pb2.ComputeWorkerStatus
    last_activity: str
    current_job_id: str
    resource_config: ComputeWorkerResourceConfig
    effective_resources: ComputeWorkerResourceConfig
    defaults: ComputeWorkerDefaults
    scope: _enums_pb2.ComputeWorkerScope
    reuse_policy: _enums_pb2.ComputeWorkerReusePolicy
    datasource_id: str
    build_id: str
    current_build_id: str
    current_engine_run_id: str
    container_id: str
    image_digest: str
    lifecycle_status: _enums_pb2.ComputeWorkerInstanceStatus
    termination_reason: str
    exit_code: int
    oom_killed: bool
    supervisor_id: str
    owner_id: str
    def __init__(self, analysis_id: _Optional[str] = ..., resource_id: _Optional[str] = ..., status: _Optional[_Union[_enums_pb2.ComputeWorkerStatus, str]] = ..., last_activity: _Optional[str] = ..., current_job_id: _Optional[str] = ..., resource_config: _Optional[_Union[ComputeWorkerResourceConfig, _Mapping]] = ..., effective_resources: _Optional[_Union[ComputeWorkerResourceConfig, _Mapping]] = ..., defaults: _Optional[_Union[ComputeWorkerDefaults, _Mapping]] = ..., scope: _Optional[_Union[_enums_pb2.ComputeWorkerScope, str]] = ..., reuse_policy: _Optional[_Union[_enums_pb2.ComputeWorkerReusePolicy, str]] = ..., datasource_id: _Optional[str] = ..., build_id: _Optional[str] = ..., current_build_id: _Optional[str] = ..., current_engine_run_id: _Optional[str] = ..., container_id: _Optional[str] = ..., image_digest: _Optional[str] = ..., lifecycle_status: _Optional[_Union[_enums_pb2.ComputeWorkerInstanceStatus, str]] = ..., termination_reason: _Optional[str] = ..., exit_code: _Optional[int] = ..., oom_killed: _Optional[bool] = ..., supervisor_id: _Optional[str] = ..., owner_id: _Optional[str] = ...) -> None: ...

class ComputeAckResult(_message.Message):
    __slots__ = ("success",)
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    def __init__(self, success: _Optional[bool] = ...) -> None: ...

class ComputeErrorResult(_message.Message):
    __slots__ = ("error", "status_code", "error_code", "details", "message")
    ERROR_FIELD_NUMBER: _ClassVar[int]
    STATUS_CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    error: str
    status_code: int
    error_code: _errors_pb2.ErrorCode
    details: _struct_pb2.Struct
    message: str
    def __init__(self, error: _Optional[str] = ..., status_code: _Optional[int] = ..., error_code: _Optional[_Union[_errors_pb2.ErrorCode, str]] = ..., details: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., message: _Optional[str] = ...) -> None: ...

class ComputeResponse(_message.Message):
    __slots__ = ("preview", "schema", "row_count", "export", "datasource", "engine_status", "ack", "error")
    PREVIEW_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_FIELD_NUMBER: _ClassVar[int]
    EXPORT_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_FIELD_NUMBER: _ClassVar[int]
    ENGINE_STATUS_FIELD_NUMBER: _ClassVar[int]
    ACK_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    preview: StepPreviewResult
    schema: StepSchemaResult
    row_count: StepRowCountResult
    export: ExportResult
    datasource: _datasource_pb2.DatasourceResult
    engine_status: ComputeWorkerStatusResult
    ack: ComputeAckResult
    error: ComputeErrorResult
    def __init__(self, preview: _Optional[_Union[StepPreviewResult, _Mapping]] = ..., schema: _Optional[_Union[StepSchemaResult, _Mapping]] = ..., row_count: _Optional[_Union[StepRowCountResult, _Mapping]] = ..., export: _Optional[_Union[ExportResult, _Mapping]] = ..., datasource: _Optional[_Union[_datasource_pb2.DatasourceResult, _Mapping]] = ..., engine_status: _Optional[_Union[ComputeWorkerStatusResult, _Mapping]] = ..., ack: _Optional[_Union[ComputeAckResult, _Mapping]] = ..., error: _Optional[_Union[ComputeErrorResult, _Mapping]] = ...) -> None: ...

class ComputeCommandEnvelope(_message.Message):
    __slots__ = ("kind", "version", "idempotency_key", "correlation_id", "command")
    KIND_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    kind: _enums_pb2.ComputeRequestKind
    version: int
    idempotency_key: str
    correlation_id: str
    command: ComputeCommand
    def __init__(self, kind: _Optional[_Union[_enums_pb2.ComputeRequestKind, str]] = ..., version: _Optional[int] = ..., idempotency_key: _Optional[str] = ..., correlation_id: _Optional[str] = ..., command: _Optional[_Union[ComputeCommand, _Mapping]] = ...) -> None: ...

class ComputeResponseEnvelope(_message.Message):
    __slots__ = ("kind", "version", "correlation_id", "status", "error_message", "response")
    KIND_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_FIELD_NUMBER: _ClassVar[int]
    kind: _enums_pb2.ComputeRequestKind
    version: int
    correlation_id: str
    status: _enums_pb2.ComputeRequestStatus
    error_message: str
    response: ComputeResponse
    def __init__(self, kind: _Optional[_Union[_enums_pb2.ComputeRequestKind, str]] = ..., version: _Optional[int] = ..., correlation_id: _Optional[str] = ..., status: _Optional[_Union[_enums_pb2.ComputeRequestStatus, str]] = ..., error_message: _Optional[str] = ..., response: _Optional[_Union[ComputeResponse, _Mapping]] = ...) -> None: ...

class BuildEventContext(_message.Message):
    __slots__ = ("build_id", "analysis_id", "emitted_at", "sequence", "current_kind", "current_datasource_id", "tab_id", "tab_name", "current_output_id", "current_output_name", "engine_run_id")
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    EMITTED_AT_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    CURRENT_KIND_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    TAB_NAME_FIELD_NUMBER: _ClassVar[int]
    CURRENT_OUTPUT_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_OUTPUT_NAME_FIELD_NUMBER: _ClassVar[int]
    ENGINE_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    build_id: str
    analysis_id: str
    emitted_at: _timestamp_pb2.Timestamp
    sequence: int
    current_kind: _enums_pb2.ComputeWorkerRunKind
    current_datasource_id: str
    tab_id: str
    tab_name: str
    current_output_id: str
    current_output_name: str
    engine_run_id: str
    def __init__(self, build_id: _Optional[str] = ..., analysis_id: _Optional[str] = ..., emitted_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., sequence: _Optional[int] = ..., current_kind: _Optional[_Union[_enums_pb2.ComputeWorkerRunKind, str]] = ..., current_datasource_id: _Optional[str] = ..., tab_id: _Optional[str] = ..., tab_name: _Optional[str] = ..., current_output_id: _Optional[str] = ..., current_output_name: _Optional[str] = ..., engine_run_id: _Optional[str] = ...) -> None: ...

class BuildTabResult(_message.Message):
    __slots__ = ("tab_id", "tab_name", "status", "output_id", "output_name", "error")
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    TAB_NAME_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_ID_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_NAME_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    tab_id: str
    tab_name: str
    status: _enums_pb2.BuildTabStatus
    output_id: str
    output_name: str
    error: str
    def __init__(self, tab_id: _Optional[str] = ..., tab_name: _Optional[str] = ..., status: _Optional[_Union[_enums_pb2.BuildTabStatus, str]] = ..., output_id: _Optional[str] = ..., output_name: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class BuildPlanEvent(_message.Message):
    __slots__ = ("optimized_plan", "unoptimized_plan")
    OPTIMIZED_PLAN_FIELD_NUMBER: _ClassVar[int]
    UNOPTIMIZED_PLAN_FIELD_NUMBER: _ClassVar[int]
    optimized_plan: str
    unoptimized_plan: str
    def __init__(self, optimized_plan: _Optional[str] = ..., unoptimized_plan: _Optional[str] = ...) -> None: ...

class BuildStepKind(_message.Message):
    __slots__ = ("pipeline", "execution_category")
    PIPELINE_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_CATEGORY_FIELD_NUMBER: _ClassVar[int]
    pipeline: _enums_pb2.StepType
    execution_category: _enums_pb2.ComputeWorkerRunExecutionCategory
    def __init__(self, pipeline: _Optional[_Union[_enums_pb2.StepType, str]] = ..., execution_category: _Optional[_Union[_enums_pb2.ComputeWorkerRunExecutionCategory, str]] = ...) -> None: ...

class ComputeWorkerRunExecutionEntry(_message.Message):
    __slots__ = ("key", "label", "category", "order", "duration_ms", "share_pct", "optimized_plan", "unoptimized_plan", "step_type")
    KEY_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    ORDER_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    SHARE_PCT_FIELD_NUMBER: _ClassVar[int]
    OPTIMIZED_PLAN_FIELD_NUMBER: _ClassVar[int]
    UNOPTIMIZED_PLAN_FIELD_NUMBER: _ClassVar[int]
    STEP_TYPE_FIELD_NUMBER: _ClassVar[int]
    key: str
    label: str
    category: _enums_pb2.ComputeWorkerRunExecutionCategory
    order: int
    duration_ms: float
    share_pct: float
    optimized_plan: str
    unoptimized_plan: str
    step_type: _enums_pb2.StepType
    def __init__(self, key: _Optional[str] = ..., label: _Optional[str] = ..., category: _Optional[_Union[_enums_pb2.ComputeWorkerRunExecutionCategory, str]] = ..., order: _Optional[int] = ..., duration_ms: _Optional[float] = ..., share_pct: _Optional[float] = ..., optimized_plan: _Optional[str] = ..., unoptimized_plan: _Optional[str] = ..., step_type: _Optional[_Union[_enums_pb2.StepType, str]] = ...) -> None: ...

class BuildStepStartedEvent(_message.Message):
    __slots__ = ("build_step_index", "step_index", "step_id", "step_name", "total_steps", "step_kind")
    BUILD_STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    STEP_NAME_FIELD_NUMBER: _ClassVar[int]
    TOTAL_STEPS_FIELD_NUMBER: _ClassVar[int]
    STEP_KIND_FIELD_NUMBER: _ClassVar[int]
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    total_steps: int
    step_kind: BuildStepKind
    def __init__(self, build_step_index: _Optional[int] = ..., step_index: _Optional[int] = ..., step_id: _Optional[str] = ..., step_name: _Optional[str] = ..., total_steps: _Optional[int] = ..., step_kind: _Optional[_Union[BuildStepKind, _Mapping]] = ...) -> None: ...

class BuildStepCompletedEvent(_message.Message):
    __slots__ = ("build_step_index", "step_index", "step_id", "step_name", "duration_ms", "row_count", "total_steps", "step_kind")
    BUILD_STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    STEP_NAME_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_STEPS_FIELD_NUMBER: _ClassVar[int]
    STEP_KIND_FIELD_NUMBER: _ClassVar[int]
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    duration_ms: int
    row_count: int
    total_steps: int
    step_kind: BuildStepKind
    def __init__(self, build_step_index: _Optional[int] = ..., step_index: _Optional[int] = ..., step_id: _Optional[str] = ..., step_name: _Optional[str] = ..., duration_ms: _Optional[int] = ..., row_count: _Optional[int] = ..., total_steps: _Optional[int] = ..., step_kind: _Optional[_Union[BuildStepKind, _Mapping]] = ...) -> None: ...

class BuildStepFailedEvent(_message.Message):
    __slots__ = ("build_step_index", "step_index", "step_id", "step_name", "error", "total_steps", "step_kind")
    BUILD_STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    STEP_NAME_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    TOTAL_STEPS_FIELD_NUMBER: _ClassVar[int]
    STEP_KIND_FIELD_NUMBER: _ClassVar[int]
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    error: str
    total_steps: int
    step_kind: BuildStepKind
    def __init__(self, build_step_index: _Optional[int] = ..., step_index: _Optional[int] = ..., step_id: _Optional[str] = ..., step_name: _Optional[str] = ..., error: _Optional[str] = ..., total_steps: _Optional[int] = ..., step_kind: _Optional[_Union[BuildStepKind, _Mapping]] = ...) -> None: ...

class BuildProgressEvent(_message.Message):
    __slots__ = ("progress", "elapsed_ms", "estimated_remaining_ms", "current_step", "current_step_index", "total_steps")
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_MS_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_REMAINING_MS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STEP_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    TOTAL_STEPS_FIELD_NUMBER: _ClassVar[int]
    progress: float
    elapsed_ms: int
    estimated_remaining_ms: int
    current_step: str
    current_step_index: int
    total_steps: int
    def __init__(self, progress: _Optional[float] = ..., elapsed_ms: _Optional[int] = ..., estimated_remaining_ms: _Optional[int] = ..., current_step: _Optional[str] = ..., current_step_index: _Optional[int] = ..., total_steps: _Optional[int] = ...) -> None: ...

class BuildResourceEvent(_message.Message):
    __slots__ = ("cpu_percent", "memory_mb", "memory_limit_mb", "active_threads", "max_threads")
    CPU_PERCENT_FIELD_NUMBER: _ClassVar[int]
    MEMORY_MB_FIELD_NUMBER: _ClassVar[int]
    MEMORY_LIMIT_MB_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_THREADS_FIELD_NUMBER: _ClassVar[int]
    MAX_THREADS_FIELD_NUMBER: _ClassVar[int]
    cpu_percent: float
    memory_mb: float
    memory_limit_mb: float
    active_threads: int
    max_threads: int
    def __init__(self, cpu_percent: _Optional[float] = ..., memory_mb: _Optional[float] = ..., memory_limit_mb: _Optional[float] = ..., active_threads: _Optional[int] = ..., max_threads: _Optional[int] = ...) -> None: ...

class BuildLogEvent(_message.Message):
    __slots__ = ("level", "message", "step_name", "step_id")
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    STEP_NAME_FIELD_NUMBER: _ClassVar[int]
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    level: _enums_pb2.BuildLogLevel
    message: str
    step_name: str
    step_id: str
    def __init__(self, level: _Optional[_Union[_enums_pb2.BuildLogLevel, str]] = ..., message: _Optional[str] = ..., step_name: _Optional[str] = ..., step_id: _Optional[str] = ...) -> None: ...

class BuildTerminalEvent(_message.Message):
    __slots__ = ("progress", "elapsed_ms", "total_steps", "tabs_built", "results", "duration_ms", "error", "cancelled_at", "cancelled_by")
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_MS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_STEPS_FIELD_NUMBER: _ClassVar[int]
    TABS_BUILT_FIELD_NUMBER: _ClassVar[int]
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_AT_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_BY_FIELD_NUMBER: _ClassVar[int]
    progress: float
    elapsed_ms: int
    total_steps: int
    tabs_built: int
    results: _containers.RepeatedCompositeFieldContainer[BuildTabResult]
    duration_ms: int
    error: str
    cancelled_at: _timestamp_pb2.Timestamp
    cancelled_by: str
    def __init__(self, progress: _Optional[float] = ..., elapsed_ms: _Optional[int] = ..., total_steps: _Optional[int] = ..., tabs_built: _Optional[int] = ..., results: _Optional[_Iterable[_Union[BuildTabResult, _Mapping]]] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ..., cancelled_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., cancelled_by: _Optional[str] = ...) -> None: ...

class BuildEvent(_message.Message):
    __slots__ = ("context", "namespace", "plan", "step_started", "step_completed", "step_failed", "progress", "resources", "log", "completed", "failed", "cancelled")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    PLAN_FIELD_NUMBER: _ClassVar[int]
    STEP_STARTED_FIELD_NUMBER: _ClassVar[int]
    STEP_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    STEP_FAILED_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    RESOURCES_FIELD_NUMBER: _ClassVar[int]
    LOG_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    FAILED_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_FIELD_NUMBER: _ClassVar[int]
    context: BuildEventContext
    namespace: str
    plan: BuildPlanEvent
    step_started: BuildStepStartedEvent
    step_completed: BuildStepCompletedEvent
    step_failed: BuildStepFailedEvent
    progress: BuildProgressEvent
    resources: BuildResourceEvent
    log: BuildLogEvent
    completed: BuildTerminalEvent
    failed: BuildTerminalEvent
    cancelled: BuildTerminalEvent
    def __init__(self, context: _Optional[_Union[BuildEventContext, _Mapping]] = ..., namespace: _Optional[str] = ..., plan: _Optional[_Union[BuildPlanEvent, _Mapping]] = ..., step_started: _Optional[_Union[BuildStepStartedEvent, _Mapping]] = ..., step_completed: _Optional[_Union[BuildStepCompletedEvent, _Mapping]] = ..., step_failed: _Optional[_Union[BuildStepFailedEvent, _Mapping]] = ..., progress: _Optional[_Union[BuildProgressEvent, _Mapping]] = ..., resources: _Optional[_Union[BuildResourceEvent, _Mapping]] = ..., log: _Optional[_Union[BuildLogEvent, _Mapping]] = ..., completed: _Optional[_Union[BuildTerminalEvent, _Mapping]] = ..., failed: _Optional[_Union[BuildTerminalEvent, _Mapping]] = ..., cancelled: _Optional[_Union[BuildTerminalEvent, _Mapping]] = ...) -> None: ...

class BuildStarter(_message.Message):
    __slots__ = ("user_id", "display_name", "email", "triggered_by")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    TRIGGERED_BY_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    display_name: str
    email: str
    triggered_by: str
    def __init__(self, user_id: _Optional[str] = ..., display_name: _Optional[str] = ..., email: _Optional[str] = ..., triggered_by: _Optional[str] = ...) -> None: ...

class BuildResourceConfigSummary(_message.Message):
    __slots__ = ("max_threads", "max_memory_mb", "streaming_chunk_size")
    MAX_THREADS_FIELD_NUMBER: _ClassVar[int]
    MAX_MEMORY_MB_FIELD_NUMBER: _ClassVar[int]
    STREAMING_CHUNK_SIZE_FIELD_NUMBER: _ClassVar[int]
    max_threads: int
    max_memory_mb: int
    streaming_chunk_size: int
    def __init__(self, max_threads: _Optional[int] = ..., max_memory_mb: _Optional[int] = ..., streaming_chunk_size: _Optional[int] = ...) -> None: ...

class BuildStepSnapshot(_message.Message):
    __slots__ = ("build_step_index", "step_index", "step_id", "step_name", "tab_id", "tab_name", "state", "duration_ms", "row_count", "error", "step_kind")
    BUILD_STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    STEP_NAME_FIELD_NUMBER: _ClassVar[int]
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    TAB_NAME_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ROW_COUNT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    STEP_KIND_FIELD_NUMBER: _ClassVar[int]
    build_step_index: int
    step_index: int
    step_id: str
    step_name: str
    tab_id: str
    tab_name: str
    state: _enums_pb2.BuildStepState
    duration_ms: int
    row_count: int
    error: str
    step_kind: BuildStepKind
    def __init__(self, build_step_index: _Optional[int] = ..., step_index: _Optional[int] = ..., step_id: _Optional[str] = ..., step_name: _Optional[str] = ..., tab_id: _Optional[str] = ..., tab_name: _Optional[str] = ..., state: _Optional[_Union[_enums_pb2.BuildStepState, str]] = ..., duration_ms: _Optional[int] = ..., row_count: _Optional[int] = ..., error: _Optional[str] = ..., step_kind: _Optional[_Union[BuildStepKind, _Mapping]] = ...) -> None: ...

class BuildQueryPlanSnapshot(_message.Message):
    __slots__ = ("tab_id", "tab_name", "optimized_plan", "unoptimized_plan")
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    TAB_NAME_FIELD_NUMBER: _ClassVar[int]
    OPTIMIZED_PLAN_FIELD_NUMBER: _ClassVar[int]
    UNOPTIMIZED_PLAN_FIELD_NUMBER: _ClassVar[int]
    tab_id: str
    tab_name: str
    optimized_plan: str
    unoptimized_plan: str
    def __init__(self, tab_id: _Optional[str] = ..., tab_name: _Optional[str] = ..., optimized_plan: _Optional[str] = ..., unoptimized_plan: _Optional[str] = ...) -> None: ...

class BuildResourceSnapshot(_message.Message):
    __slots__ = ("sampled_at", "cpu_percent", "memory_mb", "memory_limit_mb", "active_threads", "max_threads")
    SAMPLED_AT_FIELD_NUMBER: _ClassVar[int]
    CPU_PERCENT_FIELD_NUMBER: _ClassVar[int]
    MEMORY_MB_FIELD_NUMBER: _ClassVar[int]
    MEMORY_LIMIT_MB_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_THREADS_FIELD_NUMBER: _ClassVar[int]
    MAX_THREADS_FIELD_NUMBER: _ClassVar[int]
    sampled_at: _timestamp_pb2.Timestamp
    cpu_percent: float
    memory_mb: float
    memory_limit_mb: float
    active_threads: int
    max_threads: int
    def __init__(self, sampled_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., cpu_percent: _Optional[float] = ..., memory_mb: _Optional[float] = ..., memory_limit_mb: _Optional[float] = ..., active_threads: _Optional[int] = ..., max_threads: _Optional[int] = ...) -> None: ...

class BuildLogEntry(_message.Message):
    __slots__ = ("timestamp", "level", "message", "step_name", "step_id", "tab_id", "tab_name")
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    STEP_NAME_FIELD_NUMBER: _ClassVar[int]
    STEP_ID_FIELD_NUMBER: _ClassVar[int]
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    TAB_NAME_FIELD_NUMBER: _ClassVar[int]
    timestamp: _timestamp_pb2.Timestamp
    level: _enums_pb2.BuildLogLevel
    message: str
    step_name: str
    step_id: str
    tab_id: str
    tab_name: str
    def __init__(self, timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., level: _Optional[_Union[_enums_pb2.BuildLogLevel, str]] = ..., message: _Optional[str] = ..., step_name: _Optional[str] = ..., step_id: _Optional[str] = ..., tab_id: _Optional[str] = ..., tab_name: _Optional[str] = ...) -> None: ...

class BuildRunSummary(_message.Message):
    __slots__ = ("build_id", "analysis_id", "analysis_name", "namespace", "status", "started_at", "starter", "resource_config", "progress", "elapsed_ms", "estimated_remaining_ms", "current_step", "current_step_index", "total_steps", "current_kind", "current_datasource_id", "current_tab_id", "current_tab_name", "current_output_id", "current_output_name", "current_engine_run_id", "total_tabs", "cancelled_at", "cancelled_by", "result_json")
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_NAME_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    STARTER_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_MS_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_REMAINING_MS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STEP_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    TOTAL_STEPS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_KIND_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TAB_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TAB_NAME_FIELD_NUMBER: _ClassVar[int]
    CURRENT_OUTPUT_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_OUTPUT_NAME_FIELD_NUMBER: _ClassVar[int]
    CURRENT_ENGINE_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    TOTAL_TABS_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_AT_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_BY_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    build_id: str
    analysis_id: str
    analysis_name: str
    namespace: str
    status: _enums_pb2.BuildLifecycleStatus
    started_at: _timestamp_pb2.Timestamp
    starter: BuildStarter
    resource_config: BuildResourceConfigSummary
    progress: float
    elapsed_ms: int
    estimated_remaining_ms: int
    current_step: str
    current_step_index: int
    total_steps: int
    current_kind: _enums_pb2.ComputeWorkerRunKind
    current_datasource_id: str
    current_tab_id: str
    current_tab_name: str
    current_output_id: str
    current_output_name: str
    current_engine_run_id: str
    total_tabs: int
    cancelled_at: _timestamp_pb2.Timestamp
    cancelled_by: str
    result_json: _struct_pb2.Struct
    def __init__(self, build_id: _Optional[str] = ..., analysis_id: _Optional[str] = ..., analysis_name: _Optional[str] = ..., namespace: _Optional[str] = ..., status: _Optional[_Union[_enums_pb2.BuildLifecycleStatus, str]] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., starter: _Optional[_Union[BuildStarter, _Mapping]] = ..., resource_config: _Optional[_Union[BuildResourceConfigSummary, _Mapping]] = ..., progress: _Optional[float] = ..., elapsed_ms: _Optional[int] = ..., estimated_remaining_ms: _Optional[int] = ..., current_step: _Optional[str] = ..., current_step_index: _Optional[int] = ..., total_steps: _Optional[int] = ..., current_kind: _Optional[_Union[_enums_pb2.ComputeWorkerRunKind, str]] = ..., current_datasource_id: _Optional[str] = ..., current_tab_id: _Optional[str] = ..., current_tab_name: _Optional[str] = ..., current_output_id: _Optional[str] = ..., current_output_name: _Optional[str] = ..., current_engine_run_id: _Optional[str] = ..., total_tabs: _Optional[int] = ..., cancelled_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., cancelled_by: _Optional[str] = ..., result_json: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class BuildRunDetail(_message.Message):
    __slots__ = ("summary", "steps", "query_plans", "latest_resources", "resources", "logs", "results", "duration_ms", "error", "request_json")
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    STEPS_FIELD_NUMBER: _ClassVar[int]
    QUERY_PLANS_FIELD_NUMBER: _ClassVar[int]
    LATEST_RESOURCES_FIELD_NUMBER: _ClassVar[int]
    RESOURCES_FIELD_NUMBER: _ClassVar[int]
    LOGS_FIELD_NUMBER: _ClassVar[int]
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    REQUEST_JSON_FIELD_NUMBER: _ClassVar[int]
    summary: BuildRunSummary
    steps: _containers.RepeatedCompositeFieldContainer[BuildStepSnapshot]
    query_plans: _containers.RepeatedCompositeFieldContainer[BuildQueryPlanSnapshot]
    latest_resources: BuildResourceSnapshot
    resources: _containers.RepeatedCompositeFieldContainer[BuildResourceSnapshot]
    logs: _containers.RepeatedCompositeFieldContainer[BuildLogEntry]
    results: _containers.RepeatedCompositeFieldContainer[BuildTabResult]
    duration_ms: int
    error: str
    request_json: _struct_pb2.Struct
    def __init__(self, summary: _Optional[_Union[BuildRunSummary, _Mapping]] = ..., steps: _Optional[_Iterable[_Union[BuildStepSnapshot, _Mapping]]] = ..., query_plans: _Optional[_Iterable[_Union[BuildQueryPlanSnapshot, _Mapping]]] = ..., latest_resources: _Optional[_Union[BuildResourceSnapshot, _Mapping]] = ..., resources: _Optional[_Iterable[_Union[BuildResourceSnapshot, _Mapping]]] = ..., logs: _Optional[_Iterable[_Union[BuildLogEntry, _Mapping]]] = ..., results: _Optional[_Iterable[_Union[BuildTabResult, _Mapping]]] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ..., request_json: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class BuildRunListResponse(_message.Message):
    __slots__ = ("builds", "total")
    BUILDS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    builds: _containers.RepeatedCompositeFieldContainer[BuildRunSummary]
    total: int
    def __init__(self, builds: _Optional[_Iterable[_Union[BuildRunSummary, _Mapping]]] = ..., total: _Optional[int] = ...) -> None: ...

class BuildSnapshotMessage(_message.Message):
    __slots__ = ("type", "build", "last_sequence")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    BUILD_FIELD_NUMBER: _ClassVar[int]
    LAST_SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    type: str
    build: BuildRunDetail
    last_sequence: int
    def __init__(self, type: _Optional[str] = ..., build: _Optional[_Union[BuildRunDetail, _Mapping]] = ..., last_sequence: _Optional[int] = ...) -> None: ...

class BuildListSnapshotMessage(_message.Message):
    __slots__ = ("type", "builds")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    BUILDS_FIELD_NUMBER: _ClassVar[int]
    type: str
    builds: _containers.RepeatedCompositeFieldContainer[BuildRunSummary]
    def __init__(self, type: _Optional[str] = ..., builds: _Optional[_Iterable[_Union[BuildRunSummary, _Mapping]]] = ...) -> None: ...

class BuildWebsocketErrorMessage(_message.Message):
    __slots__ = ("type", "error", "status_code")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    STATUS_CODE_FIELD_NUMBER: _ClassVar[int]
    type: str
    error: str
    status_code: int
    def __init__(self, type: _Optional[str] = ..., error: _Optional[str] = ..., status_code: _Optional[int] = ...) -> None: ...
