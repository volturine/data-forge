import { apiRequest } from './client';
import type { ApiError } from './client';
import type { ResultAsync } from 'neverthrow';
import { isNamespaceReady, requireNamespace } from '$lib/stores/namespace.svelte';
import type { ActiveBuildDetail, ActiveBuildSummary } from '$lib/types/build-stream';
import { shareInFlight } from './in-flight';

export interface ListBuildsParams {
	analysis_id?: string;
	datasource_id?: string;
	kind?: string;
	status?: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
	limit?: number;
	offset?: number;
}

interface ActiveBuildListResponse {
	builds: ActiveBuildSummary[];
	total: number;
}

function buildQueryString(params?: ListBuildsParams): string {
	if (!params) return '';
	const query = new URLSearchParams();
	if (params.analysis_id) query.set('analysis_id', params.analysis_id);
	if (params.datasource_id) query.set('datasource_id', params.datasource_id);
	if (params.kind) query.set('kind', params.kind);
	if (params.status) query.set('status', params.status);
	if (params.limit !== undefined) query.set('limit', String(params.limit));
	if (params.offset !== undefined) query.set('offset', String(params.offset));
	const str = query.toString();
	return str ? `?${str}` : '';
}

const inFlight = new Map<string, ResultAsync<ActiveBuildListResponse, ApiError>>();

function namespaceKey(): string {
	if (!isNamespaceReady()) return '';
	return requireNamespace();
}

export function listBuilds(
	params?: ListBuildsParams,
	signal?: AbortSignal
): ResultAsync<ActiveBuildListResponse, ApiError> {
	const endpoint = `/v1/compute/builds${buildQueryString(params)}`;
	if (signal) return apiRequest<ActiveBuildListResponse>(endpoint, { signal });
	return shareInFlight(inFlight, `${namespaceKey()}:${endpoint}`, () =>
		apiRequest<ActiveBuildListResponse>(endpoint)
	);
}

export function getBuild(buildId: string): ResultAsync<ActiveBuildDetail, ApiError> {
	return apiRequest<ActiveBuildDetail>(`/v1/compute/builds/${buildId}`);
}
