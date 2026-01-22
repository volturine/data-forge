import { err, ResultAsync } from 'neverthrow';

// Always use relative paths - works in both dev (via proxy) and prod
export const BASE_URL = '/api';

export type ApiErrorType = 'network' | 'http' | 'parse';

export interface ApiError {
	type: ApiErrorType;
	message: string;
	status?: number;
	statusText?: string;
}

function createApiError(
	type: ApiErrorType,
	message: string,
	status?: number,
	statusText?: string
): ApiError {
	return { type, message, status, statusText };
}

export function apiRequest<T>(endpoint: string, options?: RequestInit): ResultAsync<T, ApiError> {
	const isFormData = options?.body instanceof FormData;
	const headers = new Headers(options?.headers);

	if (!isFormData && !headers.has('Content-Type')) {
		headers.set('Content-Type', 'application/json');
	}

	return ResultAsync.fromPromise(
		fetch(`${BASE_URL}${endpoint}`, {
			...options,
			headers
		}),
		(error): ApiError =>
			createApiError('network', error instanceof Error ? error.message : 'Network error')
	).andThen((response) => {
		if (!response.ok) {
			return ResultAsync.fromPromise(
				response.text().catch(() => response.statusText),
				() => createApiError('http', response.statusText, response.status, response.statusText)
			).andThen((errorText) =>
				err(
					createApiError(
						'http',
						errorText || response.statusText,
						response.status,
						response.statusText
					)
				)
			);
		}
		return ResultAsync.fromPromise(
			response.json() as Promise<T>,
			(): ApiError => createApiError('parse', 'Failed to parse response JSON')
		);
	});
}

export function apiBlobRequest(endpoint: string, options?: RequestInit): ResultAsync<Blob, ApiError> {
	const headers = new Headers(options?.headers);
	if (!headers.has('Content-Type')) {
		headers.set('Content-Type', 'application/json');
	}

	return ResultAsync.fromPromise(
		fetch(`${BASE_URL}${endpoint}`, { ...options, headers }),
		(error): ApiError =>
			createApiError('network', error instanceof Error ? error.message : 'Network error')
	).andThen((response) => {
		if (!response.ok) {
			return ResultAsync.fromPromise(
				response.text().catch(() => response.statusText),
				() => createApiError('http', response.statusText, response.status, response.statusText)
			).andThen((errorText) =>
				err(
					createApiError(
						'http',
						errorText || response.statusText,
						response.status,
						response.statusText
					)
				)
			);
		}
		return ResultAsync.fromPromise(
			response.blob(),
			(): ApiError => createApiError('parse', 'Failed to read response')
		);
	});
}
