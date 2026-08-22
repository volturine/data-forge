<script lang="ts">
	import { css } from '$lib/styles/panda';
	import { chatStore } from '$lib/stores/chat.svelte';
	import { methodColor, outputHint } from '$lib/chat/presentation';

	interface Props {
		maximized: boolean;
	}

	let { maximized }: Props = $props();

	const tagEntries = $derived(
		Array.from(chatStore.modeFilteredTagGroups.entries()).sort((a, b) => a[0].localeCompare(b[0]))
	);

	const enabledCount = $derived(chatStore.modeFilteredTools.length);
</script>

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
