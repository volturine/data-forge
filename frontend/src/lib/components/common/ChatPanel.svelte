<script lang="ts">
	import {
		X,
		Send,
		Square,
		ChevronDown,
		ChevronUp,
		Plus,
		Trash2,
		Settings2,
		Search,
		LoaderCircle,
		Wrench,
		CircleAlert,
		Copy,
		ClipboardCheck,
		ArrowDown,
		RotateCcw,
		Maximize2,
		Minimize2,
		Eye,
		Play,
		CircleCheck,
		CircleX,
		History,
		RefreshCw,
		ShieldAlert,
		Check,
		Ban,
		Timer,
		WifiOff
	} from 'lucide-svelte';
	import { css, iconButton, button, input, label } from '$lib/styles/panda';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { chatStore } from '$lib/stores/chat.svelte';
	import { overlayStack } from '$lib/stores/overlay.svelte';
	import type { OverlayConfig } from '$lib/stores/overlay.svelte';
	import type { MCPTool } from '$lib/api/mcp';
	import type { ChatUiPatchEvent } from '$lib/api/chat';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { renderMarkdown, timeAgo } from '$lib/utils/markdown';

	const queryClient = useQueryClient();

	let configOpen = $state(false);
	let toolsOpen = $state(false);
	let sessionsOpen = $state(false);
	let apiKeyDraft = $state('');
	let providerDraft = $state('openrouter');
	let modelDraft = $state('');
	let systemPromptDraft = $state('');
	let modelSearch = $state('');
	let inputValue = $state('');
	let messagesEl: HTMLElement | undefined;
	let copiedId = $state<string | null>(null);
	let userScrolledUp = $state(false);
	let inputEl = $state<HTMLTextAreaElement | undefined>();
	let maximized = $state(false);
	const anyPanelOpen = $derived(configOpen || toolsOpen || sessionsOpen);
	let modelPickerOpen = $state(false);
	let modelPickerSearch = $state('');
	let panelHeight = $state(500);
	let panelWidth = $state(420);
	let expandedHeight = $state(
		typeof window !== 'undefined' ? Math.round(window.innerHeight * 0.95) : 800
	);
	let isResizing = $state(false);

	async function stopGeneration() {
		if (chatStore.sessionId) {
			const { stopGeneration: stopGen } = await import('$lib/api/chat');
			await stopGen(chatStore.sessionId);
		}
		chatStore.loading = false;
	}

	function autoResize() {
		if (!inputEl) return;
		inputEl.style.height = 'auto';
		inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
	}

	function isGrouped(idx: number): boolean {
		if (idx === 0) return false;
		const cur = chatStore.timeline[idx];
		const prev = chatStore.timeline[idx - 1];
		if (cur.kind !== 'message' || prev.kind !== 'message') return false;
		return cur.item.role === prev.item.role && cur.item.role !== 'tool';
	}

	function dateSeparator(idx: number): string | null {
		const entry = chatStore.timeline[idx];
		const ts = entry.kind === 'message' ? entry.item.ts : 0;
		if (!ts) return null;
		for (let i = idx - 1; i >= 0; i--) {
			const prev = chatStore.timeline[i];
			const prevTs = prev.kind === 'message' ? prev.item.ts : 0;
			if (prevTs) {
				return new Date(ts).toDateString() !== new Date(prevTs).toDateString()
					? formatDateLabel(ts)
					: null;
			}
		}
		return idx === 0 ? formatDateLabel(ts) : null;
	}

	function formatDateLabel(ts: number): string {
		const d = new Date(ts);
		const now = Date.now();
		const todayStr = new Date(now).toDateString();
		if (d.toDateString() === todayStr) return 'Today';
		const yesterdayMs = now - 86_400_000;
		if (d.toDateString() === new Date(yesterdayMs).toDateString()) return 'Yesterday';
		return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
	}

	/** Extract a human-readable name from a tool_id like "post_analysis" → "Create Analysis" */
	function toolDisplayName(toolId: string, method: string): string {
		const verbMap: Record<string, string> = {
			GET: 'Get',
			POST: 'Create',
			PUT: 'Update',
			PATCH: 'Update',
			DELETE: 'Delete'
		};
		const verb = verbMap[method] ?? method;
		const name = toolId
			.replace(/^(get|post|put|patch|delete)_/i, '')
			.replace(/_/g, ' ')
			.replace(/\b\w/g, (c) => c.toUpperCase());
		return `${verb} ${name}`;
	}

	/** Format a result status for compact display */
	function resultSummary(result: unknown): string {
		if (!result || typeof result !== 'object') return '';
		const r = result as { ok?: boolean; status?: number; body?: unknown };
		if (r.ok === false) return `Error ${r.status ?? ''}`;
		if (r.ok === true) return `OK ${r.status ?? 200}`;
		return '';
	}

	function findTool(toolId: string): MCPTool | undefined {
		return chatStore.tools.find((t) => t.id === toolId);
	}

	function outputHint(tool: MCPTool | undefined): string | null {
		if (!tool?.output_schema) return null;
		return tool.output_schema.hint ?? null;
	}

	const EXAMPLE_PROMPTS = [
		'List all data sources',
		'Show recent analyses',
		'What tools are available?'
	];

	function bindMessages(el: HTMLElement) {
		messagesEl = el;
	}

	function handleScroll() {
		if (!messagesEl) return;
		const { scrollTop, scrollHeight, clientHeight } = messagesEl;
		userScrolledUp = scrollHeight - scrollTop - clientHeight > 80;
	}

	function scrollToBottom() {
		if (messagesEl) {
			messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
			userScrolledUp = false;
		}
	}

	// DOM scroll after timeline update — $derived cannot trigger rAF
	const timelineLength = $derived(chatStore.timeline.length);
	const isLoading = $derived(chatStore.loading);
	$effect(() => {
		void timelineLength;
		void isLoading;
		if (!userScrolledUp && messagesEl) {
			requestAnimationFrame(() => {
				requestAnimationFrame(() => {
					messagesEl?.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
				});
			});
		}
	});

	// event listener side effect — must imperatively add/remove from window
	$effect(() => {
		if (typeof window === 'undefined') return;
		function onPatch(e: Event) {
			const detail = (e as CustomEvent<ChatUiPatchEvent>).detail;
			const resource = detail.resource;
			if (!resource) return;
			if (resource === 'analysis' || resource === 'analyses') {
				void queryClient.invalidateQueries({ queryKey: ['analyses'] });
				void queryClient.invalidateQueries({ queryKey: ['analysis'] });
			} else if (resource === 'datasource' || resource === 'datasources') {
				void queryClient.invalidateQueries({ queryKey: ['datasources'] });
			} else if (resource === 'healthcheck' || resource === 'healthchecks') {
				void queryClient.invalidateQueries({ queryKey: ['healthchecks'] });
			} else if (resource === 'scheduler' || resource === 'schedules') {
				void queryClient.invalidateQueries({ queryKey: ['schedules'] });
			}
		}
		window.addEventListener('chat:ui_patch', onPatch);
		return () => window.removeEventListener('chat:ui_patch', onPatch);
	});

	// Overlay config for the panel — two-level escape: close sub-panels first, then close panel.
	const chatOverlayConfig = $derived<OverlayConfig>({
		onEscape: () => {
			if (configOpen || toolsOpen || sessionsOpen) {
				configOpen = false;
				toolsOpen = false;
				sessionsOpen = false;
				return;
			}
			chatStore.close();
		}
	});

	// DOM focus after state change — $derived cannot call focus()
	$effect(() => {
		if (chatStore.open && !chatStore.loading && inputEl) {
			requestAnimationFrame(() => inputEl?.focus());
		}
	});

	// Cmd/Ctrl+K to open & focus chat
	$effect(() => {
		if (typeof window === 'undefined') return;
		function onGlobalKey(e: KeyboardEvent) {
			if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
				e.preventDefault();
				if (!chatStore.open) {
					void chatStore.open_panel();
				}
				requestAnimationFrame(() => inputEl?.focus());
			}
		}
		window.addEventListener('keydown', onGlobalKey);
		return () => window.removeEventListener('keydown', onGlobalKey);
	});

	// DOM mutation: $derived can't inject buttons into rendered HTML.
	$effect(() => {
		void timelineLength;
		if (!messagesEl) return;
		const buttons: HTMLButtonElement[] = [];
		requestAnimationFrame(() => {
			const blocks = messagesEl?.querySelectorAll('.chat-markdown pre');
			if (!blocks) return;
			for (const block of blocks) {
				if (block.querySelector('.code-copy-btn')) continue;
				const pre = block as HTMLElement;
				pre.style.position = 'relative';
				const btn = document.createElement('button');
				btn.className = 'code-copy-btn';
				btn.title = 'Copy code';
				btn.innerHTML =
					'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
				btn.addEventListener('click', () => {
					const code = pre.querySelector('code')?.textContent ?? pre.textContent ?? '';
					void navigator.clipboard.writeText(code).then(() => {
						btn.innerHTML =
							'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
						setTimeout(() => {
							btn.innerHTML =
								'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
						}, 2000);
					});
				});
				pre.appendChild(btn);
				buttons.push(btn);
			}
		});
		return () => {
			for (const btn of buttons) {
				btn.remove();
			}
		};
	});

	const connectionColor = $derived(
		chatStore.connection === 'connected'
			? 'fg.success'
			: chatStore.connection === 'reconnecting'
				? 'fg.warning'
				: 'fg.muted'
	);

	const connectionLabel = $derived(
		chatStore.connection === 'connected'
			? 'Connected'
			: chatStore.connection === 'reconnecting'
				? `Reconnecting\u2026`
				: 'Disconnected'
	);

	function formatDuration(ms: number): string {
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(1)}s`;
	}

	/** Reactive elapsed timer — ticks every second while a tool is running. */
	let elapsedTick = $state(Date.now());
	$effect(() => {
		const hasRunning = chatStore.toolCalls.some((tc) => tc.status === 'running' && tc.startedAt);
		if (!hasRunning) return;
		const iv = setInterval(() => {
			elapsedTick = Date.now();
		}, 1000);
		return () => clearInterval(iv);
	});

	const filteredModels = $derived(
		modelSearch
			? chatStore.models.filter(
					(m) =>
						m.id.toLowerCase().includes(modelSearch.toLowerCase()) ||
						m.name.toLowerCase().includes(modelSearch.toLowerCase())
				)
			: chatStore.models
	);

	const pickerModels = $derived(
		modelPickerSearch
			? chatStore.models.filter(
					(m) =>
						m.id.toLowerCase().includes(modelPickerSearch.toLowerCase()) ||
						m.name.toLowerCase().includes(modelPickerSearch.toLowerCase())
				)
			: chatStore.models
	);

	function pickModel(id: string) {
		modelPickerSearch = '';
		modelPickerOpen = false;
		modelDraft = id;
		void chatStore.changeModel(id);
	}

	function toggleModelPicker() {
		modelPickerOpen = !modelPickerOpen;
		modelPickerSearch = '';
		if (modelPickerOpen && chatStore.models.length === 0) {
			void chatStore.loadModels();
		}
	}

	const PANEL_HEIGHT_KEY = 'chat_panel_height';
	const PANEL_WIDTH_KEY = 'chat_panel_width';
	const EXPANDED_HEIGHT_KEY = 'chat_expanded_height';

	// Restore persisted panel dimensions
	if (typeof window !== 'undefined') {
		const stored = localStorage.getItem(PANEL_HEIGHT_KEY);
		if (stored) panelHeight = Math.max(300, Number(stored));
		const storedW = localStorage.getItem(PANEL_WIDTH_KEY);
		if (storedW) panelWidth = Math.max(320, Number(storedW));
		const storedExpanded = localStorage.getItem(EXPANDED_HEIGHT_KEY);
		if (storedExpanded) expandedHeight = Math.max(400, Number(storedExpanded));
	}

	const activeHeight = $derived(maximized ? expandedHeight : panelHeight);

	function persistDimensions() {
		localStorage.setItem(maximized ? EXPANDED_HEIGHT_KEY : PANEL_HEIGHT_KEY, String(activeHeight));
		localStorage.setItem(PANEL_WIDTH_KEY, String(panelWidth));
	}

	function startResize(e: PointerEvent) {
		e.preventDefault();
		isResizing = true;
		const startY = e.clientY;
		const startH = activeHeight;
		const minH = maximized ? 400 : 300;
		function onMove(ev: PointerEvent) {
			const delta = startY - ev.clientY;
			const clamped = Math.max(minH, Math.min(window.innerHeight * 0.95, startH + delta));
			if (maximized) {
				expandedHeight = clamped;
			} else {
				panelHeight = clamped;
			}
		}
		function onUp() {
			isResizing = false;
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
			persistDimensions();
		}
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}

	function startResizeWidth(e: PointerEvent) {
		e.preventDefault();
		isResizing = true;
		const startX = e.clientX;
		const startW = panelWidth;
		function onMove(ev: PointerEvent) {
			panelWidth = Math.max(320, Math.min(window.innerWidth * 0.9, startW + (startX - ev.clientX)));
		}
		function onUp() {
			isResizing = false;
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
			persistDimensions();
		}
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}

	function startResizeCorner(e: PointerEvent) {
		e.preventDefault();
		isResizing = true;
		const startX = e.clientX;
		const startY = e.clientY;
		const startW = panelWidth;
		const startH = activeHeight;
		const minH = maximized ? 400 : 300;
		function onMove(ev: PointerEvent) {
			panelWidth = Math.max(320, Math.min(window.innerWidth * 0.9, startW + (startX - ev.clientX)));
			const dh = Math.max(
				minH,
				Math.min(window.innerHeight * 0.95, startH + (startY - ev.clientY))
			);
			if (maximized) {
				expandedHeight = dh;
			} else {
				panelHeight = dh;
			}
		}
		function onUp() {
			isResizing = false;
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
			persistDimensions();
		}
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}

	const tagEntries = $derived(
		Array.from(chatStore.modeFilteredTagGroups.entries()).sort((a, b) => a[0].localeCompare(b[0]))
	);

	const enabledCount = $derived(chatStore.modeFilteredTools.length);

	function togglePanel(panel: 'config' | 'tools' | 'sessions') {
		if (panel === 'config') {
			configOpen = !configOpen;
			toolsOpen = false;
			sessionsOpen = false;
			if (configOpen && chatStore.models.length === 0) {
				void chatStore.loadModels();
			}
		} else if (panel === 'tools') {
			toolsOpen = !toolsOpen;
			configOpen = false;
			sessionsOpen = false;
		} else if (panel === 'sessions') {
			sessionsOpen = !sessionsOpen;
			configOpen = false;
			toolsOpen = false;
			if (sessionsOpen) {
				void chatStore.loadSessions();
			}
		}
	}

	function openConfig() {
		apiKeyDraft = chatStore.apiKey;
		providerDraft = chatStore.provider;
		modelDraft = chatStore.model;
		systemPromptDraft = chatStore.systemPrompt;
		togglePanel('config');
	}

	async function saveConfig() {
		chatStore.setProvider(providerDraft as 'openrouter' | 'openai' | 'ollama' | 'huggingface');
		chatStore.model = modelDraft;
		chatStore.systemPrompt = systemPromptDraft;
		await chatStore.configure(apiKeyDraft);
		configOpen = false;
	}

	function handleLoadModels() {
		chatStore.setProvider(providerDraft as 'openrouter' | 'openai' | 'ollama' | 'huggingface');
		chatStore.apiKey = apiKeyDraft;
		void chatStore.loadModels();
	}

	function selectModel(id: string) {
		modelDraft = id;
		modelSearch = '';
	}

	async function handleSend() {
		const text = inputValue.trim();
		if (!text) return;
		const sent = await chatStore.send(text);
		if (sent) {
			inputValue = '';
			userScrolledUp = false;
			if (inputEl) {
				inputEl.style.height = 'auto';
				requestAnimationFrame(() => inputEl?.focus());
			}
		}
	}

	async function handleSendPrompt(text: string) {
		inputValue = '';
		const sent = await chatStore.send(text);
		if (!sent) {
			inputValue = text;
			return;
		}
		requestAnimationFrame(() => inputEl?.focus());
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			void handleSend();
		}
	}

	function handlePaste() {
		requestAnimationFrame(autoResize);
	}

	function collapseAllTools() {
		for (const tc of chatStore.toolCalls) {
			tc.expanded = false;
		}
	}

	function expandAllTools() {
		for (const tc of chatStore.toolCalls) {
			tc.expanded = true;
		}
	}

	const hasToolCalls = $derived(chatStore.toolCalls.length > 0);

	const inputPlaceholder = $derived(
		!chatStore.configured
			? 'Loading\u2026'
			: chatStore.mode === 'plan'
				? 'Describe what you want to analyze\u2026'
				: 'Tell me what to do\u2026'
	);

	async function copyToClipboard(text: string, id: string) {
		await navigator.clipboard.writeText(text).catch(() => {});
		copiedId = id;
		setTimeout(() => {
			if (copiedId === id) copiedId = null;
		}, 2000);
	}

	function methodColor(method: string): string {
		if (method === 'GET') return 'fg.success';
		if (method === 'DELETE') return 'fg.error';
		if (method === 'POST') return 'fg.primary';
		return 'fg.warning';
	}

	function formatTokens(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
		return String(n);
	}

	const lastPromptTokens = $derived(chatStore.lastTurnUsage?.prompt_tokens ?? 0);
	const contextPct = $derived(
		chatStore.contextLimit > 0
			? Math.min(100, (lastPromptTokens / chatStore.contextLimit) * 100)
			: 0
	);

	const contextBarColor = $derived(
		contextPct > 90 ? 'fg.error' : contextPct > 70 ? 'fg.warning' : 'accent.primary'
	);

	const showQuickReplies = $derived.by(() => {
		if (chatStore.loading) return false;
		if (chatStore.mode !== 'plan') return false;
		for (let i = chatStore.timeline.length - 1; i >= 0; i--) {
			const entry = chatStore.timeline[i];
			if (entry.kind === 'message') {
				return entry.item.role === 'assistant';
			}
		}
		return false;
	});
</script>

<ConfirmDialog
	show={chatStore.confirmClose}
	heading="Close Session"
	message="This will end the current chat session. Message history will be lost."
	confirmText="Close"
	cancelText="Keep"
	onConfirm={() => void chatStore.closeSession()}
	onCancel={() => chatStore.cancelCloseSession()}
/>

{#if chatStore.open}
	<div
		id="chat-panel"
		class={css({
			position: 'fixed',
			bottom: '0',
			right: '4',
			display: 'flex',
			flexDirection: 'column',
			backgroundColor: 'bg.panel',
			borderWidth: '1',
			borderTopRadius: 'lg',
			boxShadow: 'lg',
			zIndex: 'overlay',
			userSelect: isResizing ? 'none' : 'auto',
			overflow: 'hidden'
		})}
		style:width="{panelWidth}px"
		style:height="{activeHeight}px"
		use:overlayStack.action={chatOverlayConfig}
	>
		<!-- Corner resize handle (top-left) -->
		<div
			role="separator"
			tabindex="-1"
			class={css({
				position: 'absolute',
				top: '0',
				left: '0',
				width: '12px',
				height: '12px',
				cursor: 'nwse-resize',
				zIndex: '1',
				borderTopLeftRadius: 'lg',
				touchAction: 'none'
			})}
			onpointerdown={startResizeCorner}
		></div>

		<!-- Left edge resize handle -->
		<div
			role="separator"
			aria-orientation="vertical"
			tabindex="-1"
			class={css({
				position: 'absolute',
				top: '12px',
				left: '0',
				bottom: '0',
				width: '6px',
				cursor: 'ew-resize',
				zIndex: '1',
				touchAction: 'none',
				_hover: { backgroundColor: 'border.primary' }
			})}
			onpointerdown={startResizeWidth}
		></div>

		<!-- Top edge resize handle -->
		<div
			role="separator"
			aria-orientation="horizontal"
			tabindex="-1"
			class={css({
				position: 'relative',
				height: '6px',
				cursor: 'ns-resize',
				flexShrink: '0',
				borderTopRadius: 'lg',
				touchAction: 'none',
				_before: {
					content: '""',
					position: 'absolute',
					top: '-4px',
					left: '12px',
					right: '0',
					bottom: '0'
				},
				_hover: { backgroundColor: 'border.primary' }
			})}
			onpointerdown={startResize}
		></div>

		<!-- Header -->
		<div
			class={css({
				borderBottomWidth: '1',
				flexShrink: '0'
			})}
		>
			<!-- Top row: mode toggle + action buttons -->
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'space-between',
					paddingX: '3',
					paddingY: '1.5'
				})}
			>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<!-- Mode toggle -->
					<div
						class={css({
							display: 'flex',
							borderRadius: 'md',
							overflow: 'hidden',
							borderWidth: '1',
							flexShrink: '0'
						})}
					>
						<button
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '1',
								paddingX: '2',
								paddingY: '1',
								fontSize: '11px',
								fontWeight: 'medium',
								border: 'none',
								cursor: 'pointer',
								backgroundColor: chatStore.mode === 'plan' ? 'bg.accent' : 'transparent',
								color: chatStore.mode === 'plan' ? 'fg.primary' : 'fg.muted',
								_hover: chatStore.mode === 'plan' ? {} : { backgroundColor: 'bg.tertiary' }
							})}
							onclick={() => chatStore.setMode('plan')}
							type="button"
							title="Plan mode: read-only, proposes plans"
						>
							<Eye size={10} />
							Plan
						</button>
						<button
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '1',
								paddingX: '2',
								paddingY: '1',
								fontSize: '11px',
								fontWeight: 'medium',
								border: 'none',
								borderLeftWidth: '1',
								cursor: 'pointer',
								backgroundColor: chatStore.mode === 'execute' ? 'fg.primary' : 'transparent',
								color: chatStore.mode === 'execute' ? 'bg.panel' : 'fg.muted',
								_hover: chatStore.mode === 'execute' ? {} : { backgroundColor: 'bg.tertiary' }
							})}
							onclick={() => chatStore.setMode('execute')}
							type="button"
							title="Execute mode: full access, auto-executes"
						>
							<Play size={10} />
							Execute
						</button>
					</div>
					{#if chatStore.loading}
						<LoaderCircle
							size={10}
							class={css({ animation: 'spin 1s linear infinite', flexShrink: '0' })}
						/>
					{/if}
				</div>
				<div class={css({ display: 'flex', gap: '0.5', flexShrink: '0' })}>
					<button
						class={[
							css({
								display: 'inline-flex',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								backgroundColor: 'bg.primary',
								padding: '2',
								color: 'fg.secondary',
								transitionProperty: 'color, background-color, border-color, opacity',
								transitionDuration: '160ms',
								transitionTimingFunction: 'ease',
								_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
							}),
							toolsOpen && css({ color: 'fg.primary' })
						]}
						onclick={() => togglePanel('tools')}
						title="Tools"
						aria-label="Tools"
					>
						<Wrench size={13} />
					</button>
					<button
						class={[
							css({
								display: 'inline-flex',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								backgroundColor: 'bg.primary',
								padding: '2',
								color: 'fg.secondary',
								transitionProperty: 'color, background-color, border-color, opacity',
								transitionDuration: '160ms',
								transitionTimingFunction: 'ease',
								_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
							}),
							sessionsOpen && css({ color: 'fg.primary' })
						]}
						onclick={() => togglePanel('sessions')}
						title="Sessions"
						aria-label="Sessions"
					>
						<History size={13} />
					</button>
					<button
						class={[
							css({
								display: 'inline-flex',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								backgroundColor: 'bg.primary',
								padding: '2',
								color: 'fg.secondary',
								transitionProperty: 'color, background-color, border-color, opacity',
								transitionDuration: '160ms',
								transitionTimingFunction: 'ease',
								_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
							}),
							configOpen && css({ color: 'fg.primary' })
						]}
						onclick={openConfig}
						title="Configure"
						aria-label="Configure"
					>
						<Settings2 size={13} />
					</button>
					<button
						class={iconButton()}
						onclick={() => (maximized = !maximized)}
						title={maximized ? 'Minimize' : 'Expand'}
						aria-label={maximized ? 'Minimize' : 'Expand'}
					>
						{#if maximized}<Minimize2 size={13} />{:else}<Maximize2 size={13} />{/if}
					</button>
					<button
						class={iconButton()}
						onclick={() => void chatStore.newSession()}
						title="New session"
						aria-label="New session"
					>
						<Plus size={13} />
					</button>
					<button
						class={iconButton()}
						onclick={() => chatStore.close()}
						title="Close chat (Esc)"
						aria-label="Close chat"
					>
						<X size={13} />
					</button>
				</div>
			</div>
		</div>

		<!-- Config panel -->
		{#if configOpen}
			<div
				class={css({
					padding: '3',
					borderBottomWidth: '1',
					display: 'flex',
					flexDirection: 'column',
					gap: '2',
					minHeight: '0',
					overflowY: 'auto',
					...(maximized ? { flexShrink: '1', maxHeight: '55vh' } : { flex: '1' })
				})}
			>
				<div>
					<label class={label()} for="chat-provider">Provider</label>
					<select
						id="chat-provider"
						class={input()}
						bind:value={providerDraft}
						disabled={!!chatStore.sessionId}
					>
						<option value="openrouter">OpenRouter</option>
						<option value="openai">OpenAI</option>
						<option value="ollama">Ollama</option>
						<option value="huggingface">Hugging Face</option>
					</select>
				</div>

				<div>
					<label class={label()} for="chat-key">API Key</label>
					<div class={css({ display: 'flex', gap: '1' })}>
						<input
							id="chat-key"
							class={[
								css({
									width: 'full',
									fontSize: 'sm2',
									color: 'fg.primary',
									backgroundColor: 'bg.primary',
									borderWidth: '1',
									borderRadius: '0',
									paddingX: '3.5',
									paddingY: '2.25',
									transitionProperty: 'border-color',
									transitionDuration: '160ms',
									transitionTimingFunction: 'ease',
									_focus: { outline: 'none' },
									_focusVisible: { borderColor: 'border.accent' },
									_disabled: {
										opacity: '0.5',
										cursor: 'not-allowed',
										backgroundColor: 'bg.tertiary'
									},
									_placeholder: { color: 'fg.muted' }
								}),
								css({ flex: '1' })
							]}
							type="password"
							bind:value={apiKeyDraft}
							placeholder="sk-or-… (uses global if empty)"
							disabled={!!chatStore.sessionId}
						/>
						<button
							class={button({ variant: 'ghost', size: 'sm' })}
							onclick={handleLoadModels}
							disabled={chatStore.modelsLoading || !!chatStore.sessionId}
							title="Fetch models"
							type="button"
						>
							{#if chatStore.modelsLoading}
								<LoaderCircle size={12} class={css({ animation: 'spin 1s linear infinite' })} />
							{:else}
								<Search size={12} />
							{/if}
						</button>
					</div>
				</div>

				<div>
					<label class={label()} for="chat-model">Model</label>
					{#if chatStore.models.length > 0}
						<div class={css({ position: 'relative' })}>
							<input
								id="chat-model-search"
								class={input()}
								type="text"
								bind:value={modelSearch}
								placeholder="Search models…"
								disabled={!!chatStore.sessionId}
							/>
							{#if modelSearch && filteredModels.length > 0}
								<div
									class={css({
										position: 'absolute',
										top: '100%',
										left: '0',
										right: '0',
										maxHeight: '150px',
										overflowY: 'auto',
										backgroundColor: 'bg.panel',
										borderWidth: '1',
										borderRadius: 'sm',
										zIndex: 'dropdown',
										boxShadow: 'md'
									})}
								>
									{#each filteredModels.slice(0, 20) as m (m.id)}
										<button
											class={css({
												display: 'block',
												width: '100%',
												textAlign: 'left',
												padding: '1.5',
												paddingX: '2',
												fontSize: 'xs',
												border: 'none',
												backgroundColor: m.id === modelDraft ? 'bg.accent' : 'transparent',
												color: m.id === modelDraft ? 'fg.primary' : 'fg.primary',
												cursor: 'pointer',
												_hover: { backgroundColor: 'bg.hover' }
											})}
											onclick={() => selectModel(m.id)}
											type="button"
										>
											{m.name}
											<span class={css({ color: 'fg.muted', fontFamily: 'mono', fontSize: 'xs' })}
												>{m.id}</span
											>
										</button>
									{/each}
								</div>
							{/if}
						</div>
						<div
							class={css({
								fontSize: 'xs',
								color: 'fg.muted',
								marginTop: '1',
								fontFamily: 'mono',
								wordBreak: 'break-all'
							})}
						>
							{modelDraft}
						</div>
					{:else}
						<input
							id="chat-model"
							class={input()}
							type="text"
							bind:value={modelDraft}
							placeholder={modelDraft || 'openai/gpt-4o-mini'}
							disabled
						/>
						<span class={css({ fontSize: 'xs', color: 'fg.muted', marginTop: '0.5' })}>
							Click <Search size={10} class={css({ display: 'inline' })} /> to load available models
						</span>
					{/if}
				</div>

				<div>
					<label class={label()} for="chat-system-prompt">System Prompt (override)</label>
					<textarea
						id="chat-system-prompt"
						class={css({
							width: 'full',
							fontSize: 'sm2',
							color: 'fg.primary',
							backgroundColor: 'bg.primary',
							borderWidth: '1',
							borderRadius: '0',
							paddingX: '3.5',
							paddingY: '2.25',
							transitionProperty: 'border-color',
							transitionDuration: '160ms',
							transitionTimingFunction: 'ease',
							_focus: { outline: 'none' },
							_focusVisible: { borderColor: 'border.accent' },
							_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
							_placeholder: { color: 'fg.muted' },
							resize: 'none',
							minHeight: '48px',
							maxHeight: '100px'
						})}
						bind:value={systemPromptDraft}
						placeholder="Leave empty to use mode default ({chatStore.mode})"
						rows={2}
						disabled={!!chatStore.sessionId}
					></textarea>
				</div>

				<button
					class={button({ variant: 'primary' })}
					onclick={saveConfig}
					disabled={!!chatStore.sessionId}
				>
					{chatStore.sessionId ? 'Active session — close to reconfigure' : 'Apply'}
				</button>
			</div>
		{/if}

		{#if toolsOpen}
			<div
				class={css({
					display: 'flex',
					flexDirection: 'column',
					minHeight: '0',
					overflowY: 'auto',
					...(maximized ? { flexShrink: '1', maxHeight: '55vh' } : { flex: '1' })
				})}
			>
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '2',
						paddingX: '3',
						paddingY: '2',
						fontSize: 'xs',
						color: 'fg.muted',
						flexShrink: '0'
					})}
				>
					<span>Tools ({enabledCount}/{chatStore.tools.length})</span>
					{#if chatStore.mode === 'plan'}
						<span class={css({ fontStyle: 'italic' })}>— read-only</span>
					{/if}
				</div>
				<div class={css({ display: 'flex', flexDirection: 'column' })}>
					{#each tagEntries as [tag, tagTools] (tag)}
						{@const tagEnabled = chatStore.isTagFullyEnabled(tag)}
						{@const tagCount = tagTools.filter((t) => chatStore.isToolEnabled(t.id)).length}
						<div>
							<button
								class={css({
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'flex-start',
									gap: '2',
									width: '100%',
									border: 'none',
									backgroundColor: 'transparent',
									cursor: 'pointer',
									paddingX: '3',
									paddingY: '1.5',
									fontSize: 'xs',
									textAlign: 'left',
									_hover: { backgroundColor: 'bg.hover' }
								})}
								onclick={() => chatStore.toggleTag(tag)}
								type="button"
								disabled={!!chatStore.sessionId}
							>
								<div
									class={css({
										width: '14px',
										height: '14px',
										borderRadius: 'sm',
										borderWidth: '1',
										backgroundColor: 'transparent',
										flexShrink: '0',
										display: 'flex',
										alignItems: 'center',
										justifyContent: 'center',
										color: 'green.400',
										fontSize: '9px'
									})}
								>
									{#if tagEnabled}&#10003;{/if}
								</div>
								<span
									class={css({
										flex: '1',
										fontWeight: 'medium',
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										fontSize: '10px',
										color: 'fg.secondary'
									})}
								>
									{tag}
								</span>
								<span
									class={css({
										fontSize: '10px',
										fontFamily: 'mono',
										color: 'fg.muted'
									})}
								>
									{tagCount}/{tagTools.length}
								</span>
							</button>
							<div class={css({ display: 'flex', flexDirection: 'column' })}>
								{#each tagTools as tool (tool.id)}
									{@const enabled = chatStore.isToolEnabled(tool.id)}
									{@const hint = outputHint(tool)}
									<button
										class={css({
											display: 'flex',
											alignItems: 'center',
											justifyContent: 'flex-start',
											gap: '2',
											width: '100%',
											border: 'none',
											backgroundColor: 'transparent',
											cursor: 'pointer',
											paddingLeft: '6',
											paddingRight: '3',
											paddingY: '1',
											fontSize: '11px',
											textAlign: 'left',
											color: enabled ? 'fg.primary' : 'fg.muted',
											_hover: { backgroundColor: 'bg.hover' }
										})}
										onclick={() => chatStore.toggleTool(tool.id)}
										type="button"
										disabled={!!chatStore.sessionId}
									>
										<div
											class={css({
												width: '12px',
												height: '12px',
												borderRadius: 'xs',
												borderWidth: '1',
												backgroundColor: 'transparent',
												flexShrink: '0',
												display: 'flex',
												alignItems: 'center',
												justifyContent: 'center',
												color: 'green.400',
												fontSize: '8px'
											})}
										>
											{#if enabled}&#10003;{/if}
										</div>
										<span
											class={css({
												fontFamily: 'mono',
												fontWeight: 'semibold',
												fontSize: '9px',
												paddingX: '1',
												paddingY: '0.5',
												borderRadius: 'xs',
												backgroundColor: 'bg.tertiary',
												color: methodColor(tool.method),
												flexShrink: '0'
											})}
										>
											{tool.method}
										</span>
										<span
											class={css({
												flex: '1',
												minWidth: '0',
												fontFamily: 'mono',
												fontSize: '11px',
												overflow: 'hidden',
												textOverflow: 'ellipsis',
												whiteSpace: 'nowrap'
											})}
											title={tool.path}
										>
											{tool.path}
										</span>
										{#if hint}
											<span
												class={css({
													fontSize: '9px',
													color: 'fg.muted',
													flexShrink: '0',
													maxWidth: '80px',
													overflow: 'hidden',
													textOverflow: 'ellipsis',
													whiteSpace: 'nowrap'
												})}
												title={hint}
											>
												→ {hint}
											</span>
										{/if}
									</button>
								{/each}
							</div>
						</div>
					{/each}
					{#if chatStore.tools.length === 0}
						<div class={css({ paddingX: '3', paddingY: '2', fontSize: 'xs', color: 'fg.muted' })}>
							No tools loaded
						</div>
					{/if}
				</div>
			</div>
		{/if}

		{#if sessionsOpen}
			<div
				class={css({
					padding: '3',
					borderBottomWidth: '1',
					display: 'flex',
					flexDirection: 'column',
					gap: '2',
					minHeight: '0',
					overflowY: 'auto',
					...(maximized ? { flexShrink: '1', maxHeight: '55vh' } : { flex: '1' })
				})}
			>
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '1',
						fontSize: 'xs',
						color: 'fg.muted'
					})}
				>
					<span class={css({ flex: '1' })}>Sessions</span>
					<button
						class={css({
							background: 'none',
							border: 'none',
							cursor: 'pointer',
							padding: '0',
							color: 'fg.muted',
							display: 'flex',
							alignItems: 'center'
						})}
						onclick={() => void chatStore.loadSessions()}
						title="Refresh sessions"
						type="button"
					>
						<RefreshCw size={10} />
					</button>
				</div>
				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						gap: '0',
						fontSize: 'xs'
					})}
				>
					{#each chatStore.sessions as session (session.id)}
						<div
							class={[
								'group',
								css({
									display: 'flex',
									alignItems: 'center',
									gap: '1',
									borderRadius: 'sm',
									overflow: 'hidden',
									_hover: { backgroundColor: 'bg.hover' }
								})
							]}
						>
							<button
								class={css({
									display: 'flex',
									flexDirection: 'column',
									gap: '0',
									flex: '1',
									textAlign: 'left',
									padding: '1.5',
									paddingX: '2',
									border: 'none',
									background: 'none',
									color: 'fg.secondary',
									cursor: 'pointer',
									minWidth: '0',
									overflow: 'hidden'
								})}
								onclick={() => void chatStore.resumeSession(session.id)}
								type="button"
								disabled={chatStore.loading}
							>
								<span
									class={css({
										fontSize: 'xs',
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap',
										color: session.preview ? 'fg.primary' : 'fg.muted'
									})}
								>
									{session.preview || 'Empty session'}
								</span>
								<span class={css({ fontSize: '10px', color: 'fg.muted', fontFamily: 'mono' })}>
									{session.model} · {timeAgo(session.created_at)}
								</span>
							</button>
							<button
								class={css({
									padding: '1',
									border: 'none',
									background: 'none',
									color: 'fg.muted',
									cursor: 'pointer',
									flexShrink: '0',
									borderRadius: 'sm',
									opacity: '0',
									_groupHover: { opacity: '1' },
									_hover: { color: 'fg.error', backgroundColor: 'bg.errorSubtle' }
								})}
								onclick={(e) => {
									e.stopPropagation();
									void chatStore.deleteSession(session.id);
								}}
								title="Delete session"
								type="button"
							>
								<Trash2 size={11} />
							</button>
						</div>
					{/each}
					{#if chatStore.sessions.length === 0}
						<span class={css({ color: 'fg.muted' })}>No sessions</span>
					{/if}
				</div>
			</div>
		{/if}

		{#if maximized || !anyPanelOpen}
			<!-- Messages area -->
			<div
				class={css({
					flex: '1',
					overflowY: 'auto',
					padding: '3',
					display: 'flex',
					flexDirection: 'column',
					gap: '1.5',
					minHeight: '0',
					position: 'relative'
				})}
				use:bindMessages
				onscroll={handleScroll}
			>
				<!-- Empty state -->
				{#if chatStore.timeline.length === 0 && !chatStore.loading}
					<div
						class={css({
							flex: '1',
							display: 'flex',
							flexDirection: 'column',
							alignItems: 'center',
							justifyContent: 'center',
							gap: '3',
							paddingY: '6',
							color: 'fg.muted'
						})}
					>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
							{#if chatStore.mode === 'plan'}
								<Eye size={24} class={css({ opacity: '0.4' })} />
							{:else}
								<Play size={24} class={css({ opacity: '0.4' })} />
							{/if}
						</div>
						<div class={css({ textAlign: 'center' })}>
							<p class={css({ fontSize: 'sm', margin: '0', marginBottom: '1' })}>
								{chatStore.mode === 'plan'
									? 'Plan mode — read-only, proposes before acting'
									: 'Execute mode — full access, acts directly'}
							</p>
							<p class={css({ fontSize: 'xs', margin: '0', color: 'fg.muted' })}>
								{chatStore.sessionId
									? 'Send a message to get started.'
									: 'Start a session and ask anything.'}
							</p>
						</div>
						{#if chatStore.configured}
							<div
								class={css({
									display: 'flex',
									flexDirection: 'column',
									gap: '1.5',
									width: '100%',
									maxWidth: '280px'
								})}
							>
								{#each EXAMPLE_PROMPTS as prompt (prompt)}
									<button
										class={css({
											display: 'block',
											width: '100%',
											textAlign: 'left',
											padding: '2',
											paddingX: '3',
											fontSize: 'xs',
											borderWidth: '1',
											borderRadius: 'md',
											backgroundColor: 'transparent',
											color: 'fg.secondary',
											cursor: 'pointer',
											_hover: { backgroundColor: 'bg.tertiary' }
										})}
										onclick={() => void handleSendPrompt(prompt)}
										type="button"
										disabled={chatStore.loading}
									>
										{prompt}
									</button>
								{/each}
							</div>
						{/if}
						{#if chatStore.sessions.length > 0}
							<div
								class={css({
									display: 'flex',
									flexDirection: 'column',
									gap: '1',
									width: '100%',
									maxWidth: '280px'
								})}
							>
								<div
									class={css({
										display: 'flex',
										alignItems: 'center',
										gap: '1',
										fontSize: '10px',
										color: 'fg.muted',
										fontWeight: 'medium',
										textTransform: 'uppercase',
										letterSpacing: 'wide'
									})}
								>
									<History size={10} />
									Recent sessions
								</div>
								{#each chatStore.sessions.slice(0, 5) as session (session.id)}
									<div
										class={[
											'group',
											css({
												display: 'flex',
												alignItems: 'center',
												gap: '1',
												borderRadius: 'sm',
												overflow: 'hidden',
												_hover: { backgroundColor: 'bg.hover' }
											})
										]}
									>
										<button
											class={css({
												display: 'flex',
												flexDirection: 'column',
												gap: '0',
												flex: '1',
												textAlign: 'left',
												padding: '1.5',
												paddingX: '2',
												border: 'none',
												background: 'none',
												color: 'fg.secondary',
												cursor: 'pointer',
												minWidth: '0',
												overflow: 'hidden'
											})}
											onclick={() => void chatStore.resumeSession(session.id)}
											type="button"
											disabled={chatStore.loading}
										>
											<span
												class={css({
													fontSize: 'xs',
													overflow: 'hidden',
													textOverflow: 'ellipsis',
													whiteSpace: 'nowrap',
													color: session.preview ? 'fg.primary' : 'fg.muted'
												})}
											>
												{session.preview || 'Empty session'}
											</span>
											<span
												class={css({
													fontSize: '10px',
													color: 'fg.muted',
													fontFamily: 'mono'
												})}
											>
												{session.model} · {timeAgo(session.created_at)}
											</span>
										</button>
										<button
											class={css({
												padding: '1',
												border: 'none',
												background: 'none',
												color: 'fg.muted',
												cursor: 'pointer',
												flexShrink: '0',
												borderRadius: 'sm',
												opacity: '0',
												_groupHover: { opacity: '1' },
												_hover: { color: 'fg.error', backgroundColor: 'bg.errorSubtle' }
											})}
											onclick={(e) => {
												e.stopPropagation();
												void chatStore.deleteSession(session.id);
											}}
											title="Delete session"
											type="button"
										>
											<Trash2 size={11} />
										</button>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/if}

				<!-- Timeline controls -->
				{#if hasToolCalls}
					<div
						class={css({
							display: 'flex',
							justifyContent: 'flex-end',
							paddingX: '2',
							paddingY: '0.5'
						})}
					>
						<button
							class={css({
								border: 'none',
								background: 'none',
								padding: '0',
								cursor: 'pointer',
								color: 'fg.muted',
								fontSize: '10px',
								fontFamily: 'mono',
								_hover: { color: 'fg.primary' }
							})}
							onclick={() => {
								const anyExpanded = chatStore.toolCalls.some((tc) => tc.expanded);
								if (anyExpanded) collapseAllTools();
								else expandAllTools();
							}}
							type="button"
						>
							{chatStore.toolCalls.some((tc) => tc.expanded)
								? 'Collapse all tools'
								: 'Expand all tools'}
						</button>
					</div>
				{/if}

				<!-- Timeline -->
				{#each chatStore.timeline as entry, idx (entry.kind === 'message' ? entry.item.id : entry.item.tool_id + idx)}
					{@const dateLabel = dateSeparator(idx)}
					{@const grouped = isGrouped(idx)}
					{#if dateLabel}
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '3',
								paddingY: '1'
							})}
						>
							<div
								class={css({ flex: '1', height: '1px', backgroundColor: 'border.subtle' })}
							></div>
							<span class={css({ fontSize: '10px', color: 'fg.muted', whiteSpace: 'nowrap' })}
								>{dateLabel}</span
							>
							<div
								class={css({ flex: '1', height: '1px', backgroundColor: 'border.subtle' })}
							></div>
						</div>
					{/if}
					{#if entry.kind === 'message'}
						{@const msg = entry.item}
						{#if msg.role === 'tool'}
							<!-- Tool error inline -->
							<div
								class={css({
									display: 'flex',
									alignItems: 'flex-start',
									gap: '1.5',
									paddingX: '2',
									paddingY: '1',
									borderRadius: 'sm',
									backgroundColor: 'bg.errorSubtle',
									borderLeftWidth: '2',
									borderColor: 'border.error',
									fontSize: '11px',
									color: 'fg.error'
								})}
							>
								<CircleAlert size={10} class={css({ flexShrink: '0', marginTop: '1px' })} />
								<pre
									class={css({
										margin: '0',
										whiteSpace: 'pre-wrap',
										wordBreak: 'break-word',
										fontFamily: 'mono',
										lineHeight: '1.4'
									})}>{msg.content}</pre>
							</div>
						{:else}
							<!-- User / Assistant message -->
							<div
								class={[
									'chat-msg-enter',
									css({
										display: 'flex',
										flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
										gap: '1.5',
										marginTop: grouped ? '-0.5' : '0'
									})
								]}
							>
								{#if msg.role === 'assistant'}
									{#if !grouped}
										<div
											class={css({
												width: '22px',
												height: '22px',
												borderRadius: 'full',
												backgroundColor:
													chatStore.mode === 'execute' ? 'accent.primary' : 'bg.tertiary',
												display: 'flex',
												alignItems: 'center',
												justifyContent: 'center',
												flexShrink: '0',
												marginTop: '1'
											})}
										>
											{#if chatStore.mode === 'execute'}
												<Play size={10} class={css({ color: 'white' })} />
											{:else}
												<Eye size={10} class={css({ color: 'fg.muted' })} />
											{/if}
										</div>
									{:else}
										<div class={css({ width: '22px', flexShrink: '0' })}></div>
									{/if}
								{/if}
								<div
									class={css({
										maxWidth: msg.role === 'assistant' ? 'calc(100% - 30px)' : '85%',
										display: 'flex',
										flexDirection: 'column',
										gap: '0.5',
										alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start'
									})}
								>
									<div
										class={[
											css({
												padding: '2',
												borderRadius: 'md',
												fontSize: 'sm',
												backgroundColor: msg.role === 'user' ? 'bg.accent' : 'bg.tertiary',
												color: msg.role === 'user' ? 'fg.primary' : 'fg.primary',
												wordBreak: 'break-word',
												position: 'relative',
												lineHeight: '1.5',
												_hover: { '& .chat-copy-btn': { opacity: '1' } }
											}),
											msg.role === 'assistant' ? 'chat-markdown' : ''
										]}
									>
										{#if msg.role === 'assistant'}
											<!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown from our own AI, not user-supplied HTML -->
											{@html renderMarkdown(msg.content)}
										{:else}
											<span class={css({ whiteSpace: 'pre-wrap' })}>{msg.content}</span>
										{/if}
										<button
											class={[
												'chat-copy-btn',
												css({
													position: 'absolute',
													top: '1',
													right: '1',
													padding: '1',
													border: 'none',
													backgroundColor: 'transparent',
													color: 'fg.muted',
													cursor: 'pointer',
													opacity: '0',
													_hover: { color: 'fg.primary' }
												})
											]}
											onclick={() => copyToClipboard(msg.content, msg.id)}
											title="Copy message"
											type="button"
										>
											{#if copiedId === msg.id}
												<ClipboardCheck size={11} />
											{:else}
												<Copy size={11} />
											{/if}
										</button>
									</div>
									<span
										class={[
											'chat-ts',
											css({
												fontSize: '10px',
												color: 'fg.muted',
												paddingX: '1'
											})
										]}
									>
										{timeAgo(msg.ts)}
									</span>
								</div>
							</div>
						{/if}
					{:else}
						<!-- Tool call card -->
						{@const tc = entry.item}
						{@const summary = resultSummary(tc.result)}
						{@const toolDef = findTool(tc.tool_id)}
						{@const elapsed =
							tc.startedAt && tc.status === 'running' ? elapsedTick - tc.startedAt : undefined}
						<div
							class={css({
								borderRadius: 'md',
								overflow: 'hidden',
								fontSize: '11px',
								marginLeft: '30px',
								maxWidth: 'calc(100% - 30px)',
								minWidth: '0',
								flexShrink: '0',
								backgroundColor: 'bg.secondary',
								borderWidth: '1',
								borderColor:
									tc.status === 'error'
										? 'border.error'
										: tc.status === 'confirming'
											? 'fg.warning'
											: tc.status === 'done'
												? 'border.subtle'
												: 'border.primary'
							})}
						>
							<button
								class={css({
									display: 'flex',
									alignItems: 'center',
									gap: '1.5',
									width: '100%',
									paddingY: '2',
									paddingX: '2',
									minHeight: '32px',
									border: 'none',
									backgroundColor: 'transparent',
									cursor: 'pointer',
									textAlign: 'left',
									color: 'fg.primary'
								})}
								onclick={() => (tc.expanded = !tc.expanded)}
								type="button"
							>
								{#if tc.status === 'running'}
									<LoaderCircle
										size={11}
										class={css({
											animation: 'spin 1s linear infinite',
											flexShrink: '0',
											color: 'accent.primary'
										})}
									/>
								{:else if tc.status === 'confirming'}
									<ShieldAlert size={11} class={css({ flexShrink: '0', color: 'fg.warning' })} />
								{:else if tc.status === 'done'}
									<CircleCheck size={11} class={css({ flexShrink: '0', color: 'fg.success' })} />
								{:else}
									<CircleX size={11} class={css({ flexShrink: '0', color: 'fg.error' })} />
								{/if}
								<Wrench size={9} class={css({ flexShrink: '0', color: 'fg.muted' })} />
								<span
									class={css({
										flex: '1',
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap',
										fontWeight: 'medium'
									})}
								>
									{toolDisplayName(tc.tool_id, tc.method)}
								</span>
								{#if tc.status === 'confirming'}
									<span
										class={css({
											fontSize: '10px',
											color: 'fg.warning',
											fontWeight: 'medium',
											flexShrink: '0'
										})}>Confirm?</span
									>
								{:else if elapsed !== undefined}
									<span
										class={css({
											fontSize: '10px',
											color: elapsed > 5000 ? 'fg.warning' : 'fg.muted',
											fontFamily: 'mono',
											flexShrink: '0'
										})}>{formatDuration(elapsed)}</span
									>
								{:else if tc.duration_ms !== undefined}
									<span
										class={css({
											fontSize: '10px',
											color: 'fg.muted',
											fontFamily: 'mono',
											flexShrink: '0'
										})}>{formatDuration(tc.duration_ms)}</span
									>
								{/if}
								{#if summary}
									<span
										class={css({
											fontSize: '10px',
											color: 'fg.muted',
											fontFamily: 'mono',
											flexShrink: '0'
										})}>{summary}</span
									>
								{/if}
								{#if tc.expanded}<ChevronUp size={10} />{:else}<ChevronDown size={10} />{/if}
							</button>
							{#if tc.status === 'confirming'}
								<!-- Confirmation actions -->
								<div
									class={css({
										display: 'flex',
										alignItems: 'center',
										gap: '2',
										padding: '2',
										borderTopWidth: '1',
										borderColor: 'border.warning',
										backgroundColor: 'bg.tertiary'
									})}
								>
									<ShieldAlert size={12} class={css({ flexShrink: '0', color: 'fg.warning' })} />
									<span
										class={css({
											flex: '1',
											fontSize: '11px',
											color: 'fg.primary'
										})}
									>
										This action will modify data. Allow?
									</span>
									<button
										class={css({
											display: 'flex',
											alignItems: 'center',
											gap: '1',
											paddingX: '2',
											paddingY: '1',
											borderRadius: 'sm',
											border: 'none',
											backgroundColor: 'fg.success',
											color: 'white',
											fontSize: '11px',
											fontWeight: 'medium',
											cursor: 'pointer'
										})}
										onclick={() => void chatStore.approveConfirm()}
										type="button"
									>
										<Check size={10} />
										Allow
									</button>
									<button
										class={css({
											display: 'flex',
											alignItems: 'center',
											gap: '1',
											paddingX: '2',
											paddingY: '1',
											borderRadius: 'sm',
											border: 'none',
											backgroundColor: 'fg.error',
											color: 'white',
											fontSize: '11px',
											fontWeight: 'medium',
											cursor: 'pointer'
										})}
										onclick={() => void chatStore.denyConfirm()}
										type="button"
									>
										<Ban size={10} />
										Deny
									</button>
								</div>
							{/if}
							{#if tc.expanded}
								<div
									class={css({
										padding: '2',
										fontFamily: 'mono',
										fontSize: '10px',
										overflow: 'auto',
										maxHeight: '200px',
										borderTopWidth: '1',
										backgroundColor: 'bg.tertiary',
										wordBreak: 'break-word'
									})}
								>
									<div class={css({ color: 'fg.muted', marginBottom: '0.5' })}>
										<span
											class={css({
												color: methodColor(tc.method),
												fontWeight: 'medium'
											})}>{tc.method}</span
										>
										{tc.path}
									</div>
									{#if toolDef?.output_schema}
										{@const out = toolDef.output_schema}
										{@const fields = out.fields ?? []}
										<div
											class={css({
												display: 'flex',
												flexWrap: 'wrap',
												alignItems: 'center',
												gap: '1',
												color: 'fg.muted',
												marginBottom: '0.5'
											})}
										>
											<span>→</span>
											{#if out.response_model}
												<span
													class={css({
														paddingX: '1',
														paddingY: '0.5',
														borderRadius: 'xs',
														backgroundColor: 'bg.secondary',
														fontWeight: 'medium',
														color: 'fg.secondary'
													})}
												>
													{out.response_model}
												</span>
											{/if}
											{#if out.status_code}
												<span>{out.status_code}</span>
											{/if}
											{#if out.content_type}
												<span>{out.content_type}</span>
											{/if}
											{#if fields.length > 0}
												<span class={css({ color: 'fg.muted' })} title={fields.join(', ')}>
													{`{ ${fields.slice(0, 6).join(', ')}${fields.length > 6 ? ', \u2026' : ''} }`}
												</span>
											{/if}
										</div>
									{/if}
									{#if Object.keys(tc.args).length > 0}
										<div
											class={css({
												display: 'flex',
												alignItems: 'center',
												justifyContent: 'space-between',
												color: 'fg.muted',
												marginTop: '1',
												marginBottom: '0.5'
											})}
										>
											Arguments
											<button
												class={css({
													border: 'none',
													background: 'none',
													padding: '0',
													cursor: 'pointer',
													color: 'fg.muted',
													_hover: { color: 'fg.primary' }
												})}
												onclick={() =>
													void copyToClipboard(
														JSON.stringify(tc.args, null, 2),
														`args-${tc.tool_id}`
													)}
												type="button"
												title="Copy arguments"
											>
												{#if copiedId === `args-${tc.tool_id}`}<ClipboardCheck
														size={9}
													/>{:else}<Copy size={9} />{/if}
											</button>
										</div>
										<pre
											class={css({
												margin: '0',
												whiteSpace: 'pre-wrap',
												wordBreak: 'break-word',
												color: 'fg.secondary'
											})}>{JSON.stringify(tc.args, null, 2)}</pre>
									{/if}
									{#if tc.errors && tc.errors.length > 0}
										<div class={css({ color: 'fg.error', marginTop: '1', marginBottom: '0.5' })}>
											Errors
										</div>
										{#each tc.errors as err (err.path)}
											<div class={css({ color: 'fg.error', marginBottom: '0.5' })}>
												<span class={css({ fontWeight: 'medium' })}>{err.path}</span>: {err.message}
											</div>
										{/each}
									{/if}
									{#if tc.result !== undefined}
										<div
											class={css({
												display: 'flex',
												alignItems: 'center',
												justifyContent: 'space-between',
												color: 'fg.muted',
												marginTop: '1',
												marginBottom: '0.5'
											})}
										>
											Response
											<button
												class={css({
													border: 'none',
													background: 'none',
													padding: '0',
													cursor: 'pointer',
													color: 'fg.muted',
													_hover: { color: 'fg.primary' }
												})}
												onclick={() =>
													void copyToClipboard(
														JSON.stringify(tc.result, null, 2),
														`result-${tc.tool_id}`
													)}
												type="button"
												title="Copy response"
											>
												{#if copiedId === `result-${tc.tool_id}`}
													<ClipboardCheck size={9} />
												{:else}
													<Copy size={9} />
												{/if}
											</button>
										</div>
										<pre
											class={css({
												margin: '0',
												whiteSpace: 'pre-wrap',
												wordBreak: 'break-word',
												color: 'fg.secondary'
											})}>{JSON.stringify(tc.result, null, 2)}</pre>
									{/if}
								</div>
							{/if}
						</div>
					{/if}
				{/each}

				<!-- Typing indicator -->
				{#if chatStore.loading && chatStore.timeline.length > 0}
					<div class={css({ display: 'flex', gap: '2', marginLeft: '30px' })}>
						<div
							class={css({
								padding: '1.5',
								paddingX: '3',
								borderRadius: 'md',
								backgroundColor: 'bg.tertiary',
								display: 'flex',
								alignItems: 'center',
								gap: '1'
							})}
						>
							<span class="chat-dot chat-dot-1"></span>
							<span class="chat-dot chat-dot-2"></span>
							<span class="chat-dot chat-dot-3"></span>
						</div>
					</div>
				{/if}

				<!-- Quick replies (plan mode only) -->
				{#if showQuickReplies}
					<div
						class={css({
							display: 'flex',
							gap: '2',
							paddingTop: '1',
							marginLeft: '30px',
							flexWrap: 'wrap'
						})}
					>
						<button
							class={css({
								paddingX: '3',
								paddingY: '1',
								borderRadius: 'full',
								borderWidth: '1',
								borderColor: 'border.accent',
								backgroundColor: 'transparent',
								color: 'accent.primary',
								fontSize: '11px',
								fontWeight: 'medium',
								cursor: 'pointer',
								_hover: { backgroundColor: 'bg.accent', color: 'fg.primary' }
							})}
							onclick={() => void handleSendPrompt('Go ahead, execute the plan.')}
							type="button"
						>
							Execute plan
						</button>
						<button
							class={css({
								paddingX: '3',
								paddingY: '1',
								borderRadius: 'full',
								borderWidth: '1',
								backgroundColor: 'transparent',
								color: 'fg.muted',
								fontSize: '11px',
								cursor: 'pointer',
								_hover: { backgroundColor: 'bg.tertiary' }
							})}
							onclick={() => inputEl?.focus()}
							type="button"
						>
							Modify
						</button>
					</div>
				{/if}
			</div>

			<!-- Scroll to bottom -->
			{#if userScrolledUp}
				<div class={css({ position: 'relative' })}>
					<button
						class={css({
							position: 'absolute',
							bottom: '2',
							left: '50%',
							transform: 'translateX(-50%)',
							display: 'flex',
							alignItems: 'center',
							gap: '1',
							paddingX: '3',
							paddingY: '1',
							borderRadius: 'full',
							borderWidth: '1',
							backgroundColor: 'bg.panel',
							color: 'fg.muted',
							fontSize: '11px',
							cursor: 'pointer',
							boxShadow: 'md',
							zIndex: '1',
							_hover: { backgroundColor: 'bg.tertiary' }
						})}
						onclick={scrollToBottom}
						type="button"
					>
						<ArrowDown size={10} />
						{chatStore.loading ? 'New messages' : 'Jump to latest'}
					</button>
				</div>
			{/if}

			<!-- Error banner -->
			{#if chatStore.error}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '2',
						paddingX: '3',
						paddingY: '1.5',
						borderTopWidth: '1',
						borderColor: 'border.error',
						backgroundColor: 'bg.errorSubtle',
						flexShrink: '0'
					})}
				>
					<CircleAlert size={11} class={css({ color: 'fg.error', flexShrink: '0' })} />
					<span
						class={css({
							flex: '1',
							color: 'fg.error',
							fontSize: '11px',
							overflow: 'hidden',
							textOverflow: 'ellipsis'
						})}
					>
						{chatStore.error}
					</span>
					{#if chatStore.lastFailedContent}
						<button
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '1',
								padding: '1',
								paddingX: '2',
								border: 'none',
								borderRadius: 'sm',
								backgroundColor: 'transparent',
								color: 'fg.error',
								fontSize: '11px',
								fontWeight: 'medium',
								cursor: 'pointer',
								flexShrink: '0',
								_hover: { backgroundColor: 'bg.tertiary' }
							})}
							onclick={() => void chatStore.retry()}
							type="button"
						>
							<RotateCcw size={10} />
							Retry
						</button>
					{/if}
					<button
						class={css({
							padding: '1',
							border: 'none',
							backgroundColor: 'transparent',
							color: 'fg.error',
							cursor: 'pointer',
							flexShrink: '0',
							_hover: { opacity: '0.7' }
						})}
						onclick={() => chatStore.dismissError()}
						type="button"
						title="Dismiss error"
					>
						<X size={11} />
					</button>
				</div>
			{/if}
		{/if}

		<!-- Input area -->
		<div
			class={css({
				display: 'flex',
				flexDirection: 'column',
				gap: '1',
				padding: '2',
				paddingX: '3',
				paddingBottom: '2',
				borderTopWidth: '1',
				flexShrink: '0'
			})}
		>
			<!-- Model picker + indicators row -->
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					position: 'relative',
					fontSize: '10px',
					fontFamily: 'mono',
					color: 'fg.muted'
				})}
			>
				<select
					class={css({
						borderWidth: '1',
						backgroundColor: 'bg.panel',
						color: 'fg.muted',
						fontSize: '10px',
						fontFamily: 'mono',
						paddingX: '1',
						paddingY: '0.5',
						height: '20px',
						flexShrink: '0'
					})}
					value={chatStore.provider}
					onchange={(event) => {
						const provider = (event.currentTarget as HTMLSelectElement).value as
							| 'openrouter'
							| 'openai'
							| 'ollama'
							| 'huggingface';
						chatStore.setProvider(provider);
						if (chatStore.models.length === 0) {
							void chatStore.loadModels();
						}
					}}
					title="Chat provider"
				>
					<option value="openrouter">OpenRouter</option>
					<option value="openai">OpenAI</option>
					<option value="ollama">Ollama</option>
					<option value="huggingface">HF</option>
				</select>

				<button
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '1',
						border: 'none',
						background: 'none',
						padding: '0',
						cursor: 'pointer',
						color: 'fg.muted',
						fontSize: '10px',
						fontFamily: 'mono',
						flexShrink: '0',
						_hover: { color: 'fg.primary' }
					})}
					onclick={toggleModelPicker}
					type="button"
					title={chatStore.model}
				>
					{chatStore.modelDisplayName}
					<ChevronDown size={8} />
				</button>
				{#if chatStore.sessionId}
					<span
						class={css({
							display: 'inline-block',
							height: 'dot',
							width: 'dot',
							flexShrink: '0',
							borderRadius: 'full',
							backgroundColor: connectionColor
						})}
						title={connectionLabel}
					></span>
					{#if chatStore.connection === 'disconnected'}
						<button
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '0.5',
								border: 'none',
								background: 'none',
								padding: '0',
								cursor: 'pointer',
								color: 'fg.muted',
								fontSize: '10px',
								fontFamily: 'mono',
								flexShrink: '0',
								_hover: { color: 'fg.primary' }
							})}
							onclick={() => chatStore.reconnectNow()}
							type="button"
							title="Reconnect now"
						>
							<WifiOff size={8} />
							Reconnect
						</button>
					{/if}
					{#if chatStore.currentTurn > 0}
						<span
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '0.5',
								flexShrink: '0',
								color: 'accent.primary',
								fontSize: '10px',
								fontFamily: 'mono'
							})}
							title={chatStore.maxTurns != null
								? `Agent turn ${chatStore.currentTurn} of ${chatStore.maxTurns}`
								: `Agent turn ${chatStore.currentTurn}`}
						>
							<Timer size={8} />
							Turn {chatStore.currentTurn}{chatStore.maxTurns != null
								? `/${chatStore.maxTurns}`
								: ''}
						</span>
					{/if}
				{/if}
				{#if chatStore.sessionId && chatStore.sessionUsage.total_tokens > 0}
					<span
						class={css({ flexShrink: '0' })}
						title={`Prompt: ${formatTokens(lastPromptTokens)} | Completion: ${formatTokens(chatStore.lastTurnUsage?.completion_tokens ?? 0)} | Session: ${formatTokens(chatStore.sessionUsage.prompt_tokens)} in / ${formatTokens(chatStore.sessionUsage.completion_tokens)} out / ${formatTokens(chatStore.sessionUsage.total_tokens)} total`}
					>
						{formatTokens(lastPromptTokens)}{chatStore.contextLimit > 0
							? ` / ${formatTokens(chatStore.contextLimit)}`
							: ''}
					</span>
					{#if chatStore.contextLimit > 0}
						<div
							class={css({
								flex: '1',
								minWidth: '20px',
								height: '3px',
								backgroundColor: 'bg.secondary',
								borderRadius: 'full',
								overflow: 'hidden'
							})}
							title={`${Math.round(contextPct)}% context used`}
						>
							<div
								class={css({
									height: '100%',
									borderRadius: 'full',
									backgroundColor: contextBarColor
								})}
								style="width: {contextPct}%"
							></div>
						</div>
						<span
							class={css({
								flexShrink: '0',
								color: contextPct > 70 ? contextBarColor : 'fg.muted'
							})}
						>
							{Math.round(contextPct)}%
						</span>
					{/if}
				{/if}
				{#if modelPickerOpen}
					<div
						class={css({
							position: 'absolute',
							bottom: '100%',
							left: '0',
							minWidth: '260px',
							maxHeight: '200px',
							overflowY: 'auto',
							backgroundColor: 'bg.panel',
							borderWidth: '1',
							borderRadius: 'sm',
							zIndex: 'dropdown',
							boxShadow: 'md',
							marginBottom: '4px'
						})}
					>
						<input
							class={css({
								width: 'full',
								color: 'fg.primary',
								paddingX: '3.5',
								paddingY: '2.25',
								transitionProperty: 'border-color',
								transitionDuration: '160ms',
								transitionTimingFunction: 'ease',
								_focus: { outline: 'none' },
								_focusVisible: { borderColor: 'border.accent' },
								_disabled: {
									opacity: '0.5',
									cursor: 'not-allowed',
									backgroundColor: 'bg.tertiary'
								},
								_placeholder: { color: 'fg.muted' },
								borderRadius: '0',
								borderWidth: '0',
								borderBottomWidth: '1',
								fontSize: 'xs'
							})}
							type="text"
							bind:value={modelPickerSearch}
							placeholder="Search models\u2026"
						/>
						{#if chatStore.modelsLoading}
							<div
								class={css({
									padding: '2',
									textAlign: 'center',
									fontSize: 'xs',
									color: 'fg.muted'
								})}
							>
								<LoaderCircle
									size={12}
									class={css({ animation: 'spin 1s linear infinite', display: 'inline' })}
								/> Loading\u2026
							</div>
						{:else if pickerModels.length === 0}
							<div class={css({ padding: '2', fontSize: 'xs', color: 'fg.muted' })}>
								{chatStore.models.length === 0 ? 'No models loaded' : 'No matches'}
							</div>
						{:else}
							{#each pickerModels.slice(0, 30) as m (m.id)}
								<button
									class={css({
										display: 'flex',
										flexDirection: 'column',
										gap: '0',
										width: '100%',
										textAlign: 'left',
										padding: '1.5',
										paddingX: '2',
										border: 'none',
										backgroundColor: m.id === chatStore.model ? 'bg.accent' : 'transparent',
										color: m.id === chatStore.model ? 'fg.primary' : 'fg.primary',
										cursor: 'pointer',
										_hover: { backgroundColor: 'bg.hover' }
									})}
									onclick={() => pickModel(m.id)}
									type="button"
								>
									<span class={css({ fontSize: 'xs' })}>{m.name}</span>
									<span
										class={css({
											fontSize: '9px',
											color: m.id === chatStore.model ? 'fg.primary' : 'fg.muted',
											fontFamily: 'mono'
										})}
									>
										{m.id}{m.context_length > 0
											? ` \u00b7 ${formatTokens(m.context_length)} ctx`
											: ''}
									</span>
								</button>
							{/each}
						{/if}
					</div>
				{/if}
			</div>
			<!-- Textarea + send button -->
			<div class={css({ display: 'flex', gap: '2', alignItems: 'flex-end' })}>
				<textarea
					class={css({
						width: 'full',
						color: 'fg.primary',
						backgroundColor: 'bg.primary',
						borderWidth: '1',
						borderRadius: '0',
						paddingX: '3.5',
						paddingY: '2.25',
						transitionProperty: 'border-color',
						transitionDuration: '160ms',
						transitionTimingFunction: 'ease',
						_focus: { outline: 'none' },
						_focusVisible: { borderColor: 'border.accent' },
						_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
						_placeholder: { color: 'fg.muted' },
						flex: '1',
						resize: 'none',
						minHeight: '34px',
						maxHeight: '120px',
						fontSize: 'sm'
					})}
					bind:value={inputValue}
					bind:this={inputEl}
					onkeydown={handleKeydown}
					oninput={autoResize}
					onpaste={handlePaste}
					placeholder={inputPlaceholder}
					disabled={!chatStore.configured || chatStore.loading}
					rows={1}
				></textarea>
				{#if chatStore.loading}
					<button
						class={iconButton()}
						onclick={stopGeneration}
						title="Stop generating"
						aria-label="Stop generating"
					>
						<Square size={13} />
					</button>
				{:else}
					<button
						class={iconButton()}
						onclick={() => void handleSend()}
						disabled={!inputValue.trim() || !chatStore.configured}
						title="Send message"
						aria-label="Send message"
					>
						<Send size={14} />
					</button>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	/* Typing indicator dots */
	:global(.chat-dot) {
		display: inline-block;
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background-color: var(--colors-fg-muted);
		animation: chat-bounce 1.4s ease-in-out infinite;
	}
	:global(.chat-dot-1) {
		animation-delay: 0s;
	}
	:global(.chat-dot-2) {
		animation-delay: 0.2s;
	}
	:global(.chat-dot-3) {
		animation-delay: 0.4s;
	}
	@keyframes chat-bounce {
		0%,
		60%,
		100% {
			transform: translateY(0);
			opacity: 0.4;
		}
		30% {
			transform: translateY(-3px);
			opacity: 1;
		}
	}

	/* Markdown styling for assistant messages */
	:global(.chat-markdown p) {
		margin: 0 0 0.4em 0;
	}
	:global(.chat-markdown p:last-child) {
		margin-bottom: 0;
	}
	:global(.chat-markdown code) {
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: 0.85em;
		padding: 0.1em 0.3em;
		border-radius: 3px;
		background-color: var(--colors-bg-tertiary);
	}
	:global(.chat-markdown pre) {
		margin: 0.4em 0;
		padding: 0.6em;
		border-radius: 4px;
		background-color: var(--colors-bg-tertiary);
		overflow-x: auto;
		position: relative;
	}
	:global(.chat-markdown pre code) {
		padding: 0;
		background: none;
		font-size: 0.8em;
		line-height: 1.4;
	}
	:global(.chat-markdown ul),
	:global(.chat-markdown ol) {
		margin: 0.2em 0;
		padding-left: 1.4em;
	}
	:global(.chat-markdown li) {
		margin: 0.1em 0;
	}
	:global(.chat-markdown h1),
	:global(.chat-markdown h2),
	:global(.chat-markdown h3) {
		margin: 0.4em 0 0.2em 0;
		font-size: 1em;
		font-weight: 600;
	}
	:global(.chat-markdown blockquote) {
		margin: 0.4em 0;
		padding-left: 0.6em;
		border-left: 2px solid var(--colors-border-primary);
		color: var(--colors-fg-muted);
	}
	:global(.chat-markdown a) {
		color: var(--colors-accent-primary);
		text-decoration: underline;
	}
	:global(.chat-markdown table) {
		border-collapse: collapse;
		margin: 0.4em 0;
		font-size: 0.85em;
		width: 100%;
	}
	:global(.chat-markdown th),
	:global(.chat-markdown td) {
		border: 1px solid var(--colors-border-default);
		padding: 0.3em 0.4em;
		text-align: left;
	}
	:global(.chat-markdown th) {
		background-color: var(--colors-bg-subtle);
		font-weight: 600;
	}

	/* Copy button visibility on hover */
	:global(.chat-copy-btn) {
		transition: opacity 150ms ease;
	}

	/* Timestamp shown on hover of message group */
	:global(.chat-ts) {
		transition:
			opacity 150ms ease,
			height 150ms ease;
	}
	:global(.chat-msg-enter:hover .chat-ts) {
		opacity: 1 !important;
		height: auto !important;
		overflow: visible !important;
	}

	/* Code block copy button */
	:global(.code-copy-btn) {
		position: absolute;
		top: 4px;
		right: 4px;
		padding: 3px;
		border: none;
		border-radius: 3px;
		background-color: transparent;
		color: var(--colors-fg-muted);
		cursor: pointer;
		opacity: 0;
		transition: opacity 150ms ease;
		line-height: 1;
	}
	:global(.chat-markdown pre:hover .code-copy-btn) {
		opacity: 1;
	}
	:global(.code-copy-btn:hover) {
		color: var(--colors-fg-primary);
		background-color: var(--colors-bg-subtle);
	}

	/* Subtle slide-in for new messages */
	@keyframes chat-msg-in {
		from {
			opacity: 0;
			transform: translateY(4px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
	:global(.chat-msg-enter) {
		animation: chat-msg-in 150ms ease-out;
	}
</style>
