<script lang="ts">
	import type { UdfInput } from '$lib/types/udf';
	import ColumnTypeDropdown from '$lib/components/common/ColumnTypeDropdown.svelte';
	import { css, cx, button, emptyText, input, label, rowBetween } from '$lib/styles/panda';

	interface Props {
		inputs: UdfInput[];
		onChange: (inputs: UdfInput[]) => void;
	}

	let { inputs, onChange }: Props = $props();

	function addInput() {
		const next = [
			...inputs,
			{ position: inputs.length, dtype: 'Float64', label: `arg${inputs.length + 1}` }
		];
		onChange(next);
	}

	function removeInput(index: number) {
		const next = inputs
			.filter((_, idx) => idx !== index)
			.map((item, idx) => ({ ...item, position: idx }));
		onChange(next);
	}

	function updateInput(index: number, updates: Partial<UdfInput>) {
		const next = inputs.map((item, idx) => (idx === index ? { ...item, ...updates } : item));
		onChange(next);
	}
</script>

<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
	<div class={rowBetween}>
		<h4 class={css({ margin: '0', fontSize: 'sm', color: 'fg.secondary' })}>Inputs</h4>
		<button type="button" class={button({ variant: 'secondary', size: 'sm' })} onclick={addInput}
			>Add input</button
		>
	</div>
	{#if inputs.length === 0}
		<p class={emptyText({ size: 'inline' })}>No inputs yet.</p>
	{:else}
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
			{#each inputs as item, index (index)}
				<div
					class={css({
						display: 'grid',
						gridTemplateColumns: '1fr',
						gap: '2',
						alignItems: 'center',
						md: { gridTemplateColumns: '32px 1fr 200px auto' }
					})}
				>
					<label
						class={cx(label(), css({ textAlign: 'left', md: { textAlign: 'center' } }))}
						for="udf-input-{index}-label">{index + 1}</label
					>
					<input
						type="text"
						id="udf-input-{index}-label"
						placeholder="Label"
						value={item.label ?? ''}
						class={input()}
						oninput={(e) => updateInput(index, { label: e.currentTarget.value })}
					/>
					<div>
						<ColumnTypeDropdown
							value={item.dtype}
							onChange={(val) => updateInput(index, { dtype: val })}
							placeholder="Select type..."
						/>
					</div>
					<button
						class={button({ variant: 'ghost', size: 'sm' })}
						type="button"
						onclick={() => removeInput(index)}
					>
						Remove
					</button>
				</div>
			{/each}
		</div>
	{/if}
</div>
