import type { ComputeWorkerStatus, ComputeWorkerStatusResponse } from '$lib/types/compute';

export function computeWorkerIdentityKey(computeWorker: ComputeWorkerStatusResponse): string {
	return `${computeWorker.scope ?? 'analysis_interactive'}:${computeWorker.resource_id}`;
}

export function computeWorkerStatusColor(status: ComputeWorkerStatus): string {
	return status === 'healthy' ? 'fg.success' : 'fg.error';
}

export function computeWorkerStatusLabel(status: ComputeWorkerStatus): string {
	return status === 'healthy' ? 'Healthy' : 'Terminated';
}
