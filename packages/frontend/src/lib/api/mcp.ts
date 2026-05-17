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

export interface MCPCallResult {
	status: 'executed' | 'pending' | 'validation_error';
	errors?: { path: string; message: string }[];
	token?: string;
	tool_id?: string;
	method?: string;
	path?: string;
	args?: Record<string, unknown>;
	confirm_required?: boolean;
	result?: { status: number; body: unknown; ok: boolean };
}

export interface MCPConfirmResult {
	status: 'executed';
	result: { status: number; body: unknown; ok: boolean };
	tool_id: string;
}

export function listTools(): ResultAsync<MCPTool[], ApiError> {
	return apiRequest<MCPTool[]>('/v1/mcp/tools');
}

export function callTool(
	toolId: string,
	args: Record<string, unknown>
): ResultAsync<MCPCallResult, ApiError> {
	return apiRequest<MCPCallResult>('/v1/mcp/call', {
		method: 'POST',
		body: JSON.stringify({ tool_id: toolId, args })
	});
}

export function confirmTool(token: string): ResultAsync<MCPConfirmResult, ApiError> {
	return apiRequest<MCPConfirmResult>('/v1/mcp/confirm', {
		method: 'POST',
		body: JSON.stringify({ token })
	});
}

export interface MCPValidateResult {
	valid: boolean;
	errors: { path: string; message: string }[];
	args: Record<string, unknown>;
}

export function validateTool(
	toolId: string,
	args: Record<string, unknown>
): ResultAsync<MCPValidateResult, ApiError> {
	return apiRequest<MCPValidateResult>('/v1/mcp/validate', {
		method: 'POST',
		body: JSON.stringify({ tool_id: toolId, args })
	});
}

export interface MCPCapabilityEntry {
	tool_id: string;
	supported: boolean;
	issues: { path: string; message: string }[];
}

export function capabilityReport(
	toolIds: string[] = []
): ResultAsync<MCPCapabilityEntry[], ApiError> {
	return apiRequest<MCPCapabilityEntry[]>('/v1/mcp/capabilities', {
		method: 'POST',
		body: JSON.stringify({ tool_ids: toolIds })
	});
}
