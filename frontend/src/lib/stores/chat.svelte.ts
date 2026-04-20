import {
	createSession,
	sendMessage,
	openEventStream,
	getHistory,
	closeSession,
	updateSession,
	listModels,
	listSessions,
	confirmTool
} from '$lib/api/chat';
import type { ChatEvent, ChatUiPatchEvent, ChatModel, ChatSessionInfo } from '$lib/api/chat';
import { getSettings, updateSettings, isMasked } from '$lib/api/settings';
import type { AppSettings } from '$lib/api/settings';
import { listTools } from '$lib/api/mcp';
import type { MCPTool } from '$lib/api/mcp';
import { analysisStore } from '$lib/stores/analysis.svelte';
import { schemaStore } from '$lib/stores/schema.svelte';
import type { Schema } from '$lib/types/schema';
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
	'Do NOT use PUT /analysis/{id} — use the dedicated tab/step endpoints instead.';

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
	status: 'running' | 'done' | 'error' | 'confirming';
	result?: unknown;
	errors?: { path: string; message: string }[];
	expanded: boolean;
	startedAt?: number;
	duration_ms?: number;
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
	endpointUrl = $state('');
	organizationId = $state('');
	systemPrompt = $state('');
	mode = $state<AgentMode>('plan');
	settings = $state<AppSettings | null>(null);
	tools = $state<MCPTool[]>([]);
	models = $state<ChatModel[]>([]);
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
	currentTurn = $state(0);
	maxTurns = $state<number | null>(null);
	pendingConfirm = $state<{
		tool_id: string;
		method: string;
		path: string;
		args: Record<string, unknown>;
	} | null>(null);

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
			this.disabledTools = new SvelteSet(
				prefs.disabledTools.filter((x): x is string => typeof x === 'string')
			);
		}
		if (Array.isArray(prefs.disabledTags)) {
			this.disabledTags = new SvelteSet(
				prefs.disabledTags.filter((x): x is string => typeof x === 'string')
			);
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
				this._applyProviderDefaults();
			},
			(e) => {
				this.error = e.message;
			}
		);
		toolsResult.match(
			(t) => {
				this.tools = t;
			},
			(e) => {
				this.error = e.message;
			}
		);
	}

	async loadModels(): Promise<void> {
		this.modelsLoading = true;
		if (
			(this.provider === 'openrouter' || this.provider === 'huggingface') &&
			this.apiKey.length === 0
		) {
			this.models = [];
			this.modelsLoading = false;
			this.error = 'API key is required';
			return;
		}
		const result = await listModels(
			this.provider,
			this.apiKey,
			this.endpointUrl || undefined,
			this.organizationId || undefined
		);
		result.match(
			(m) => {
				this.error = null;
				this.models = m.map((item) => ({
					id: item.id || item.name,
					name: item.name || item.id,
					context_length: Number(item.context_length ?? 0)
				}));
			},
			(e) => {
				this.error = e.message;
			}
		);
		this.modelsLoading = false;
	}

	async loadSessions(): Promise<void> {
		const result = await listSessions();
		result.match(
			(s) => {
				this.sessions = s;
			},
			(e) => {
				this.error = e.message;
			}
		);
	}

	async configure(apiKey: string): Promise<void> {
		this.apiKey = apiKey;
		this._refreshConfigured();
		this.error = null;
		this._savePrefs();
		if (this.provider === 'openrouter') {
			await updateSettings({ openrouter_api_key: apiKey });
		} else if (this.provider === 'openai') {
			await updateSettings({ openai_api_key: apiKey });
		} else if (this.provider === 'huggingface') {
			await updateSettings({ huggingface_api_token: apiKey });
		}
	}

	setProvider(provider: 'openrouter' | 'openai' | 'ollama' | 'huggingface'): void {
		this.provider = provider;
		this.models = [];
		this._applyProviderDefaults();
		if (this.sessionId) {
			void updateSession(this.sessionId, {
				provider: this.provider,
				model: this.model,
				api_key: this.apiKey || undefined
			});
		}
	}

	private _refreshConfigured(): void {
		if (this.provider === 'openrouter') {
			this.configured = this.apiKey.length > 0;
			return;
		}
		if (this.provider === 'huggingface') {
			this.configured = this.apiKey.length > 0;
			return;
		}
		// OpenAI can be self-hosted without key; Ollama requires no key.
		this.configured = true;
	}

	private _applyProviderDefaults(): void {
		const s = this.settings;
		if (!s) {
			this._refreshConfigured();
			return;
		}
		if (this.provider === 'openrouter') {
			this.model = s.openrouter_default_model || this.model || 'openai/gpt-4o-mini';
			this.apiKey =
				s.openrouter_api_key && !isMasked(s.openrouter_api_key) ? s.openrouter_api_key : '';
			this.endpointUrl = 'https://openrouter.ai/api/v1';
			this.organizationId = '';
		} else if (this.provider === 'openai') {
			this.model = s.openai_default_model || 'gpt-4o-mini';
			this.apiKey = s.openai_api_key && !isMasked(s.openai_api_key) ? s.openai_api_key : '';
			this.endpointUrl = s.openai_endpoint_url || 'https://api.openai.com';
			this.organizationId = s.openai_organization_id || '';
		} else if (this.provider === 'ollama') {
			this.model = s.ollama_default_model || 'llama3.2';
			this.apiKey = '';
			this.endpointUrl = s.ollama_endpoint_url || 'http://localhost:11434';
			this.organizationId = '';
		} else {
			this.model = s.huggingface_default_model || 'google/flan-t5-base';
			this.apiKey =
				s.huggingface_api_token && !isMasked(s.huggingface_api_token)
					? s.huggingface_api_token
					: '';
			this.endpointUrl = 'https://api-inference.huggingface.co';
			this.organizationId = '';
		}
		this._refreshConfigured();
	}

	async startSession(): Promise<void> {
		this.error = null;
		const result = await createSession(
			this.provider,
			this.model,
			this.apiKey,
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
			(e) => {
				if (typeof window !== 'undefined') {
					localStorage.removeItem(SESSION_KEY);
				}
				this.error = e.message;
				return false;
			}
		);
	}

	async open_panel(): Promise<void> {
		this.open = true;
		await this.loadContext();
		void this.loadSessions();
		if (this.configured && this.models.length === 0) {
			void this.loadModels();
		}
		if (this.sessionId) return;
		if (!this.configured) {
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
				const event: ChatEvent = JSON.parse(ev.data);
				this._handleEvent(event);
			} catch {
				console.debug('[chat] failed to parse SSE event:', ev.data);
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
		return content.replace(/^\[ctx:[^\]]*\]\n?/, '');
	}

	private _handleEvent(event: ChatEvent): void {
		switch (event.type) {
			case 'message': {
				const displayContent =
					event.role === 'user' ? ChatStore._stripPageContext(event.content) : event.content;
				const msg: ChatMessage = {
					id: this._id(),
					role: event.role,
					content: displayContent,
					ts: event.ts ?? Date.now()
				};
				this.messages.push(msg);
				this.timeline.push({ kind: 'message', item: msg });
				break;
			}
			case 'tool_call': {
				const tc: ToolCall = {
					tool_id: event.tool_id,
					method: event.method,
					path: event.path,
					args: event.args,
					status: 'running',
					expanded: false
				};
				this.toolCalls.push(tc);
				this.timeline.push({ kind: 'tool', item: tc });
				break;
			}
			case 'tool_result': {
				this._updateToolStatus(event.tool_id, 'done', event.result, undefined, event.duration_ms);
				break;
			}
			case 'tool_error': {
				this._updateToolStatus(event.tool_id, 'error', undefined, event.errors);
				const summary =
					event.errors.length > 0
						? event.errors.map((e) => `${e.path}: ${e.message}`).join('\n')
						: 'Validation failed';
				const errMsg: ChatMessage = {
					id: this._id(),
					role: 'tool',
					content: summary,
					ts: event.ts ?? Date.now()
				};
				this.messages.push(errMsg);
				this.timeline.push({ kind: 'message', item: errMsg });
				this.loading = false;
				break;
			}
			case 'turn_start': {
				this.currentTurn = event.turn;
				this.maxTurns = event.max_turns;
				break;
			}
			case 'tool_start': {
				const startTc = this.toolCalls.findLast(
					(t) => t.tool_id === event.tool_id && t.status === 'running'
				);
				if (startTc) {
					startTc.startedAt = Date.now();
				}
				for (let i = this.timeline.length - 1; i >= 0; i--) {
					const entry = this.timeline[i];
					if (
						entry.kind === 'tool' &&
						entry.item.tool_id === event.tool_id &&
						entry.item.status === 'running'
					) {
						entry.item.startedAt = Date.now();
						break;
					}
				}
				break;
			}
			case 'tool_confirm': {
				this.pendingConfirm = {
					tool_id: event.tool_id,
					method: event.method,
					path: event.path,
					args: event.args
				};
				const confirmTc = this.toolCalls.findLast(
					(t) => t.tool_id === event.tool_id && t.status === 'running'
				);
				if (confirmTc) confirmTc.status = 'confirming';
				for (let i = this.timeline.length - 1; i >= 0; i--) {
					const entry = this.timeline[i];
					if (
						entry.kind === 'tool' &&
						entry.item.tool_id === event.tool_id &&
						entry.item.status === 'running'
					) {
						entry.item.status = 'confirming';
						break;
					}
				}
				break;
			}
			case 'ui_patch': {
				this._applyUiPatch(event);
				break;
			}
			case 'usage': {
				const turn: UsageInfo = {
					prompt_tokens: event.prompt_tokens,
					completion_tokens: event.completion_tokens,
					total_tokens: event.total_tokens
				};
				this.lastTurnUsage = turn;
				this.sessionUsage = {
					prompt_tokens: this.sessionUsage.prompt_tokens + turn.prompt_tokens,
					completion_tokens: this.sessionUsage.completion_tokens + turn.completion_tokens,
					total_tokens: this.sessionUsage.total_tokens + turn.total_tokens
				};
				break;
			}
			case 'error': {
				this.error = event.content;
				break;
			}
			case 'done': {
				this.loading = false;
				this.currentTurn = 0;
				this.maxTurns = null;
				this.pendingConfirm = null;
				break;
			}
		}
	}

	private _updateToolStatus(
		toolId: string,
		status: 'done' | 'error',
		result?: unknown,
		errors?: { path: string; message: string }[],
		duration_ms?: number
	): void {
		// Update in toolCalls array
		const tc = this.toolCalls.findLast(
			(t) => t.tool_id === toolId && (t.status === 'running' || t.status === 'confirming')
		);
		if (tc) {
			tc.status = status;
			if (result !== undefined) tc.result = result;
			if (errors) tc.errors = errors;
			if (duration_ms !== undefined) tc.duration_ms = duration_ms;
		}
		// Also update through timeline proxy to ensure reactivity in both arrays
		for (let i = this.timeline.length - 1; i >= 0; i--) {
			const entry = this.timeline[i];
			if (
				entry.kind === 'tool' &&
				entry.item.tool_id === toolId &&
				(entry.item.status === 'running' || entry.item.status === 'confirming')
			) {
				entry.item.status = status;
				if (result !== undefined) entry.item.result = result;
				if (errors) entry.item.errors = errors;
				if (duration_ms !== undefined) entry.item.duration_ms = duration_ms;
				break;
			}
		}
	}

	private _applyUiPatch(event: ChatUiPatchEvent): void {
		if (typeof window === 'undefined') return;
		window.dispatchEvent(new CustomEvent('chat:ui_patch', { detail: event }));
	}

	private _resolveSchema(): Schema | null {
		const last = schemaStore.getLastOutput();
		if (last) return last;

		const calculated = analysisStore.calculatedSchema;
		if (calculated) return calculated;

		const key = analysisStore.activeSchemaKey;
		const source = key ? analysisStore.sourceSchemas.get(key) : undefined;
		if (!source) return null;
		return { columns: source.columns, row_count: source.row_count };
	}

	private _pageContext(): string {
		if (typeof window === 'undefined') return '';
		const path = window.location.pathname;
		if (!path || path === '/') return '';

		const parts: string[] = [`path=${path}`];

		const analysis = analysisStore.current;
		if (analysis) {
			parts.push(`analysis="${analysis.name}"`);
			const tab = analysisStore.activeTab;
			if (tab) {
				parts.push(`tab="${tab.name}" tab_id=${tab.id}`);
				const schema = this._resolveSchema();
				if (schema && schema.columns.length > 0) {
					const total = schema.columns.length;
					const cols = schema.columns
						.slice(0, 50)
						.map((c) => `${c.name}:${c.dtype}`)
						.join(',');
					const suffix = total > 50 ? ` (${total} cols, truncated)` : '';
					parts.push(`schema={${cols}}${suffix}`);
				}
			}
		}

		return `[ctx:${parts.join(' ')}]\n`;
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

	async approveConfirm(): Promise<void> {
		if (!this.sessionId || !this.pendingConfirm) return;
		this.pendingConfirm = null;
		await confirmTool(this.sessionId, true);
	}

	async denyConfirm(): Promise<void> {
		if (!this.sessionId || !this.pendingConfirm) return;
		this.pendingConfirm = null;
		await confirmTool(this.sessionId, false);
	}

	reconnectNow(): void {
		if (!this.sessionId) return;
		this._clearRetry();
		this._connectStream(this.sessionId);
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
		this.currentTurn = 0;
		this.maxTurns = null;
		this.pendingConfirm = null;
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

	destroy(): void {
		if (typeof window !== 'undefined') {
			window.removeEventListener('beforeunload', this._onUnload);
		}
		this.close();
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
