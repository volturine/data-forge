import type { ApiError } from '$lib/api/client';

/**
 * Preview/row-count/schema requests run through the compute runtime and can
 * transiently fail under load: 409 when the analysis engine already has an
 * active job, 503 when the runtime is saturated, or a network error while the
 * browser tab was backgrounded. These resolve on retry; validation errors
 * (4xx) do not and stay terminal.
 */
export class ComputeTransientError extends Error {
	readonly status?: number;
	readonly errorType?: ApiError['type'];

	constructor(message: string, options: { status?: number; errorType?: ApiError['type'] } = {}) {
		super(message);
		this.status = options.status;
		this.errorType = options.errorType;
	}
}

export function toComputeError(error: ApiError): ComputeTransientError {
	return new ComputeTransientError(error.message, { status: error.status, errorType: error.type });
}

export function isTransientComputeError(error: unknown): boolean {
	if (!(error instanceof ComputeTransientError)) return false;
	if (error.errorType === 'network') return true;
	return error.status === 409 || error.status === 503;
}

export function computeRetryDelay(attempt: number): number {
	return Math.min(1000 * 2 ** attempt, 8000);
}
