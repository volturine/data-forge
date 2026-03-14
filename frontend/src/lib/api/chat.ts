import { apiRequest } from '$lib/api/client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from '$lib/api/client';

export interface ChatSession {
	session_id: string;
	model: string;
	provider: string;
}

export interface ChatHistoryResponse {
	session_id: string;
	history: ChatEvent[];
}

export interface ChatEvent {
	type:
		| 'message'
		| 'tool_call'
		| 'pending'
		| 'tool_result'
		| 'tool_error'
		| 'ui_patch'
		| 'usage'
		| 'done'
		| 'error';
	role?: 'user' | 'assistant';
	content?: string;
	tool_id?: string;
	method?: string;
	path?: string;
	args?: Record<string, unknown>;
	token?: string;
	confirm_required?: boolean;
	result?: { status: number; body: unknown; ok: boolean };
	errors?: { path: string; message: string }[];
	resource?: string;
	action?: string;
	id?: string;
	data?: unknown;
	prompt_tokens?: number;
	completion_tokens?: number;
	total_tokens?: number;
}

export interface ApplyResult {
	status: 'executed';
	result: { status: number; body: unknown; ok: boolean };
	patch: { resource: string; action: string; id?: string; data?: unknown } | null;
}

export function createSession(
	provider: string,
	model: string,
	apiKey?: string,
	systemPrompt?: string
): ResultAsync<ChatSession, ApiError> {
	const body: Record<string, string> = { provider, model };
	if (apiKey) body.api_key = apiKey;
	if (systemPrompt) body.system_prompt = systemPrompt;
	return apiRequest<ChatSession>('/v1/ai/chat/sessions', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}

export function sendMessage(
	sessionId: string,
	content: string,
	toolIds?: string[]
): ResultAsync<{ status: string; session_id: string }, ApiError> {
	const payload: Record<string, unknown> = { session_id: sessionId, content };
	if (toolIds && toolIds.length > 0) payload.tool_ids = toolIds;
	return apiRequest('/v1/ai/chat/message', {
		method: 'POST',
		body: JSON.stringify(payload)
	});
}

export function applyPending(sessionId: string, token: string): ResultAsync<ApplyResult, ApiError> {
	return apiRequest<ApplyResult>('/v1/ai/chat/apply', {
		method: 'POST',
		body: JSON.stringify({ session_id: sessionId, token })
	});
}

export function getHistory(sessionId: string): ResultAsync<ChatHistoryResponse, ApiError> {
	return apiRequest<ChatHistoryResponse>(`/v1/ai/chat/history/${sessionId}`);
}

export function closeSession(
	sessionId: string
): ResultAsync<{ status: string; session_id: string }, ApiError> {
	return apiRequest(`/v1/ai/chat/sessions/${sessionId}`, { method: 'DELETE' });
}

export interface OpenRouterModel {
	id: string;
	name: string;
	context_length: number;
}

export function listModels(apiKey?: string): ResultAsync<OpenRouterModel[], ApiError> {
	const params = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : '';
	return apiRequest<OpenRouterModel[]>(`/v1/ai/chat/models${params}`);
}

export function openEventStream(sessionId: string): EventSource {
	return new EventSource(`/api/v1/ai/chat/stream/${sessionId}`);
}
