import type { ApiError } from '#lib/api/client.js';

export class ComputeError extends Error {}

export function toComputeError(error: ApiError): ComputeError {
	return new ComputeError(error.message);
}
