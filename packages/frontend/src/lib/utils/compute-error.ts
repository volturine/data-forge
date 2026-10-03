import type { ApiError } from '$lib/api/client';

export class ComputeError extends Error {
	readonly status?: number;
	readonly errorType?: ApiError['type'];

	constructor(message: string, options: { status?: number; errorType?: ApiError['type'] } = {}) {
		super(message);
		this.status = options.status;
		this.errorType = options.errorType;
	}
}

export function toComputeError(error: ApiError): ComputeError {
	return new ComputeError(error.message, { status: error.status, errorType: error.type });
}
