import { apiRequest } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import type { SourceType } from '$lib/types/datasource';

export interface LineageNode {
	id: string;
	type: string;
	name: string;
	source_type?: SourceType;
	status?: string;
	branch?: string | null;
}

export interface LineageEdge {
	from: string;
	to: string;
	type: string;
}

export interface LineageResponse {
	nodes: LineageNode[];
	edges: LineageEdge[];
}

export function getLineage(
	targetDatasourceId?: string | null,
	branch?: string | null
): ResultAsync<LineageResponse, ApiError> {
	const params = new URLSearchParams();
	if (targetDatasourceId) params.set('target_datasource_id', targetDatasourceId);
	if (branch) params.set('branch', branch);
	const suffix = params.toString() ? `?${params.toString()}` : '';
	return apiRequest<LineageResponse>(`/v1/datasource/lineage${suffix}`);
}
