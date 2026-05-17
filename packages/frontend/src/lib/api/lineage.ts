import { apiRequest } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import type { SourceType } from '$lib/types/datasource';

export type NodeKind = 'source' | 'output' | 'internal' | 'analysis';
export type EdgeType = 'uses' | 'produces' | 'chains' | 'consumes_internal';
export type LineageMode = 'full' | 'upstream' | 'downstream';

export interface LineageNode {
	id: string;
	type: string;
	node_kind: NodeKind;
	name: string;
	source_type?: SourceType;
	status?: string;
	branch?: string | null;
}

export interface LineageEdge {
	from: string;
	to: string;
	type: EdgeType;
}

export interface LineageResponse {
	nodes: LineageNode[];
	edges: LineageEdge[];
}

export interface LineageParams {
	target?: string | null;
	branch?: string | null;
	mode?: LineageMode;
	internals?: boolean;
}

export function getLineage(params: LineageParams = {}): ResultAsync<LineageResponse, ApiError> {
	const search = new URLSearchParams();
	if (params.target) search.set('target_datasource_id', params.target);
	if (params.branch) search.set('branch', params.branch);
	if (params.mode && params.mode !== 'full') search.set('mode', params.mode);
	if (params.internals) search.set('include_internals', 'true');
	const suffix = search.toString() ? `?${search.toString()}` : '';
	return apiRequest<LineageResponse>(`/v1/datasource/lineage${suffix}`);
}
