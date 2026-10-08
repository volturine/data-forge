import datetime

from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import analysis_pb2 as _analysis_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from dataforge_protocol import compute_pb2 as _compute_pb2
from dataforge_protocol import datasource_pb2 as _datasource_pb2
from dataforge_protocol import enums_pb2 as _enums_pb2
from google.protobuf import struct_pb2 as _struct_pb2
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
    __slots__ = ("job_id", "build_id", "namespace", "claim_token", "lease_generation", "lease_expires_at", "attempt", "lease_ttl_seconds")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    LEASE_EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    LEASE_TTL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    build_id: str
    namespace: str
    claim_token: str
    lease_generation: int
    lease_expires_at: _timestamp_pb2.Timestamp
    attempt: int
    lease_ttl_seconds: int
    def __init__(self, job_id: _Optional[str] = ..., build_id: _Optional[str] = ..., namespace: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ..., lease_expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., attempt: _Optional[int] = ..., lease_ttl_seconds: _Optional[int] = ...) -> None: ...

class WorkerClaimBuildJobResponse(_message.Message):
    __slots__ = ("job",)
    JOB_FIELD_NUMBER: _ClassVar[int]
    job: WorkerClaimedBuildJob
    def __init__(self, job: _Optional[_Union[WorkerClaimedBuildJob, _Mapping]] = ...) -> None: ...

class WorkerPendingRuntimeWorkNamespacesRequest(_message.Message):
    __slots__ = ("kinds",)
    KINDS_FIELD_NUMBER: _ClassVar[int]
    kinds: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, kinds: _Optional[_Iterable[str]] = ...) -> None: ...

class WorkerBuildJobClaimRequest(_message.Message):
    __slots__ = ("job_id", "namespace", "claim_token", "lease_generation", "worker_id")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    namespace: str
    claim_token: str
    lease_generation: int
    worker_id: str
    def __init__(self, job_id: _Optional[str] = ..., namespace: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ..., worker_id: _Optional[str] = ...) -> None: ...

class WorkerRenewBuildJobLeaseResponse(_message.Message):
    __slots__ = ("renewed", "lease_expires_at", "lease_ttl_seconds")
    RENEWED_FIELD_NUMBER: _ClassVar[int]
    LEASE_EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    LEASE_TTL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    renewed: bool
    lease_expires_at: _timestamp_pb2.Timestamp
    lease_ttl_seconds: int
    def __init__(self, renewed: _Optional[bool] = ..., lease_expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., lease_ttl_seconds: _Optional[int] = ...) -> None: ...

class WorkerClaimedComputeRequest(_message.Message):
    __slots__ = ("id", "namespace", "kind", "command", "claim_token", "lease_generation", "lease_expires_at", "attempt", "lease_ttl_seconds")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    LEASE_EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    LEASE_TTL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    id: str
    namespace: str
    kind: _enums_pb2.ComputeRequestKind
    command: _compute_pb2.ComputeCommandEnvelope
    claim_token: str
    lease_generation: int
    lease_expires_at: _timestamp_pb2.Timestamp
    attempt: int
    lease_ttl_seconds: int
    def __init__(self, id: _Optional[str] = ..., namespace: _Optional[str] = ..., kind: _Optional[_Union[_enums_pb2.ComputeRequestKind, str]] = ..., command: _Optional[_Union[_compute_pb2.ComputeCommandEnvelope, _Mapping]] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ..., lease_expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., attempt: _Optional[int] = ..., lease_ttl_seconds: _Optional[int] = ...) -> None: ...

class WorkerClaimComputeRequestResponse(_message.Message):
    __slots__ = ("request",)
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    request: WorkerClaimedComputeRequest
    def __init__(self, request: _Optional[_Union[WorkerClaimedComputeRequest, _Mapping]] = ...) -> None: ...

class WorkerComputeRequestLeaseRenewal(_message.Message):
    __slots__ = ("request_id", "claim_token", "lease_generation")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    claim_token: str
    lease_generation: int
    def __init__(self, request_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ...) -> None: ...

class WorkerRenewComputeRequestLeasesRequest(_message.Message):
    __slots__ = ("namespace", "worker_id", "renewals")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    RENEWALS_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    worker_id: str
    renewals: _containers.RepeatedCompositeFieldContainer[WorkerComputeRequestLeaseRenewal]
    def __init__(self, namespace: _Optional[str] = ..., worker_id: _Optional[str] = ..., renewals: _Optional[_Iterable[_Union[WorkerComputeRequestLeaseRenewal, _Mapping]]] = ...) -> None: ...

class WorkerComputeRequestLeaseRenewalResult(_message.Message):
    __slots__ = ("request_id", "renewed", "lease_ttl_seconds")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    RENEWED_FIELD_NUMBER: _ClassVar[int]
    LEASE_TTL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    renewed: bool
    lease_ttl_seconds: int
    def __init__(self, request_id: _Optional[str] = ..., renewed: _Optional[bool] = ..., lease_ttl_seconds: _Optional[int] = ...) -> None: ...

class WorkerRenewComputeRequestLeasesResponse(_message.Message):
    __slots__ = ("renewals",)
    RENEWALS_FIELD_NUMBER: _ClassVar[int]
    renewals: _containers.RepeatedCompositeFieldContainer[WorkerComputeRequestLeaseRenewalResult]
    def __init__(self, renewals: _Optional[_Iterable[_Union[WorkerComputeRequestLeaseRenewalResult, _Mapping]]] = ...) -> None: ...

class WorkerCompleteComputeRequestRequest(_message.Message):
    __slots__ = ("namespace", "request_id", "artifact_path", "artifact_name", "artifact_content_type", "response_envelope", "worker_id", "claim_token", "lease_generation", "engine_run_finalization")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_PATH_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_NAME_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_ENVELOPE_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    ENGINE_RUN_FINALIZATION_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    request_id: str
    artifact_path: str
    artifact_name: str
    artifact_content_type: str
    response_envelope: _compute_pb2.ComputeResponseEnvelope
    worker_id: str
    claim_token: str
    lease_generation: int
    engine_run_finalization: WorkerComputeWorkerRunFinalization
    def __init__(self, namespace: _Optional[str] = ..., request_id: _Optional[str] = ..., artifact_path: _Optional[str] = ..., artifact_name: _Optional[str] = ..., artifact_content_type: _Optional[str] = ..., response_envelope: _Optional[_Union[_compute_pb2.ComputeResponseEnvelope, _Mapping]] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ..., engine_run_finalization: _Optional[_Union[WorkerComputeWorkerRunFinalization, _Mapping]] = ...) -> None: ...

class WorkerFailComputeRequestRequest(_message.Message):
    __slots__ = ("namespace", "request_id", "error_message", "response_envelope", "worker_id", "claim_token", "lease_generation", "engine_run_finalization")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_ENVELOPE_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    ENGINE_RUN_FINALIZATION_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    request_id: str
    error_message: str
    response_envelope: _compute_pb2.ComputeResponseEnvelope
    worker_id: str
    claim_token: str
    lease_generation: int
    engine_run_finalization: WorkerComputeWorkerRunFinalization
    def __init__(self, namespace: _Optional[str] = ..., request_id: _Optional[str] = ..., error_message: _Optional[str] = ..., response_envelope: _Optional[_Union[_compute_pb2.ComputeResponseEnvelope, _Mapping]] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ..., engine_run_finalization: _Optional[_Union[WorkerComputeWorkerRunFinalization, _Mapping]] = ...) -> None: ...

class WorkerRegisterDatasourceStageRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id", "worker_id", "claim_token", "lease_generation", "compute_request_id", "job_id", "build_id", "prefix_url", "artifact_url", "catalog_identifier")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    COMPUTE_REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    PREFIX_URL_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_URL_FIELD_NUMBER: _ClassVar[int]
    CATALOG_IDENTIFIER_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    worker_id: str
    claim_token: str
    lease_generation: int
    compute_request_id: str
    job_id: str
    build_id: str
    prefix_url: str
    artifact_url: str
    catalog_identifier: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ..., compute_request_id: _Optional[str] = ..., job_id: _Optional[str] = ..., build_id: _Optional[str] = ..., prefix_url: _Optional[str] = ..., artifact_url: _Optional[str] = ..., catalog_identifier: _Optional[str] = ...) -> None: ...

class WorkerClaimStorageCleanupRequest(_message.Message):
    __slots__ = ("namespace", "limit")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    limit: int
    def __init__(self, namespace: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class WorkerStorageCleanupClaimRequest(_message.Message):
    __slots__ = ("namespace", "event_id", "claim_token", "lease_generation")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    event_id: str
    claim_token: str
    lease_generation: int
    def __init__(self, namespace: _Optional[str] = ..., event_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ...) -> None: ...

class WorkerStorageCleanupClaim(_message.Message):
    __slots__ = ("claim", "resource_id", "url", "is_prefix", "catalog_identifier", "catalog_type", "catalog_uri", "warehouse", "catalog_namespace", "catalog_table", "catalog_family_prefix")
    CLAIM_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    IS_PREFIX_FIELD_NUMBER: _ClassVar[int]
    CATALOG_IDENTIFIER_FIELD_NUMBER: _ClassVar[int]
    CATALOG_TYPE_FIELD_NUMBER: _ClassVar[int]
    CATALOG_URI_FIELD_NUMBER: _ClassVar[int]
    WAREHOUSE_FIELD_NUMBER: _ClassVar[int]
    CATALOG_NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    CATALOG_TABLE_FIELD_NUMBER: _ClassVar[int]
    CATALOG_FAMILY_PREFIX_FIELD_NUMBER: _ClassVar[int]
    claim: WorkerStorageCleanupClaimRequest
    resource_id: str
    url: str
    is_prefix: bool
    catalog_identifier: str
    catalog_type: str
    catalog_uri: str
    warehouse: str
    catalog_namespace: str
    catalog_table: str
    catalog_family_prefix: str
    def __init__(self, claim: _Optional[_Union[WorkerStorageCleanupClaimRequest, _Mapping]] = ..., resource_id: _Optional[str] = ..., url: _Optional[str] = ..., is_prefix: _Optional[bool] = ..., catalog_identifier: _Optional[str] = ..., catalog_type: _Optional[str] = ..., catalog_uri: _Optional[str] = ..., warehouse: _Optional[str] = ..., catalog_namespace: _Optional[str] = ..., catalog_table: _Optional[str] = ..., catalog_family_prefix: _Optional[str] = ...) -> None: ...

class WorkerStorageCleanupClaimsResponse(_message.Message):
    __slots__ = ("cleanups",)
    CLEANUPS_FIELD_NUMBER: _ClassVar[int]
    cleanups: _containers.RepeatedCompositeFieldContainer[WorkerStorageCleanupClaim]
    def __init__(self, cleanups: _Optional[_Iterable[_Union[WorkerStorageCleanupClaim, _Mapping]]] = ...) -> None: ...

class WorkerCompleteStorageCleanupRequest(_message.Message):
    __slots__ = ("claim", "error")
    CLAIM_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    claim: WorkerStorageCleanupClaimRequest
    error: str
    def __init__(self, claim: _Optional[_Union[WorkerStorageCleanupClaimRequest, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class WorkerPublishDatasourceCreateRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id", "name", "description", "source_type", "config", "owner_id", "schema_info", "compute_request_id", "worker_id", "claim_token", "lease_generation")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    OWNER_ID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_INFO_FIELD_NUMBER: _ClassVar[int]
    COMPUTE_REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    name: str
    description: str
    source_type: _enums_pb2.DataSourceType
    config: _struct_pb2.Struct
    owner_id: str
    schema_info: _datasource_pb2.SchemaInfo
    compute_request_id: str
    worker_id: str
    claim_token: str
    lease_generation: int
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ..., name: _Optional[str] = ..., description: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., owner_id: _Optional[str] = ..., schema_info: _Optional[_Union[_datasource_pb2.SchemaInfo, _Mapping]] = ..., compute_request_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ...) -> None: ...

class WorkerPublishDatasourceCreateResponse(_message.Message):
    __slots__ = ("datasource",)
    DATASOURCE_FIELD_NUMBER: _ClassVar[int]
    datasource: _datasource_pb2.DataSourceRecord
    def __init__(self, datasource: _Optional[_Union[_datasource_pb2.DataSourceRecord, _Mapping]] = ...) -> None: ...

class WorkerPublishDatasourceIngestRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id", "config", "expected_revision", "schema_info", "compute_request_id", "job_id", "build_id", "worker_id", "claim_token", "lease_generation")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_REVISION_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_INFO_FIELD_NUMBER: _ClassVar[int]
    COMPUTE_REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    config: _struct_pb2.Struct
    expected_revision: int
    schema_info: _datasource_pb2.SchemaInfo
    compute_request_id: str
    job_id: str
    build_id: str
    worker_id: str
    claim_token: str
    lease_generation: int
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., expected_revision: _Optional[int] = ..., schema_info: _Optional[_Union[_datasource_pb2.SchemaInfo, _Mapping]] = ..., compute_request_id: _Optional[str] = ..., job_id: _Optional[str] = ..., build_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ...) -> None: ...

class WorkerPublishDatasourceIngestResponse(_message.Message):
    __slots__ = ("datasource",)
    DATASOURCE_FIELD_NUMBER: _ClassVar[int]
    datasource: _datasource_pb2.DataSourceRecord
    def __init__(self, datasource: _Optional[_Union[_datasource_pb2.DataSourceRecord, _Mapping]] = ...) -> None: ...

class WorkerPublishDatasourceSchemaCacheRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id", "schema_info", "expected_revision", "compute_request_id", "worker_id", "claim_token", "lease_generation")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_INFO_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_REVISION_FIELD_NUMBER: _ClassVar[int]
    COMPUTE_REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    schema_info: _datasource_pb2.SchemaInfo
    expected_revision: int
    compute_request_id: str
    worker_id: str
    claim_token: str
    lease_generation: int
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ..., schema_info: _Optional[_Union[_datasource_pb2.SchemaInfo, _Mapping]] = ..., expected_revision: _Optional[int] = ..., compute_request_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ...) -> None: ...

class WorkerPublishDatasourceSchemaCacheResponse(_message.Message):
    __slots__ = ("schema_info",)
    SCHEMA_INFO_FIELD_NUMBER: _ClassVar[int]
    schema_info: _datasource_pb2.SchemaInfo
    def __init__(self, schema_info: _Optional[_Union[_datasource_pb2.SchemaInfo, _Mapping]] = ...) -> None: ...

class WorkerDatasourceMetadataRequest(_message.Message):
    __slots__ = ("namespace", "datasource_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    datasource_id: str
    def __init__(self, namespace: _Optional[str] = ..., datasource_id: _Optional[str] = ...) -> None: ...

class WorkerDatasourceMetadataResponse(_message.Message):
    __slots__ = ("found", "id", "name", "source_type", "config", "is_hidden", "schema_info", "revision", "description", "column_descriptions", "created_by")
    class ColumnDescriptionsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    FOUND_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    IS_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_INFO_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    COLUMN_DESCRIPTIONS_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    found: bool
    id: str
    name: str
    source_type: _enums_pb2.DataSourceType
    config: _struct_pb2.Struct
    is_hidden: bool
    schema_info: _datasource_pb2.SchemaInfo
    revision: int
    description: str
    column_descriptions: _containers.ScalarMap[str, str]
    created_by: str
    def __init__(self, found: _Optional[bool] = ..., id: _Optional[str] = ..., name: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., is_hidden: _Optional[bool] = ..., schema_info: _Optional[_Union[_datasource_pb2.SchemaInfo, _Mapping]] = ..., revision: _Optional[int] = ..., description: _Optional[str] = ..., column_descriptions: _Optional[_Mapping[str, str]] = ..., created_by: _Optional[str] = ...) -> None: ...

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

class WorkerComputeWorkerCredentialsRequest(_message.Message):
    __slots__ = ("namespace", "role")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    role: str
    def __init__(self, namespace: _Optional[str] = ..., role: _Optional[str] = ...) -> None: ...

class WorkerComputeWorkerCredentialsResponse(_message.Message):
    __slots__ = ("access_key", "secret_key")
    ACCESS_KEY_FIELD_NUMBER: _ClassVar[int]
    SECRET_KEY_FIELD_NUMBER: _ClassVar[int]
    access_key: str
    secret_key: str
    def __init__(self, access_key: _Optional[str] = ..., secret_key: _Optional[str] = ...) -> None: ...

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
    __slots__ = ("namespace", "build_id", "result", "job_id", "worker_id", "claim_token", "lease_generation")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    build_id: str
    result: _struct_pb2.Struct
    job_id: str
    worker_id: str
    claim_token: str
    lease_generation: int
    def __init__(self, namespace: _Optional[str] = ..., build_id: _Optional[str] = ..., result: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., job_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ...) -> None: ...

class WorkerUpsertOutputDatasourceRequest(_message.Message):
    __slots__ = ("namespace", "result_id", "name", "source_type", "config", "analysis_id", "is_hidden", "keep_schema_cache", "schema_info", "job_id", "build_id", "worker_id", "claim_token", "lease_generation", "build_result", "notification_delivery")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    RESULT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    IS_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    KEEP_SCHEMA_CACHE_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_INFO_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    BUILD_RESULT_FIELD_NUMBER: _ClassVar[int]
    NOTIFICATION_DELIVERY_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    result_id: str
    name: str
    source_type: _enums_pb2.DataSourceType
    config: _struct_pb2.Struct
    analysis_id: str
    is_hidden: bool
    keep_schema_cache: bool
    schema_info: _datasource_pb2.SchemaInfo
    job_id: str
    build_id: str
    worker_id: str
    claim_token: str
    lease_generation: int
    build_result: _struct_pb2.Struct
    notification_delivery: _containers.RepeatedCompositeFieldContainer[WorkerNotificationDelivery]
    def __init__(self, namespace: _Optional[str] = ..., result_id: _Optional[str] = ..., name: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., analysis_id: _Optional[str] = ..., is_hidden: _Optional[bool] = ..., keep_schema_cache: _Optional[bool] = ..., schema_info: _Optional[_Union[_datasource_pb2.SchemaInfo, _Mapping]] = ..., job_id: _Optional[str] = ..., build_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ..., build_result: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., notification_delivery: _Optional[_Iterable[_Union[WorkerNotificationDelivery, _Mapping]]] = ...) -> None: ...

class WorkerEmailDelivery(_message.Message):
    __slots__ = ("to", "subject", "body")
    TO_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    to: str
    subject: str
    body: str
    def __init__(self, to: _Optional[str] = ..., subject: _Optional[str] = ..., body: _Optional[str] = ...) -> None: ...

class WorkerTelegramDelivery(_message.Message):
    __slots__ = ("chat_id", "message", "bot_token")
    CHAT_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    BOT_TOKEN_FIELD_NUMBER: _ClassVar[int]
    chat_id: str
    message: str
    bot_token: str
    def __init__(self, chat_id: _Optional[str] = ..., message: _Optional[str] = ..., bot_token: _Optional[str] = ...) -> None: ...

class WorkerNotificationDelivery(_message.Message):
    __slots__ = ("email", "telegram")
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    TELEGRAM_FIELD_NUMBER: _ClassVar[int]
    email: WorkerEmailDelivery
    telegram: WorkerTelegramDelivery
    def __init__(self, email: _Optional[_Union[WorkerEmailDelivery, _Mapping]] = ..., telegram: _Optional[_Union[WorkerTelegramDelivery, _Mapping]] = ...) -> None: ...

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
    config: _struct_pb2.Struct
    critical: bool
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., check_type: _Optional[_Union[_enums_pb2.HealthCheckType, str]] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., critical: _Optional[bool] = ...) -> None: ...

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
    details: _struct_pb2.Struct
    checked_at: _timestamp_pb2.Timestamp
    def __init__(self, healthcheck_id: _Optional[str] = ..., passed: _Optional[bool] = ..., message: _Optional[str] = ..., details: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., checked_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class WorkerRecordHealthCheckResultsRequest(_message.Message):
    __slots__ = ("namespace", "results")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    results: _containers.RepeatedCompositeFieldContainer[WorkerHealthCheckResultPayload]
    def __init__(self, namespace: _Optional[str] = ..., results: _Optional[_Iterable[_Union[WorkerHealthCheckResultPayload, _Mapping]]] = ...) -> None: ...

class WorkerCreateComputeWorkerRunRequest(_message.Message):
    __slots__ = ("namespace", "analysis_id", "datasource_id", "kind", "status", "request", "result", "error_message", "created_at", "completed_at", "duration_ms", "query_plan", "progress", "current_step", "triggered_by", "timing_by_key", "execution_entry", "idempotency_key")
    class TimingByKeyEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    QUERY_PLAN_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STEP_FIELD_NUMBER: _ClassVar[int]
    TRIGGERED_BY_FIELD_NUMBER: _ClassVar[int]
    TIMING_BY_KEY_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_ENTRY_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    analysis_id: str
    datasource_id: str
    kind: _enums_pb2.ComputeWorkerRunKind
    status: _enums_pb2.ComputeWorkerRunStatus
    request: _struct_pb2.Struct
    result: _struct_pb2.Struct
    error_message: str
    created_at: _timestamp_pb2.Timestamp
    completed_at: _timestamp_pb2.Timestamp
    duration_ms: int
    query_plan: str
    progress: float
    current_step: str
    triggered_by: str
    timing_by_key: _containers.ScalarMap[str, float]
    execution_entry: _containers.RepeatedCompositeFieldContainer[_compute_pb2.ComputeWorkerRunExecutionEntry]
    idempotency_key: str
    def __init__(self, namespace: _Optional[str] = ..., analysis_id: _Optional[str] = ..., datasource_id: _Optional[str] = ..., kind: _Optional[_Union[_enums_pb2.ComputeWorkerRunKind, str]] = ..., status: _Optional[_Union[_enums_pb2.ComputeWorkerRunStatus, str]] = ..., request: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., result: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., error_message: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., duration_ms: _Optional[int] = ..., query_plan: _Optional[str] = ..., progress: _Optional[float] = ..., current_step: _Optional[str] = ..., triggered_by: _Optional[str] = ..., timing_by_key: _Optional[_Mapping[str, float]] = ..., execution_entry: _Optional[_Iterable[_Union[_compute_pb2.ComputeWorkerRunExecutionEntry, _Mapping]]] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class ComputeWorkerRunStepTimings(_message.Message):
    __slots__ = ("values",)
    class ValuesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    VALUES_FIELD_NUMBER: _ClassVar[int]
    values: _containers.ScalarMap[str, float]
    def __init__(self, values: _Optional[_Mapping[str, float]] = ...) -> None: ...

class ComputeWorkerRunExecutionEntryList(_message.Message):
    __slots__ = ("entries",)
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[_compute_pb2.ComputeWorkerRunExecutionEntry]
    def __init__(self, entries: _Optional[_Iterable[_Union[_compute_pb2.ComputeWorkerRunExecutionEntry, _Mapping]]] = ...) -> None: ...

class WorkerComputeWorkerRunUpdateFields(_message.Message):
    __slots__ = ("analysis_id", "datasource_id", "kind", "status", "request_json", "result_json", "error_message", "completed_at", "duration_ms", "step_timings", "query_plan", "execution_entries", "progress", "current_step", "triggered_by", "clear_current_step")
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    REQUEST_JSON_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    STEP_TIMINGS_FIELD_NUMBER: _ClassVar[int]
    QUERY_PLAN_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STEP_FIELD_NUMBER: _ClassVar[int]
    TRIGGERED_BY_FIELD_NUMBER: _ClassVar[int]
    CLEAR_CURRENT_STEP_FIELD_NUMBER: _ClassVar[int]
    analysis_id: str
    datasource_id: str
    kind: _enums_pb2.ComputeWorkerRunKind
    status: _enums_pb2.ComputeWorkerRunStatus
    request_json: _struct_pb2.Struct
    result_json: _struct_pb2.Struct
    error_message: str
    completed_at: _timestamp_pb2.Timestamp
    duration_ms: int
    step_timings: ComputeWorkerRunStepTimings
    query_plan: str
    execution_entries: ComputeWorkerRunExecutionEntryList
    progress: float
    current_step: str
    triggered_by: str
    clear_current_step: bool
    def __init__(self, analysis_id: _Optional[str] = ..., datasource_id: _Optional[str] = ..., kind: _Optional[_Union[_enums_pb2.ComputeWorkerRunKind, str]] = ..., status: _Optional[_Union[_enums_pb2.ComputeWorkerRunStatus, str]] = ..., request_json: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., result_json: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., error_message: _Optional[str] = ..., completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., duration_ms: _Optional[int] = ..., step_timings: _Optional[_Union[ComputeWorkerRunStepTimings, _Mapping]] = ..., query_plan: _Optional[str] = ..., execution_entries: _Optional[_Union[ComputeWorkerRunExecutionEntryList, _Mapping]] = ..., progress: _Optional[float] = ..., current_step: _Optional[str] = ..., triggered_by: _Optional[str] = ..., clear_current_step: _Optional[bool] = ...) -> None: ...

class WorkerComputeWorkerRunFinalization(_message.Message):
    __slots__ = ("run_id", "merge_result", "update")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    MERGE_RESULT_FIELD_NUMBER: _ClassVar[int]
    UPDATE_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    merge_result: bool
    update: WorkerComputeWorkerRunUpdateFields
    def __init__(self, run_id: _Optional[str] = ..., merge_result: _Optional[bool] = ..., update: _Optional[_Union[WorkerComputeWorkerRunUpdateFields, _Mapping]] = ...) -> None: ...

class WorkerUpdateComputeWorkerRunRequest(_message.Message):
    __slots__ = ("namespace", "run_id", "merge_result", "update")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    MERGE_RESULT_FIELD_NUMBER: _ClassVar[int]
    UPDATE_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    run_id: str
    merge_result: bool
    update: WorkerComputeWorkerRunUpdateFields
    def __init__(self, namespace: _Optional[str] = ..., run_id: _Optional[str] = ..., merge_result: _Optional[bool] = ..., update: _Optional[_Union[WorkerComputeWorkerRunUpdateFields, _Mapping]] = ...) -> None: ...

class WorkerComputeWorkerRunStateRequest(_message.Message):
    __slots__ = ("namespace", "run_id")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    run_id: str
    def __init__(self, namespace: _Optional[str] = ..., run_id: _Optional[str] = ...) -> None: ...

class WorkerComputeWorkerRunStateResponse(_message.Message):
    __slots__ = ("found", "status", "result", "cancelled_at", "cancelled_by")
    FOUND_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_AT_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_BY_FIELD_NUMBER: _ClassVar[int]
    found: bool
    status: _enums_pb2.ComputeWorkerRunStatus
    result: _struct_pb2.Struct
    cancelled_at: _timestamp_pb2.Timestamp
    cancelled_by: str
    def __init__(self, found: _Optional[bool] = ..., status: _Optional[_Union[_enums_pb2.ComputeWorkerRunStatus, str]] = ..., result: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., cancelled_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., cancelled_by: _Optional[str] = ...) -> None: ...

class WorkerFailBuildJobRequest(_message.Message):
    __slots__ = ("job_id", "namespace", "error", "claim_token", "lease_generation", "worker_id", "build_id")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    namespace: str
    error: str
    claim_token: str
    lease_generation: int
    worker_id: str
    build_id: str
    def __init__(self, job_id: _Optional[str] = ..., namespace: _Optional[str] = ..., error: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ..., worker_id: _Optional[str] = ..., build_id: _Optional[str] = ...) -> None: ...

class WorkerFinalizeBuildJobRequest(_message.Message):
    __slots__ = ("job_id", "build_id", "namespace", "claim_token", "lease_generation", "worker_id")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    build_id: str
    namespace: str
    claim_token: str
    lease_generation: int
    worker_id: str
    def __init__(self, job_id: _Optional[str] = ..., build_id: _Optional[str] = ..., namespace: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ..., worker_id: _Optional[str] = ...) -> None: ...

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
    __slots__ = ("namespace", "build_id", "build_event", "build_resource_config", "job_id", "worker_id", "claim_token", "lease_generation")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_EVENT_FIELD_NUMBER: _ClassVar[int]
    BUILD_RESOURCE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    build_id: str
    build_event: _compute_pb2.BuildEvent
    build_resource_config: _compute_pb2.BuildResourceConfigSummary
    job_id: str
    worker_id: str
    claim_token: str
    lease_generation: int
    def __init__(self, namespace: _Optional[str] = ..., build_id: _Optional[str] = ..., build_event: _Optional[_Union[_compute_pb2.BuildEvent, _Mapping]] = ..., build_resource_config: _Optional[_Union[_compute_pb2.BuildResourceConfigSummary, _Mapping]] = ..., job_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ...) -> None: ...

class WorkerPersistBuildEventResponse(_message.Message):
    __slots__ = ("sequence",)
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    sequence: int
    def __init__(self, sequence: _Optional[int] = ...) -> None: ...

class WorkerBuildRunPayload(_message.Message):
    __slots__ = ("id", "namespace", "analysis_id", "analysis_name", "current_kind", "current_datasource_id", "current_tab_id", "current_tab_name", "current_output_id", "current_output_name", "started_at", "total_tabs", "build_starter", "build_resource_config", "analysis_pipeline", "tab_id")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_NAME_FIELD_NUMBER: _ClassVar[int]
    CURRENT_KIND_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DATASOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TAB_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TAB_NAME_FIELD_NUMBER: _ClassVar[int]
    CURRENT_OUTPUT_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_OUTPUT_NAME_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_TABS_FIELD_NUMBER: _ClassVar[int]
    BUILD_STARTER_FIELD_NUMBER: _ClassVar[int]
    BUILD_RESOURCE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_PIPELINE_FIELD_NUMBER: _ClassVar[int]
    TAB_ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    namespace: str
    analysis_id: str
    analysis_name: str
    current_kind: _enums_pb2.ComputeWorkerRunKind
    current_datasource_id: str
    current_tab_id: str
    current_tab_name: str
    current_output_id: str
    current_output_name: str
    started_at: _timestamp_pb2.Timestamp
    total_tabs: int
    build_starter: _compute_pb2.BuildStarter
    build_resource_config: _compute_pb2.BuildResourceConfigSummary
    analysis_pipeline: _analysis_pb2.AnalysisPipelinePayload
    tab_id: str
    def __init__(self, id: _Optional[str] = ..., namespace: _Optional[str] = ..., analysis_id: _Optional[str] = ..., analysis_name: _Optional[str] = ..., current_kind: _Optional[_Union[_enums_pb2.ComputeWorkerRunKind, str]] = ..., current_datasource_id: _Optional[str] = ..., current_tab_id: _Optional[str] = ..., current_tab_name: _Optional[str] = ..., current_output_id: _Optional[str] = ..., current_output_name: _Optional[str] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., total_tabs: _Optional[int] = ..., build_starter: _Optional[_Union[_compute_pb2.BuildStarter, _Mapping]] = ..., build_resource_config: _Optional[_Union[_compute_pb2.BuildResourceConfigSummary, _Mapping]] = ..., analysis_pipeline: _Optional[_Union[_analysis_pb2.AnalysisPipelinePayload, _Mapping]] = ..., tab_id: _Optional[str] = ...) -> None: ...

class WorkerStartBuildRunRequest(_message.Message):
    __slots__ = ("namespace", "build_id", "job_id", "worker_id", "claim_token", "lease_generation")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    BUILD_ID_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    CLAIM_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    build_id: str
    job_id: str
    worker_id: str
    claim_token: str
    lease_generation: int
    def __init__(self, namespace: _Optional[str] = ..., build_id: _Optional[str] = ..., job_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., claim_token: _Optional[str] = ..., lease_generation: _Optional[int] = ...) -> None: ...

class WorkerStartBuildRunResponse(_message.Message):
    __slots__ = ("run",)
    RUN_FIELD_NUMBER: _ClassVar[int]
    run: WorkerBuildRunPayload
    def __init__(self, run: _Optional[_Union[WorkerBuildRunPayload, _Mapping]] = ...) -> None: ...

class WorkerPersistComputeWorkerSnapshotRequest(_message.Message):
    __slots__ = ("worker_id", "namespace", "engine_status")
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    ENGINE_STATUS_FIELD_NUMBER: _ClassVar[int]
    worker_id: str
    namespace: str
    engine_status: _containers.RepeatedCompositeFieldContainer[_compute_pb2.ComputeWorkerStatusResult]
    def __init__(self, worker_id: _Optional[str] = ..., namespace: _Optional[str] = ..., engine_status: _Optional[_Iterable[_Union[_compute_pb2.ComputeWorkerStatusResult, _Mapping]]] = ...) -> None: ...

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
    __slots__ = ("to", "subject", "body", "attachments", "namespace")
    TO_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    to: str
    subject: str
    body: str
    attachments: _containers.RepeatedCompositeFieldContainer[_common_pb2.NotificationAttachment]
    namespace: str
    def __init__(self, to: _Optional[str] = ..., subject: _Optional[str] = ..., body: _Optional[str] = ..., attachments: _Optional[_Iterable[_Union[_common_pb2.NotificationAttachment, _Mapping]]] = ..., namespace: _Optional[str] = ...) -> None: ...

class WorkerSendTelegramRequest(_message.Message):
    __slots__ = ("chat_id", "message", "bot_token", "attachments", "namespace")
    CHAT_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    BOT_TOKEN_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    chat_id: str
    message: str
    bot_token: str
    attachments: _containers.RepeatedCompositeFieldContainer[_common_pb2.NotificationAttachment]
    namespace: str
    def __init__(self, chat_id: _Optional[str] = ..., message: _Optional[str] = ..., bot_token: _Optional[str] = ..., attachments: _Optional[_Iterable[_Union[_common_pb2.NotificationAttachment, _Mapping]]] = ..., namespace: _Optional[str] = ...) -> None: ...

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
    options: _struct_pb2.Struct
    def __init__(self, provider: _Optional[_Union[_enums_pb2.AIProvider, str]] = ..., prompts: _Optional[_Iterable[str]] = ..., model: _Optional[str] = ..., endpoint_url: _Optional[str] = ..., api_key: _Optional[str] = ..., options: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

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
