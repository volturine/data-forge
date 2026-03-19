import {
	createSession,
	sendMessage,
	openEventStream,
	getHistory,
	closeSession,
	updateSession,
	listModels,
	listSessions
} from '$lib/api/chat';
import type { ChatEvent, OpenRouterModel, ChatSessionInfo } from '$lib/api/chat';
import { getSettings, updateSettings } from '$lib/api/settings';
import type { AppSettings } from '$lib/api/settings';
import { listTools } from '$lib/api/mcp';
import type { MCPTool } from '$lib/api/mcp';
import { SvelteSet, SvelteMap } from 'svelte/reactivity';

const SESSION_KEY = 'chat_session_id';
const PREFS_KEY = 'chat_prefs';
const MAX_BACKOFF = 30_000;
const BASE_BACKOFF = 1_000;
const MAX_RETRIES = 10;

export type AgentMode = 'plan' | 'execute';

const PLAN_SYSTEM_PROMPT =
	'You assist with a data pipeline platform (datasources, analyses, schedules, healthchecks, UDFs). ' +
	'You only have read-only tools. Analyze the request, inspect existing resources, and propose a step-by-step plan. ' +
	'Do NOT attempt to create or modify anything — only describe what you would do.';

const EXECUTE_SYSTEM_PROMPT =
	'You assist with a data pipeline platform (datasources, analyses, schedules, healthchecks, UDFs). ' +
	'Execute actions directly using the available tools. Be concise. Do not ask the user for IDs — look them up yourself. ' +
	'CRITICAL: Never invent IDs. Always GET existing resources first to obtain real IDs. ' +
	'Domain model: An analysis has tabs. Each tab reads from a datasource (input) and writes to a result (output). ' +
	'A "derived" tab reuses an existing tab\'s output result_id as its datasource.id (chaining tabs). ' +
	'A "raw" tab uses a regular datasource from GET /datasource. ' +
	'Workflow to add a derived tab to an existing analysis: ' +
	'1) GET /analysis/{id} to see current tabs and their output.result_id values. ' +
	"2) POST /analysis/{id}/tabs/{tab_id}/derive to create a new tab chained from an existing tab's output. " +
	'3) POST /analysis/{id}/tabs/{tab_id}/steps to add steps to the new tab. ' +
	'Do NOT use PUT /analysis/{id} — it requires a lock token.';

export type ConnectionStatus = 'connected' | 'reconnecting' | 'disconnected';

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant' | 'tool';
	content: string;
	ts: number;
}

export interface ToolCall {
	tool_id: string;
	method: string;
	path: string;
	args: Record<string, unknown>;
	status: 'running' | 'done' | 'error';
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
	mode = $state<AgentMode>('plan');
	settings = $state<AppSettings | null>(null);
	tools = $state<MCPTool[]>([]);
	models = $state<OpenRouterModel[]>([]);
	modelsLoading = $state(false);
	disabledTools = $state<SvelteSet<string>>(new SvelteSet());
	disabledTags = $state<SvelteSet<string>>(new SvelteSet());
	messages = $state<ChatMessage[]>([]);
	toolCalls = $state<ToolCall[]>([]);
	timeline = $state<TimelineEntry[]>([]);
	toolDrafts = $state<SvelteMap<string, ToolDraft>>(new SvelteMap());
	loading = $state(false);
	error = $state<string | null>(null);
	configured = $state(false);
	connection = $state<ConnectionStatus>('disconnected');
	confirmClose = $state(false);
	sessionUsage = $state<UsageInfo>({ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 });
	lastTurnUsage = $state<UsageInfo | null>(null);
	lastFailedContent = $state<string | null>(null);
	sessions = $state<ChatSessionInfo[]>([]);

	private _es: EventSource | null = null;
	private _counter = 0;
	private _retries = 0;
	private _retryTimer: ReturnType<typeof setTimeout> | null = null;

	private _onUnload = () => {
		this._clearRetry();
		this._es?.close();
		this._es = null;
	};

	constructor() {
		this._loadPrefs();
		if (typeof window !== 'undefined') {
			window.addEventListener('beforeunload', this._onUnload);
		}
	}

	private _loadPrefs(): void {
		if (typeof window === 'undefined') return;
		const raw = localStorage.getItem(PREFS_KEY);
		if (!raw) return;
		const prefs = JSON.parse(raw) as Record<string, unknown>;
		if (typeof prefs.model === 'string') this.model = prefs.model;
		if (typeof prefs.systemPrompt === 'string') this.systemPrompt = prefs.systemPrompt;
		if (prefs.mode === 'plan' || prefs.mode === 'execute') this.mode = prefs.mode;
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
				model: this.model,
				systemPrompt: this.systemPrompt,
				mode: this.mode,
				disabledTools: [...this.disabledTools],
				disabledTags: [...this.disabledTags]
			})
		);
	}

	private _id(): string {
		this._counter += 1;
		return String(this._counter);
	}

	get effectiveSystemPrompt(): string {
		if (this.systemPrompt) return this.systemPrompt;
		return this.mode === 'plan' ? PLAN_SYSTEM_PROMPT : EXECUTE_SYSTEM_PROMPT;
	}

	/** In plan mode, only safe (GET) tools; in execute mode, all enabled tools. */
	get modeFilteredTools(): MCPTool[] {
		const enabled = this.enabledTools;
		if (this.mode === 'plan') {
			return enabled.filter((t) => t.safety === 'safe');
		}
		return enabled;
	}

	get enabledTools(): MCPTool[] {
		return this.tools.filter((t) => {
			if (this.disabledTools.has(t.id)) return false;
			const tag = t.tags.length ? t.tags[0] : 'uncategorized';
			return !this.disabledTags.has(tag);
		});
	}

	get contextLimit(): number {
		const found = this.models.find((m) => m.id === this.model);
		return found?.context_length ?? 0;
	}

	private _groupByTag(tools: MCPTool[]): SvelteMap<string, MCPTool[]> {
		const groups = new SvelteMap<string, MCPTool[]>();
		for (const tool of tools) {
			const tag = tool.tags.length ? tool.tags[0] : 'uncategorized';
			const list = groups.get(tag) ?? [];
			list.push(tool);
			groups.set(tag, list);
		}
		return groups;
	}

	get tagGroups(): SvelteMap<string, MCPTool[]> {
		return this._groupByTag(this.tools);
	}

	get modeFilteredTagGroups(): SvelteMap<string, MCPTool[]> {
		const source =
			this.mode === 'plan' ? this.tools.filter((t) => t.safety === 'safe') : this.tools;
		return this._groupByTag(source);
	}

	setMode(mode: AgentMode): void {
		this.mode = mode;
		this._savePrefs();
	}

	async changeModel(modelId: string): Promise<void> {
		this.model = modelId;
		this._savePrefs();
		if (this.sessionId) {
			await updateSession(this.sessionId, { model: modelId });
		}
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
		const group = this.tagGroups.get(tag) ?? [];
		const allEnabled = group.every((t) => this.isToolEnabled(t.id));
		if (allEnabled) {
			this.disabledTags.add(tag);
		} else {
			this.disabledTags.delete(tag);
			for (const tool of group) {
				this.disabledTools.delete(tool.id);
			}
		}
		this._savePrefs();
	}

	isTagFullyEnabled(tag: string): boolean {
		const group = this.tagGroups.get(tag) ?? [];
		return group.length > 0 && group.every((t) => this.isToolEnabled(t.id));
	}

	isTagEnabled(tag: string): boolean {
		return !this.disabledTags.has(tag);
	}

	isToolEnabled(id: string): boolean {
		const tool = this.tools.find((t) => t.id === id);
		if (!tool) return false;
		if (this.disabledTools.has(id)) return false;
		const tag = tool.tags.length ? tool.tags[0] : 'uncategorized';
		return !this.disabledTags.has(tag);
	}

	async loadContext(): Promise<void> {
		const [settingsResult, toolsResult] = await Promise.all([getSettings(), listTools()]);
		settingsResult.match(
			(s) => {
				this.settings = s;
				if (s.openrouter_api_key) this.apiKey = s.openrouter_api_key;
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

	async loadSessions(): Promise<void> {
		const result = await listSessions();
		result.match(
			(s) => {
				this.sessions = s;
			},
			() => {}
		);
	}

	async configure(apiKey: string): Promise<void> {
		this.apiKey = apiKey;
		this.configured = true;
		this.error = null;
		this._savePrefs();
		await updateSettings({ openrouter_api_key: apiKey });
	}

	async startSession(): Promise<void> {
		this.error = null;
		const result = await createSession(
			this.provider,
			this.model,
			this.apiKey || undefined,
			this.effectiveSystemPrompt
		);
		result.match(
			(s) => {
				this.sessionId = s.session_id;
				if (typeof window !== 'undefined') {
					localStorage.setItem(SESSION_KEY, s.session_id);
				}
				this._connectStream(s.session_id);
				void this.loadSessions();
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
				this.sessionUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
				this.lastTurnUsage = null;

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
				this.error = null;
				return false;
			}
		);
	}

	async open_panel(): Promise<void> {
		this.open = true;
		await this.loadContext();
		void this.loadSessions();
		if (this.apiKey && this.models.length === 0) {
			void this.loadModels();
		}
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
			try {
				const event: ChatEvent = JSON.parse(ev.data as string);
				this._handleEvent(event);
			} catch {
				console.error('[chat] failed to parse SSE event:', ev.data);
			}
		};
		this._es.onerror = () => {
			this.connection = 'reconnecting';
			this._es?.close();
			this._es = null;
			this._scheduleReconnect();
		};
	}

	private _scheduleReconnect(): void {
		this._retries += 1;
		if (this._retries > MAX_RETRIES) {
			this.connection = 'disconnected';
			this.error = 'Connection lost. Please refresh or start a new session.';
			return;
		}
		const delay = Math.min(BASE_BACKOFF * Math.pow(2, this._retries - 1), MAX_BACKOFF);
		this._retryTimer = setTimeout(() => {
			if (!this.sessionId) return;
			this._connectStream(this.sessionId);
		}, delay);
	}

	private _clearRetry(): void {
		if (this._retryTimer) {
			clearTimeout(this._retryTimer);
			this._retryTimer = null;
		}
	}

	private static _stripPageContext(content: string): string {
		return content.replace(/^\[user is viewing [^\]]*\]\n?/, '');
	}

	private _handleEvent(event: ChatEvent): void {
		if (event.type === 'message' && event.role && event.content !== undefined) {
			const displayContent =
				event.role === 'user'
					? ChatStore._stripPageContext(event.content ?? '')
					: (event.content ?? '');
			const msg: ChatMessage = {
				id: this._id(),
				role: event.role,
				content: displayContent,
				ts: event.ts ?? Date.now()
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
		if (event.type === 'tool_result' && event.tool_id) {
			this._updateToolStatus(event.tool_id, 'done', event.result);
		}
		if (event.type === 'tool_error' && event.tool_id) {
			const errors = event.errors ?? [];
			this._updateToolStatus(event.tool_id, 'error', undefined, errors);
			const summary =
				event.errors && event.errors.length > 0
					? event.errors.map((e) => `${e.path}: ${e.message}`).join('\n')
					: 'Validation failed';
			const msg: ChatMessage = {
				id: this._id(),
				role: 'tool',
				content: summary,
				ts: event.ts ?? Date.now()
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

	private _updateToolStatus(
		toolId: string,
		status: 'done' | 'error',
		result?: unknown,
		errors?: { path: string; message: string }[]
	): void {
		// Update in toolCalls array
		const tc = this.toolCalls.findLast((t) => t.tool_id === toolId && t.status === 'running');
		if (tc) {
			tc.status = status;
			if (result !== undefined) tc.result = result;
			if (errors) tc.errors = errors;
		}
		// Also update through timeline proxy to ensure reactivity in both arrays
		for (let i = this.timeline.length - 1; i >= 0; i--) {
			const entry = this.timeline[i];
			if (
				entry.kind === 'tool' &&
				entry.item.tool_id === toolId &&
				entry.item.status === 'running'
			) {
				entry.item.status = status;
				if (result !== undefined) entry.item.result = result;
				if (errors) entry.item.errors = errors;
				break;
			}
		}
	}

	private _applyUiPatch(event: ChatEvent): void {
		if (typeof window === 'undefined') return;
		window.dispatchEvent(new CustomEvent('chat:ui_patch', { detail: event }));
	}

	private _pageContext(): string {
		if (typeof window === 'undefined') return '';
		const path = window.location.pathname;
		if (path === '/' || !path) return '';
		return `[user is viewing ${path}]\n`;
	}

	async send(content: string): Promise<boolean> {
		this.loading = true;
		this.error = null;
		this.lastFailedContent = null;
		if (!this.sessionId) {
			await this.startSession();
			if (!this.sessionId) {
				this.loading = false;
				this.lastFailedContent = content;
				return false;
			}
		}
		const ids = this.modeFilteredTools.map((t) => t.id);
		const messageContent = this._pageContext() + content;
		const result = await sendMessage(this.sessionId, messageContent, ids);
		return result.match(
			() => {
				this.lastFailedContent = null;
				return true;
			},
			(e) => {
				this.error = e.message;
				this.lastFailedContent = content;
				this.loading = false;
				return false;
			}
		);
	}

	dismissError(): void {
		this.error = null;
	}

	async retry(): Promise<boolean> {
		if (!this.lastFailedContent) return false;
		const content = this.lastFailedContent;
		this.lastFailedContent = null;
		return this.send(content);
	}

	get modelDisplayName(): string {
		const found = this.models.find((m) => m.id === this.model);
		if (found) return found.name;
		const parts = this.model.split('/');
		return parts[parts.length - 1];
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
		this._updateToolStatus(toolId, 'done', result);
	}

	setLocalToolError(toolId: string, errors: { path: string; message: string }[]): void {
		this._updateToolStatus(toolId, 'error', undefined, errors);
	}

	requestCloseSession(): void {
		if (!this.sessionId) return;
		this.confirmClose = true;
	}

	cancelCloseSession(): void {
		this.confirmClose = false;
	}

	private _disconnectStream(): void {
		this._clearRetry();
		if (this._es) {
			this._es.close();
			this._es = null;
		}
		this.connection = 'disconnected';
	}

	private _resetState(): void {
		this.sessionId = null;
		this.messages = [];
		this.toolCalls = [];
		this.timeline = [];
		this.toolDrafts = new SvelteMap();
		this.loading = false;
		this.error = null;
		this.lastFailedContent = null;
		this.sessionUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
		this.lastTurnUsage = null;
		if (typeof window !== 'undefined') {
			localStorage.removeItem(SESSION_KEY);
		}
	}

	/** Start a fresh session without deleting the current one. */
	async newSession(): Promise<void> {
		this._disconnectStream();
		this._resetState();
		void this.loadSessions();
	}

	/** Delete a session by ID (from session history). */
	async deleteSession(sessionId: string): Promise<void> {
		await closeSession(sessionId);
		if (this.sessionId === sessionId) {
			await this.newSession();
		}
		this.sessions = this.sessions.filter((s) => s.id !== sessionId);
	}

	async closeSession(): Promise<void> {
		this.confirmClose = false;
		this._disconnectStream();
		if (this.sessionId) {
			await closeSession(this.sessionId);
		}
		this._resetState();
		void this.loadSessions();
	}

	close(): void {
		this._disconnectStream();
		this.open = false;
	}

	reset(): void {
		this.close();
		this._resetState();
	}
}

export const chatStore = new ChatStore();
