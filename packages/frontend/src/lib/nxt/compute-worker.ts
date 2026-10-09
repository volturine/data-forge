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

/** Whether the compute worker is currently running a job. */
export function computeWorkerHasActiveJob(computeWorker: ComputeWorkerStatusResponse): boolean {
	return Boolean(computeWorker.current_job_id);
}

/** Human activity label: idle warm container vs job in flight. */
export function computeWorkerActivityLabel(computeWorker: ComputeWorkerStatusResponse): string {
	if (computeWorker.status !== 'healthy') return computeWorkerStatusLabel(computeWorker.status);
	return computeWorkerHasActiveJob(computeWorker) ? 'Job running' : 'Idle';
}

export function computeWorkerShutdownHeading(computeWorker: ComputeWorkerStatusResponse): string {
	return computeWorkerHasActiveJob(computeWorker)
		? 'Cancel job and shut down compute worker?'
		: 'Shut down idle compute worker?';
}

export function computeWorkerShutdownMessage(computeWorker: ComputeWorkerStatusResponse): string {
	const id = computeWorker.resource_id;
	if (computeWorkerHasActiveJob(computeWorker)) {
		return (
			`Compute worker ${id} has an active job. Confirming will cancel that job first, ` +
			`then stop and remove the compute worker container.`
		);
	}
	return (
		`Compute worker ${id} is idle. Confirming will stop and remove the warm container ` +
		`so it no longer holds compute capacity.`
	);
}

export function computeWorkerShutdownConfirmText(
	computeWorker: ComputeWorkerStatusResponse
): string {
	return computeWorkerHasActiveJob(computeWorker) ? 'Cancel job & shut down' : 'Shut down';
}
