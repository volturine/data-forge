<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import { css, input, label, stepConfig } from '$lib/styles/panda';

	interface Props {
		schema: Schema;
		config?: { column?: string; k?: number; descending?: boolean };
	}

	let { schema, config = $bindable({ column: '', k: 10, descending: false }) }: Props = $props();

	function setK(value: string) {
		const num = parseInt(value, 10);
		config.k = isNaN(num) ? 10 : num;
	}

	function setDescending(checked: boolean) {
		config.descending = checked;
	}
</script>

<div class={stepConfig()} role="region" aria-label="Top K configuration">
	<div class={css({ marginBottom: '5' })}>
		<div
			class={css({
				display: 'block',
				fontSize: 'xs',
				fontWeight: 'semibold',
				color: 'fg.muted',
				marginBottom: '1.5',
				textTransform: 'uppercase',
				letterSpacing: 'wider'
			})}
		>
			Column to sort by
		</div>
		<ColumnDropdown
			{schema}
			value={config.column ?? ''}
			onChange={(val) => (config.column = val)}
			placeholder="Select column..."
		/>
	</div>

	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="topk-input-k">Number of rows (k)</label>
		<input
			id="topk-input-k"
			data-testid="topk-k-input"
			type="number"
			class={input()}
			value={config.k}
			oninput={(e) => setK(e.currentTarget.value)}
			min="1"
			placeholder="e.g., 10"
		/>
	</div>

	<div class={css({ marginBottom: '0' })}>
		<label class={label({ variant: 'checkbox' })}>
			<input
				id="topk-checkbox-descending"
				data-testid="topk-descending-checkbox"
				type="checkbox"
				checked={config.descending}
				onchange={(e) => setDescending(e.currentTarget.checked)}
				aria-describedby="topk-descending-help"
			/>
			<span>Descending (largest first)</span>
		</label>
		<span
			id="topk-descending-help"
			class={css({
				position: 'absolute',
				width: 'px',
				height: 'px',
				padding: '0',
				margin: '-1px',
				overflow: 'hidden',
				clip: 'rect(0, 0, 0, 0)',
				whiteSpace: 'nowrap',
				border: '0'
			})}>Sort in descending order (largest values first)</span
		>
	</div>
</div>
