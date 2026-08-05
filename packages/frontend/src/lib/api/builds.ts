import { apiRequest } from './client';
import type { ApiError } from './client';
import type { ResultAsync } from 'neverthrow';
import { isNamespaceReady, requireNamespace } from '$lib/stores/namespace.svelte';
import type { BuildRunDetail, BuildRunListResponse } from '$lib/types/build-stream';
import { shareInFlight } from './in-flight';

export interface ListBuildsParams {
	analysis_id?: string;
	datasource_id?: string;
	kind?: string;
	status?: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
	search?: string;
	limit?: number;
	offset?: number;
}

function buildQueryString(params?: ListBuildsParams): string {
	if (!params) return '';
	const query = new URLSearchParams();
	if (params.analysis_id) query.set('analysis_id', params.analysis_id);
	if (params.datasource_id) query.set('datasource_id', params.datasource_id);
	if (params.kind) query.set('kind', params.kind);
	if (params.status) query.set('status', params.status);
	if (params.search) query.set('search', params.search);
	if (params.limit !== undefined) query.set('limit', String(params.limit));
	if (params.offset !== undefined) query.set('offset', String(params.offset));
	const str = query.toString();
	return str ? `?${str}` : '';
}

const inFlight = new Map<string, ResultAsync<BuildRunListResponse, ApiError>>();

function namespaceKey(): string {
	if (!isNamespaceReady()) return '';
	return requireNamespace();
}

export function listBuilds(
	params?: ListBuildsParams,
	signal?: AbortSignal
): ResultAsync<BuildRunListResponse, ApiError> {
	const endpoint = `/v1/compute/builds${buildQueryString(params)}`;
	if (signal) return apiRequest<BuildRunListResponse>(endpoint, { signal });
	return shareInFlight(inFlight, `${namespaceKey()}:${endpoint}`, () =>
		apiRequest<BuildRunListResponse>(endpoint)
	);
}

export function getBuild(buildId: string): ResultAsync<BuildRunDetail, ApiError> {
	return apiRequest<BuildRunDetail>(`/v1/compute/builds/${buildId}`);
}
