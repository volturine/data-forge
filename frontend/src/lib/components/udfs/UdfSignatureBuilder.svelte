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

<div class="flex flex-col gap-3">
	<div class="flex justify-between items-center">
		<h4 class="m-0 text-sm text-fg-secondary">Inputs</h4>
		<button type="button" class="btn-secondary btn-sm" onclick={addInput}>Add input</button>
	</div>
	{#if inputs.length === 0}
		<p class="m-0 text-sm text-fg-muted">No inputs yet.</p>
	{:else}
		<div class="flex flex-col gap-2">
			{#each inputs as input, index (index)}
				<div class="grid grid-cols-1 md:grid-cols-[32px_1fr_200px_auto] gap-2 items-center">
					<span class="text-xs text-left md:text-center text-fg-muted">{index + 1}</span>
					<input
						type="text"
						placeholder="Label"
						value={input.label ?? ''}
						oninput={(e) => updateInput(index, { label: e.currentTarget.value })}
					/>
					<div>
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
