<script lang="ts">
	import type { UdfInput } from '$lib/types/udf';
	import ColumnTypeDropdown from '$lib/components/common/ColumnTypeDropdown.svelte';

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

<div class="signature-builder">
	<div class="header">
		<h4>Inputs</h4>
		<button type="button" class="btn-secondary btn-sm" onclick={addInput}>Add input</button>
	</div>
	{#if inputs.length === 0}
		<p class="empty">No inputs yet.</p>
	{:else}
		<div class="inputs">
			{#each inputs as input, index (index)}
				<div class="input-row">
					<span class="index">{index + 1}</span>
					<input
						type="text"
						placeholder="Label"
						value={input.label ?? ''}
						oninput={(e) => updateInput(index, { label: e.currentTarget.value })}
					/>
					<div class="type-dropdown-wrapper">
						<ColumnTypeDropdown
							value={input.dtype}
							onChange={(val) => updateInput(index, { dtype: val })}
							placeholder="Select type..."
						/>
					</div>
					<button class="btn-ghost btn-sm" type="button" onclick={() => removeInput(index)}>
						Remove
					</button>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.signature-builder {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.header h4 {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}
	.empty {
		color: var(--fg-muted);
		font-size: var(--text-sm);
		margin: 0;
	}
	.inputs {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.input-row {
		display: grid;
		grid-template-columns: 32px 1fr 200px auto;
		gap: var(--space-2);
		align-items: center;
	}
	.index {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		text-align: center;
	}
	@media (max-width: 700px) {
		.input-row {
			grid-template-columns: 1fr;
		}
		.index {
			text-align: left;
		}
	}
</style>
