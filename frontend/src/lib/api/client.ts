import { err, ResultAsync } from 'neverthrow';

// In dev, always use relative URLs so Vite's dev proxy handles /api
// In prod, allow overriding via VITE_API_URL, otherwise default to current host:8000
const apiEnv = import.meta.env.VITE_API_URL?.trim();

const runtimeBase =
	typeof window === 'undefined'
		? 'http://localhost:8000'
		: `${window.location.protocol}//${window.location.hostname}:8000`;

export const BASE_URL = import.meta.env.DEV ? '' : apiEnv || runtimeBase;

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
	return ResultAsync.fromPromise(
		fetch(`${BASE_URL}${endpoint}`, {
			...options,
			headers: {
				'Content-Type': 'application/json',
				...options?.headers
			}
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
