import { apiRequest } from '$lib/api/client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from '$lib/api/client';

export interface MCPTool {
	id: string;
	method: string;
	path: string;
	description: string;
	safety: 'safe' | 'mutating';
	confirm_required: boolean;
	input_schema: Record<string, unknown>;
	tags: string[];
}

export interface MCPCallResult {
	status: 'executed' | 'pending';
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

export interface MCPPreflightResult {
	valid: boolean;
	status?: 'pending' | 'ready';
	errors?: { path: string; message: string }[];
	token?: string;
	tool_id?: string;
	method?: string;
	path?: string;
	args?: Record<string, unknown>;
	confirm_required?: boolean;
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

export function preflightTool(
	toolId: string,
	args: Record<string, unknown>
): ResultAsync<MCPPreflightResult, ApiError> {
	return apiRequest<MCPPreflightResult>('/v1/mcp/preflight', {
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
