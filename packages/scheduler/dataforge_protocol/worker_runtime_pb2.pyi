import datetime

from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from dataforge_protocol import enums_pb2 as _enums_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RuntimeWorkerRegisterRequest(_message.Message):
    __slots__ = ("worker_id", "kind", "hostname", "pid", "capacity", "active_jobs")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    HOSTNAME_FIELD_NUMBER: _ClassVar[int]
    PID_FIELD_NUMBER: _ClassVar[int]
    CAPACITY_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_JOBS_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    kind: _enums_pb2.RuntimeWorkerKind
    hostname: str
    pid: int
    capacity: int
    active_jobs: int
    def __init__(self, worker_id: _Optional[str] = ..., kind: _Optional[_Union[_enums_pb2.RuntimeWorkerKind, str]] = ..., hostname: _Optional[str] = ..., pid: _Optional[int] = ..., capacity: _Optional[int] = ..., active_jobs: _Optional[int] = ...) -> None: ...

class RuntimeWorkerHeartbeatRequest(_message.Message):
    __slots__ = ("worker_id", "active_jobs")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_JOBS_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    active_jobs: int
    def __init__(self, worker_id: _Optional[str] = ..., active_jobs: _Optional[int] = ...) -> None: ...

class WorkerClaimedBuildJob(_message.Message):
    __slots__ = ("job_id", "build_id", "namespace")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    build_id: str
    namespace: str
    def __init__(self, job_id: _Optional[str] = ..., build_id: _Optional[str] = ..., namespace: _Optional[str] = ...) -> None: ...

class WorkerClaimBuildJobResponse(_message.Message):
    __slots__ = ("job",)
    JOB_FIELD_NUMBER: _ClassVar[int]
    job: WorkerClaimedBuildJob
    def __init__(self, job: _Optional[_Union[WorkerClaimedBuildJob, _Mapping]] = ...) -> None: ...

class WorkerClaimedComputeRequest(_message.Message):
    __slots__ = ("id", "namespace", "kind", "request_json")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    REQUEST_JSON_FIELD_NUMBER: _ClassVar[int]
    id: str
    namespace: str
    kind: _enums_pb2.ComputeRequestKind
    request_json: _common_pb2.JsonPayload
    def __init__(self, id: _Optional[str] = ..., namespace: _Optional[str] = ..., kind: _Optional[_Union[_enums_pb2.ComputeRequestKind, str]] = ..., request_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...

class WorkerClaimComputeRequestResponse(_message.Message):
    __slots__ = ("request",)
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    request: WorkerClaimedComputeRequest
    def __init__(self, request: _Optional[_Union[WorkerClaimedComputeRequest, _Mapping]] = ...) -> None: ...

class WorkerCompleteComputeRequestRequest(_message.Message):
    __slots__ = ("namespace", "request_id", "response_json", "artifact_path", "artifact_name", "artifact_content_type")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_JSON_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_PATH_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_NAME_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    request_id: str
    response_json: _common_pb2.JsonPayload
    artifact_path: str
    artifact_name: str
    artifact_content_type: str
    def __init__(self, namespace: _Optional[str] = ..., request_id: _Optional[str] = ..., response_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., artifact_path: _Optional[str] = ..., artifact_name: _Optional[str] = ..., artifact_content_type: _Optional[str] = ...) -> None: ...

class WorkerFailComputeRequestRequest(_message.Message):
    __slots__ = ("namespace", "request_id", "error_message", "response_json")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_JSON_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    request_id: str
    error_message: str
    response_json: _common_pb2.JsonPayload
    def __init__(self, namespace: _Optional[str] = ..., request_id: _Optional[str] = ..., error_message: _Optional[str] = ..., response_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...

class WorkerExecuteDatasourceRequest(_message.Message):
    __slots__ = ("namespace", "kind", "request_json")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    REQUEST_JSON_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    kind: _enums_pb2.ComputeRequestKind
    request_json: _common_pb2.JsonPayload
    def __init__(self, namespace: _Optional[str] = ..., kind: _Optional[_Union[_enums_pb2.ComputeRequestKind, str]] = ..., request_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...

class WorkerScheduleIngestDatasourceRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ...) -> None: ...

class JsonResponse(_message.Message):
    __slots__ = ("response_json",)
    RESPONSE_JSON_FIELD_NUMBER: _ClassVar[int]
    response_json: _common_pb2.JsonPayload
    def __init__(self, response_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...

class WorkerDatasourceMetadataRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ...) -> None: ...

class WorkerDatasourceMetadataResponse(_message.Message):
    __slots__ = ("found", "id", "name", "source_type", "config", "schema_cache", "is_hidden")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_CACHE_FIELD_NUMBER: _ClassVar[int]
    IS_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    found: bool
    id: str
    name: str
    source_type: _enums_pb2.DataSourceType
    config: _common_pb2.JsonPayload
    schema_cache: _common_pb2.JsonPayload
    is_hidden: bool
    def __init__(self, found: _Optional[bool] = ..., id: _Optional[str] = ..., name: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., config: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., schema_cache: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., is_hidden: _Optional[bool] = ...) -> None: ...

class WorkerUdfCodesRequest(_message.Message):
    __slots__ = ("namespace", "udf_ids")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    UDF_IDS_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    udf_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, namespace: _Optional[str] = ..., udf_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class WorkerUdfCodesResponse(_message.Message):
    __slots__ = ("codes",)
    class CodesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    CODES_FIELD_NUMBER: _ClassVar[int]
    codes: _containers.ScalarMap[str, str]
    def __init__(self, codes: _Optional[_Mapping[str, str]] = ...) -> None: ...

class WorkerAnalysisMetadataRequest(_message.Message):
    __slots__ = ("namespace", "analysis_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    analysis_id: str
    def __init__(self, namespace: _Optional[str] = ..., analysis_id: _Optional[str] = ...) -> None: ...

class WorkerAnalysisMetadataResponse(_message.Message):
    __slots__ = ("found", "name")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    found: bool
    name: str
    def __init__(self, found: _Optional[bool] = ..., name: _Optional[str] = ...) -> None: ...

class WorkerBuildCancelStatusRequest(_message.Message):
    __slots__ = ("namespace", "build_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    build_id: str
    def __init__(self, namespace: _Optional[str] = ..., build_id: _Optional[str] = ...) -> None: ...

class WorkerBuildCancelStatusResponse(_message.Message):
    __slots__ = ("cancelled", "cancelled_at", "cancelled_by")
    CANCELLED_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_AT_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_BY_FIELD_NUMBER: _ClassVar[int]
    cancelled: bool
    cancelled_at: _timestamp_pb2.Timestamp
    cancelled_by: str
    def __init__(self, cancelled: _Optional[bool] = ..., cancelled_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., cancelled_by: _Optional[str] = ...) -> None: ...

class WorkerUpdateBuildResultRequest(_message.Message):
    __slots__ = ("namespace", "build_id", "result_json")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    build_id: str
    result_json: _common_pb2.JsonPayload
    def __init__(self, namespace: _Optional[str] = ..., build_id: _Optional[str] = ..., result_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...

class WorkerUpsertOutputDatasourceRequest(_message.Message):
    __slots__ = ("namespace", "result_id", "name", "source_type", "config", "schema_cache", "analysis_id", "is_hidden", "keep_schema_cache")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    RESULT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_CACHE_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    IS_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    KEEP_SCHEMA_CACHE_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    result_id: str
    name: str
    source_type: _enums_pb2.DataSourceType
    config: _common_pb2.JsonPayload
    schema_cache: _common_pb2.JsonPayload
    analysis_id: str
    is_hidden: bool
    keep_schema_cache: bool
    def __init__(self, namespace: _Optional[str] = ..., result_id: _Optional[str] = ..., name: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., config: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., schema_cache: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., analysis_id: _Optional[str] = ..., is_hidden: _Optional[bool] = ..., keep_schema_cache: _Optional[bool] = ...) -> None: ...

class WorkerUpsertOutputDatasourceResponse(_message.Message):
    __slots__ = ("datasource_id", "datasource_name", "is_hidden")
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_NAME_FIELD_NUMBER: _ClassVar[int]
    IS_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    datasource_id: str
    datasource_name: str
    is_hidden: bool
    def __init__(self, datasource_id: _Optional[str] = ..., datasource_name: _Optional[str] = ..., is_hidden: _Optional[bool] = ...) -> None: ...

class WorkerHealthCheckSpec(_message.Message):
    __slots__ = ("id", "name", "check_type", "config", "critical")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    CHECK_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    CRITICAL_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    check_type: _enums_pb2.HealthCheckType
    config: _common_pb2.JsonPayload
    critical: bool
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., check_type: _Optional[_Union[_enums_pb2.HealthCheckType, str]] = ..., config: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., critical: _Optional[bool] = ...) -> None: ...

class WorkerListHealthChecksRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ...) -> None: ...

class WorkerListHealthChecksResponse(_message.Message):
    __slots__ = ("checks",)
    CHECKS_FIELD_NUMBER: _ClassVar[int]
    checks: _containers.RepeatedCompositeFieldContainer[WorkerHealthCheckSpec]
    def __init__(self, checks: _Optional[_Iterable[_Union[WorkerHealthCheckSpec, _Mapping]]] = ...) -> None: ...

class WorkerHealthCheckResultPayload(_message.Message):
    __slots__ = ("healthcheck_id", "passed", "message", "details", "checked_at")
    HEALTHCHECK_ID_FIELD_NUMBER: _ClassVar[int]
    PASSED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    CHECKED_AT_FIELD_NUMBER: _ClassVar[int]
    healthcheck_id: str
    passed: bool
    message: str
    details: _common_pb2.JsonPayload
    checked_at: _timestamp_pb2.Timestamp
    def __init__(self, healthcheck_id: _Optional[str] = ..., passed: _Optional[bool] = ..., message: _Optional[str] = ..., details: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., checked_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class WorkerRecordHealthCheckResultsRequest(_message.Message):
    __slots__ = ("namespace", "results")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    results: _containers.RepeatedCompositeFieldContainer[WorkerHealthCheckResultPayload]
    def __init__(self, namespace: _Optional[str] = ..., results: _Optional[_Iterable[_Union[WorkerHealthCheckResultPayload, _Mapping]]] = ...) -> None: ...

class WorkerCreateEngineRunRequest(_message.Message):
    __slots__ = ("namespace", "analysis_id", "datasource_id", "kind", "status", "request_json", "result_json", "error_message", "created_at", "completed_at", "duration_ms", "step_timings", "query_plan", "execution_entries", "progress", "current_step", "triggered_by")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    REQUEST_JSON_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    STEP_TIMINGS_FIELD_NUMBER: _ClassVar[int]
    QUERY_PLAN_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STEP_FIELD_NUMBER: _ClassVar[int]
    TRIGGERED_BY_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    analysis_id: str
    datasource_id: str
    kind: _enums_pb2.EngineRunKind
    status: _enums_pb2.EngineRunStatus
    request_json: _common_pb2.JsonPayload
    result_json: _common_pb2.JsonPayload
    error_message: str
    created_at: _timestamp_pb2.Timestamp
    completed_at: _timestamp_pb2.Timestamp
    duration_ms: int
    step_timings: _common_pb2.JsonPayload
    query_plan: str
    execution_entries: _containers.RepeatedCompositeFieldContainer[_common_pb2.JsonPayload]
    progress: float
    current_step: str
    triggered_by: str
    def __init__(self, namespace: _Optional[str] = ..., analysis_id: _Optional[str] = ..., datasource_id: _Optional[str] = ..., kind: _Optional[_Union[_enums_pb2.EngineRunKind, str]] = ..., status: _Optional[_Union[_enums_pb2.EngineRunStatus, str]] = ..., request_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., result_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., error_message: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., duration_ms: _Optional[int] = ..., step_timings: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., query_plan: _Optional[str] = ..., execution_entries: _Optional[_Iterable[_Union[_common_pb2.JsonPayload, _Mapping]]] = ..., progress: _Optional[float] = ..., current_step: _Optional[str] = ..., triggered_by: _Optional[str] = ...) -> None: ...

class WorkerUpdateEngineRunRequest(_message.Message):
    __slots__ = ("namespace", "run_id", "fields", "merge_result_json")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    MERGE_RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    run_id: str
    fields: _common_pb2.JsonPayload
    merge_result_json: bool
    def __init__(self, namespace: _Optional[str] = ..., run_id: _Optional[str] = ..., fields: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., merge_result_json: _Optional[bool] = ...) -> None: ...

class WorkerEngineRunStateRequest(_message.Message):
    __slots__ = ("namespace", "run_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    run_id: str
    def __init__(self, namespace: _Optional[str] = ..., run_id: _Optional[str] = ...) -> None: ...

class WorkerEngineRunStateResponse(_message.Message):
    __slots__ = ("found", "status", "result_json", "cancelled_at", "cancelled_by")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_AT_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_BY_FIELD_NUMBER: _ClassVar[int]
    found: bool
    status: _enums_pb2.EngineRunStatus
    result_json: _common_pb2.JsonPayload
    cancelled_at: _timestamp_pb2.Timestamp
    cancelled_by: str
    def __init__(self, found: _Optional[bool] = ..., status: _Optional[_Union[_enums_pb2.EngineRunStatus, str]] = ..., result_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., cancelled_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., cancelled_by: _Optional[str] = ...) -> None: ...

class WorkerFailBuildJobRequest(_message.Message):
    __slots__ = ("job_id", "namespace", "error")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    namespace: str
    error: str
    def __init__(self, job_id: _Optional[str] = ..., namespace: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class WorkerFinalizeBuildJobRequest(_message.Message):
    __slots__ = ("job_id", "build_id", "namespace")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    build_id: str
    namespace: str
    def __init__(self, job_id: _Optional[str] = ..., build_id: _Optional[str] = ..., namespace: _Optional[str] = ...) -> None: ...

class WorkerIdlePidsResponse(_message.Message):
    __slots__ = ("pids",)
    PIDS_FIELD_NUMBER: _ClassVar[int]
    pids: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, pids: _Optional[_Iterable[int]] = ...) -> None: ...

class WorkerNamespacesResponse(_message.Message):
    __slots__ = ("namespaces",)
    NAMESPACES_FIELD_NUMBER: _ClassVar[int]
    namespaces: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, namespaces: _Optional[_Iterable[str]] = ...) -> None: ...

class WorkerPersistBuildEventRequest(_message.Message):
    __slots__ = ("namespace", "build_id", "event", "resource_config_json")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    EVENT_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_CONFIG_JSON_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    build_id: str
    event: _common_pb2.JsonPayload
    resource_config_json: _common_pb2.JsonPayload
    def __init__(self, namespace: _Optional[str] = ..., build_id: _Optional[str] = ..., event: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., resource_config_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...

class WorkerPersistBuildEventResponse(_message.Message):
    __slots__ = ("sequence",)
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    sequence: int
    def __init__(self, sequence: _Optional[int] = ...) -> None: ...

class WorkerBuildRunPayload(_message.Message):
    __slots__ = ("id", "namespace", "analysis_id", "analysis_name", "request_json", "starter_json", "resource_config_json", "current_kind", "current_datasource_id", "current_tab_id", "current_tab_name", "current_output_id", "current_output_name", "started_at", "total_tabs")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_NAME_FIELD_NUMBER: _ClassVar[int]
    REQUEST_JSON_FIELD_NUMBER: _ClassVar[int]
    STARTER_JSON_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_CONFIG_JSON_FIELD_NUMBER: _ClassVar[int]
    CURRENT_KIND_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TAB_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TAB_NAME_FIELD_NUMBER: _ClassVar[int]
    CURRENT_OUTPUT_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_OUTPUT_NAME_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_TABS_FIELD_NUMBER: _ClassVar[int]
    id: str
    namespace: str
    analysis_id: str
    analysis_name: str
    request_json: _common_pb2.JsonPayload
    starter_json: _common_pb2.JsonPayload
    resource_config_json: _common_pb2.JsonPayload
    current_kind: _enums_pb2.ComputeRequestKind
    current_datasource_id: str
    current_tab_id: str
    current_tab_name: str
    current_output_id: str
    current_output_name: str
    started_at: _timestamp_pb2.Timestamp
    total_tabs: int
    def __init__(self, id: _Optional[str] = ..., namespace: _Optional[str] = ..., analysis_id: _Optional[str] = ..., analysis_name: _Optional[str] = ..., request_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., starter_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., resource_config_json: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ..., current_kind: _Optional[_Union[_enums_pb2.ComputeRequestKind, str]] = ..., current_datasource_id: _Optional[str] = ..., current_tab_id: _Optional[str] = ..., current_tab_name: _Optional[str] = ..., current_output_id: _Optional[str] = ..., current_output_name: _Optional[str] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., total_tabs: _Optional[int] = ...) -> None: ...

class WorkerStartBuildRunRequest(_message.Message):
    __slots__ = ("namespace", "build_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    build_id: str
    def __init__(self, namespace: _Optional[str] = ..., build_id: _Optional[str] = ...) -> None: ...

class WorkerStartBuildRunResponse(_message.Message):
    __slots__ = ("run",)
    RUN_FIELD_NUMBER: _ClassVar[int]
    run: WorkerBuildRunPayload
    def __init__(self, run: _Optional[_Union[WorkerBuildRunPayload, _Mapping]] = ...) -> None: ...

class WorkerPersistEngineSnapshotRequest(_message.Message):
    __slots__ = ("worker_id", "namespace", "statuses")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    STATUSES_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    namespace: str
    statuses: _containers.RepeatedCompositeFieldContainer[_common_pb2.JsonPayload]
    def __init__(self, worker_id: _Optional[str] = ..., namespace: _Optional[str] = ..., statuses: _Optional[_Iterable[_Union[_common_pb2.JsonPayload, _Mapping]]] = ...) -> None: ...

class WorkerPendingDatasourceDelete(_message.Message):
    __slots__ = ("namespace", "datasource_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ...) -> None: ...

class WorkerPendingDatasourceDeletesResponse(_message.Message):
    __slots__ = ("deletes",)
    DELETES_FIELD_NUMBER: _ClassVar[int]
    deletes: _containers.RepeatedCompositeFieldContainer[WorkerPendingDatasourceDelete]
    def __init__(self, deletes: _Optional[_Iterable[_Union[WorkerPendingDatasourceDelete, _Mapping]]] = ...) -> None: ...

class WorkerFinalizeDatasourceDeleteRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ...) -> None: ...

class WorkerFinalizeDatasourceDeleteResponse(_message.Message):
    __slots__ = ("deleted",)
    DELETED_FIELD_NUMBER: _ClassVar[int]
    deleted: bool
    def __init__(self, deleted: _Optional[bool] = ...) -> None: ...

class WorkerTelegramSettingsResponse(_message.Message):
    __slots__ = ("enabled",)
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    enabled: bool
    def __init__(self, enabled: _Optional[bool] = ...) -> None: ...

class WorkerSendEmailRequest(_message.Message):
    __slots__ = ("to", "subject", "body", "attachments")
    TO_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    to: str
    subject: str
    body: str
    attachments: _containers.RepeatedCompositeFieldContainer[_common_pb2.NotificationAttachment]
    def __init__(self, to: _Optional[str] = ..., subject: _Optional[str] = ..., body: _Optional[str] = ..., attachments: _Optional[_Iterable[_Union[_common_pb2.NotificationAttachment, _Mapping]]] = ...) -> None: ...

class WorkerSendTelegramRequest(_message.Message):
    __slots__ = ("chat_id", "message", "bot_token", "attachments")
    CHAT_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    BOT_TOKEN_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    chat_id: str
    message: str
    bot_token: str
    attachments: _containers.RepeatedCompositeFieldContainer[_common_pb2.NotificationAttachment]
    def __init__(self, chat_id: _Optional[str] = ..., message: _Optional[str] = ..., bot_token: _Optional[str] = ..., attachments: _Optional[_Iterable[_Union[_common_pb2.NotificationAttachment, _Mapping]]] = ...) -> None: ...

class WorkerGenerateAIRequest(_message.Message):
    __slots__ = ("provider", "prompts", "model", "endpoint_url", "api_key", "options")
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    PROMPTS_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_URL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_FIELD_NUMBER: _ClassVar[int]
    provider: _enums_pb2.AIProvider
    prompts: _containers.RepeatedScalarFieldContainer[str]
    model: str
    endpoint_url: str
    api_key: str
    options: _common_pb2.JsonPayload
    def __init__(self, provider: _Optional[_Union[_enums_pb2.AIProvider, str]] = ..., prompts: _Optional[_Iterable[str]] = ..., model: _Optional[str] = ..., endpoint_url: _Optional[str] = ..., api_key: _Optional[str] = ..., options: _Optional[_Union[_common_pb2.JsonPayload, _Mapping]] = ...) -> None: ...

class WorkerGenerateAIResponse(_message.Message):
    __slots__ = ("outputs",)
    OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    outputs: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, outputs: _Optional[_Iterable[str]] = ...) -> None: ...

class WorkerTelegramTargetsRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id", "active_subscribers")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_SUBSCRIBERS_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    active_subscribers: bool
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ..., active_subscribers: _Optional[bool] = ...) -> None: ...

class WorkerTelegramTarget(_message.Message):
    __slots__ = ("chat_id", "bot_token")
    CHAT_ID_FIELD_NUMBER: _ClassVar[int]
    BOT_TOKEN_FIELD_NUMBER: _ClassVar[int]
    chat_id: str
    bot_token: str
    def __init__(self, chat_id: _Optional[str] = ..., bot_token: _Optional[str] = ...) -> None: ...

class WorkerTelegramTargetsResponse(_message.Message):
    __slots__ = ("targets",)
    TARGETS_FIELD_NUMBER: _ClassVar[int]
    targets: _containers.RepeatedCompositeFieldContainer[WorkerTelegramTarget]
    def __init__(self, targets: _Optional[_Iterable[_Union[WorkerTelegramTarget, _Mapping]]] = ...) -> None: ...

class CountResponse(_message.Message):
    __slots__ = ("count",)
    COUNT_FIELD_NUMBER: _ClassVar[int]
    count: int
    def __init__(self, count: _Optional[int] = ...) -> None: ...

class BoolResponse(_message.Message):
    __slots__ = ("value",)
    VALUE_FIELD_NUMBER: _ClassVar[int]
    value: bool
    def __init__(self, value: _Optional[bool] = ...) -> None: ...

class IdResponse(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...
