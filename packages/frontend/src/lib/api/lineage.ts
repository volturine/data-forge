import { apiRequest } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import type { SourceType } from '#lib/types/datasource.js';
import { withQuery } from './query';

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
	return apiRequest<LineageResponse>(
		withQuery('/v1/datasource/lineage', {
			target_datasource_id: params.target,
			branch: params.branch,
			mode: params.mode === 'full' ? undefined : params.mode,
			include_internals: params.internals
		})
	);
}
