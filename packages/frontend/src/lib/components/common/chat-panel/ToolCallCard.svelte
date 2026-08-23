<script lang="ts">
	import {
		LoaderCircle,
		ShieldAlert,
		CircleCheck,
		CircleX,
		Wrench,
		ChevronUp,
		ChevronDown,
		Check,
		Ban,
		Copy,
		ClipboardCheck
	} from '@lucide/svelte';
	import { css } from '$lib/styles/panda';
	import { chatStore } from '$lib/stores/chat.svelte';
	import type { ToolCall } from '$lib/stores/chat.svelte';
	import {
		formatDuration,
		methodColor,
		resultSummary,
		toolDisplayName
	} from '$lib/chat/presentation';

	interface Props {
		tc: ToolCall;
		tick: number;
	}

	let { tc, tick }: Props = $props();

	const summary = $derived(resultSummary(tc.result));
	const toolDef = $derived(chatStore.tools.find((t) => t.id === tc.tool_id));
	const elapsed = $derived(
		tc.startedAt && tc.status === 'running' ? tick - tc.startedAt : undefined
	);

	let copiedId = $state<string | null>(null);

	async function copyToClipboard(text: string, id: string) {
		await navigator.clipboard.writeText(text).catch(() => {});
		copiedId = id;
	}

	// Auto-clear the copied indicator; timer is cancelled on teardown
	$effect(() => {
		if (!copiedId) return;
		const id = copiedId;
		const timer = setTimeout(() => {
			if (copiedId === id) copiedId = null;
		}, 2000);
		return () => clearTimeout(timer);
	});
</script>

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
							void copyToClipboard(JSON.stringify(tc.args, null, 2), `args-${tc.tool_id}`)}
						type="button"
						title="Copy arguments"
					>
						{#if copiedId === `args-${tc.tool_id}`}<ClipboardCheck size={9} />{:else}<Copy
								size={9}
							/>{/if}
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
				<div class={css({ color: 'fg.error', marginTop: '1', marginBottom: '0.5' })}>Errors</div>
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
							void copyToClipboard(JSON.stringify(tc.result, null, 2), `result-${tc.tool_id}`)}
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
