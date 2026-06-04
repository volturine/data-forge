from __future__ import annotations

from pydantic import BaseModel, Field


class RuntimeWorkerRequest(BaseModel):
    worker_id: str = Field(min_length=1)


class RuntimeWorkerRegisterRequest(RuntimeWorkerRequest):
    kind: str = Field(min_length=1)
    hostname: str = Field(min_length=1)
    pid: int = Field(ge=1)
    capacity: int = Field(ge=0)
    active_jobs: int = Field(default=0, ge=0)


class RuntimeWorkerHeartbeatRequest(RuntimeWorkerRequest):
    active_jobs: int | None = Field(default=None, ge=0)


class RuntimeWorkerResponse(BaseModel):
    worker_id: str


class WorkerClaimBuildJobRequest(RuntimeWorkerRequest):
    pass


class WorkerClaimedBuildJob(BaseModel):
    job_id: str
    build_id: str
    namespace: str


class WorkerClaimBuildJobResponse(BaseModel):
    job: WorkerClaimedBuildJob | None


class WorkerFailBuildJobRequest(BaseModel):
    job_id: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    error: str = Field(min_length=1)


class WorkerFinalizeBuildJobRequest(BaseModel):
    job_id: str = Field(min_length=1)
    build_id: str = Field(min_length=1)
    namespace: str = Field(min_length=1)


class WorkerQueueCountResponse(BaseModel):
    queued: int


class WorkerDispatchOutboxResponse(BaseModel):
    dispatched: int


class WorkerReleaseJobsResponse(BaseModel):
    released: int


class WorkerIdlePidsResponse(BaseModel):
    pids: list[int]


class WorkerNamespacesResponse(BaseModel):
    namespaces: list[str]


class WorkerPersistBuildEventRequest(BaseModel):
    namespace: str = Field(min_length=1)
    build_id: str = Field(min_length=1)
    event: dict[str, object]
    resource_config_json: dict[str, object] | None = None


class WorkerPersistBuildEventResponse(BaseModel):
    sequence: int | None


class WorkerStartBuildRunRequest(BaseModel):
    namespace: str = Field(min_length=1)
    build_id: str = Field(min_length=1)


class WorkerBuildRunPayload(BaseModel):
    id: str
    namespace: str
    analysis_id: str
    analysis_name: str
    request_json: dict[str, object]
    starter_json: dict[str, object]
    resource_config_json: dict[str, object] | None
    current_kind: str | None
    current_datasource_id: str | None
    current_tab_id: str | None
    current_tab_name: str | None
    current_output_id: str | None
    current_output_name: str | None
    started_at: str
    total_tabs: int


class WorkerStartBuildRunResponse(BaseModel):
    run: WorkerBuildRunPayload | None


class WorkerPersistEngineSnapshotRequest(BaseModel):
    worker_id: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    statuses: list[dict[str, object]]


class WorkerPersistEngineSnapshotResponse(BaseModel):
    persisted: int


class WorkerPendingDatasourceDelete(BaseModel):
    namespace: str = Field(min_length=1)
    datasource_id: str = Field(min_length=1)


class WorkerPendingDatasourceDeletesResponse(BaseModel):
    deletes: list[WorkerPendingDatasourceDelete]


class WorkerFinalizeDatasourceDeleteRequest(BaseModel):
    namespace: str = Field(min_length=1)
    datasource_id: str = Field(min_length=1)


class WorkerFinalizeDatasourceDeleteResponse(BaseModel):
    deleted: bool


class WorkerNotificationAttachment(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str
    content_type: str = Field(default='text/plain', min_length=1)


class WorkerSendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    attachments: list[WorkerNotificationAttachment] = Field(default_factory=list)


class WorkerSendTelegramRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    message: str
    bot_token: str | None = None
    attachments: list[WorkerNotificationAttachment] = Field(default_factory=list)


class WorkerNotificationResponse(BaseModel):
    sent: bool


class WorkerTelegramSettingsResponse(BaseModel):
    enabled: bool


class WorkerGenerateAIRequest(BaseModel):
    provider: str = Field(min_length=1)
    prompts: list[str]
    model: str = Field(min_length=1)
    endpoint_url: str | None = None
    api_key: str | None = None
    options: dict[str, object] = Field(default_factory=dict)


class WorkerGenerateAIResponse(BaseModel):
    outputs: list[str]


class WorkerTelegramTargetsRequest(BaseModel):
    namespace: str = Field(min_length=1)
    datasource_id: str | None = None
    active_subscribers: bool = False


class WorkerTelegramTarget(BaseModel):
    chat_id: str
    bot_token: str


class WorkerTelegramTargetsResponse(BaseModel):
    targets: list[WorkerTelegramTarget]


class WorkerClaimComputeRequestRequest(RuntimeWorkerRequest):
    pass


class WorkerClaimedComputeRequest(BaseModel):
    id: str
    namespace: str
    kind: str
    request_json: dict[str, object]


class WorkerClaimComputeRequestResponse(BaseModel):
    request: WorkerClaimedComputeRequest | None


class WorkerCompleteComputeRequestRequest(BaseModel):
    namespace: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    response_json: dict[str, object] | None = None
    artifact_path: str | None = None
    artifact_name: str | None = None
    artifact_content_type: str | None = None


class WorkerFailComputeRequestRequest(BaseModel):
    namespace: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    error_message: str
    response_json: dict[str, object]


class WorkerReleaseComputeRequestsResponse(BaseModel):
    released: int


class WorkerExecuteDatasourceRequest(BaseModel):
    namespace: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    request_json: dict[str, object]


class WorkerExecuteDatasourceResponse(BaseModel):
    response_json: dict[str, object]


class WorkerScheduleIngestDatasourceRequest(BaseModel):
    namespace: str = Field(min_length=1)
    datasource_id: str = Field(min_length=1)


class WorkerDatasourceMetadataRequest(BaseModel):
    namespace: str = Field(min_length=1)
    datasource_id: str = Field(min_length=1)


class WorkerDatasourceMetadataResponse(BaseModel):
    found: bool
    id: str | None = None
    name: str | None = None
    source_type: str | None = None
    config: dict[str, object] | None = None
    schema_cache: dict[str, object] | None = None
    is_hidden: bool | None = None


class WorkerUdfCodesRequest(BaseModel):
    namespace: str = Field(min_length=1)
    udf_ids: list[str]


class WorkerUdfCodesResponse(BaseModel):
    codes: dict[str, str]


class WorkerAnalysisMetadataRequest(BaseModel):
    namespace: str = Field(min_length=1)
    analysis_id: str = Field(min_length=1)


class WorkerAnalysisMetadataResponse(BaseModel):
    found: bool
    name: str | None = None


class WorkerBuildCancelStatusRequest(BaseModel):
    namespace: str = Field(min_length=1)
    build_id: str = Field(min_length=1)


class WorkerBuildCancelStatusResponse(BaseModel):
    cancelled: bool
    cancelled_at: str | None = None
    cancelled_by: str | None = None


class WorkerUpdateBuildResultRequest(BaseModel):
    namespace: str = Field(min_length=1)
    build_id: str = Field(min_length=1)
    result_json: dict[str, object]


class WorkerUpsertOutputDatasourceRequest(BaseModel):
    namespace: str = Field(min_length=1)
    result_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    config: dict[str, object]
    schema_cache: dict[str, object]
    analysis_id: str | None = None
    is_hidden: bool | None = None
    keep_schema_cache: bool = False


class WorkerUpsertOutputDatasourceResponse(BaseModel):
    datasource_id: str
    datasource_name: str
    is_hidden: bool


class WorkerHealthCheckSpec(BaseModel):
    id: str
    name: str
    check_type: str
    config: dict[str, object]
    critical: bool


class WorkerListHealthChecksRequest(BaseModel):
    namespace: str = Field(min_length=1)
    datasource_id: str = Field(min_length=1)


class WorkerListHealthChecksResponse(BaseModel):
    checks: list[WorkerHealthCheckSpec]


class WorkerHealthCheckResultPayload(BaseModel):
    healthcheck_id: str = Field(min_length=1)
    passed: bool
    message: str
    details: dict[str, object]
    checked_at: str


class WorkerRecordHealthCheckResultsRequest(BaseModel):
    namespace: str = Field(min_length=1)
    results: list[WorkerHealthCheckResultPayload]


class WorkerRecordHealthCheckResultsResponse(BaseModel):
    recorded: int


class WorkerCreateEngineRunRequest(BaseModel):
    namespace: str = Field(min_length=1)
    analysis_id: str | None = None
    datasource_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    status: str = Field(min_length=1)
    request_json: dict[str, object]
    result_json: dict[str, object] | None = None
    error_message: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    step_timings: dict[str, float] | None = None
    query_plan: str | None = None
    execution_entries: list[dict[str, object]] | None = None
    progress: float = 0.0
    current_step: str | None = None
    triggered_by: str | None = None


class WorkerEngineRunResponse(BaseModel):
    id: str


class WorkerUpdateEngineRunRequest(BaseModel):
    namespace: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    fields: dict[str, object]
    merge_result_json: bool = True


class WorkerEngineRunStateRequest(BaseModel):
    namespace: str = Field(min_length=1)
    run_id: str = Field(min_length=1)


class WorkerEngineRunStateResponse(BaseModel):
    found: bool
    status: str | None = None
    result_json: dict[str, object] | None = None
    cancelled_at: str | None = None
    cancelled_by: str | None = None
