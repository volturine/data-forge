<script lang="ts">
	import {
		X,
		Send,
		Square,
		ChevronDown,
		ChevronUp,
		LogOut,
		Settings2,
		Search,
		Loader2,
		Wrench,
		AlertCircle,
		Copy,
		ClipboardCheck,
		ArrowDown,
		RotateCcw,
		Maximize2,
		Minimize2,
		Eye,
		Play,
		CheckCircle2,
		XCircle,
		History,
		RefreshCw
	} from 'lucide-svelte';
	import { css, cx, iconButton, button, input, label } from '$lib/styles/panda';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { chatStore } from '$lib/stores/chat.svelte';
	import type { ChatEvent } from '$lib/api/chat';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { renderMarkdown, timeAgo } from '$lib/utils/markdown';

	const queryClient = useQueryClient();

	let configOpen = $state(false);
	let toolsOpen = $state(false);
	let sessionsOpen = $state(false);
	let apiKeyDraft = $state(chatStore.apiKey);
	let modelDraft = $state(chatStore.model);
	let systemPromptDraft = $state(chatStore.systemPrompt);
	let modelSearch = $state('');
	let inputValue = $state('');
	let messagesEl: HTMLElement | undefined;
	let copiedId = $state<string | null>(null);
	let userScrolledUp = $state(false);
	let inputEl = $state<HTMLTextAreaElement | undefined>();
	let maximized = $state(false);
	let modelPickerOpen = $state(false);
	let modelPickerSearch = $state('');
	let panelHeight = $state(500);
	let isResizing = $state(false);

	function stopGeneration() {
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

	$effect(() => {
		const _ = chatStore.timeline.length;
		const _l = chatStore.loading;
		void _l;
		if (!userScrolledUp && messagesEl) {
			requestAnimationFrame(() => {
				requestAnimationFrame(() => {
					messagesEl?.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
				});
			});
		}
	});

	$effect(() => {
		if (typeof window === 'undefined') return;
		function onPatch(e: Event) {
			const detail = (e as CustomEvent<ChatEvent>).detail;
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

	$effect(() => {
		if (!chatStore.open) return;
		if (typeof window === 'undefined') return;
		function onKey(e: KeyboardEvent) {
			if (e.key === 'Escape') {
				if (configOpen) {
					configOpen = false;
				} else {
					chatStore.close();
				}
			}
		}
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	});

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

	// Inject copy buttons into rendered code blocks
	$effect(() => {
		const _ = chatStore.timeline.length;
		if (!messagesEl) return;
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
			}
		});
	});

	const connectionColor = $derived(
		chatStore.connection === 'connected'
			? 'success.fg'
			: chatStore.connection === 'reconnecting'
				? 'fg.warning'
				: 'fg.muted'
	);

	const connectionLabel = $derived(
		chatStore.connection === 'connected'
			? 'Connected'
			: chatStore.connection === 'reconnecting'
				? 'Reconnecting…'
				: 'Disconnected'
	);

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
		if (modelPickerOpen && chatStore.apiKey && chatStore.models.length === 0) {
			void chatStore.loadModels();
		}
	}

	function startResize(e: PointerEvent) {
		e.preventDefault();
		isResizing = true;
		const startY = e.clientY;
		const startH = panelHeight;
		function onMove(ev: PointerEvent) {
			const delta = startY - ev.clientY;
			panelHeight = Math.max(300, Math.min(window.innerHeight * 0.95, startH + delta));
		}
		function onUp() {
			isResizing = false;
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
		}
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}

	const tagEntries = $derived(
		Array.from(chatStore.tagGroups.entries()).sort((a, b) => a[0].localeCompare(b[0]))
	);

	const enabledCount = $derived(chatStore.enabledTools.length);

	function openConfig() {
		apiKeyDraft = chatStore.apiKey;
		modelDraft = chatStore.model;
		systemPromptDraft = chatStore.systemPrompt;
		configOpen = !configOpen;
		if (configOpen && chatStore.apiKey && chatStore.models.length === 0) {
			void chatStore.loadModels();
		}
		if (configOpen) {
			void chatStore.loadSessions();
		}
	}

	function saveConfig() {
		chatStore.apiKey = apiKeyDraft;
		chatStore.model = modelDraft;
		chatStore.systemPrompt = systemPromptDraft;
		chatStore.configure(apiKeyDraft);
		configOpen = false;
	}

	function handleLoadModels() {
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
		} else {
			requestAnimationFrame(() => inputEl?.focus());
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			void handleSend();
		}
	}

	async function copyToClipboard(text: string, id: string) {
		await navigator.clipboard.writeText(text);
		copiedId = id;
		setTimeout(() => {
			if (copiedId === id) copiedId = null;
		}, 2000);
	}

	function methodColor(method: string): string {
		if (method === 'GET') return 'fg.success';
		if (method === 'DELETE') return 'fg.error';
		if (method === 'POST') return 'fg.accent';
		return 'fg.warning';
	}

	function formatTokens(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
		return String(n);
	}

	const contextPct = $derived(
		chatStore.contextLimit > 0
			? Math.min(100, (chatStore.sessionUsage.total_tokens / chatStore.contextLimit) * 100)
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
		class={css({
			position: 'fixed',
			bottom: '0',
			right: '4',
			display: 'flex',
			flexDirection: 'column',
			backgroundColor: 'bg.panel',
			borderWidth: '1',
			borderColor: 'border.default',
			borderTopRadius: 'lg',
			boxShadow: 'lg',
			zIndex: 'overlay',
			userSelect: isResizing ? 'none' : 'auto'
		})}
		style="width: {maximized ? '640px' : '420px'}; height: {maximized
			? '95vh'
			: panelHeight + 'px'}"
	>
		<!-- Resize handle -->
		<div
			role="separator"
			aria-orientation="horizontal"
			class={css({
				height: '4px',
				cursor: 'ns-resize',
				flexShrink: '0',
				borderTopRadius: 'lg',
				_hover: { backgroundColor: 'accent.primary' }
			})}
			style="touch-action: none"
			onpointerdown={startResize}
		></div>

		<!-- Header -->
		<div
			class={css({
				borderBottomWidth: '1',
				borderColor: 'border.default',
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
							borderColor: 'border.default',
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
								color: chatStore.mode === 'plan' ? 'fg.onAccent' : 'fg.muted',
								_hover: chatStore.mode === 'plan' ? {} : { backgroundColor: 'bg.subtle' }
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
								borderColor: 'border.default',
								cursor: 'pointer',
								backgroundColor: chatStore.mode === 'execute' ? 'fg.default' : 'transparent',
								color: chatStore.mode === 'execute' ? 'bg.panel' : 'fg.muted',
								_hover: chatStore.mode === 'execute' ? {} : { backgroundColor: 'bg.subtle' }
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
						<Loader2
							size={10}
							class={css({ animation: 'spin 1s linear infinite', flexShrink: '0' })}
						/>
					{/if}
				</div>
				<div class={css({ display: 'flex', gap: '0.5', flexShrink: '0' })}>
					<button
						class={iconButton()}
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
					{#if chatStore.sessionId}
						<button
							class={iconButton()}
							onclick={() => chatStore.requestCloseSession()}
							title="Close session"
							aria-label="Close session"
						>
							<LogOut size={13} />
						</button>
					{/if}
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
			<!-- Info bar: model + tokens + context -->
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					paddingX: '3',
					paddingY: '1',
					backgroundColor: 'bg.subtle',
					fontSize: '10px',
					fontFamily: 'mono',
					color: 'fg.muted'
				})}
			>
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
				{/if}
				<div class={css({ position: 'relative', flexShrink: '0' })}>
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
							_hover: { color: 'fg.default' }
						})}
						onclick={toggleModelPicker}
						type="button"
						title={chatStore.model}
					>
						{chatStore.modelDisplayName}
						<ChevronDown size={8} />
					</button>
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
								borderColor: 'border.default',
								borderRadius: 'sm',
								zIndex: 'dropdown',
								boxShadow: 'md',
								marginBottom: '2px'
							})}
						>
							<input
								class={cx(
									input(),
									css({
										borderRadius: '0',
										borderWidth: '0',
										borderBottomWidth: '1',
										fontSize: 'xs'
									})
								)}
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
									<Loader2
										size={12}
										class={css({ animation: 'spin 1s linear infinite', display: 'inline' })}
									/> Loading\u2026
								</div>
							{:else if pickerModels.length === 0}
								<div class={css({ padding: '2', fontSize: 'xs', color: 'fg.muted' })}>
									{chatStore.models.length === 0
										? 'No models loaded \u2014 set API key first'
										: 'No matches'}
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
											color: m.id === chatStore.model ? 'fg.onAccent' : 'fg.default',
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
												color: m.id === chatStore.model ? 'fg.onAccent' : 'fg.muted',
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
				{#if chatStore.sessionId && chatStore.sessionUsage.total_tokens > 0}
					<span class={css({ color: 'border.default' })}>|</span>
					<span
						title={`Prompt: ${formatTokens(chatStore.sessionUsage.prompt_tokens)} / Completion: ${formatTokens(chatStore.sessionUsage.completion_tokens)}`}
					>
						{formatTokens(chatStore.sessionUsage.total_tokens)}{chatStore.contextLimit > 0
							? ` / ${formatTokens(chatStore.contextLimit)}`
							: ''}
					</span>
					{#if chatStore.contextLimit > 0}
						<div
							class={css({
								flex: '1',
								minWidth: '20px',
								height: '3px',
								backgroundColor: 'bg.canvas',
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
			</div>
		</div>

		<!-- Config panel -->
		{#if configOpen}
			<div
				class={css({
					padding: '3',
					borderBottomWidth: '1',
					borderColor: 'border.default',
					display: 'flex',
					flexDirection: 'column',
					gap: '2',
					flexShrink: '0',
					maxHeight: '60vh',
					overflowY: 'auto'
				})}
			>
				<div>
					<label class={label()} for="chat-key">API Key</label>
					<div class={css({ display: 'flex', gap: '1' })}>
						<input
							id="chat-key"
							class={cx(input(), css({ flex: '1' }))}
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
								<Loader2 size={12} class={css({ animation: 'spin 1s linear infinite' })} />
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
										borderColor: 'border.default',
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
												color: m.id === modelDraft ? 'fg.onAccent' : 'fg.default',
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
						class={cx(input(), css({ resize: 'none', minHeight: '48px', maxHeight: '100px' }))}
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

				<button
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '1',
						fontSize: 'xs',
						color: 'fg.muted',
						background: 'none',
						border: 'none',
						cursor: 'pointer',
						padding: '0',
						textAlign: 'left'
					})}
					onclick={() => (toolsOpen = !toolsOpen)}
					type="button"
				>
					{#if toolsOpen}<ChevronUp size={12} />{:else}<ChevronDown size={12} />{/if}
					Tools ({enabledCount}/{chatStore.tools.length})
					{#if chatStore.mode === 'plan'}
						<span class={css({ color: 'fg.muted', fontStyle: 'italic' })}
							>— read-only in plan mode</span
						>
					{/if}
				</button>

				{#if toolsOpen}
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '1',
							padding: '2',
							backgroundColor: 'bg.subtle',
							borderRadius: 'md',
							fontSize: 'xs',
							maxHeight: '240px',
							overflowY: 'auto'
						})}
					>
						{#each tagEntries as [tag, tagTools] (tag)}
							<div>
								<button
									class={css({
										display: 'flex',
										alignItems: 'center',
										gap: '2',
										width: '100%',
										border: 'none',
										backgroundColor: 'transparent',
										cursor: 'pointer',
										padding: '1',
										paddingX: '0',
										fontSize: 'xs',
										textAlign: 'left'
									})}
									onclick={() => chatStore.toggleTag(tag)}
									type="button"
									disabled={!!chatStore.sessionId}
								>
									<div
										class={css({
											width: '28px',
											height: '16px',
											borderRadius: 'full',
											backgroundColor: chatStore.isTagEnabled(tag)
												? 'accent.primary'
												: 'bg.tertiary',
											flexShrink: '0',
											position: 'relative'
										})}
									>
										<div
											class={css({
												width: '12px',
												height: '12px',
												borderRadius: 'full',
												backgroundColor: 'white',
												position: 'absolute',
												top: '2px'
											})}
											style="left: {chatStore.isTagEnabled(tag) ? '14px' : '2px'}"
										></div>
									</div>
									<span
										class={css({
											fontWeight: 'medium',
											textTransform: 'uppercase',
											letterSpacing: 'wide'
										})}
									>
										{tag}
									</span>
									<span class={css({ color: 'fg.muted', marginLeft: 'auto' })}>
										{tagTools.filter((t) => chatStore.isToolEnabled(t.id)).length}/{tagTools.length}
									</span>
								</button>
								<div
									class={css({
										paddingLeft: '4',
										display: 'flex',
										flexDirection: 'column',
										gap: '0'
									})}
								>
									{#each tagTools as tool (tool.id)}
										<button
											class={css({
												display: 'flex',
												alignItems: 'center',
												gap: '2',
												width: '100%',
												border: 'none',
												backgroundColor: 'transparent',
												cursor: 'pointer',
												padding: '0.5',
												paddingX: '0',
												fontSize: 'xs',
												textAlign: 'left',
												opacity: chatStore.isToolEnabled(tool.id) ? 1 : 0.4
											})}
											onclick={() => chatStore.toggleTool(tool.id)}
											type="button"
											disabled={!!chatStore.sessionId}
										>
											<div
												class={css({
													width: '24px',
													height: '14px',
													borderRadius: 'full',
													backgroundColor: chatStore.isToolEnabled(tool.id)
														? 'accent.primary'
														: 'bg.tertiary',
													flexShrink: '0',
													position: 'relative'
												})}
											>
												<div
													class={css({
														width: '10px',
														height: '10px',
														borderRadius: 'full',
														backgroundColor: 'white',
														position: 'absolute',
														top: '2px'
													})}
													style="left: {chatStore.isToolEnabled(tool.id) ? '12px' : '2px'}"
												></div>
											</div>
											<span
												class={css({
													color: methodColor(tool.method),
													fontWeight: 'medium',
													fontFamily: 'mono',
													flexShrink: '0'
												})}
											>
												{tool.method}
											</span>
											<span
												class={css({
													fontFamily: 'mono',
													color: 'fg.subtle',
													flex: '1',
													overflow: 'hidden',
													textOverflow: 'ellipsis',
													whiteSpace: 'nowrap'
												})}
											>
												{tool.path}
											</span>
										</button>
									{/each}
								</div>
							</div>
						{/each}
						{#if chatStore.tools.length === 0}
							<span class={css({ color: 'fg.muted' })}>No tools loaded</span>
						{/if}
					</div>
				{/if}

				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '1'
					})}
				>
					<button
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '1',
							fontSize: 'xs',
							color: 'fg.muted',
							background: 'none',
							border: 'none',
							cursor: 'pointer',
							padding: '0',
							textAlign: 'left',
							flex: '1'
						})}
						onclick={() => (sessionsOpen = !sessionsOpen)}
						type="button"
					>
						{#if sessionsOpen}<ChevronUp size={12} />{:else}<ChevronDown size={12} />{/if}
						Sessions
					</button>
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

				{#if sessionsOpen}
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '1',
							padding: '2',
							backgroundColor: 'bg.subtle',
							borderRadius: 'md',
							fontSize: 'xs',
							maxHeight: '200px',
							overflowY: 'auto'
						})}
					>
						{#each chatStore.sessions as session (session.id)}
							<button
								class={css({
									display: 'flex',
									flexDirection: 'column',
									gap: '0.5',
									width: '100%',
									textAlign: 'left',
									padding: '2',
									paddingX: '2',
									borderWidth: '1',
									borderColor: 'border.default',
									borderRadius: 'md',
									backgroundColor: 'transparent',
									color: 'fg.secondary',
									cursor: 'pointer',
									_hover: { backgroundColor: 'bg.hover', borderColor: 'border.primary' }
								})}
								onclick={() => void chatStore.resumeSession(session.id)}
								type="button"
								disabled={chatStore.loading}
							>
								<span
									class={css({
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap',
										color: session.preview ? 'fg.default' : 'fg.muted'
									})}
								>
									{session.preview || 'Empty session'}
								</span>
								<span class={css({ fontSize: '10px', color: 'fg.muted', fontFamily: 'mono' })}>
									{session.model}
								</span>
							</button>
						{/each}
						{#if chatStore.sessions.length === 0}
							<span class={css({ color: 'fg.muted' })}>No sessions</span>
						{/if}
					</div>
				{/if}
			</div>
		{/if}

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
										borderColor: 'border.default',
										borderRadius: 'md',
										backgroundColor: 'transparent',
										color: 'fg.secondary',
										cursor: 'pointer',
										_hover: { backgroundColor: 'bg.subtle', borderColor: 'border.primary' }
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
								<button
									class={css({
										display: 'flex',
										flexDirection: 'column',
										gap: '0.5',
										width: '100%',
										textAlign: 'left',
										padding: '2',
										paddingX: '3',
										fontSize: 'xs',
										borderWidth: '1',
										borderColor: 'border.default',
										borderRadius: 'md',
										backgroundColor: 'transparent',
										color: 'fg.secondary',
										cursor: 'pointer',
										_hover: { backgroundColor: 'bg.subtle', borderColor: 'border.primary' }
									})}
									onclick={() => void chatStore.resumeSession(session.id)}
									type="button"
									disabled={chatStore.loading}
								>
									<span
										class={css({
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											whiteSpace: 'nowrap',
											color: session.preview ? 'fg.default' : 'fg.muted'
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
										{session.model}
									</span>
								</button>
							{/each}
						</div>
					{/if}
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
						<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.subtle' })}></div>
						<span class={css({ fontSize: '10px', color: 'fg.muted', whiteSpace: 'nowrap' })}
							>{dateLabel}</span
						>
						<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.subtle' })}></div>
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
							<AlertCircle size={10} class={css({ flexShrink: '0', marginTop: '1px' })} />
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
							class={cx(
								'chat-msg-enter',
								css({
									display: 'flex',
									flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
									gap: '1.5',
									marginTop: grouped ? '-0.5' : '0'
								})
							)}
						>
							{#if msg.role === 'assistant'}
								{#if !grouped}
									<div
										class={css({
											width: '22px',
											height: '22px',
											borderRadius: 'full',
											backgroundColor:
												chatStore.mode === 'execute' ? 'accent.primary' : 'bg.subtle',
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
									class={cx(
										css({
											padding: '2',
											borderRadius: 'md',
											fontSize: 'sm',
											backgroundColor: msg.role === 'user' ? 'bg.accent' : 'bg.subtle',
											color: msg.role === 'user' ? 'fg.onAccent' : 'fg.default',
											wordBreak: 'break-word',
											position: 'relative',
											lineHeight: '1.5',
											_hover: { '& .chat-copy-btn': { opacity: '1' } }
										}),
										msg.role === 'assistant' ? 'chat-markdown' : ''
									)}
								>
									{#if msg.role === 'assistant'}
										<!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown from our own AI, not user-supplied HTML -->
										{@html renderMarkdown(msg.content)}
									{:else}
										<span class={css({ whiteSpace: 'pre-wrap' })}>{msg.content}</span>
									{/if}
									<button
										class={cx(
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
										)}
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
									class={cx(
										'chat-ts',
										css({
											fontSize: '10px',
											color: 'fg.muted',
											paddingX: '1'
										})
									)}
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
					<div
						class={css({
							borderRadius: 'md',
							overflow: 'hidden',
							fontSize: '11px',
							marginLeft: '30px',
							maxWidth: 'calc(100% - 30px)',
							minWidth: '0',
							backgroundColor: 'bg.canvas',
							borderWidth: '1',
							borderColor:
								tc.status === 'error'
									? 'border.error'
									: tc.status === 'done'
										? 'border.subtle'
										: 'border.default'
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
								color: 'fg.default'
							})}
							onclick={() => (tc.expanded = !tc.expanded)}
							type="button"
						>
							{#if tc.status === 'running'}
								<Loader2
									size={11}
									class={css({
										animation: 'spin 1s linear infinite',
										flexShrink: '0',
										color: 'accent.primary'
									})}
								/>
							{:else if tc.status === 'done'}
								<CheckCircle2 size={11} class={css({ flexShrink: '0', color: 'fg.success' })} />
							{:else}
								<XCircle size={11} class={css({ flexShrink: '0', color: 'fg.error' })} />
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
						{#if tc.expanded}
							<div
								class={css({
									padding: '2',
									fontFamily: 'mono',
									fontSize: '10px',
									overflow: 'auto',
									maxHeight: '200px',
									borderTopWidth: '1',
									borderColor: 'border.subtle',
									backgroundColor: 'bg.subtle',
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
								{#if Object.keys(tc.args).length > 0}
									<div class={css({ color: 'fg.muted', marginTop: '1', marginBottom: '0.5' })}>
										Arguments
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
									<div class={css({ color: 'fg.muted', marginTop: '1', marginBottom: '0.5' })}>
										Response
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
							backgroundColor: 'bg.subtle',
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
							borderColor: 'accent.primary',
							backgroundColor: 'transparent',
							color: 'accent.primary',
							fontSize: '11px',
							fontWeight: 'medium',
							cursor: 'pointer',
							_hover: { backgroundColor: 'bg.accent', color: 'fg.onAccent' }
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
							borderColor: 'border.default',
							backgroundColor: 'transparent',
							color: 'fg.muted',
							fontSize: '11px',
							cursor: 'pointer',
							_hover: { backgroundColor: 'bg.subtle' }
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
						borderColor: 'border.default',
						backgroundColor: 'bg.panel',
						color: 'fg.muted',
						fontSize: '11px',
						cursor: 'pointer',
						boxShadow: 'md',
						zIndex: '1',
						_hover: { backgroundColor: 'bg.subtle' }
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
				<AlertCircle size={11} class={css({ color: 'fg.error', flexShrink: '0' })} />
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
							_hover: { backgroundColor: 'bg.subtle' }
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

		<!-- Input area -->
		<div
			class={css({
				display: 'flex',
				gap: '2',
				padding: '2',
				paddingX: '3',
				borderTopWidth: '1',
				borderColor: 'border.default',
				flexShrink: '0',
				alignItems: 'flex-end'
			})}
		>
			<textarea
				class={cx(
					input(),
					css({ flex: '1', resize: 'none', minHeight: '34px', maxHeight: '120px', fontSize: 'sm' })
				)}
				bind:value={inputValue}
				bind:this={inputEl}
				onkeydown={handleKeydown}
				oninput={autoResize}
				placeholder={chatStore.configured ? 'Message… (Enter to send)' : 'Loading…'}
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
