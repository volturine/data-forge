import type {
	ComputeWorkerDefaultsJson as ProtocolComputeWorkerDefaultsJson,
	ComputeWorkerIdentityJson as ProtocolComputeWorkerIdentityJson,
	ComputeWorkerResourceConfigJson as ProtocolComputeWorkerResourceConfigJson,
	ComputeWorkerStatusResultJson as ProtocolComputeWorkerStatusResultJson
} from '$lib/protocol/dataforge_protocol/compute_pb';
import type {
	ComputeWorkerInstanceStatus,
	ComputeWorkerReusePolicy,
	ComputeWorkerScope,
	ComputeWorkerStatus
} from '$lib/types/protocol-enum-tokens';

export type { ComputeWorkerReusePolicy, ComputeWorkerScope, ComputeWorkerStatus };

type Field<T, K extends keyof T> = NonNullable<T[K]>;
type NumberField<T, K extends keyof T> = Extract<Field<T, K>, number>;
type StringField<T, K extends keyof T> = Extract<Field<T, K>, string>;
type OptionalNumberField<T, K extends keyof T> = NumberField<T, K> | null;
type OptionalStringField<T, K extends keyof T> = StringField<T, K> | null;
type OptionalObjectField<T, K extends keyof T> = Field<T, K> | null;

export interface ComputeWorkerResourceConfig {
	max_threads?: OptionalNumberField<ProtocolComputeWorkerResourceConfigJson, 'maxThreads'>;
	max_memory_mb?: OptionalNumberField<ProtocolComputeWorkerResourceConfigJson, 'maxMemoryMb'>;
	streaming_chunk_size?: OptionalNumberField<
		ProtocolComputeWorkerResourceConfigJson,
		'streamingChunkSize'
	>;
}

export interface ComputeWorkerDefaults {
	max_threads: NumberField<ProtocolComputeWorkerDefaultsJson, 'maxThreads'>;
	max_memory_mb: NumberField<ProtocolComputeWorkerDefaultsJson, 'maxMemoryMb'>;
	streaming_chunk_size: NumberField<ProtocolComputeWorkerDefaultsJson, 'streamingChunkSize'>;
}

export interface ComputeWorkerStatusResponse {
	analysis_id: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'analysisId'>;
	resource_id: StringField<ProtocolComputeWorkerStatusResultJson, 'resourceId'>;
	status: ComputeWorkerStatus;
	container_id: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'containerId'>;
	image_digest: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'imageDigest'>;
	lifecycle_status: ComputeWorkerInstanceStatus | null;
	termination_reason: OptionalStringField<
		ProtocolComputeWorkerStatusResultJson,
		'terminationReason'
	>;
	exit_code: OptionalNumberField<ProtocolComputeWorkerStatusResultJson, 'exitCode'>;
	oom_killed: boolean | null;
	supervisor_id: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'supervisorId'>;
	owner_id: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'ownerId'>;
	docker_host: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'dockerHost'>;
	last_activity: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'lastActivity'>;
	current_job_id: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'currentJobId'>;
	resource_config: OptionalObjectField<ProtocolComputeWorkerStatusResultJson, 'resourceConfig'>;
	effective_resources: OptionalObjectField<
		ProtocolComputeWorkerStatusResultJson,
		'effectiveResources'
	>;
	defaults: OptionalObjectField<ProtocolComputeWorkerStatusResultJson, 'defaults'>;
	scope: ComputeWorkerScope | null;
	reuse_policy: ComputeWorkerReusePolicy | null;
	datasource_id: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'datasourceId'>;
	build_id: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'buildId'>;
	current_build_id: OptionalStringField<ProtocolComputeWorkerStatusResultJson, 'currentBuildId'>;
	current_engine_run_id: OptionalStringField<
		ProtocolComputeWorkerStatusResultJson,
		'currentEngineRunId'
	>;
}

export interface ComputeWorkerIdentityPayload {
	scope: ComputeWorkerScope;
	reuse_policy: ComputeWorkerReusePolicy;
	resource_id: StringField<ProtocolComputeWorkerIdentityJson, 'resourceId'>;
	analysis_id?: OptionalStringField<ProtocolComputeWorkerIdentityJson, 'analysisId'>;
	datasource_id?: OptionalStringField<ProtocolComputeWorkerIdentityJson, 'datasourceId'>;
	build_id?: OptionalStringField<ProtocolComputeWorkerIdentityJson, 'buildId'>;
}
