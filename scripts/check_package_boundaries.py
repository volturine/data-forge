from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'packages'

EXCLUDED_DIRS = {
    '.git',
    '.artifacts',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '.svelte-kit',
    '.venv',
    'node_modules',
    '__pycache__',
    'buf',
    'tests-e2e',
    'test-results',
    'playwright-report',
    'dataforge_protocol',
}

EXPECTED_PACKAGES = {'backend', 'frontend', 'protocol', 'scheduler', 'worker'}

ROOT_TEST_RESIDUE = [
    ROOT / 'tests',
    ROOT / 'test_harness',
    ROOT / 'test_support',
    ROOT / 'pytest_fixtures.py',
    ROOT / 'postgres_harness.py',
]
ROOT_TEST_ARTIFACT_PREFIXES = ('test-results', 'playwright-report')

FORBIDDEN_OWNER_DUPLICATES = [
    Path('packages/backend/backend_grpc/codec.py'),
    Path('packages/backend/backend_core/contracts'),
    Path('packages/backend/backend_core/engine_identity.py'),
    Path('packages/backend/backend_core/object_store_paths.py'),
    Path('packages/backend/backend_core/domain/protocol_enums.py'),
    Path('packages/backend/modules/analysis/models.py'),
    Path('packages/backend/modules/datasource/models.py'),
    Path('packages/backend/modules/health/models.py'),
    Path('packages/backend/modules/healthcheck/models.py'),
    Path('packages/backend/modules/settings/models.py'),
    Path('packages/backend/modules/telegram/models.py'),
    Path('packages/backend/modules/udf/models.py'),
    Path('packages/worker/runtime/engine_identity.py'),
    Path('packages/worker/runtime/domain/protocol_enums.py'),
    Path('packages/worker/runtime/domain/step_config_enums.py'),
    Path('packages/worker/runtime/domain/compute_requests/models.py'),
    Path('packages/worker/datasources/datasource_schemas.py'),
    Path('packages/worker/runtime/models'),
    Path('packages/worker/worker_grpc/codec.py'),
]

PACKAGE_FORBIDDEN_IMPORT_ROOTS = {
    'backend': {
        'backend_contracts',
        'builds',
        'data_plane_iceberg',
        'data_plane_object_store',
        'datasources',
        'operations',
        'runtime',
        'scheduler_service',
        'worker_models',
    },
    'scheduler': {'api', 'backend_contracts', 'backend_core', 'builds', 'datasources', 'modules', 'operations', 'runtime', 'shared', 'worker_models'},
    'worker': {'api', 'backend_contracts', 'backend_core', 'modules', 'scheduler_service', 'shared', 'sqlmodel', 'worker_models'},
}

LEGACY_IMPORT_ROOTS = {'backend_contracts', 'worker_models'}
FORBIDDEN_SOURCE_TOKENS = {
    'backend_contracts': 'deleted legacy backend contract package',
    'backend_core.contracts': 'renamed backend-owned domain package',
    'runtime.models': 'renamed worker-owned domain package',
    'worker_models': 'deleted legacy worker model package',
    'backend_grpc.codec': 'deleted mirrored protobuf codec module',
    'worker_grpc.codec': 'deleted mirrored protobuf codec module',
    'backend_core.domain.protocol_enums': 'deleted mirrored protocol enum runtime',
    'runtime.domain.protocol_enums': 'deleted mirrored protocol enum runtime',
    'runtime.domain.step_config_enums': 'worker operation enums are owned by operations.enums',
    '_grpc.generated': 'deleted generated gRPC compatibility import path',
    'JsonPayload': 'generic JSON-string protocol payload',
    '__preview__': 'engine identity prefix parsing',
    'engine_key': 'engine-key string identity',
    'storage_key': 'engine storage-key string identity',
    'EngineIdentityInput': 'engine identity aliases hide generated dataforge_protocol.compute_pb2.EngineIdentity',
    'analysis_interactive_engine_identity': 'engine identity constructor helper; construct dataforge_protocol.compute_pb2.EngineIdentity directly',
    'datasource_preview_engine_identity': 'engine identity constructor helper; construct dataforge_protocol.compute_pb2.EngineIdentity directly',
    'build_engine_identity': 'engine identity constructor helper; construct dataforge_protocol.compute_pb2.EngineIdentity directly',
    'engine_identity_resource_id': 'engine identity resource helper; read dataforge_protocol.compute_pb2.EngineIdentity.resource_id directly',
    '_analysis_interactive_engine_identity': 'engine identity constructor helper; construct dataforge_protocol.compute_pb2.EngineIdentity directly',
    '_datasource_preview_engine_identity': 'engine identity constructor helper; construct dataforge_protocol.compute_pb2.EngineIdentity directly',
    '_build_engine_identity': 'engine identity constructor helper; construct dataforge_protocol.compute_pb2.EngineIdentity directly',
    '_engine_identity_resource_id': 'engine identity resource helper; read dataforge_protocol.compute_pb2.EngineIdentity.resource_id directly',
    'def _resolve_identity(self, identity': 'string-derived engine identity resolver; use dataforge_protocol.compute_pb2.EngineIdentity',
    'data_plane_object_store': 'deleted backend data-plane object-store facade',
    'data_plane_iceberg': 'deleted backend data-plane Iceberg facade',
    'generate_ts_step_types.py': 'deleted backend-derived frontend type generator',
    'generate_ts_build_stream_types.py': 'deleted backend-derived frontend type generator',
    'step-schemas.generated': 'deleted backend-derived frontend step schema import',
    'build-stream.generated': 'deleted backend-derived frontend build stream import',
    'Generated from backend/': 'backend-derived generated frontend contract banner',
    'class AIProvider(DataForgeStrEnum)': 'hand-written AI provider enum; use dataforge_protocol.enums_pb2',
    'class ComputeRequestKind(': 'hand-written compute request kind enum; use dataforge_protocol.enums_pb2',
    'class ComputeRequestStatus(': 'hand-written compute request status enum; use dataforge_protocol.enums_pb2',
    'command_envelope_from_json': 'compute command envelopes must be persisted and transported as protobuf bytes',
    'response_envelope_from_json': 'compute response envelopes must be persisted and transported as protobuf bytes',
    'envelope_to_json': 'compute envelopes must not round-trip through JSON persistence',
    'def _compute_response(kind': 'worker compute results must be constructed as generated response variants',
    'def _compute_command_payload': 'worker compute commands must be consumed as generated command variants',
    'def _tokens_to_proto_json': 'protocol boundaries must not recursively reinterpret generated message descriptors',
    'def _proto_json_to_tokens': 'protocol boundaries must not recursively reinterpret generated message descriptors',
}
SOURCE_SUFFIXES = {'.py', '.ts', '.svelte', '.proto'}
WORKER_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS = {
    'from runtime.domain.enums import DataForgeStrEnum': 'worker operation config enums must be generated-protocol-backed',
    '(DataForgeStrEnum)': 'worker operation config enums must not reintroduce copied StrEnum contracts',
}
PROTOCOL_ENUM_OWNER_REQUIREMENTS = {
    Path('packages/backend/backend_core/domain/api_enums.py'): (
        'class ApiEnumValue(str)',
        'backend API enums must remain string-shaped boundary values',
    ),
    Path('packages/worker/runtime/domain/domain_enums.py'): (
        'class DomainEnumValue(str)',
        'worker lifecycle and event enums must remain string-shaped domain values',
    ),
    Path('packages/worker/operations/enums.py'): (
        'class OperationEnumValue(int)',
        'worker operation enums must remain generated protocol-number-backed values',
    ),
}
FRONTEND_OPERATION_CONFIG_FORBIDDEN_TOKENS = {
    "export type CastMapType = 'Int64'": 'frontend cast-map type must be generated-protocol-backed',
}
FRONTEND_OPERATION_COMPONENT_FORBIDDEN_PATTERNS = {
    re.compile(r'\binterface\s+\w+ConfigData\b'): 'operation components must import protocol-anchored config types from $lib/types/operation-config',
    re.compile(r'\btype\s+WithColumnsConfigShape\b'): 'pipeline config binding must use protocol-anchored WithColumnsConfigData',
    re.compile(r'\btype\s+DownloadConfigData\b'): 'pipeline config binding must use protocol-anchored DownloadConfigData',
    re.compile(r'\bconst\s+CAST_TYPES\s*=\s*\['): 'select cast options must come from generated protocol enum tokens',
}
FRONTEND_BUILD_STREAM_ADAPTER_FORBIDDEN_PATTERNS = {
    re.compile(r'\bconst\s+ENGINE_RUN_KIND_TOKENS\s*:'): 'build-stream generated JSON enum tokens must live in protocol-enum-tokens.ts',
    re.compile(r'\bconst\s+BUILD_TAB_STATUS_TOKENS\s*:'): 'build-stream generated JSON enum tokens must live in protocol-enum-tokens.ts',
    re.compile(r'\bconst\s+BUILD_LOG_LEVEL_TOKENS\s*:'): 'build-stream generated JSON enum tokens must live in protocol-enum-tokens.ts',
}
FRONTEND_BUILD_STREAM_TYPES_REQUIRED_TOKENS = {
    'ActiveBuildSummaryJson as ProtocolActiveBuildSummaryJson': 'active build summary type must be anchored to generated protocol JSON',
    'ActiveBuildDetailJson as ProtocolActiveBuildDetailJson': 'active build detail type must be anchored to generated protocol JSON',
    'BuildSnapshotMessageJson as ProtocolBuildSnapshotMessageJson': 'build snapshot websocket type must be anchored to generated protocol JSON',
    'ActiveBuildListResponseJson as ProtocolActiveBuildListResponseJson': 'active build list response must be anchored to generated protocol JSON',
}
FRONTEND_BUILD_API_FORBIDDEN_PATTERNS = {
    re.compile(r'\binterface\s+ActiveBuildListResponse\b'): 'build list response must be imported from protocol-anchored build-stream types',
}
FRONTEND_COMPUTE_TYPES_REQUIRED_TOKENS = {
    'EngineIdentityJson as ProtocolEngineIdentityJson': 'engine identity payload must be anchored to generated protocol JSON',
    'EngineStatusResultJson as ProtocolEngineStatusResultJson': 'engine status response must be anchored to generated protocol JSON',
    'EngineResourceConfigJson as ProtocolEngineResourceConfigJson': 'engine resource config must be anchored to generated protocol JSON',
}
FRONTEND_COMPUTE_API_REQUIRED_TOKENS = {
    'StepPreviewCommandJson as ProtocolStepPreviewCommandJson': 'step preview request must be anchored to generated protocol JSON',
    'StepPreviewResultJson as ProtocolStepPreviewResultJson': 'step preview response must be anchored to generated protocol JSON',
    'ExportCommandJson as ProtocolExportCommandJson': 'export request must be anchored to generated protocol JSON',
    'ExportResultJson as ProtocolExportResultJson': 'export response must be anchored to generated protocol JSON',
    'DownloadCommandJson as ProtocolDownloadCommandJson': 'download request must be anchored to generated protocol JSON',
    'StepSchemaCommandJson as ProtocolStepSchemaCommandJson': 'step schema request must be anchored to generated protocol JSON',
    'StepRowCountResultJson as ProtocolStepRowCountResultJson': 'row-count response must be anchored to generated protocol JSON',
}
FRONTEND_COMPUTE_TYPES_FORBIDDEN_PATTERNS = {
    re.compile(r"export\s+type\s+EngineStatus\s*=\s*'healthy'"): 'engine status literals must come from generated protocol enum tokens',
    re.compile(r"export\s+type\s+EngineScope\s*=\s*'datasource_preview'"): 'engine scope literals must come from generated protocol enum tokens',
    re.compile(r"export\s+type\s+EngineReusePolicy\s*=\s*'shared'"): 'engine reuse policy literals must come from generated protocol enum tokens',
}
PROTOCOL_COMPUTE_REQUIRED_TOKENS = {
    'message ActiveBuildSummary': 'protocol must own active build summary DTOs',
    'message ActiveBuildDetail': 'protocol must own active build detail DTOs',
    'message BuildSnapshotMessage': 'protocol must own build snapshot websocket DTOs',
    'message BuildWebsocketErrorMessage': 'protocol must own build websocket error DTOs',
    'string resource_id = 6': 'protocol EngineIdentity must explicitly carry resource_id',
    'id: "engine_identity.scope_resource"': 'protocol EngineIdentity must enforce scope, reuse policy, and resource ID consistency',
}
WORKER_COMPUTE_SCHEMA_FORBIDDEN_TOKENS = {
    'class EngineIdentityPayload(BaseModel)': 'worker compute schemas must use dataforge_protocol.compute_pb2.EngineIdentity directly',
    'class SpawnEngineRequest(': 'worker must consume generated engine command messages instead of mirrored HTTP request models',
    'class StepPreviewRequest(': 'worker must consume generated preview command messages instead of mirrored HTTP request models',
    'class ExportRequest(': 'worker must consume generated export command messages instead of mirrored HTTP request models',
    'class DownloadRequest(': 'worker must consume generated download command messages instead of mirrored HTTP request models',
    'class StepSchemaRequest(': 'worker must consume generated schema command messages instead of mirrored HTTP request models',
    'class StepRowCountRequest(': 'worker must consume generated row-count command messages instead of mirrored HTTP request models',
}
WORKER_STEP_CONVERTER_REQUIRED_TOKENS = {
    'analysis_pb2.StepConfig.DESCRIPTOR': 'worker execution conversion must unwrap the generated StepConfig oneof',
}
BACKEND_COMPUTE_SCHEMA_FORBIDDEN_TOKENS = {
    'class EngineIdentityPayload(BaseModel)': 'backend compute schemas must use dataforge_protocol.compute_pb2.EngineIdentity directly',
}
COMPUTE_ENVELOPE_FORBIDDEN_TOKENS = {
    'return struct_to_dict(envelope.payload)': 'compute envelopes must reject deprecated payload-only messages',
    'response.dynamic_response.CopyFrom': 'compute responses must use typed protocol oneof variants',
    'envelope.response.dynamic_response.CopyFrom': 'compute responses must use typed protocol oneof variants',
}
COMPUTE_ENVELOPE_REQUIRED_TOKENS = {
    'compute_pb2.ComputeErrorResult': 'compute failures must use typed protocol error responses',
    'compute_pb2.EngineStatusResult': 'engine lifecycle responses must use typed protocol engine status responses',
    'compute_pb2.ComputeAckResult': 'acknowledgement responses must use typed protocol ack responses',
}
PROTOCOL_FORBIDDEN_TOKENS = {
    'deprecated = true': 'deprecated protocol compatibility fields must be removed, not carried forward',
    'enum.defined_only = true': 'protocol enums must reject UNSPECIFIED zero values in addition to unknown values',
    'google.protobuf.Struct datasource_request': 'compute commands must use typed DatasourceCommand, not generic datasource_request payloads',
    'google.protobuf.Struct dynamic_response': 'compute responses must use typed oneof variants, not generic dynamic_response payloads',
    'google.protobuf.Struct raw': 'runtime events must use typed protocol event payloads',
    'string step_type = 5': 'build stream events must use generated BuildStepKind, not legacy step_type strings',
    'google.protobuf.Struct payload = 5': 'compute envelopes must not carry deprecated generic payload fields',
    'google.protobuf.Struct event = 3': 'build-event RPCs must use typed BuildEvent messages, not generic Struct payloads',
    'optional google.protobuf.Struct resource_config = 4': 'build-event RPCs must use typed BuildResourceConfigSummary messages',
    'google.protobuf.Struct starter = 6': 'build-run payloads must use typed BuildStarter messages',
    'optional google.protobuf.Struct resource_config = 7': 'build-run payloads must use typed BuildResourceConfigSummary messages',
    'google.protobuf.Struct options = 1': 'object-store storage options must use typed ObjectStoreStorageOptions messages',
    'google.protobuf.Struct schema = 2': 'Iceberg schema sync must use typed ArrowSchemaIpc messages',
    'google.protobuf.Struct schema_cache = 7': 'datasource metadata must use typed SchemaInfo messages',
    'optional google.protobuf.Struct schema_cache = 6': 'datasource records must use typed SchemaInfo messages',
    'google.protobuf.Struct schema_cache = 6': 'datasource output upserts must use typed SchemaInfo messages',
    'optional google.protobuf.Struct step_timings = 12': 'engine-run timing maps must use typed protocol maps',
    'repeated google.protobuf.Struct execution_entries = 14': 'engine-run execution entries must use typed protocol messages',
    'google.protobuf.Struct fields = 3': 'engine-run updates must use typed WorkerEngineRunUpdateFields',
    'repeated google.protobuf.Struct statuses = 3': 'engine snapshots must use typed EngineStatusResult messages',
    'message JsonResponse': 'worker runtime RPCs must return typed protocol responses, not generic JSON envelopes',
    'returns (JsonResponse)': 'worker runtime RPCs must return typed protocol responses, not generic JSON envelopes',
}
PROTO_STRUCT_FIELD_PATTERN = re.compile(r'\bgoogle\.protobuf\.Struct\s+(\w+)\s*=\s*(\d+)')
PROTO_MESSAGE_PATTERN = re.compile(r'^\s*message\s+(\w+)\s*\{')
PROTO_STRUCT_ALLOWLIST = {
    'proto/dataforge_protocol/analysis.proto:AnalysisPipelineDatasource.config': 'datasource configs are provider/user-defined JSON escape hatches',
    'proto/dataforge_protocol/analysis.proto:AnalysisPipelineOutput.options': 'export output options are destination-specific JSON escape hatches',
    'proto/dataforge_protocol/analysis.proto:AIConfig.request_options': 'AI request options are provider-specific JSON escape hatches',
    'proto/dataforge_protocol/compute.proto:StepPreviewResult.rows': 'preview rows are arbitrary datasource result objects',
    'proto/dataforge_protocol/compute.proto:StepPreviewResult.metadata': 'preview metadata is engine/provider-specific',
    'proto/dataforge_protocol/compute.proto:ComputeErrorResult.details': 'error details are intentionally extensible diagnostics',
    'proto/dataforge_protocol/compute.proto:ActiveBuildSummary.result_json': 'active build summaries expose persisted runtime result JSON at the API boundary',
    'proto/dataforge_protocol/compute.proto:ActiveBuildDetail.request_json': 'active build details expose persisted runtime request JSON at the API boundary',
    'proto/dataforge_protocol/datasource.proto:DatasourceMetadata.config': 'datasource configs are provider/user-defined JSON escape hatches',
    'proto/dataforge_protocol/datasource.proto:CreateFileDatasourceCommand.options': 'file datasource options are format-specific JSON escape hatches',
    'proto/dataforge_protocol/datasource.proto:CreateIcebergDatasourceCommand.source': 'Iceberg source descriptors are provider-specific JSON escape hatches',
    'proto/dataforge_protocol/datasource.proto:DatasourceColumnStatsCommand.datasource_config': 'column stats run against datasource config JSON persisted at the boundary',
    'proto/dataforge_protocol/datasource.proto:DataSourceRecord.config': 'datasource records expose provider/user-defined config JSON',
    'proto/dataforge_protocol/datasource.proto:SnapshotPreview.rows': 'snapshot previews contain arbitrary row objects',
    'proto/dataforge_protocol/datasource.proto:ColumnStatsResult.top_values': 'top-value stats contain arbitrary value/count records by column type',
    'proto/dataforge_protocol/errors.proto:ErrorInfo.details': 'error details are intentionally extensible diagnostics',
    'proto/dataforge_protocol/iceberg.proto:IcebergSnapshotScanResponse.rows': 'Iceberg snapshot scans return arbitrary row objects',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerDatasourceMetadataResponse.config': 'datasource metadata exposes provider/user-defined config JSON',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerUpdateBuildResultRequest.result': 'build result is persisted runtime JSON at the database boundary',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerUpsertOutputDatasourceRequest.config': 'output datasource config is provider/user-defined JSON',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerHealthCheckSpec.config': 'healthcheck config is check-type-specific JSON',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerHealthCheckResultPayload.details': 'healthcheck result details are check-type-specific diagnostics',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerCreateEngineRunRequest.request': 'engine-run request is persisted runtime JSON at the database boundary',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerCreateEngineRunRequest.result': 'engine-run result is persisted runtime JSON at the database boundary',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerEngineRunUpdateFields.request_json': 'engine-run request updates write persisted runtime JSON at the database boundary',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerEngineRunUpdateFields.result_json': 'engine-run result updates write persisted runtime JSON at the database boundary',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerEngineRunStateResponse.result': 'engine-run state exposes persisted runtime result JSON',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerBuildRunPayload.request': 'build-run start payload exposes persisted runtime request JSON',
    'proto/dataforge_protocol/worker_runtime.proto:WorkerGenerateAIRequest.options': 'AI generation options are provider-specific JSON',
}
WORKER_RUNTIME_RPC_FORBIDDEN_TOKENS = {
    'return struct_to_dict(response.response)': 'worker runtime RPC clients must not fall back to generic JSON response fields',
    'response=dict_to_struct(response_payload)': 'worker runtime RPC servers must return typed protocol responses',
    'response=dict_to_struct(response.model_dump': 'worker runtime RPC servers must return typed protocol responses',
    'struct_to_dict(request.event)': 'worker runtime RPC servers must decode typed BuildEvent messages',
    "struct_field_to_dict(request, 'resource_config')": 'worker runtime RPC servers must decode typed BuildResourceConfigSummary messages',
    'event=dict_to_struct(event)': 'worker runtime RPC clients must send typed BuildEvent messages',
    'request.resource_config.CopyFrom(dict_to_struct': 'worker runtime RPC clients must send typed BuildResourceConfigSummary messages',
    'starter=dict_to_struct': 'worker runtime RPC servers must return typed BuildStarter messages',
    'payload.resource_config.CopyFrom(dict_to_struct': 'worker runtime RPC servers must return typed BuildResourceConfigSummary messages',
    'starter_json=struct_to_dict(run.starter)': 'worker runtime RPC clients must decode typed BuildStarter messages',
    'optional_struct_to_dict(run, "resource_config")': 'worker runtime RPC clients must decode typed BuildResourceConfigSummary messages',
    "struct_field_to_dict(request, 'step_timings')": 'worker runtime RPCs must decode typed engine-run timing maps',
    'execution_entries=repeated_structs_to_dicts(request.execution_entries)': 'worker runtime RPCs must decode typed engine-run execution entries',
    'execution_entries=[dict_to_struct(entry)': 'worker runtime RPC clients must send typed engine-run execution entries',
    'request.step_timings.CopyFrom(dict_to_struct': 'worker runtime RPC clients must send typed engine-run timing maps',
    'fields=dict_to_struct(fields)': 'worker runtime RPC clients must send typed engine-run update fields',
    'struct_to_dict(request.fields)': 'worker runtime RPC servers must decode typed engine-run update fields',
    'statuses=[dict_to_struct(dict(status))': 'worker runtime RPC clients must send typed engine snapshots',
    'repeated_structs_to_dicts(request.statuses)': 'worker runtime RPC servers must decode typed engine snapshots',
}
BACKEND_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS = {
    'from backend_core.domain.enums import DataForgeStrEnum': 'backend operation config enums must be generated-protocol-backed',
    '(DataForgeStrEnum)': 'backend operation config enums must not reintroduce copied StrEnum contracts',
}
PROTOCOL_BACKED_ENUM_FILES = [
    Path('packages/backend/backend_core/domain/analysis/models.py'),
    Path('packages/backend/backend_core/domain/analysis/step_types.py'),
    Path('packages/backend/backend_core/domain/build_jobs/models.py'),
    Path('packages/backend/backend_core/domain/build_runs/models.py'),
    Path('packages/backend/backend_core/domain/compute/schemas.py'),
    Path('packages/backend/backend_core/domain/datasource/models.py'),
    Path('packages/backend/backend_core/domain/datasource/source_types.py'),
    Path('packages/backend/backend_core/domain/engine_instances/models.py'),
    Path('packages/backend/backend_core/domain/engine_runs/schemas.py'),
    Path('packages/backend/backend_core/domain/healthcheck_models.py'),
    Path('packages/backend/backend_core/domain/runtime/events.py'),
    Path('packages/backend/backend_core/domain/runtime_workers/models.py'),
    Path('packages/backend/modules/datasource/runtime_loading.py'),
    Path('packages/backend/modules/datasource/schemas.py'),
    Path('packages/worker/datasources/datasource_loading.py'),
    Path('packages/worker/operations/datasource.py'),
    Path('packages/worker/runtime/domain/analysis/models.py'),
    Path('packages/worker/runtime/domain/analysis/step_types.py'),
    Path('packages/worker/runtime/domain/build_jobs/models.py'),
    Path('packages/worker/runtime/domain/build_runs/models.py'),
    Path('packages/worker/runtime/domain/compute/schemas.py'),
    Path('packages/worker/runtime/domain/datasource/models.py'),
    Path('packages/worker/runtime/domain/datasource/source_types.py'),
    Path('packages/worker/runtime/domain/engine_instances/models.py'),
    Path('packages/worker/runtime/domain/engine_runs/schemas.py'),
    Path('packages/worker/runtime/domain/healthcheck_models.py'),
    Path('packages/worker/runtime/domain/runtime/events.py'),
    Path('packages/worker/runtime/domain/runtime_workers/models.py'),
]
PROTOCOL_BACKED_ENUM_FORBIDDEN_TOKENS = {
    'DataForgeStrEnum': 'protocol-backed domain enums must use generated protocol descriptors',
}


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS or part.startswith('test-results') for part in path.parts)


def iter_python_files(package: str):
    package_root = PACKAGES / package
    for path in package_root.rglob('*.py'):
        rel = path.relative_to(package_root)
        if is_excluded(rel):
            continue
        yield path


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split('.')[0])
    return roots


def engine_identity_constructor_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_engine_identity = (isinstance(func, ast.Attribute) and func.attr == 'EngineIdentity') or (isinstance(func, ast.Name) and func.id == 'EngineIdentity')
        if not is_engine_identity:
            continue
        if not any(keyword.arg == 'resource_id' for keyword in node.keywords):
            lines.append(node.lineno)
    return lines


def raw_compute_request_creation_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_compute_request_service_call = (
            isinstance(func, ast.Attribute)
            and func.attr == 'create_request'
            and isinstance(func.value, ast.Name)
            and func.value.id == 'compute_requests_service'
        )
        if not is_compute_request_service_call:
            continue
        if any(keyword.arg == 'request_json' for keyword in node.keywords):
            lines.append(node.lineno)
    return lines


def iter_source_files():
    for package_root in PACKAGES.iterdir():
        if not package_root.is_dir() or package_root.name.startswith('.'):
            continue
        for path in package_root.rglob('*'):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            rel = path.relative_to(package_root)
            if is_excluded(rel):
                continue
            yield path


def proto_struct_fields(path: Path) -> list[str]:
    rel = path.relative_to(ROOT / 'packages' / 'protocol').as_posix()
    current_message: str | None = None
    fields: list[str] = []
    for line in path.read_text().splitlines():
        message_match = PROTO_MESSAGE_PATTERN.match(line)
        if message_match:
            current_message = message_match.group(1)
        field_match = PROTO_STRUCT_FIELD_PATTERN.search(line)
        if field_match and current_message is not None:
            fields.append(f'{rel}:{current_message}.{field_match.group(1)}')
        if line.strip() == '}':
            current_message = None
    return fields


def main() -> int:
    errors: list[str] = []

    actual_packages = {path.name for path in PACKAGES.iterdir() if path.is_dir() and not path.name.startswith('.')}
    unexpected = sorted((actual_packages - EXPECTED_PACKAGES) - {'__pycache__'})
    if unexpected:
        errors.append(f'unexpected package directories under packages/: {", ".join(unexpected)}')

    for path in ROOT_TEST_RESIDUE:
        if path.exists():
            errors.append(f'root test/support residue is not allowed: {path.relative_to(ROOT)}')

    for child in ROOT.iterdir():
        if child.name.startswith(ROOT_TEST_ARTIFACT_PREFIXES):
            errors.append(f'root test artifact is not allowed: {child.relative_to(ROOT)}')

    for rel_path in FORBIDDEN_OWNER_DUPLICATES:
        path = ROOT / rel_path
        if path.exists():
            errors.append(f'neutral shared model duplicated in backend owner package: {rel_path}')

    worker_operation_enums = ROOT / 'packages/worker/operations/enums.py'
    if worker_operation_enums.exists():
        content = worker_operation_enums.read_text()
        for token, reason in WORKER_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{worker_operation_enums.relative_to(ROOT)} contains {reason}: {token}')

    for rel_path, (token, reason) in PROTOCOL_ENUM_OWNER_REQUIREMENTS.items():
        path = ROOT / rel_path
        if not path.exists():
            errors.append(f'protocol enum owner is missing: {rel_path}')
        elif token not in path.read_text():
            errors.append(f'{rel_path} is missing {reason}: {token}')

    worker_operations = ROOT / 'packages/worker/operations'
    if worker_operations.exists():
        for operation_file in worker_operations.glob('*.py'):
            content = operation_file.read_text()
            for token, reason in WORKER_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS.items():
                if token in content:
                    errors.append(f'{operation_file.relative_to(ROOT)} contains {reason}: {token}')

    frontend_operation_config = ROOT / 'packages/frontend/src/lib/types/operation-config.ts'
    if frontend_operation_config.exists():
        content = frontend_operation_config.read_text()
        for token, reason in FRONTEND_OPERATION_CONFIG_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{frontend_operation_config.relative_to(ROOT)} contains {reason}: {token}')

    frontend_operation_components = ROOT / 'packages/frontend/src/lib/components/operations'
    if frontend_operation_components.exists():
        component_paths = list(frontend_operation_components.glob('*.svelte'))
        component_paths.append(ROOT / 'packages/frontend/src/lib/components/pipeline/StepConfig.svelte')
        for component_path in component_paths:
            if not component_path.exists():
                continue
            content = component_path.read_text()
            for pattern, reason in FRONTEND_OPERATION_COMPONENT_FORBIDDEN_PATTERNS.items():
                if pattern.search(content):
                    errors.append(f'{component_path.relative_to(ROOT)} contains {reason}: {pattern.pattern}')

    frontend_build_stream_adapter = ROOT / 'packages/frontend/src/lib/types/protocol-build-stream.ts'
    if frontend_build_stream_adapter.exists():
        content = frontend_build_stream_adapter.read_text()
        for pattern, reason in FRONTEND_BUILD_STREAM_ADAPTER_FORBIDDEN_PATTERNS.items():
            if pattern.search(content):
                errors.append(f'{frontend_build_stream_adapter.relative_to(ROOT)} contains {reason}: {pattern.pattern}')

    frontend_build_stream_types = ROOT / 'packages/frontend/src/lib/types/build-stream.ts'
    if frontend_build_stream_types.exists():
        content = frontend_build_stream_types.read_text()
        for token, reason in FRONTEND_BUILD_STREAM_TYPES_REQUIRED_TOKENS.items():
            if token not in content:
                errors.append(f'{frontend_build_stream_types.relative_to(ROOT)} is missing {reason}: {token}')

    frontend_build_api = ROOT / 'packages/frontend/src/lib/api/builds.ts'
    if frontend_build_api.exists():
        content = frontend_build_api.read_text()
        for pattern, reason in FRONTEND_BUILD_API_FORBIDDEN_PATTERNS.items():
            if pattern.search(content):
                errors.append(f'{frontend_build_api.relative_to(ROOT)} contains {reason}: {pattern.pattern}')

    frontend_compute_types = ROOT / 'packages/frontend/src/lib/types/compute.ts'
    if frontend_compute_types.exists():
        content = frontend_compute_types.read_text()
        for token, reason in FRONTEND_COMPUTE_TYPES_REQUIRED_TOKENS.items():
            if token not in content:
                errors.append(f'{frontend_compute_types.relative_to(ROOT)} is missing {reason}: {token}')
        for pattern, reason in FRONTEND_COMPUTE_TYPES_FORBIDDEN_PATTERNS.items():
            if pattern.search(content):
                errors.append(f'{frontend_compute_types.relative_to(ROOT)} contains {reason}: {pattern.pattern}')

    frontend_compute_api = ROOT / 'packages/frontend/src/lib/api/compute.ts'
    if frontend_compute_api.exists():
        content = frontend_compute_api.read_text()
        for token, reason in FRONTEND_COMPUTE_API_REQUIRED_TOKENS.items():
            if token not in content:
                errors.append(f'{frontend_compute_api.relative_to(ROOT)} is missing {reason}: {token}')

    protocol_compute = ROOT / 'packages/protocol/proto/dataforge_protocol/compute.proto'
    if protocol_compute.exists():
        content = protocol_compute.read_text()
        for token, reason in PROTOCOL_COMPUTE_REQUIRED_TOKENS.items():
            if token not in content:
                errors.append(f'{protocol_compute.relative_to(ROOT)} is missing {reason}: {token}')

    worker_compute_schemas = ROOT / 'packages/worker/runtime/domain/compute/schemas.py'
    if worker_compute_schemas.exists():
        content = worker_compute_schemas.read_text()
        for token, reason in WORKER_COMPUTE_SCHEMA_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{worker_compute_schemas.relative_to(ROOT)} contains {reason}: {token}')

    worker_step_converter = ROOT / 'packages/worker/operations/step_converter.py'
    if worker_step_converter.exists():
        content = worker_step_converter.read_text()
        for token, reason in WORKER_STEP_CONVERTER_REQUIRED_TOKENS.items():
            if token not in content:
                errors.append(f'{worker_step_converter.relative_to(ROOT)} is missing {reason}: {token}')

    backend_step_config_enums = ROOT / 'packages/backend/backend_core/domain/step_config_enums.py'
    if backend_step_config_enums.exists():
        content = backend_step_config_enums.read_text()
        for token, reason in BACKEND_PROTOCOL_ADAPTER_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{backend_step_config_enums.relative_to(ROOT)} contains {reason}: {token}')

    backend_compute_schemas = ROOT / 'packages/backend/backend_core/domain/compute/schemas.py'
    if backend_compute_schemas.exists():
        content = backend_compute_schemas.read_text()
        for token, reason in BACKEND_COMPUTE_SCHEMA_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{backend_compute_schemas.relative_to(ROOT)} contains {reason}: {token}')

    for rel_path in (
        Path('packages/backend/backend_core/domain/compute_requests/models.py'),
        Path('packages/worker/runtime/compute_request_runtime.py'),
    ):
        path = ROOT / rel_path
        if not path.exists():
            errors.append(f'compute envelope adapter is missing: {rel_path}')
            continue
        content = path.read_text()
        for token, reason in COMPUTE_ENVELOPE_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{rel_path} contains {reason}: {token}')
        for token, reason in COMPUTE_ENVELOPE_REQUIRED_TOKENS.items():
            if token not in content:
                errors.append(f'{rel_path} is missing {reason}: {token}')

    for rel_path in (
        Path('packages/backend/backend_grpc/server.py'),
        Path('packages/worker/runtime/internal_api.py'),
    ):
        path = ROOT / rel_path
        if not path.exists():
            errors.append(f'worker runtime RPC implementation is missing: {rel_path}')
            continue
        content = path.read_text()
        for token, reason in WORKER_RUNTIME_RPC_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{rel_path} contains {reason}: {token}')

    for rel_path in PROTOCOL_BACKED_ENUM_FILES:
        path = ROOT / rel_path
        if not path.exists():
            errors.append(f'protocol-backed enum file is missing: {rel_path}')
            continue
        content = path.read_text()
        for token, reason in PROTOCOL_BACKED_ENUM_FORBIDDEN_TOKENS.items():
            if token in content:
                errors.append(f'{rel_path} contains {reason}: {token}')

    seen_proto_struct_fields: set[str] = set()
    for path in (PACKAGES / 'protocol' / 'proto').rglob('*.proto'):
        content = path.read_text()
        for token, reason in PROTOCOL_FORBIDDEN_TOKENS.items():
            if token in content:
                rel = path.relative_to(ROOT)
                errors.append(f'{rel} contains {reason}: {token}')
        for field in proto_struct_fields(path):
            seen_proto_struct_fields.add(field)
            if field not in PROTO_STRUCT_ALLOWLIST:
                errors.append(f'{path.relative_to(ROOT)} contains unclassified google.protobuf.Struct field: {field}')

    stale_struct_allowlist = sorted(set(PROTO_STRUCT_ALLOWLIST) - seen_proto_struct_fields)
    if stale_struct_allowlist:
        errors.append(f'protocol Struct allowlist references missing fields: {", ".join(stale_struct_allowlist)}')

    for package, forbidden_roots in PACKAGE_FORBIDDEN_IMPORT_ROOTS.items():
        for path in iter_python_files(package):
            roots = imported_roots(path)
            violations = sorted(roots & forbidden_roots)
            if violations:
                rel = path.relative_to(ROOT)
                errors.append(f'{rel} imports cross-owner private modules: {", ".join(violations)}')
            legacy = sorted(roots & LEGACY_IMPORT_ROOTS)
            if legacy:
                rel = path.relative_to(ROOT)
                errors.append(f'{rel} imports deleted legacy contract roots: {", ".join(legacy)}')
            for line in engine_identity_constructor_lines(path):
                rel = path.relative_to(ROOT)
                errors.append(f'{rel}:{line} constructs EngineIdentity without explicit resource_id')
            for line in raw_compute_request_creation_lines(path):
                rel = path.relative_to(ROOT)
                errors.append(f'{rel}:{line} calls compute_requests_service.create_request with raw request_json; pass a typed ComputeCommand')

    for path in iter_source_files():
        content = path.read_text()
        for token, reason in FORBIDDEN_SOURCE_TOKENS.items():
            if token in content:
                rel = path.relative_to(ROOT)
                errors.append(f'{rel} contains {reason}: {token}')

    if errors:
        print('Package boundary violations:')
        for error in errors:
            print(f'  - {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
