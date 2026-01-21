import { err, ResultAsync } from 'neverthrow';

// API URL configuration:
// - In dev: Use empty string so Vite's proxy handles /api requests
// - In prod: Use /api prefix if served from same origin, otherwise use VITE_API_URL
const apiEnv = import.meta.env.VITE_API_URL?.trim();

// For production builds served by FastAPI, use /api prefix
// For separate deployments, use VITE_API_URL or fallback to :8000
const runtimeBase =
	typeof window === 'undefined'
		? 'http://localhost:8000'
		: apiEnv ||
		  (window.location.port === '8000' ? '/api' : `${window.location.protocol}//${window.location.hostname}:8000`);

export const BASE_URL = import.meta.env.DEV ? '' : runtimeBase;

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
