import type { EngineStatus, EngineStatusResponse } from '$lib/types/compute';

export function engineIdentityKey(engine: EngineStatusResponse): string {
	return `${engine.scope ?? 'analysis_interactive'}:${engine.resource_id}`;
}

export function engineStatusColor(status: EngineStatus): string {
	return status === 'healthy' ? 'fg.success' : 'fg.error';
}

export function engineStatusLabel(status: EngineStatus): string {
	return status === 'healthy' ? 'Healthy' : 'Terminated';
}
