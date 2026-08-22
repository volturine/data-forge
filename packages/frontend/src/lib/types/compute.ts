import type {
	EngineDefaultsJson as ProtocolEngineDefaultsJson,
	EngineIdentityJson as ProtocolEngineIdentityJson,
	EngineResourceConfigJson as ProtocolEngineResourceConfigJson,
	EngineStatusResultJson as ProtocolEngineStatusResultJson
} from '$lib/protocol/dataforge_protocol/compute_pb';
import type {
	EngineInstanceStatus,
	EngineReusePolicy,
	EngineScope,
	EngineStatus
} from '$lib/types/protocol-enum-tokens';

export type { EngineReusePolicy, EngineScope, EngineStatus };

type Field<T, K extends keyof T> = NonNullable<T[K]>;
type NumberField<T, K extends keyof T> = Extract<Field<T, K>, number>;
type StringField<T, K extends keyof T> = Extract<Field<T, K>, string>;
type OptionalNumberField<T, K extends keyof T> = NumberField<T, K> | null;
type OptionalStringField<T, K extends keyof T> = StringField<T, K> | null;
type OptionalObjectField<T, K extends keyof T> = Field<T, K> | null;

export interface EngineResourceConfig {
	max_threads?: OptionalNumberField<ProtocolEngineResourceConfigJson, 'maxThreads'>;
	max_memory_mb?: OptionalNumberField<ProtocolEngineResourceConfigJson, 'maxMemoryMb'>;
	streaming_chunk_size?: OptionalNumberField<
		ProtocolEngineResourceConfigJson,
		'streamingChunkSize'
	>;
}

export interface EngineDefaults {
	max_threads: NumberField<ProtocolEngineDefaultsJson, 'maxThreads'>;
	max_memory_mb: NumberField<ProtocolEngineDefaultsJson, 'maxMemoryMb'>;
	streaming_chunk_size: NumberField<ProtocolEngineDefaultsJson, 'streamingChunkSize'>;
}

export interface EngineStatusResponse {
	analysis_id: StringField<ProtocolEngineStatusResultJson, 'analysisId'>;
	resource_id: StringField<ProtocolEngineStatusResultJson, 'resourceId'>;
	status: EngineStatus;
	container_id: OptionalStringField<ProtocolEngineStatusResultJson, 'containerId'>;
	image_digest: OptionalStringField<ProtocolEngineStatusResultJson, 'imageDigest'>;
	lifecycle_status: EngineInstanceStatus | null;
	termination_reason: OptionalStringField<ProtocolEngineStatusResultJson, 'terminationReason'>;
	exit_code: OptionalNumberField<ProtocolEngineStatusResultJson, 'exitCode'>;
	oom_killed: boolean | null;
	supervisor_id: OptionalStringField<ProtocolEngineStatusResultJson, 'supervisorId'>;
	owner_id: OptionalStringField<ProtocolEngineStatusResultJson, 'ownerId'>;
	last_activity: OptionalStringField<ProtocolEngineStatusResultJson, 'lastActivity'>;
	current_job_id: OptionalStringField<ProtocolEngineStatusResultJson, 'currentJobId'>;
	resource_config: OptionalObjectField<ProtocolEngineStatusResultJson, 'resourceConfig'>;
	effective_resources: OptionalObjectField<ProtocolEngineStatusResultJson, 'effectiveResources'>;
	defaults: OptionalObjectField<ProtocolEngineStatusResultJson, 'defaults'>;
	scope: EngineScope | null;
	reuse_policy: EngineReusePolicy | null;
	datasource_id: OptionalStringField<ProtocolEngineStatusResultJson, 'datasourceId'>;
	build_id: OptionalStringField<ProtocolEngineStatusResultJson, 'buildId'>;
	current_build_id: OptionalStringField<ProtocolEngineStatusResultJson, 'currentBuildId'>;
	current_engine_run_id: OptionalStringField<ProtocolEngineStatusResultJson, 'currentEngineRunId'>;
}

export interface EngineIdentityPayload {
	scope: EngineScope;
	reuse_policy: EngineReusePolicy;
	resource_id: StringField<ProtocolEngineIdentityJson, 'resourceId'>;
	analysis_id?: OptionalStringField<ProtocolEngineIdentityJson, 'analysisId'>;
	datasource_id?: OptionalStringField<ProtocolEngineIdentityJson, 'datasourceId'>;
	build_id?: OptionalStringField<ProtocolEngineIdentityJson, 'buildId'>;
}
