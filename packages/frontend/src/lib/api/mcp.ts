import { apiRequest } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export interface MCPTool {
	id: string;
	method: string;
	path: string;
	description: string;
	safety: 'safe' | 'mutating';
	confirm_required: boolean;
	input_schema: Record<string, unknown>;
	output_schema?: {
		status_code: string;
		content_type: string | null;
		schema: Record<string, unknown> | boolean | null;
		response_model: string | null;
		fields?: string[];
		hint?: string;
	} | null;
	tags: string[];
}

export function listTools(): ResultAsync<MCPTool[], ApiError> {
	return apiRequest<MCPTool[]>('/v1/mcp/tools');
}
