<script lang="ts">
	import type { PipelineStep } from '#lib/types/analysis.js';
	import type { Schema } from '#lib/types/schema.js';
	import PanelHeader from '#lib/components/ui/PanelHeader.svelte';
	import Callout from '#lib/components/ui/Callout.svelte';
	import { Settings2, X } from '@lucide/svelte';
	import { button, css, spinner } from '#lib/styles/panda.js';

	interface Props {
		step?: PipelineStep | null;
		schema: Schema | null;
		isLoadingSchema?: boolean;
		onClose?: () => void;
		onConfigApply?: () => void;
		readOnly?: boolean;
	}

	let {
		step = $bindable(null),
		schema,
		isLoadingSchema = false,
		onClose,
		onConfigApply,
		readOnly = false
	}: Props = $props();
	let loadAttempt = $state(0);

	const selectedPanelClass = [
		'step-config',
		css({
			boxSizing: 'border-box',
			display: 'flex',
			height: '100%',
			minHeight: '0',
			width: 'full',
			flexDirection: 'column',
			overflowY: 'auto',
			backgroundColor: 'bg.primary',
			color: 'fg.primary'
		})
	];
	const fallbackContentClass = css({
		flex: '1',
		overflowY: 'auto',
		backgroundColor: 'bg.primary',
		padding: '5'
	});
	const fallbackCenterClass = css({
		display: 'flex',
		flex: '1',
		flexDirection: 'column',
		alignItems: 'center',
		justifyContent: 'center',
		gap: '4',
		backgroundColor: 'bg.primary',
		padding: '10',
		textAlign: 'center',
		color: 'fg.tertiary'
	});
	const closeButtonClass = css({
		display: 'flex',
		height: 'row',
		width: 'row',
		cursor: 'pointer',
		alignItems: 'center',
		justifyContent: 'center',
		borderWidth: '0',
		backgroundColor: 'transparent',
		padding: '0',
		lineHeight: 'none',
		color: 'fg.muted',
		_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
	});
	const emptyPanelClass = [
		'step-config',
		css({
			boxSizing: 'border-box',
			display: 'flex',
			height: '100%',
			minHeight: '0',
			width: 'full',
			flexDirection: 'column',
			alignItems: 'center',
			justifyContent: 'center',
			overflowY: 'auto',
			backgroundColor: 'bg.primary',
			color: 'fg.primary'
		})
	];
	const emptyContentClass = css({
		display: 'flex',
		flexDirection: 'column',
		alignItems: 'center',
		justifyContent: 'center',
		padding: '10',
		textAlign: 'center',
		color: 'fg.muted'
	});
	const emptyIconClass = css({ marginBottom: '6', opacity: '0.3' });
	const emptyHeadingClass = css({
		margin: '0',
		marginBottom: '3',
		fontSize: 'md',
		color: 'fg.primary'
	});
	const emptyTextClass = css({ margin: '0', fontSize: 'xs', color: 'fg.muted' });
</script>

{#snippet fallback(failed: boolean)}
	<div
		class={selectedPanelClass}
		data-step-config-loading={failed ? undefined : step?.type}
		data-step-config-error={failed ? step?.type : undefined}
		data-testid={failed ? 'step-config-load-error' : 'step-config-load-status'}
	>
		<PanelHeader>
			{#snippet title()}Step configuration{/snippet}
			{#snippet actions()}
				<button
					class={closeButtonClass}
					onclick={onClose}
					aria-label="Close step configuration"
					title="Close"
					type="button"
				>
					<X size={14} />
				</button>
			{/snippet}
		</PanelHeader>
		<div class={fallbackContentClass}>
			{#if failed}
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
					<Callout tone="error">
						Could not load step configuration. Check your connection and try again.
					</Callout>
					<div class={css({ display: 'flex', justifyContent: 'flex-end', gap: '2' })}>
						<button
							class={button({ variant: 'ghost', size: 'sm' })}
							onclick={onClose}
							type="button"
						>
							Back to steps
						</button>
						<button
							class={button({ variant: 'secondary', size: 'sm' })}
							onclick={() => (loadAttempt += 1)}
							type="button"
						>
							Retry
						</button>
					</div>
				</div>
			{:else}
				<div class={fallbackCenterClass} role="status">
					<div class={spinner({ size: 'md' })}></div>
					<p class={css({ margin: '0', fontSize: 'xs' })}>Loading step configuration…</p>
				</div>
			{/if}
		</div>
	</div>
{/snippet}

{#if step === null}
	<div class={emptyPanelClass}>
		<div class={emptyContentClass}>
			<div class={emptyIconClass}><Settings2 size={40} /></div>
			<h3 class={emptyHeadingClass}>No step selected</h3>
			<p class={emptyTextClass}>Click on a pipeline step to configure it</p>
		</div>
	</div>
{:else}
	{#key step.id}
		{#key loadAttempt}
			{#await import('./StepConfigBody.svelte')}
				{@render fallback(false)}
			{:then { default: StepConfigBody }}
				<StepConfigBody {step} {schema} {isLoadingSchema} {onClose} {onConfigApply} {readOnly} />
			{:catch}
				{@render fallback(true)}
			{/await}
		{/key}
	{/key}
{/if}
