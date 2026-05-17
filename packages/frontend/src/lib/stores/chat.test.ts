import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import type { ChatEvent, ChatModel } from '$lib/api/chat';
import type { MCPTool } from '$lib/api/mcp';

vi.mock('$lib/api/chat', () => ({
	createSession: vi.fn(),
	sendMessage: vi.fn(),
	openEventStream: vi.fn(),
	getHistory: vi.fn(),
	closeSession: vi.fn(),
	updateSession: vi.fn(),
	listModels: vi.fn(),
	listSessions: vi.fn(),
	confirmTool: vi.fn()
}));

vi.mock('$lib/api/settings', () => ({
	getSettings: vi.fn(),
	updateSettings: vi.fn()
}));

vi.mock('$lib/api/mcp', () => ({
	listTools: vi.fn()
}));

vi.mock('$lib/stores/analysis.svelte', () => ({
	analysisStore: {
		current: null,
		activeTab: null,
		calculatedSchema: null,
		activeSchemaKey: null,
		sourceSchemas: new Map()
	}
}));

vi.mock('$lib/stores/schema.svelte', () => ({
	schemaStore: { getLastOutput: () => null }
}));

// Mock localStorage + window for the test environment (chat store guards with `typeof window`)
const storage = new Map<string, string>();
const mockLocalStorage = {
	getItem: (key: string) => storage.get(key) ?? null,
	setItem: (key: string, value: string) => storage.set(key, value),
	removeItem: (key: string) => storage.delete(key),
	clear: () => storage.clear(),
	get length() {
		return storage.size;
	},
	key: (_i: number) => null
};
vi.stubGlobal('localStorage', mockLocalStorage);
vi.stubGlobal('window', {
	addEventListener: vi.fn(),
	removeEventListener: vi.fn(),
	localStorage: mockLocalStorage
});

const { ChatStore } = await import('./chat.svelte');

function makeTool(overrides: Partial<MCPTool> = {}): MCPTool {
	return {
		id: 'tool-1',
		method: 'GET',
		path: '/test',
		description: 'test tool',
		safety: 'safe',
		confirm_required: false,
		input_schema: {},
		output_schema: null,
		tags: ['default'],
		...overrides
	};
}

describe('ChatStore — pure local logic', () => {
	let store: InstanceType<typeof ChatStore>;

	beforeEach(() => {
		vi.clearAllMocks();
		storage.clear();
		store = new ChatStore();
	});

	afterEach(() => {
		storage.clear();
	});

	describe('initial state', () => {
		test('open is false', () => {
			expect(store.open).toBe(false);
		});

		test('sessionId is null', () => {
			expect(store.sessionId).toBeNull();
		});

		test('mode defaults to plan', () => {
			expect(store.mode).toBe('plan');
		});

		test('model defaults to openai/gpt-4o-mini', () => {
			expect(store.model).toBe('openai/gpt-4o-mini');
		});

		test('loading is false', () => {
			expect(store.loading).toBe(false);
		});

		test('connection is disconnected', () => {
			expect(store.connection).toBe('disconnected');
		});

		test('sessionUsage starts at zero', () => {
			expect(store.sessionUsage).toEqual({
				prompt_tokens: 0,
				completion_tokens: 0,
				total_tokens: 0
			});
		});
	});

	describe('effectiveSystemPrompt', () => {
		test('returns plan prompt when mode is plan and no custom prompt', () => {
			store.mode = 'plan';
			store.systemPrompt = '';
			expect(store.effectiveSystemPrompt).toContain('read-only tools');
		});

		test('returns execute prompt when mode is execute and no custom prompt', () => {
			store.mode = 'execute';
			store.systemPrompt = '';
			expect(store.effectiveSystemPrompt).toContain('Execute actions directly');
		});

		test('returns custom prompt when set', () => {
			store.systemPrompt = 'custom instructions';
			expect(store.effectiveSystemPrompt).toBe('custom instructions');
		});
	});

	describe('mode switching', () => {
		test('setMode changes mode', () => {
			store.setMode('execute');
			expect(store.mode).toBe('execute');
		});

		test('setMode persists to localStorage', () => {
			store.setMode('execute');
			const raw = storage.get('chat_prefs');
			expect(raw).toBeDefined();
			const prefs = JSON.parse(raw!);
			expect(prefs.mode).toBe('execute');
		});
	});

	describe('tool filtering', () => {
		const safeTool = makeTool({ id: 'safe-1', safety: 'safe', tags: ['read'] });
		const mutatingTool = makeTool({ id: 'mut-1', safety: 'mutating', tags: ['write'] });

		test('enabledTools includes all tools by default', () => {
			store.tools = [safeTool, mutatingTool];
			expect(store.enabledTools).toHaveLength(2);
		});

		test('toggleTool disables a tool', () => {
			store.tools = [safeTool, mutatingTool];
			store.toggleTool('safe-1');
			expect(store.enabledTools.map((t) => t.id)).toEqual(['mut-1']);
		});

		test('toggleTool re-enables a disabled tool', () => {
			store.tools = [safeTool, mutatingTool];
			store.toggleTool('safe-1');
			store.toggleTool('safe-1');
			expect(store.enabledTools).toHaveLength(2);
		});

		test('modeFilteredTools returns only safe tools in plan mode', () => {
			store.tools = [safeTool, mutatingTool];
			store.mode = 'plan';
			expect(store.modeFilteredTools.map((t) => t.id)).toEqual(['safe-1']);
		});

		test('modeFilteredTools returns all enabled in execute mode', () => {
			store.tools = [safeTool, mutatingTool];
			store.mode = 'execute';
			expect(store.modeFilteredTools).toHaveLength(2);
		});

		test('isToolEnabled returns false for disabled tool', () => {
			store.tools = [safeTool];
			store.toggleTool('safe-1');
			expect(store.isToolEnabled('safe-1')).toBe(false);
		});

		test('isToolEnabled returns false for unknown tool', () => {
			store.tools = [safeTool];
			expect(store.isToolEnabled('nonexistent')).toBe(false);
		});
	});

	describe('tag filtering', () => {
		const tool1 = makeTool({ id: 't1', tags: ['group-a'] });
		const tool2 = makeTool({ id: 't2', tags: ['group-a'] });
		const tool3 = makeTool({ id: 't3', tags: ['group-b'] });

		test('toggleTag disables all tools in tag', () => {
			store.tools = [tool1, tool2, tool3];
			store.toggleTag('group-a');
			expect(store.isToolEnabled('t1')).toBe(false);
			expect(store.isToolEnabled('t2')).toBe(false);
			expect(store.isToolEnabled('t3')).toBe(true);
		});

		test('isTagFullyEnabled returns true when all tools enabled', () => {
			store.tools = [tool1, tool2];
			expect(store.isTagFullyEnabled('group-a')).toBe(true);
		});

		test('isTagFullyEnabled returns false after toggling tag off', () => {
			store.tools = [tool1, tool2];
			store.toggleTag('group-a');
			expect(store.isTagFullyEnabled('group-a')).toBe(false);
		});
	});

	describe('modelDisplayName', () => {
		test('returns model name from models list', () => {
			store.models = [{ id: 'openai/gpt-4o', name: 'GPT-4o', context_length: 128000 }];
			store.model = 'openai/gpt-4o';
			expect(store.modelDisplayName).toBe('GPT-4o');
		});

		test('returns last segment of ID when model not in list', () => {
			store.models = [];
			store.model = 'anthropic/claude-3-opus';
			expect(store.modelDisplayName).toBe('claude-3-opus');
		});
	});

	describe('contextLimit', () => {
		test('returns context_length from matching model', () => {
			store.models = [
				{ id: 'openai/gpt-4o', name: 'GPT-4o', context_length: 128000 }
			] satisfies ChatModel[];
			store.model = 'openai/gpt-4o';
			expect(store.contextLimit).toBe(128000);
		});

		test('returns 0 when model not found', () => {
			store.models = [];
			expect(store.contextLimit).toBe(0);
		});
	});

	describe('draft management', () => {
		test('ensureDraft creates a draft if missing', () => {
			store.ensureDraft('tool-x', { key: 'value' });
			expect(store.toolDrafts.has('tool-x')).toBe(true);
			expect(store.toolDrafts.get('tool-x')?.args).toEqual({ key: 'value' });
		});

		test('ensureDraft does not overwrite existing draft', () => {
			store.ensureDraft('tool-x', { key: 'original' });
			store.ensureDraft('tool-x', { key: 'new' });
			expect(store.toolDrafts.get('tool-x')?.args).toEqual({ key: 'original' });
		});

		test('updateDraft replaces args', () => {
			store.ensureDraft('tool-x', { key: 'old' });
			store.updateDraft('tool-x', { key: 'updated' });
			expect(store.toolDrafts.get('tool-x')?.args).toEqual({ key: 'updated' });
		});

		test('setDraftErrors updates errors', () => {
			store.ensureDraft('tool-x', {});
			store.setDraftErrors('tool-x', [{ path: '/a', message: 'required' }]);
			expect(store.toolDrafts.get('tool-x')?.errors).toEqual([{ path: '/a', message: 'required' }]);
		});

		test('clearDraft removes draft', () => {
			store.ensureDraft('tool-x', {});
			store.clearDraft('tool-x');
			expect(store.toolDrafts.has('tool-x')).toBe(false);
		});
	});

	describe('addLocalToolCall / setLocalToolResult / setLocalToolError', () => {
		test('addLocalToolCall adds to toolCalls and timeline', () => {
			const tc = store.addLocalToolCall('t1', 'GET', '/path', { a: 1 });
			expect(tc.status).toBe('running');
			expect(store.toolCalls).toHaveLength(1);
			expect(store.timeline).toHaveLength(1);
			expect(store.timeline[0].kind).toBe('tool');
		});

		test('setLocalToolResult marks tool done', () => {
			store.addLocalToolCall('t1', 'GET', '/path', {});
			store.setLocalToolResult('t1', { ok: true });
			expect(store.toolCalls[0].status).toBe('done');
			expect(store.toolCalls[0].result).toEqual({ ok: true });
		});

		test('setLocalToolError marks tool error', () => {
			store.addLocalToolCall('t1', 'GET', '/path', {});
			store.setLocalToolError('t1', [{ path: '/', message: 'fail' }]);
			expect(store.toolCalls[0].status).toBe('error');
			expect(store.toolCalls[0].errors).toHaveLength(1);
		});
	});

	describe('_handleEvent via event processing', () => {
		function handle(event: ChatEvent) {
			const fn = Reflect.get(store, '_handleEvent') as ((event: ChatEvent) => void) | undefined;
			expect(fn).toBeTypeOf('function');
			fn?.call(store, event);
		}

		test('message event adds to messages and timeline', () => {
			handle({ type: 'message', role: 'assistant', content: 'Hello', ts: 1000 });
			expect(store.messages).toHaveLength(1);
			expect(store.messages[0].content).toBe('Hello');
			expect(store.messages[0].role).toBe('assistant');
			expect(store.timeline).toHaveLength(1);
		});

		test('user message strips page context prefix', () => {
			handle({
				type: 'message',
				role: 'user',
				content: '[ctx:path=/test]\nWhat is this?',
				ts: 1000
			});
			expect(store.messages[0].content).toBe('What is this?');
		});

		test('tool_call event adds to toolCalls and timeline', () => {
			handle({
				type: 'tool_call',
				tool_id: 'tool-1',
				method: 'GET',
				path: '/api/test',
				args: { id: '123' }
			});
			expect(store.toolCalls).toHaveLength(1);
			expect(store.toolCalls[0].status).toBe('running');
			expect(store.toolCalls[0].tool_id).toBe('tool-1');
		});

		test('tool_result updates tool status to done', () => {
			handle({ type: 'tool_call', tool_id: 'tool-1', method: 'GET', path: '/test', args: {} });
			handle({
				type: 'tool_result',
				tool_id: 'tool-1',
				result: { status: 200, body: {}, ok: true },
				duration_ms: 150
			});
			expect(store.toolCalls[0].status).toBe('done');
			expect(store.toolCalls[0].duration_ms).toBe(150);
		});

		test('tool_error updates tool status and adds error message', () => {
			handle({ type: 'tool_call', tool_id: 'tool-1', method: 'POST', path: '/test', args: {} });
			handle({
				type: 'tool_error',
				tool_id: 'tool-1',
				errors: [{ path: '/body', message: 'invalid' }]
			});
			expect(store.toolCalls[0].status).toBe('error');
			expect(store.messages).toHaveLength(1);
			expect(store.messages[0].role).toBe('tool');
			expect(store.loading).toBe(false);
		});

		test('usage event accumulates session usage', () => {
			handle({ type: 'usage', prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 });
			expect(store.sessionUsage).toEqual({
				prompt_tokens: 100,
				completion_tokens: 50,
				total_tokens: 150
			});
			expect(store.lastTurnUsage).toEqual({
				prompt_tokens: 100,
				completion_tokens: 50,
				total_tokens: 150
			});

			handle({ type: 'usage', prompt_tokens: 200, completion_tokens: 100, total_tokens: 300 });
			expect(store.sessionUsage).toEqual({
				prompt_tokens: 300,
				completion_tokens: 150,
				total_tokens: 450
			});
		});

		test('done event resets loading and turn state', () => {
			store.loading = true;
			store.currentTurn = 3;
			store.maxTurns = 5;
			handle({ type: 'done' });
			expect(store.loading).toBe(false);
			expect(store.currentTurn).toBe(0);
			expect(store.maxTurns).toBeNull();
		});

		test('error event sets error string', () => {
			handle({ type: 'error', content: 'Something went wrong' });
			expect(store.error).toBe('Something went wrong');
		});

		test('turn_start event sets currentTurn and maxTurns', () => {
			handle({ type: 'turn_start', turn: 2, max_turns: 10 });
			expect(store.currentTurn).toBe(2);
			expect(store.maxTurns).toBe(10);
		});

		test('tool_confirm sets pendingConfirm and updates tool status', () => {
			handle({ type: 'tool_call', tool_id: 'tool-1', method: 'POST', path: '/action', args: {} });
			handle({
				type: 'tool_confirm',
				tool_id: 'tool-1',
				method: 'POST',
				path: '/action',
				args: { x: 1 }
			});
			expect(store.pendingConfirm).toEqual({
				tool_id: 'tool-1',
				method: 'POST',
				path: '/action',
				args: { x: 1 }
			});
			expect(store.toolCalls[0].status).toBe('confirming');
		});
	});

	describe('session close state', () => {
		test('requestCloseSession does nothing without session', () => {
			store.requestCloseSession();
			expect(store.confirmClose).toBe(false);
		});

		test('requestCloseSession sets confirmClose', () => {
			store.sessionId = 'session-1';
			store.requestCloseSession();
			expect(store.confirmClose).toBe(true);
		});

		test('cancelCloseSession clears confirmClose', () => {
			store.confirmClose = true;
			store.cancelCloseSession();
			expect(store.confirmClose).toBe(false);
		});
	});

	describe('dismissError', () => {
		test('clears error', () => {
			store.error = 'some error';
			store.dismissError();
			expect(store.error).toBeNull();
		});
	});

	describe('close / reset', () => {
		test('close sets open to false', () => {
			store.open = true;
			store.close();
			expect(store.open).toBe(false);
		});

		test('reset clears session state', () => {
			store.open = true;
			store.sessionId = 'sess-1';
			store.messages = [{ id: '1', role: 'user', content: 'hi', ts: 0 }];
			store.reset();
			expect(store.open).toBe(false);
			expect(store.sessionId).toBeNull();
			expect(store.messages).toHaveLength(0);
		});
	});

	describe('preference persistence', () => {
		test('model preference round-trips through localStorage', () => {
			store.setMode('execute');
			const raw = storage.get('chat_prefs');
			expect(raw).toBeDefined();
			const prefs = JSON.parse(raw!);
			expect(prefs.mode).toBe('execute');

			const restored = new ChatStore();
			expect(restored.mode).toBe('execute');
		});

		test('disabled tools persist', () => {
			store.tools = [makeTool({ id: 'x', tags: ['t'] })];
			store.toggleTool('x');
			const restored = new ChatStore();
			expect(restored.disabledTools.has('x')).toBe(true);
		});
	});
});
