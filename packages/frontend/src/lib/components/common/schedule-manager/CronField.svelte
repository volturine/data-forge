<script lang="ts">
	import { Check, Pencil, X } from '@lucide/svelte';
	import { css, input } from '$lib/styles/panda';

	interface Props {
		scheduleId: string;
		cronExpression: string;
		editing: boolean;
		editValue?: string;
		savePending?: boolean;
		variant?: 'compact' | 'table';
		onSave: () => void;
		onCancel: () => void;
		onEdit: () => void;
	}

	let {
		scheduleId,
		cronExpression,
		editing,
		editValue = $bindable(''),
		savePending = false,
		variant = 'compact',
		onSave,
		onCancel,
		onEdit
	}: Props = $props();

	const microInputClass = input({ variant: 'micro' });
	const tableInputClass = css({
		color: 'fg.primary',
		borderWidth: '1',
		borderRadius: '0',
		transitionProperty: 'border-color',
		transitionDuration: '160ms',
		transitionTimingFunction: 'ease',
		_focus: { outline: 'none' },
		_focusVisible: { borderColor: 'border.accent' },
		_disabled: {
			opacity: '0.5',
			cursor: 'not-allowed'
		},
		_placeholder: { color: 'fg.muted' },
		width: 'colMd',
		backgroundColor: 'transparent',
		paddingX: '1.5',
		paddingY: '0.5',
		fontSize: '2xs'
	});

	const compactSaveClass = css({
		flexShrink: '0',
		border: 'none',
		backgroundColor: 'transparent',
		padding: '0.5',
		color: 'fg.success'
	});
	const tableSaveClass = css({
		display: 'inline-flex',
		alignItems: 'center',
		justifyContent: 'center',
		border: 'none',
		backgroundColor: 'transparent',
		padding: '0.5',
		color: 'fg.success',
		_hover: { color: 'fg.successMuted' }
	});

	const compactCancelClass = css({
		flexShrink: '0',
		border: 'none',
		backgroundColor: 'transparent',
		padding: '0.5',
		color: 'fg.muted',
		_hover: { color: 'fg.primary' }
	});
	const tableCancelClass = css({
		display: 'inline-flex',
		alignItems: 'center',
		justifyContent: 'center',
		border: 'none',
		backgroundColor: 'transparent',
		padding: '0.5',
		color: 'fg.muted',
		_hover: { color: 'fg.primary' }
	});

	const compactEditClass = css({
		border: 'none',
		backgroundColor: 'transparent',
		padding: '0.5',
		color: 'fg.muted',
		_hover: { color: 'fg.primary' }
	});
	const tableEditClass = css({
		display: 'inline-flex',
		alignItems: 'center',
		justifyContent: 'center',
		border: 'none',
		backgroundColor: 'transparent',
		padding: '0.5',
		color: 'fg.muted',
		_hover: { color: 'fg.primary' }
	});

	const inputClass = $derived(variant === 'table' ? tableInputClass : microInputClass);
	const saveClass = $derived(variant === 'table' ? tableSaveClass : compactSaveClass);
	const cancelClass = $derived(variant === 'table' ? tableCancelClass : compactCancelClass);
	const editClass = $derived(variant === 'table' ? tableEditClass : compactEditClass);
	const editTitle = $derived(variant === 'table' ? 'Edit cron expression' : 'Edit');
</script>

{#if editing}
	<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
		<input
			type="text"
			class={inputClass}
			id="sched-{scheduleId}-cron"
			aria-label="Cron expression"
			bind:value={editValue}
			onkeydown={(e) => {
				if (e.key === 'Enter') onSave();
				if (e.key === 'Escape') onCancel();
			}}
		/>
		<button class={saveClass} onclick={onSave} disabled={savePending} title="Save">
			<Check size={12} />
		</button>
		<button class={cancelClass} onclick={onCancel} title="Cancel">
			<X size={12} />
		</button>
	</div>
{:else}
	<div class={css({ display: 'flex', alignItems: 'center', gap: '1' })}>
		<code
			class={css({
				backgroundColor: 'bg.tertiary',
				paddingX: '1',
				paddingY: '0.5',
				fontSize: '2xs'
			})}
		>
			{cronExpression}
		</code>
		<button class={editClass} onclick={onEdit} title={editTitle}>
			<Pencil size={10} />
		</button>
	</div>
{/if}
