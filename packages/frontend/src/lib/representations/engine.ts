import type { ComputeWorkerStatus, ComputeWorkerStatusResponse } from '$lib/types/compute';

export function engineIdentityKey(engine: ComputeWorkerStatusResponse): string {
	return `${engine.scope ?? 'analysis_interactive'}:${engine.resource_id}`;
}

export function engineStatusColor(status: ComputeWorkerStatus): string {
	return status === 'healthy' ? 'fg.success' : 'fg.error';
}

export function engineStatusLabel(status: ComputeWorkerStatus): string {
	return status === 'healthy' ? 'Healthy' : 'Terminated';
}
