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

/** Whether the engine is currently running a compute job. */
export function engineHasActiveJob(engine: ComputeWorkerStatusResponse): boolean {
	return Boolean(engine.current_job_id);
}

/** Human activity label: idle warm container vs job in flight. */
export function engineActivityLabel(engine: ComputeWorkerStatusResponse): string {
	if (engine.status !== 'healthy') return engineStatusLabel(engine.status);
	return engineHasActiveJob(engine) ? 'Job running' : 'Idle';
}

export function engineShutdownHeading(engine: ComputeWorkerStatusResponse): string {
	return engineHasActiveJob(engine) ? 'Cancel job and shut down engine?' : 'Shut down idle engine?';
}

export function engineShutdownMessage(engine: ComputeWorkerStatusResponse): string {
	const id = engine.resource_id;
	if (engineHasActiveJob(engine)) {
		return (
			`Engine ${id} has an active job. Confirming will cancel that job first, ` +
			`then stop and remove the engine container.`
		);
	}
	return (
		`Engine ${id} is idle. Confirming will stop and remove the warm container ` +
		`so it no longer holds compute capacity.`
	);
}

export function engineShutdownConfirmText(engine: ComputeWorkerStatusResponse): string {
	return engineHasActiveJob(engine) ? 'Cancel job & shut down' : 'Shut down';
}
