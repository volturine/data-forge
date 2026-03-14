import {
	createSession,
	sendMessage,
	applyPending,
	openEventStream,
	getHistory,
	closeSession,
	listModels
} from '$lib/api/chat';
import type { ChatEvent, ApplyResult, OpenRouterModel } from '$lib/api/chat';
import { getSettings } from '$lib/api/settings';
import type { AppSettings } from '$lib/api/settings';
import { listTools } from '$lib/api/mcp';
import type { MCPTool } from '$lib/api/mcp';
import { SvelteSet, SvelteMap } from 'svelte/reactivity';

const SESSION_KEY = 'chat_session_id';
const PREFS_KEY = 'chat_prefs';
const MAX_BACKOFF = 30_000;
const BASE_BACKOFF = 1_000;

export type ConnectionStatus = 'connected' | 'reconnecting' | 'disconnected';

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant' | 'tool';
	content: string;
	ts: number;
}

export interface PendingAction {
	token: string;
	tool_id: string;
	method: string;
	path: string;
	args: Record<string, unknown>;
	confirm_required: boolean;
}

export interface ToolCall {
	tool_id: string;
	method: string;
	path: string;
	args: Record<string, unknown>;
	status: 'running' | 'done' | 'pending' | 'error';
	result?: unknown;
	errors?: { path: string; message: string }[];
	expanded: boolean;
}

export interface UsageInfo {
	prompt_tokens: number;
	completion_tokens: number;
	total_tokens: number;
}

export type TimelineEntry =
	| { kind: 'message'; item: ChatMessage }
	| { kind: 'tool'; item: ToolCall };

export interface ToolDraft {
	args: Record<string, unknown>;
	errors: { path: string; message: string }[];
}

export class ChatStore {
	open = $state(false);
	sessionId = $state<string | null>(null);
	provider = $state('openrouter');
	model = $state('openai/gpt-4o-mini');
	apiKey = $state('');
	systemPrompt = $state('');
	settings = $state<AppSettings | null>(null);
	tools = $state<MCPTool[]>([]);
	models = $state<OpenRouterModel[]>([]);
	modelsLoading = $state(false);
	disabledTools = $state<SvelteSet<string>>(new SvelteSet());
	disabledTags = $state<SvelteSet<string>>(new SvelteSet());
	messages = $state<ChatMessage[]>([]);
	toolCalls = $state<ToolCall[]>([]);
	timeline = $state<TimelineEntry[]>([]);
	pending = $state<PendingAction[]>([]);
	toolDrafts = $state<SvelteMap<string, ToolDraft>>(new SvelteMap());
	loading = $state(false);
	error = $state<string | null>(null);
	configured = $state(false);
	connection = $state<ConnectionStatus>('disconnected');
	confirmClose = $state(false);
	sessionUsage = $state<UsageInfo>({ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 });
	lastTurnUsage = $state<UsageInfo | null>(null);

	private _es: EventSource | null = null;
	private _counter = 0;
	private _retries = 0;
	private _retryTimer: ReturnType<typeof setTimeout> | null = null;

	constructor() {
		this._loadPrefs();
	}

	private _loadPrefs(): void {
		if (typeof window === 'undefined') return;
		const raw = localStorage.getItem(PREFS_KEY);
		if (!raw) return;
		const prefs = JSON.parse(raw) as Record<string, unknown>;
		if (typeof prefs.apiKey === 'string') this.apiKey = prefs.apiKey;
		if (typeof prefs.model === 'string') this.model = prefs.model;
		if (typeof prefs.systemPrompt === 'string') this.systemPrompt = prefs.systemPrompt;
		if (Array.isArray(prefs.disabledTools)) {
			this.disabledTools = new SvelteSet(prefs.disabledTools as string[]);
		}
		if (Array.isArray(prefs.disabledTags)) {
			this.disabledTags = new SvelteSet(prefs.disabledTags as string[]);
		}
	}

	private _savePrefs(): void {
		if (typeof window === 'undefined') return;
		localStorage.setItem(
			PREFS_KEY,
			JSON.stringify({
				apiKey: this.apiKey,
				model: this.model,
				systemPrompt: this.systemPrompt,
				disabledTools: [...this.disabledTools],
				disabledTags: [...this.disabledTags]
			})
		);
	}

	private _id(): string {
		this._counter += 1;
		return String(this._counter);
	}

	get enabledTools(): MCPTool[] {
		return this.tools.filter(
			(t) => !this.disabledTools.has(t.id) && !t.tags.some((tag) => this.disabledTags.has(tag))
		);
	}

	get contextLimit(): number {
		const found = this.models.find((m) => m.id === this.model);
		return found?.context_length ?? 0;
	}

	get tagGroups(): SvelteMap<string, MCPTool[]> {
		const groups = new SvelteMap<string, MCPTool[]>();
		for (const tool of this.tools) {
			const tags = tool.tags.length ? tool.tags : ['uncategorized'];
			for (const tag of tags) {
				const list = groups.get(tag) ?? [];
				list.push(tool);
				groups.set(tag, list);
			}
		}
		return groups;
	}

	toggleTool(id: string): void {
		if (this.disabledTools.has(id)) {
			this.disabledTools.delete(id);
		} else {
			this.disabledTools.add(id);
		}
		this._savePrefs();
	}

	toggleTag(tag: string): void {
		if (this.disabledTags.has(tag)) {
			this.disabledTags.delete(tag);
		} else {
			this.disabledTags.add(tag);
		}
		this._savePrefs();
	}

	isTagEnabled(tag: string): boolean {
		return !this.disabledTags.has(tag);
	}

	isToolEnabled(id: string): boolean {
		const tool = this.tools.find((t) => t.id === id);
		if (!tool) return false;
		if (this.disabledTools.has(id)) return false;
		return !tool.tags.some((t) => this.disabledTags.has(t));
	}

	async loadContext(): Promise<void> {
		const [settingsResult, toolsResult] = await Promise.all([getSettings(), listTools()]);
		settingsResult.match(
			(s) => {
				this.settings = s;
				if (!this.apiKey && s.openrouter_api_key) this.apiKey = s.openrouter_api_key;
				this.configured = true;
			},
			() => {}
		);
		toolsResult.match(
			(t) => {
				this.tools = t;
			},
			() => {}
		);
	}

	async loadModels(): Promise<void> {
		this.modelsLoading = true;
		const result = await listModels(this.apiKey || undefined);
		result.match(
			(m) => {
				this.models = m;
			},
			() => {}
		);
		this.modelsLoading = false;
	}

	configure(apiKey: string): void {
		this.apiKey = apiKey;
		this.configured = true;
		this.error = null;
		this._savePrefs();
	}

	async startSession(): Promise<void> {
		this.error = null;
		const result = await createSession(
			this.provider,
			this.model,
			this.apiKey || undefined,
			this.systemPrompt || undefined
		);
		result.match(
			(s) => {
				this.sessionId = s.session_id;
				if (typeof window !== 'undefined') {
					localStorage.setItem(SESSION_KEY, s.session_id);
				}
				this._connectStream(s.session_id);
			},
			(e) => {
				this.error = e.message;
			}
		);
	}

	async resumeSession(sessionId: string): Promise<boolean> {
		const result = await getHistory(sessionId);
		return result.match(
			(data) => {
				this.sessionId = sessionId;
				this.messages = [];
				this.toolCalls = [];
				this.timeline = [];
				this.pending = [];
				for (const event of data.history) {
					this._handleEvent(event);
				}
				this._connectStream(sessionId);
				return true;
			},
			() => {
				if (typeof window !== 'undefined') {
					localStorage.removeItem(SESSION_KEY);
				}
				return false;
			}
		);
	}

	async open_panel(): Promise<void> {
		this.open = true;
		await this.loadContext();
		if (this.sessionId) return;
		if (!this.apiKey) {
			if (typeof window !== 'undefined') localStorage.removeItem(SESSION_KEY);
			return;
		}
		const stored = typeof window !== 'undefined' ? localStorage.getItem(SESSION_KEY) : null;
		if (stored) {
			await this.resumeSession(stored);
		}
	}

	private _connectStream(sid: string): void {
		this._clearRetry();
		if (this._es) {
			this._es.close();
		}
		this._es = openEventStream(sid);
		this._es.onopen = () => {
			this.connection = 'connected';
			this._retries = 0;
			this.error = null;
		};
		this._es.onmessage = (ev) => {
			const event: ChatEvent = JSON.parse(ev.data as string);
			this._handleEvent(event);
		};
		this._es.onerror = () => {
			this.connection = 'reconnecting';
			this._es?.close();
			this._es = null;
			this._scheduleReconnect(sid);
		};
	}

	private _scheduleReconnect(sid: string): void {
		this._retries += 1;
		const delay = Math.min(BASE_BACKOFF * Math.pow(2, this._retries - 1), MAX_BACKOFF);
		this._retryTimer = setTimeout(() => {
			if (!this.sessionId) return;
			this._connectStream(sid);
		}, delay);
	}

	private _clearRetry(): void {
		if (this._retryTimer) {
			clearTimeout(this._retryTimer);
			this._retryTimer = null;
		}
	}

	private _handleEvent(event: ChatEvent): void {
		if (event.type === 'message' && event.role && event.content !== undefined) {
			const msg: ChatMessage = {
				id: this._id(),
				role: event.role,
				content: event.content ?? '',
				ts: Date.now()
			};
			this.messages.push(msg);
			this.timeline.push({ kind: 'message', item: msg });
		}
		if (event.type === 'tool_call' && event.tool_id) {
			const tc: ToolCall = {
				tool_id: event.tool_id,
				method: event.method ?? '',
				path: event.path ?? '',
				args: event.args ?? {},
				status: 'running',
				expanded: false
			};
			this.toolCalls.push(tc);
			this.timeline.push({ kind: 'tool', item: tc });
		}
		if (event.type === 'pending' && event.token && event.tool_id) {
			const existing = this.toolCalls.find(
				(t) => t.tool_id === event.tool_id && t.status === 'running'
			);
			if (existing) existing.status = 'pending';
			this.pending.push({
				token: event.token,
				tool_id: event.tool_id,
				method: event.method ?? '',
				path: event.path ?? '',
				args: event.args ?? {},
				confirm_required: event.confirm_required ?? false
			});
		}
		if (event.type === 'tool_result' && event.tool_id) {
			const tc = this.toolCalls.find((t) => t.tool_id === event.tool_id && t.status !== 'done');
			if (tc) {
				tc.status = 'done';
				tc.result = event.result;
			}
			this.pending = this.pending.filter((p) => p.tool_id !== event.tool_id);
		}
		if (event.type === 'tool_error' && event.tool_id) {
			const tc = this.toolCalls.find(
				(t) => t.tool_id === event.tool_id && t.status !== 'done' && t.status !== 'error'
			);
			if (tc) {
				tc.status = 'error';
				tc.errors = event.errors ?? [];
			}
			this.pending = this.pending.filter((p) => p.tool_id !== event.tool_id);
			const summary =
				event.errors && event.errors.length > 0
					? event.errors.map((e) => `${e.path}: ${e.message}`).join('\n')
					: 'Validation failed';
			const msg: ChatMessage = {
				id: this._id(),
				role: 'tool',
				content: summary,
				ts: Date.now()
			};
			this.messages.push(msg);
			this.timeline.push({ kind: 'message', item: msg });
			this.loading = false;
		}
		if (event.type === 'ui_patch') {
			this._applyUiPatch(event);
		}
		if (event.type === 'usage') {
			const turn: UsageInfo = {
				prompt_tokens: event.prompt_tokens ?? 0,
				completion_tokens: event.completion_tokens ?? 0,
				total_tokens: event.total_tokens ?? 0
			};
			this.lastTurnUsage = turn;
			this.sessionUsage = {
				prompt_tokens: this.sessionUsage.prompt_tokens + turn.prompt_tokens,
				completion_tokens: this.sessionUsage.completion_tokens + turn.completion_tokens,
				total_tokens: this.sessionUsage.total_tokens + turn.total_tokens
			};
		}
		if (event.type === 'error' && event.content) {
			this.error = event.content;
		}
		if (event.type === 'done') {
			this.loading = false;
		}
	}

	private _applyUiPatch(event: ChatEvent): void {
		if (typeof window === 'undefined') return;
		window.dispatchEvent(new CustomEvent('chat:ui_patch', { detail: event }));
	}

	async send(content: string): Promise<void> {
		if (!this.sessionId) {
			await this.startSession();
			if (!this.sessionId) return;
		}
		this.loading = true;
		this.error = null;
		const ids = this.enabledTools.map((t) => t.id);
		const result = await sendMessage(this.sessionId, content, ids);
		result.mapErr((e) => {
			this.error = e.message;
			this.loading = false;
		});
	}

	async apply(token: string): Promise<ApplyResult | null> {
		if (!this.sessionId) return null;
		const entry = this.pending.find((p) => p.token === token);
		const result = await applyPending(this.sessionId, token);
		return result.match(
			(r) => {
				this.pending = this.pending.filter((p) => p.token !== token);
				if (entry) {
					const tc = this.toolCalls.find((t) => t.tool_id === entry.tool_id && t.status !== 'done');
					if (tc) tc.status = 'done';
				}
				if (r.patch) {
					this._applyUiPatch({ type: 'ui_patch', ...r.patch });
				}
				return r;
			},
			(e) => {
				this.error = e.message;
				return null;
			}
		);
	}

	dismiss(token: string): void {
		this.pending = this.pending.filter((p) => p.token !== token);
	}

	removePendingByToolId(toolId: string): void {
		this.pending = this.pending.filter((p) => p.tool_id !== toolId);
	}

	ensureDraft(toolId: string, args: Record<string, unknown>): void {
		if (!this.toolDrafts.has(toolId)) {
			this.toolDrafts.set(toolId, { args: { ...args }, errors: [] });
		}
	}

	updateDraft(toolId: string, args: Record<string, unknown>): void {
		const existing = this.toolDrafts.get(toolId);
		this.toolDrafts.set(toolId, { args, errors: existing?.errors ?? [] });
	}

	setDraftErrors(toolId: string, errors: { path: string; message: string }[]): void {
		const existing = this.toolDrafts.get(toolId);
		this.toolDrafts.set(toolId, { args: existing?.args ?? {}, errors });
	}

	clearDraft(toolId: string): void {
		this.toolDrafts.delete(toolId);
	}

	addLocalToolCall(
		toolId: string,
		method: string,
		path: string,
		args: Record<string, unknown>
	): ToolCall {
		const tc: ToolCall = {
			tool_id: toolId,
			method,
			path,
			args,
			status: 'running',
			expanded: false
		};
		this.toolCalls.push(tc);
		this.timeline.push({ kind: 'tool', item: tc });
		return tc;
	}

	setLocalToolResult(toolId: string, result: unknown): void {
		const tc = this.toolCalls.findLast(
			(t) => t.tool_id === toolId && t.status !== 'done' && t.status !== 'error'
		);
		if (!tc) return;
		tc.status = 'done';
		tc.result = result;
	}

	setLocalToolError(toolId: string, errors: { path: string; message: string }[]): void {
		const tc = this.toolCalls.findLast(
			(t) => t.tool_id === toolId && t.status !== 'done' && t.status !== 'error'
		);
		if (!tc) return;
		tc.status = 'error';
		tc.errors = errors;
	}

	requestCloseSession(): void {
		if (!this.sessionId) return;
		this.confirmClose = true;
	}

	cancelCloseSession(): void {
		this.confirmClose = false;
	}

	async closeSession(): Promise<void> {
		this.confirmClose = false;
		this._clearRetry();
		if (this._es) {
			this._es.close();
			this._es = null;
		}
		this.connection = 'disconnected';
		if (this.sessionId) {
			await closeSession(this.sessionId);
		}
		this.sessionId = null;
		this.messages = [];
		this.toolCalls = [];
		this.timeline = [];
		this.pending = [];
		this.toolDrafts = new SvelteMap();
		this.loading = false;
		this.error = null;
		this.sessionUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
		this.lastTurnUsage = null;
		if (typeof window !== 'undefined') {
			localStorage.removeItem(SESSION_KEY);
		}
	}

	close(): void {
		this._clearRetry();
		this._es?.close();
		this._es = null;
		this.open = false;
		this.connection = 'disconnected';
	}

	reset(): void {
		this.close();
		this.sessionId = null;
		this.messages = [];
		this.toolCalls = [];
		this.timeline = [];
		this.pending = [];
		this.toolDrafts = new SvelteMap();
		this.loading = false;
		this.error = null;
		this.sessionUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
		this.lastTurnUsage = null;
		if (typeof window !== 'undefined') {
			localStorage.removeItem(SESSION_KEY);
		}
	}
}

export const chatStore = new ChatStore();
