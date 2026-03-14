<script lang="ts">
	import {
		MessageSquare,
		X,
		Send,
		Check,
		Trash2,
		ChevronDown,
		ChevronUp,
		LogOut,
		Zap,
		Settings2,
		Search,
		Loader2,
		Wrench,
		AlertCircle,
		Edit3
	} from 'lucide-svelte';
	import { css, cx, iconButton, button, input, label } from '$lib/styles/panda';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { chatStore } from '$lib/stores/chat.svelte';
	import type { PendingAction } from '$lib/stores/chat.svelte';
	import type { ChatEvent } from '$lib/api/chat';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ToolArgsForm from '$lib/components/common/ToolArgsForm.svelte';
	import { validateTool, preflightTool, callTool } from '$lib/api/mcp';
	import type { MCPTool } from '$lib/api/mcp';

	const queryClient = useQueryClient();

	let configOpen = $state(false);
	let toolsOpen = $state(false);
	let apiKeyDraft = $state(chatStore.apiKey);
	let modelDraft = $state(chatStore.model);
	let systemPromptDraft = $state(chatStore.systemPrompt);
	let modelSearch = $state('');
	let inputValue = $state('');
	let messagesEl: HTMLElement | undefined;
	let reviewingToolId = $state<string | null>(null);
	let reviewApplying = $state(false);
	let reviewUnsupportedPaths = $state<Set<string>>(new Set());

	function bindMessages(el: HTMLElement) {
		messagesEl = el;
	}

	// DOM: $derived can't scroll on message append
	$effect(() => {
		const _ = chatStore.timeline.length;
		if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
	});

	// Subscription: $derived can't attach event listeners
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

	const tagEntries = $derived(
		Array.from(chatStore.tagGroups.entries()).sort((a, b) => a[0].localeCompare(b[0]))
	);

	const enabledCount = $derived(chatStore.enabledTools.length);

	function openConfig() {
		apiKeyDraft = chatStore.apiKey;
		modelDraft = chatStore.model;
		systemPromptDraft = chatStore.systemPrompt;
		configOpen = !configOpen;
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
		inputValue = '';
		await chatStore.send(text);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			void handleSend();
		}
	}

	function methodColor(method: string): string {
		if (method === 'GET') return 'fg.success';
		if (method === 'DELETE') return 'fg.error';
		if (method === 'POST') return 'fg.accent';
		return 'fg.warning';
	}

	function isDestructive(action: PendingAction): boolean {
		return action.confirm_required;
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

	function findTool(toolId: string): MCPTool | undefined {
		return chatStore.tools.find((t) => t.id === toolId);
	}

	function openReview(toolId: string, args: Record<string, unknown>): void {
		chatStore.removePendingByToolId(toolId);
		chatStore.ensureDraft(toolId, args);
		reviewArgs = { ...args };
		reviewUnsupportedPaths = new Set();
		reviewingToolId = toolId;
	}

	function closeReview(): void {
		reviewingToolId = null;
		reviewUnsupportedPaths = new Set();
	}

	function handleUnsupported(path: string, message: string): void {
		if (reviewingToolId && !reviewUnsupportedPaths.has(path)) {
			reviewUnsupportedPaths = new Set([...reviewUnsupportedPaths, path]);
			const existing = chatStore.toolDrafts.get(reviewingToolId)?.errors ?? [];
			const filtered = existing.filter((e) => e.path !== path);
			chatStore.setDraftErrors(reviewingToolId, [...filtered, { path, message }]);
		}
	}

	async function handleApply(toolId: string): Promise<void> {
		reviewApplying = true;
		chatStore.updateDraft(toolId, reviewArgs);
		const validateResult = await validateTool(toolId, reviewArgs);
		validateResult.match(
			(vr) => {
				if (!vr.valid) {
					chatStore.setDraftErrors(toolId, vr.errors);
					reviewApplying = false;
					return;
				}
				chatStore.setDraftErrors(toolId, []);
				void runPreflight(toolId, vr.args);
			},
			(e) => {
				chatStore.error = e.message;
				reviewApplying = false;
			}
		);
	}

	async function runPreflight(toolId: string, args: Record<string, unknown>): Promise<void> {
		const result = await preflightTool(toolId, args);
		result.match(
			(pr) => {
				if (!pr.valid) {
					chatStore.setDraftErrors(toolId, pr.errors ?? []);
					reviewApplying = false;
					return;
				}
				if (pr.status === 'pending' && pr.token) {
					const tool = findTool(toolId);
					const tc = chatStore.addLocalToolCall(
						pr.tool_id ?? toolId,
						pr.method ?? tool?.method ?? '',
						pr.path ?? tool?.path ?? '',
						pr.args ?? args
					);
					tc.status = 'pending';
					chatStore.pending.push({
						token: pr.token,
						tool_id: pr.tool_id ?? toolId,
						method: pr.method ?? '',
						path: pr.path ?? '',
						args: pr.args ?? args,
						confirm_required: pr.confirm_required ?? false
					});
					chatStore.clearDraft(toolId);
					reviewingToolId = null;
					reviewApplying = false;
					return;
				}
				void executeDirectly(toolId, args);
			},
			(e) => {
				chatStore.error = e.message;
				reviewApplying = false;
			}
		);
	}

	async function executeDirectly(toolId: string, args: Record<string, unknown>): Promise<void> {
		const tool = findTool(toolId);
		chatStore.addLocalToolCall(toolId, tool?.method ?? '', tool?.path ?? '', args);
		const result = await callTool(toolId, args);
		result.match(
			(r) => {
				chatStore.setLocalToolResult(toolId, r.result ?? null);
				void queryClient.invalidateQueries();
				chatStore.clearDraft(toolId);
				reviewingToolId = null;
				reviewApplying = false;
			},
			(e) => {
				chatStore.setLocalToolError(toolId, [{ path: '$', message: e.message }]);
				chatStore.error = e.message;
				reviewApplying = false;
			}
		);
	}

	const reviewTool = $derived(reviewingToolId ? findTool(reviewingToolId) : undefined);
	const reviewErrors = $derived(
		reviewingToolId ? (chatStore.toolDrafts.get(reviewingToolId)?.errors ?? []) : []
	);
	let reviewArgs = $state<Record<string, unknown>>({});
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
			width: '420px',
			maxHeight: '85vh',
			display: 'flex',
			flexDirection: 'column',
			backgroundColor: 'bg.panel',
			borderWidth: '1',
			borderColor: 'border.default',
			borderTopRadius: 'lg',
			boxShadow: 'lg',
			zIndex: 'overlay'
		})}
	>
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between',
				paddingX: '4',
				paddingY: '3',
				borderBottomWidth: '1',
				borderColor: 'border.default',
				flexShrink: '0'
			})}
		>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<MessageSquare size={16} />
				<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>AI Assistant</span>
				{#if chatStore.sessionId}
					<span
						class={css({
							display: 'inline-block',
							height: 'dot',
							width: 'dot',
							flexShrink: '0',
							backgroundColor: connectionColor
						})}
						title={connectionLabel}
					></span>
				{/if}
				{#if chatStore.loading}
					<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>thinking…</span>
				{/if}
				{#if chatStore.sessionId && chatStore.sessionUsage.total_tokens > 0}
					{#if chatStore.contextLimit > 0}
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '1.5',
								fontSize: 'xs',
								color: 'fg.muted'
							})}
							title={`Prompt: ${formatTokens(chatStore.sessionUsage.prompt_tokens)} / Completion: ${formatTokens(chatStore.sessionUsage.completion_tokens)} / Limit: ${formatTokens(chatStore.contextLimit)}`}
						>
							<Zap size={10} />
							<div
								class={css({
									width: '48px',
									height: '4px',
									backgroundColor: 'bg.subtle',
									borderRadius: 'full',
									overflow: 'hidden',
									flexShrink: '0'
								})}
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
							<span class={css({ fontFamily: 'mono', whiteSpace: 'nowrap' })}>
								{formatTokens(chatStore.sessionUsage.total_tokens)}/{formatTokens(
									chatStore.contextLimit
								)}
							</span>
						</div>
					{:else}
						<span
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '1',
								fontSize: 'xs',
								color: 'fg.muted'
							})}
							title={`Prompt: ${chatStore.sessionUsage.prompt_tokens} / Completion: ${chatStore.sessionUsage.completion_tokens}`}
						>
							<Zap size={10} />
							{formatTokens(chatStore.sessionUsage.total_tokens)}
						</span>
					{/if}
				{/if}
			</div>
			<div class={css({ display: 'flex', gap: '1' })}>
				<button class={iconButton()} onclick={openConfig} title="Configure" aria-label="Configure">
					<Settings2 size={14} />
				</button>
				{#if chatStore.sessionId}
					<button
						class={iconButton()}
						onclick={() => chatStore.requestCloseSession()}
						title="Close session"
						aria-label="Close session"
					>
						<LogOut size={14} />
					</button>
				{/if}
				<button
					class={iconButton()}
					onclick={() => chatStore.close()}
					title="Close chat"
					aria-label="Close chat"
				>
					<X size={14} />
				</button>
			</div>
		</div>

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
							placeholder="openai/gpt-4o-mini"
							disabled={!!chatStore.sessionId}
						/>
						<span class={css({ fontSize: 'xs', color: 'fg.muted', marginTop: '0.5' })}>
							Click <Search size={10} class={css({ display: 'inline' })} /> to load available models
						</span>
					{/if}
				</div>

				<div>
					<label class={label()} for="chat-system-prompt">System Prompt</label>
					<textarea
						id="chat-system-prompt"
						class={cx(input(), css({ resize: 'none', minHeight: '48px', maxHeight: '100px' }))}
						bind:value={systemPromptDraft}
						placeholder="Optional instructions sent with every session"
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
									<span
										class={css({
											display: 'inline-block',
											width: '12px',
											height: '12px',
											borderWidth: '1',
											borderColor: 'border.default',
											borderRadius: 'sm',
											backgroundColor: chatStore.isTagEnabled(tag)
												? 'accent.primary'
												: 'transparent',
											flexShrink: '0'
										})}
									></span>
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
											<span
												class={css({
													display: 'inline-block',
													width: '10px',
													height: '10px',
													borderWidth: '1',
													borderColor: 'border.default',
													borderRadius: 'sm',
													backgroundColor: chatStore.isToolEnabled(tool.id)
														? 'accent.primary'
														: 'transparent',
													flexShrink: '0'
												})}
											></span>
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
			</div>
		{/if}

		<div
			class={css({
				flex: '1',
				overflowY: 'auto',
				padding: '3',
				display: 'flex',
				flexDirection: 'column',
				gap: '2',
				minHeight: '0'
			})}
			use:bindMessages
		>
			{#each chatStore.timeline as entry, idx (entry.kind === 'message' ? entry.item.id : entry.item.tool_id + idx)}
				{#if entry.kind === 'message'}
					{@const msg = entry.item}
					{#if msg.role === 'tool'}
						<div
							class={css({
								display: 'flex',
								alignItems: 'flex-start',
								gap: '1.5',
								paddingX: '2',
								paddingY: '1.5',
								borderRadius: 'md',
								backgroundColor: 'bg.errorSubtle',
								borderWidth: '1',
								borderColor: 'border.error',
								fontSize: 'xs',
								color: 'fg.error'
							})}
						>
							<AlertCircle size={12} class={css({ flexShrink: '0', marginTop: '0.5' })} />
							<pre
								class={css({
									margin: '0',
									whiteSpace: 'pre-wrap',
									wordBreak: 'break-word',
									fontFamily: 'mono'
								})}>{msg.content}</pre>
						</div>
					{:else}
						<div
							class={css({
								display: 'flex',
								flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
								gap: '2'
							})}
						>
							<div
								class={css({
									maxWidth: '85%',
									padding: '2',
									borderRadius: 'md',
									fontSize: 'sm',
									backgroundColor: msg.role === 'user' ? 'bg.accent' : 'bg.subtle',
									color: msg.role === 'user' ? 'fg.onAccent' : 'fg.default',
									whiteSpace: 'pre-wrap',
									wordBreak: 'break-word'
								})}
							>
								{msg.content}
							</div>
						</div>
					{/if}
				{:else}
					{@const tc = entry.item}
					<div
						class={css({
							borderWidth: '1',
							borderColor: tc.status === 'error' ? 'border.error' : 'border.default',
							borderRadius: 'md',
							overflow: 'hidden',
							fontSize: 'xs'
						})}
					>
						<button
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '2',
								width: '100%',
								padding: '2',
								border: 'none',
								backgroundColor: tc.status === 'error' ? 'bg.errorSubtle' : 'bg.subtle',
								cursor: 'pointer',
								textAlign: 'left',
								color: 'fg.muted'
							})}
							onclick={() => (tc.expanded = !tc.expanded)}
							type="button"
						>
							<Wrench size={10} class={css({ flexShrink: '0', color: 'fg.muted' })} />
							<span
								class={css({
									color: methodColor(tc.method),
									fontWeight: 'medium',
									flexShrink: '0'
								})}>{tc.method}</span
							>
							<span
								class={css({
									fontFamily: 'mono',
									flex: '1',
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap'
								})}>{tc.path}</span
							>
							<span
								class={css({
									fontWeight: 'medium',
									flexShrink: '0',
									color:
										tc.status === 'done'
											? 'fg.success'
											: tc.status === 'error'
												? 'fg.error'
												: tc.status === 'pending'
													? 'fg.warning'
													: 'fg.muted'
								})}
							>
								{tc.status}
							</span>
							{#if tc.expanded}<ChevronUp size={10} />{:else}<ChevronDown size={10} />{/if}
						</button>
						{#if tc.expanded}
							<div
								class={css({
									padding: '2',
									backgroundColor: 'bg.canvas',
									fontFamily: 'mono',
									fontSize: 'xs',
									overflowX: 'auto',
									maxHeight: '200px',
									overflowY: 'auto',
									borderTopWidth: '1',
									borderColor: 'border.subtle'
								})}
							>
								{#if Object.keys(tc.args).length > 0}
									<div class={css({ color: 'fg.muted', marginBottom: '1' })}>Args</div>
									<pre
										class={css({
											margin: '0',
											whiteSpace: 'pre-wrap',
											wordBreak: 'break-word'
										})}>{JSON.stringify(tc.args, null, 2)}</pre>
								{/if}
								{#if tc.errors && tc.errors.length > 0}
									<div class={css({ color: 'fg.error', marginTop: '1', marginBottom: '1' })}>
										Validation Errors
									</div>
									{#each tc.errors as err (err.path)}
										<div class={css({ color: 'fg.error', marginBottom: '0.5' })}>
											<span class={css({ fontWeight: 'medium' })}>{err.path}</span>: {err.message}
										</div>
									{/each}
								{/if}
								{#if tc.result !== undefined}
									<div class={css({ color: 'fg.muted', marginTop: '1', marginBottom: '1' })}>
										Result
									</div>
									<pre
										class={css({
											margin: '0',
											whiteSpace: 'pre-wrap',
											wordBreak: 'break-word'
										})}>{JSON.stringify(tc.result, null, 2)}</pre>
								{/if}
							</div>
						{/if}
						{#if (tc.status === 'pending' || tc.status === 'running') && findTool(tc.tool_id)}
							<div
								class={css({
									padding: '2',
									borderTopWidth: '1',
									borderColor: 'border.subtle',
									display: 'flex',
									gap: '2'
								})}
							>
								<button
									class={button({ variant: 'primary', size: 'sm' })}
									onclick={() => openReview(tc.tool_id, tc.args)}
									type="button"
								>
									<Edit3 size={10} />
									Review &amp; Apply
								</button>
							</div>
						{/if}
					</div>
				{/if}
			{/each}
		</div>

		{#if chatStore.pending.length}
			<div
				class={css({
					padding: '3',
					borderTopWidth: '1',
					borderColor: 'border.default',
					display: 'flex',
					flexDirection: 'column',
					gap: '2',
					flexShrink: '0'
				})}
			>
				<span class={css({ fontSize: 'xs', fontWeight: 'medium', color: 'fg.muted' })}
					>Pending Actions</span
				>
				{#each chatStore.pending as action (action.token)}
					<div
						class={css({
							padding: '2',
							borderRadius: 'md',
							borderWidth: '1',
							borderColor: isDestructive(action) ? 'border.error' : 'border.default',
							backgroundColor: isDestructive(action) ? 'bg.errorSubtle' : 'bg.subtle',
							display: 'flex',
							flexDirection: 'column',
							gap: '1'
						})}
					>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2', fontSize: 'xs' })}>
							<span class={css({ color: methodColor(action.method), fontWeight: 'medium' })}
								>{action.method}</span
							>
							<span class={css({ fontFamily: 'mono', flex: '1' })}>{action.path}</span>
						</div>
						{#if isDestructive(action)}
							<span class={css({ fontSize: 'xs', color: 'fg.error' })}
								>This action requires confirmation.</span
							>
						{/if}
						<div class={css({ display: 'flex', gap: '2' })}>
							<button
								class={button({
									variant: isDestructive(action) ? 'danger' : 'primary',
									size: 'sm'
								})}
								onclick={() => void chatStore.apply(action.token)}
							>
								<Check size={12} />
								Apply
							</button>
							<button
								class={button({ variant: 'ghost', size: 'sm' })}
								onclick={() => chatStore.dismiss(action.token)}
							>
								<Trash2 size={12} />
								Dismiss
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		{#if chatStore.error}
			<div
				class={css({
					paddingX: '3',
					paddingY: '2',
					color: 'fg.error',
					fontSize: 'xs',
					flexShrink: '0'
				})}
			>
				{chatStore.error}
			</div>
		{/if}

		{#if reviewingToolId && reviewTool}
			<div
				class={css({
					position: 'absolute',
					inset: '0',
					backgroundColor: 'bg.panel',
					display: 'flex',
					flexDirection: 'column',
					zIndex: '1',
					borderTopRadius: 'lg'
				})}
			>
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						paddingX: '4',
						paddingY: '3',
						borderBottomWidth: '1',
						borderColor: 'border.default',
						flexShrink: '0'
					})}
				>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
						<Edit3 size={14} />
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Review & Apply</span>
					</div>
					<button
						class={iconButton()}
						onclick={closeReview}
						title="Close review"
						aria-label="Close review"
					>
						<X size={14} />
					</button>
				</div>

				<div
					class={css({
						paddingX: '4',
						paddingY: '2',
						borderBottomWidth: '1',
						borderColor: 'border.default',
						flexShrink: '0'
					})}
				>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2', fontSize: 'xs' })}>
						<span
							class={css({
								color: methodColor(reviewTool.method),
								fontWeight: 'medium',
								fontFamily: 'mono'
							})}
						>
							{reviewTool.method}
						</span>
						<span
							class={css({
								fontFamily: 'mono',
								color: 'fg.muted',
								flex: '1',
								overflow: 'hidden',
								textOverflow: 'ellipsis',
								whiteSpace: 'nowrap'
							})}
						>
							{reviewTool.path}
						</span>
					</div>
					{#if reviewTool.description}
						<p class={css({ fontSize: 'xs', color: 'fg.muted', marginTop: '1', margin: '0' })}>
							{reviewTool.description}
						</p>
					{/if}
				</div>

				<div
					class={css({
						flex: '1',
						overflowY: 'auto',
						padding: '4'
					})}
				>
					<ToolArgsForm
						schema={reviewTool.input_schema}
						bind:value={reviewArgs}
						errors={reviewErrors}
						onunsupported={handleUnsupported}
					/>
				</div>

				{#if reviewErrors.length > 0}
					<div
						class={css({
							paddingX: '4',
							paddingY: '2',
							borderTopWidth: '1',
							borderColor: 'border.error',
							backgroundColor: 'bg.errorSubtle',
							flexShrink: '0'
						})}
					>
						{#each reviewErrors as err (err.path)}
							<div class={css({ fontSize: 'xs', color: 'fg.error' })}>
								<span class={css({ fontWeight: 'medium' })}>{err.path}</span>: {err.message}
							</div>
						{/each}
					</div>
				{/if}

				<div
					class={css({
						display: 'flex',
						gap: '2',
						padding: '3',
						borderTopWidth: '1',
						borderColor: 'border.default',
						flexShrink: '0'
					})}
				>
					<button
						class={button({
							variant: reviewTool.confirm_required ? 'danger' : 'primary',
							size: 'sm'
						})}
						onclick={() => void handleApply(reviewingToolId!)}
						disabled={reviewApplying || reviewUnsupportedPaths.size > 0}
					>
						{#if reviewApplying}
							<Loader2 size={12} class={css({ animation: 'spin 1s linear infinite' })} />
						{:else}
							<Check size={12} />
						{/if}
						{reviewTool.confirm_required ? 'Confirm & Apply' : 'Apply'}
					</button>
					<button
						class={button({ variant: 'ghost', size: 'sm' })}
						onclick={closeReview}
						disabled={reviewApplying}
					>
						Cancel
					</button>
				</div>
			</div>
		{/if}

		<div
			class={css({
				display: 'flex',
				gap: '2',
				padding: '3',
				borderTopWidth: '1',
				borderColor: 'border.default',
				flexShrink: '0'
			})}
		>
			<textarea
				class={cx(
					input(),
					css({ flex: '1', resize: 'none', minHeight: '36px', maxHeight: '120px' })
				)}
				bind:value={inputValue}
				onkeydown={handleKeydown}
				placeholder={chatStore.configured ? 'Ask anything…' : 'Loading…'}
				disabled={!chatStore.configured || chatStore.loading}
				rows={1}
			></textarea>
			<button
				class={iconButton()}
				onclick={() => void handleSend()}
				disabled={!inputValue.trim() || !chatStore.configured || chatStore.loading}
				title="Send message"
				aria-label="Send message"
			>
				<Send size={16} />
			</button>
		</div>
	</div>
{/if}
