import { apiRequest } from './client';
import type { ApiError } from './client';
import type { ResultAsync } from 'neverthrow';
import type {
	BuildLifecycleStatus,
	BuildRunDetail,
	BuildRunListResponse
} from '#lib/types/build-stream.js';
import { namespaceKey, shareInFlight } from './in-flight';
import { withQuery } from './query';

export interface ListBuildsParams {
	analysis_id?: string;
	datasource_id?: string;
	kind?: string;
	status?: BuildLifecycleStatus;
	search?: string;
	limit?: number;
	offset?: number;
}

const inFlight = new Map<string, ResultAsync<BuildRunListResponse, ApiError>>();

export function listBuilds(params?: ListBuildsParams): ResultAsync<BuildRunListResponse, ApiError> {
	const endpoint = withQuery('/v1/compute/builds', {
		analysis_id: params?.analysis_id,
		datasource_id: params?.datasource_id,
		kind: params?.kind,
		status: params?.status,
		search: params?.search,
		limit: params?.limit,
		offset: params?.offset
	});
	return shareInFlight(inFlight, `${namespaceKey()}:${endpoint}`, () =>
		apiRequest<BuildRunListResponse>(endpoint)
	);
}

export function getBuild(buildId: string): ResultAsync<BuildRunDetail, ApiError> {
	return apiRequest<BuildRunDetail>(`/v1/compute/builds/${buildId}`);
}
