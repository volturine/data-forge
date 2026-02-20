import { err, ResultAsync } from 'neverthrow';
import { getClientIdentity } from '$lib/stores/clientIdentity.svelte';
import { getNamespace } from '$lib/stores/namespace.svelte';
import { track } from '$lib/utils/audit-log';

// Always use relative paths - works in both dev (via proxy) and prod
export const BASE_URL = '/api';

export type ApiErrorType = 'network' | 'http' | 'parse';

export interface ApiError {
	type: ApiErrorType;
	message: string;
	status?: number;
	statusText?: string;
}

export interface ApiResponse<T> {
	data: T;
	headers: Headers;
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
	const identity = getClientIdentity();
	const namespace = getNamespace();
	if (identity.clientId && !headers.has('X-Client-Id')) {
		headers.set('X-Client-Id', identity.clientId);
	}
	if (identity.clientSignature && !headers.has('X-Client-Signature')) {
		headers.set('X-Client-Signature', identity.clientSignature);
	}
	if (namespace && !headers.has('X-Namespace')) {
		headers.set('X-Namespace', namespace);
	}

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
			track({
				event: 'api_error',
				action: options?.method ?? 'GET',
				page: typeof window !== 'undefined' ? window.location.pathname : undefined,
				target: endpoint,
				meta: { status: response.status, statusText: response.statusText }
			});
			return ResultAsync.fromPromise(response.text(), (error) =>
				createApiError(
					'http',
					error instanceof Error ? error.message : response.statusText,
					response.status,
					response.statusText
				)
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
		if (response.status === 204) {
			return ResultAsync.fromPromise(
				Promise.resolve(undefined as T),
				(): ApiError => createApiError('parse', 'Failed to parse response JSON')
			);
		}
		return ResultAsync.fromPromise(response.json() as Promise<T>, (): ApiError => {
			track({
				event: 'api_error',
				action: options?.method ?? 'GET',
				page: typeof window !== 'undefined' ? window.location.pathname : undefined,
				target: endpoint,
				meta: { type: 'parse' }
			});
			return createApiError('parse', 'Failed to parse response JSON');
		});
	});
}

export function apiRequestWithHeaders<T>(
	endpoint: string,
	options?: RequestInit
): ResultAsync<ApiResponse<T>, ApiError> {
	const isFormData = options?.body instanceof FormData;
	const headers = new Headers(options?.headers);
	const identity = getClientIdentity();
	const namespace = getNamespace();
	if (identity.clientId && !headers.has('X-Client-Id')) {
		headers.set('X-Client-Id', identity.clientId);
	}
	if (identity.clientSignature && !headers.has('X-Client-Signature')) {
		headers.set('X-Client-Signature', identity.clientSignature);
	}
	if (namespace && !headers.has('X-Namespace')) {
		headers.set('X-Namespace', namespace);
	}

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
			track({
				event: 'api_error',
				action: options?.method ?? 'GET',
				page: typeof window !== 'undefined' ? window.location.pathname : undefined,
				target: endpoint,
				meta: { status: response.status, statusText: response.statusText }
			});
			return ResultAsync.fromPromise(response.text(), (error) =>
				createApiError(
					'http',
					error instanceof Error ? error.message : response.statusText,
					response.status,
					response.statusText
				)
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
		if (response.status === 204) {
			return ResultAsync.fromPromise(
				Promise.resolve(undefined as T),
				(): ApiError => createApiError('parse', 'Failed to parse response JSON')
			).map((data) => ({ data, headers: response.headers }));
		}
		return ResultAsync.fromPromise(response.json() as Promise<T>, (): ApiError => {
			track({
				event: 'api_error',
				action: options?.method ?? 'GET',
				page: typeof window !== 'undefined' ? window.location.pathname : undefined,
				target: endpoint,
				meta: { type: 'parse' }
			});
			return createApiError('parse', 'Failed to parse response JSON');
		}).map((data) => ({ data, headers: response.headers }));
	});
}

export function apiBlobRequest(
	endpoint: string,
	options?: RequestInit
): ResultAsync<Blob, ApiError> {
	const headers = new Headers(options?.headers);
	const identity = getClientIdentity();
	const namespace = getNamespace();
	if (identity.clientId && !headers.has('X-Client-Id')) {
		headers.set('X-Client-Id', identity.clientId);
	}
	if (identity.clientSignature && !headers.has('X-Client-Signature')) {
		headers.set('X-Client-Signature', identity.clientSignature);
	}
	if (namespace && !headers.has('X-Namespace')) {
		headers.set('X-Namespace', namespace);
	}
	if (!headers.has('Content-Type')) {
		headers.set('Content-Type', 'application/json');
	}

	return ResultAsync.fromPromise(
		fetch(`${BASE_URL}${endpoint}`, { ...options, headers }),
		(error): ApiError =>
			createApiError('network', error instanceof Error ? error.message : 'Network error')
	).andThen((response) => {
		if (!response.ok) {
			track({
				event: 'api_error',
				action: options?.method ?? 'GET',
				page: typeof window !== 'undefined' ? window.location.pathname : undefined,
				target: endpoint,
				meta: { status: response.status, statusText: response.statusText }
			});
			return ResultAsync.fromPromise(response.text(), (error) =>
				createApiError(
					'http',
					error instanceof Error ? error.message : response.statusText,
					response.status,
					response.statusText
				)
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
		return ResultAsync.fromPromise(response.blob(), (): ApiError => {
			track({
				event: 'api_error',
				action: options?.method ?? 'GET',
				page: typeof window !== 'undefined' ? window.location.pathname : undefined,
				target: endpoint,
				meta: { type: 'parse' }
			});
			return createApiError('parse', 'Failed to read response');
		});
	});
}
