import { err, okAsync, ResultAsync } from 'neverthrow';
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
	code?: string;
}

export interface ApiResponse<T> {
	data: T;
	headers: Headers;
}

function trackParseError(endpoint: string, method?: string): void {
	track({
		event: 'api_error',
		action: method ?? 'GET',
		page: typeof window !== 'undefined' ? window.location.pathname : undefined,
		target: endpoint,
		meta: { type: 'parse' }
	});
}

function createApiError(
	type: ApiErrorType,
	message: string,
	status?: number,
	statusText?: string,
	code?: string
): ApiError {
	return { type, message, status, statusText, code };
}

function buildHeaders(options?: RequestInit): Headers {
	const headers = new Headers(options?.headers);
	const identity = getClientIdentity();
	const namespace = getNamespace();
	if (identity.clientId && !headers.has('X-Client-Id'))
		headers.set('X-Client-Id', identity.clientId);
	if (identity.clientSignature && !headers.has('X-Client-Signature'))
		headers.set('X-Client-Signature', identity.clientSignature);
	if (namespace && !headers.has('X-Namespace')) headers.set('X-Namespace', namespace);
	if (!(options?.body instanceof FormData) && !headers.has('Content-Type'))
		headers.set('Content-Type', 'application/json');
	return headers;
}

function handleErrorResponse(
	response: Response,
	endpoint: string,
	options?: RequestInit
): ResultAsync<never, ApiError> {
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
	).andThen((raw) => {
		let message = raw || response.statusText;
		let code: string | undefined;
		try {
			const parsed = JSON.parse(raw);
			if (typeof parsed.detail === 'string') message = parsed.detail;
			if (typeof parsed.error_code === 'string') code = parsed.error_code;
		} catch {
			// raw text is fine as fallback
		}
		return err(createApiError('http', message, response.status, response.statusText, code));
	});
}

function apiFetch<T>(
	endpoint: string,
	options: RequestInit | undefined,
	parse: (response: Response) => ResultAsync<T, ApiError>
): ResultAsync<T, ApiError> {
	const headers = buildHeaders(options);
	return ResultAsync.fromPromise(
		fetch(`${BASE_URL}${endpoint}`, { ...options, headers }),
		(error): ApiError =>
			createApiError('network', error instanceof Error ? error.message : 'Network error')
	).andThen((response) => {
		if (!response.ok) return handleErrorResponse(response, endpoint, options);
		return parse(response);
	});
}

export function apiRequest<T>(endpoint: string, options?: RequestInit): ResultAsync<T, ApiError> {
	return apiFetch(endpoint, options, (response) => {
		if (response.status === 204) return okAsync(undefined as T);
		return ResultAsync.fromPromise(response.json() as Promise<T>, (): ApiError => {
			trackParseError(endpoint, options?.method);
			return createApiError('parse', 'Failed to parse response JSON');
		});
	});
}

export function apiRequestWithHeaders<T>(
	endpoint: string,
	options?: RequestInit
): ResultAsync<ApiResponse<T>, ApiError> {
	return apiFetch(endpoint, options, (response) => {
		if (response.status === 204)
			return okAsync({ data: undefined as T, headers: response.headers });
		return ResultAsync.fromPromise(response.json() as Promise<T>, (): ApiError => {
			trackParseError(endpoint, options?.method);
			return createApiError('parse', 'Failed to parse response JSON');
		}).map((data) => ({ data, headers: response.headers }));
	});
}

export function apiBlobRequest(
	endpoint: string,
	options?: RequestInit
): ResultAsync<Blob, ApiError> {
	return apiFetch(endpoint, options, (response) =>
		ResultAsync.fromPromise(response.blob(), (): ApiError => {
			trackParseError(endpoint, options?.method);
			return createApiError('parse', 'Failed to read response');
		})
	);
}
