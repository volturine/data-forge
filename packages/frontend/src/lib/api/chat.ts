import { apiRequest, buildBackendUrl } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import { createOwnedEventSource } from './websocket';

export interface ChatSession {
	session_id: string;
	model: string;
	provider: string;
}

export interface ChatHistoryResponse {
	session_id: string;
	history: ChatEvent[];
}

export interface ChatMessageEvent {
	type: 'message';
	role: 'user' | 'assistant';
	content: string;
	ts?: number;
}

export interface ChatToolCallEvent {
	type: 'tool_call';
	tool_id: string;
	method: string;
	path: string;
	args: Record<string, unknown>;
	confirm_required?: boolean;
}

export interface ChatToolStartEvent {
	type: 'tool_start';
	tool_id: string;
	ts?: number;
}

export interface ChatToolResultEvent {
	type: 'tool_result';
	tool_id: string;
	result: { status: number; body: unknown; ok: boolean };
	duration_ms?: number;
}

export interface ChatToolErrorEvent {
	type: 'tool_error';
	tool_id: string;
	errors: { path: string; message: string }[];
	ts?: number;
	duration_ms?: number;
}

export interface ChatToolConfirmEvent {
	type: 'tool_confirm';
	tool_id: string;
	method: string;
	path: string;
	args: Record<string, unknown>;
}

export interface ChatTurnStartEvent {
	type: 'turn_start';
	turn: number;
	max_turns: number | null;
}

export interface ChatUiPatchEvent {
	type: 'ui_patch';
	resource?: string;
	action?: string;
	id?: string;
	data?: unknown;
}

export interface ChatUsageEvent {
	type: 'usage';
	prompt_tokens: number;
	completion_tokens: number;
	total_tokens: number;
}

export interface ChatDoneEvent {
	type: 'done';
}

export interface ChatErrorEvent {
	type: 'error';
	content: string;
}

export type ChatEvent =
	| ChatMessageEvent
	| ChatToolCallEvent
	| ChatToolStartEvent
	| ChatToolResultEvent
	| ChatToolErrorEvent
	| ChatToolConfirmEvent
	| ChatTurnStartEvent
	| ChatUiPatchEvent
	| ChatUsageEvent
	| ChatDoneEvent
	| ChatErrorEvent;

export interface SessionActionResponse {
	status: string;
	session_id: string;
}

export interface ConfirmToolResponse {
	status: string;
	approved: boolean;
}

export interface CreateSessionPayload {
	provider: string;
	model: string;
	api_key?: string;
	system_prompt?: string;
}

export interface SendMessagePayload {
	session_id: string;
	content: string;
	tool_ids?: string[];
}

export interface UpdateSessionPayload {
	provider?: string;
	model?: string;
	system_prompt?: string;
	api_key?: string;
}

export interface ChatModel {
	id: string;
	name: string;
	context_length: number;
}

export interface ChatSessionInfo {
	id: string;
	model: string;
	provider: string;
	created_at: number;
	preview: string;
}

export function createSession(
	provider: string,
	model: string,
	apiKey: string,
	systemPrompt?: string
): ResultAsync<ChatSession, ApiError> {
	const payload: CreateSessionPayload = { provider, model, api_key: apiKey };
	if (systemPrompt) payload.system_prompt = systemPrompt;
	return apiRequest<ChatSession>('/v1/ai/chat/sessions', {
		method: 'POST',
		body: JSON.stringify(payload)
	});
}

export function sendMessage(
	sessionId: string,
	content: string,
	toolIds?: string[]
): ResultAsync<SessionActionResponse, ApiError> {
	const payload: SendMessagePayload = { session_id: sessionId, content };
	if (toolIds && toolIds.length > 0) payload.tool_ids = toolIds;
	return apiRequest<SessionActionResponse>('/v1/ai/chat/message', {
		method: 'POST',
		body: JSON.stringify(payload)
	});
}

export function getHistory(sessionId: string): ResultAsync<ChatHistoryResponse, ApiError> {
	return apiRequest<ChatHistoryResponse>(`/v1/ai/chat/history/${sessionId}`);
}

export function updateSession(
	sessionId: string,
	updates: UpdateSessionPayload
): ResultAsync<ChatSession, ApiError> {
	return apiRequest<ChatSession>(`/v1/ai/chat/sessions/${sessionId}`, {
		method: 'PATCH',
		body: JSON.stringify(updates)
	});
}

export function stopGeneration(sessionId: string): ResultAsync<SessionActionResponse, ApiError> {
	return apiRequest<SessionActionResponse>(`/v1/ai/chat/sessions/${sessionId}/stop`, {
		method: 'POST'
	});
}

export function confirmTool(
	sessionId: string,
	approved: boolean
): ResultAsync<ConfirmToolResponse, ApiError> {
	return apiRequest<ConfirmToolResponse>(`/v1/ai/chat/sessions/${sessionId}/confirm`, {
		method: 'POST',
		body: JSON.stringify({ approved })
	});
}

export function closeSession(sessionId: string): ResultAsync<SessionActionResponse, ApiError> {
	return apiRequest<SessionActionResponse>(`/v1/ai/chat/sessions/${sessionId}`, {
		method: 'DELETE'
	});
}

export function listModels(
	provider: string,
	apiKey: string,
	endpointUrl?: string,
	organizationId?: string
): ResultAsync<ChatModel[], ApiError> {
	const body: Record<string, string> = { provider, api_key: apiKey };
	if (endpointUrl) body.endpoint_url = endpointUrl;
	if (organizationId) body.organization_id = organizationId;
	return apiRequest<ChatModel[]>('/v1/ai/chat/models', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}

export function listSessions(): ResultAsync<ChatSessionInfo[], ApiError> {
	return apiRequest<ChatSessionInfo[]>('/v1/ai/chat/sessions');
}

export function openEventStream(sessionId: string): EventSource {
	return createOwnedEventSource(buildBackendUrl(`/v1/ai/chat/stream/${sessionId}`));
}
