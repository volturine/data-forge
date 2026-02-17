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

export function getLineage(): ResultAsync<LineageResponse, ApiError> {
	return apiRequest<LineageResponse>('/v1/datasource/lineage');
}
