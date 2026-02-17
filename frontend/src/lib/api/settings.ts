import { apiRequest } from './client';
import type { ApiError } from './client';
import { ResultAsync } from 'neverthrow';

export interface AppSettings {
	smtp_host: string;
	smtp_port: number;
	smtp_user: string;
	smtp_password: string;
	telegram_bot_token: string;
	telegram_bot_enabled: boolean;
	public_idb_debug: boolean;
}

export interface TestResult {
	success: boolean;
	message: string;
}

export function getSettings(): ResultAsync<AppSettings, ApiError> {
	return apiRequest<AppSettings>('/v1/settings');
}

export function updateSettings(data: AppSettings): ResultAsync<AppSettings, ApiError> {
	return apiRequest<AppSettings>('/v1/settings', {
		method: 'PUT',
		body: JSON.stringify(data)
	});
}

export function testSmtp(to: string): ResultAsync<TestResult, ApiError> {
	return apiRequest<TestResult>('/v1/settings/test-smtp', {
		method: 'POST',
		body: JSON.stringify({ to })
	});
}

export interface TelegramChat {
	chat_id: string;
	title: string;
}

export interface DetectTelegramResponse {
	success: boolean;
	message: string;
	chats: TelegramChat[];
}

export function detectCustomBotChat(token: string): ResultAsync<DetectTelegramResponse, ApiError> {
	return apiRequest<DetectTelegramResponse>('/v1/settings/detect-chat-custom', {
		method: 'POST',
		body: JSON.stringify({ bot_token: token })
	});
}

// Telegram bot status & subscriber management

export interface BotStatus {
	running: boolean;
	token_configured: boolean;
	subscriber_count: number;
}

export interface Subscriber {
	id: number;
	chat_id: string;
	title: string;
	bot_token: string;
	is_active: boolean;
	subscribed_at: string;
}

export function getBotStatus(): ResultAsync<BotStatus, ApiError> {
	return apiRequest<BotStatus>('/v1/telegram/status');
}

export function getSubscribers(): ResultAsync<Subscriber[], ApiError> {
	return apiRequest<Subscriber[]>('/v1/telegram/subscribers');
}

export function deleteSubscriber(id: number): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/telegram/subscribers/${id}`, { method: 'DELETE' });
}
