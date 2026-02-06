<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { X, Plus } from 'lucide-svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

	const uid = $props.id();

	interface Props {
		schema: Schema;
		config?: { columns: string[]; descending: boolean[] };
	}

	let { schema, config = $bindable({ columns: [], descending: [] }) }: Props = $props();

	let safeConfig = $derived({
		columns: config?.columns ?? [],
		descending: config?.descending ?? []
	});

	let newColumn = $state('');
	let newDescending = $state(false);

	function addSortRule() {
		if (!newColumn) return;
		if (safeConfig.columns.includes(newColumn)) return;
		config = {
			columns: [...safeConfig.columns, newColumn],
			descending: [...safeConfig.descending, newDescending]
		};
		newColumn = '';
		newDescending = false;
	}

	function removeSortRule(index: number) {
		config = {
			columns: safeConfig.columns.filter((_, i) => i !== index),
			descending: safeConfig.descending.filter((_, i) => i !== index)
		};
	}

	function setDirection(index: number, descending: boolean) {
		config = {
			...safeConfig,
			descending: safeConfig.descending.map((d, i) => (i === index ? descending : d))
		};
	}

	let availableColumns = $derived(
		schema.columns.filter((col) => !safeConfig.columns.includes(col.name))
	);
</script>

<div class="config-panel" role="region" aria-label="Sort configuration">
	<h3>Sort Configuration</h3>

	<div class="flex gap-2 items-center mb-6 flex-wrap" role="group" aria-label="Add sort rule form">
		<div class="flex-[2] min-w-[200px]">
			<span class="sr-only">Select column to sort</span>
			<ColumnDropdown
				{schema}
				value={newColumn}
				onChange={(val) => (newColumn = val)}
				placeholder="Select column..."
				filter={(col) => availableColumns.some((c) => c.name === col.name)}
			/>
		</div>

		<div class="flex" role="group" aria-label="Sort direction">
			<button
				id="{uid}-ascending"
				data-testid="sort-ascending-button"
				type="button"
				class="flex items-center justify-center w-8 h-8 p-0 cursor-pointer transition-all bg-[var(--bg-tertiary)] text-[var(--fg-secondary)] border border-[var(--border-primary)] rounded-l-[var(--radius-sm)] border-r-0 hover:bg-[var(--bg-secondary)] hover:text-[var(--fg-primary)]"
				class:!bg-[var(--accent-primary)]={!newDescending}
				class:!text-[var(--bg-primary)]={!newDescending}
				class:!border-[var(--accent-primary)]={!newDescending}
				onclick={() => (newDescending = false)}
				title="Ascending"
				aria-pressed={!newDescending}
				aria-label="Sort ascending"
			>
				<span class="text-sm leading-none" aria-hidden="true">▲</span>
			</button>
			<button
				id="{uid}-descending"
				data-testid="sort-descending-button"
				type="button"
				class="flex items-center justify-center w-8 h-8 p-0 cursor-pointer transition-all bg-[var(--bg-tertiary)] text-[var(--fg-secondary)] border border-[var(--border-primary)] rounded-r-[var(--radius-sm)] hover:bg-[var(--bg-secondary)] hover:text-[var(--fg-primary)]"
				class:!bg-[var(--accent-primary)]={newDescending}
				class:!text-[var(--bg-primary)]={newDescending}
				class:!border-[var(--accent-primary)]={newDescending}
				onclick={() => (newDescending = true)}
				title="Descending"
				aria-pressed={newDescending}
				aria-label="Sort descending"
			>
				<span class="text-sm leading-none" aria-hidden="true">▼</span>
			</button>
		</div>

		<button
			id="{uid}-add"
			data-testid="sort-add-button"
			type="button"
			class="flex items-center gap-1 py-2 px-4 border-none rounded-sm cursor-pointer whitespace-nowrap bg-[var(--accent-primary)] text-[var(--bg-primary)] disabled:bg-[var(--border-primary)] disabled:cursor-not-allowed disabled:text-[var(--fg-muted)]"
			onclick={addSortRule}
			disabled={!newColumn}
			aria-label="Add sort rule"
		>
			<Plus size={16} aria-hidden="true" />
			Add
		</button>
	</div>

	{#if safeConfig.columns.length > 0}
		<div
			id="sort-rules-list"
			class="p-4 rounded-md mb-4 bg-[var(--panel-muted-bg)] border border-[var(--panel-muted-border)]"
			role="region"
			aria-labelledby="sort-order-heading"
		>
			<h4 id="sort-order-heading" class="mt-0 mb-3 text-sm uppercase text-[var(--fg-muted)]">
				Sort Order
			</h4>
			{#each safeConfig.columns as column, i (column)}
				<div
					class="flex justify-between items-center py-2 px-3 rounded-sm mb-2 last:mb-0 bg-[var(--panel-bg)] border border-[var(--panel-border)]"
					role="group"
					aria-label={`Sort rule ${i + 1}: ${column}`}
				>
					<span class="font-medium">{column}</span>

					<div
						class="flex items-center gap-1"
						role="group"
						aria-label={`Sort direction for ${column}`}
					>
						<button
							id={`sort-btn-asc-${i}`}
							data-testid={`sort-ascending-rule-${i}`}
							type="button"
							class="flex items-center justify-center w-7 h-7 p-0 bg-transparent rounded-sm cursor-pointer transition-all text-[var(--fg-secondary)] border border-transparent hover:bg-[var(--bg-tertiary)] hover:text-[var(--fg-primary)]"
							class:!bg-[var(--accent-primary)]={!safeConfig.descending[i]}
							class:!text-[var(--bg-primary)]={!safeConfig.descending[i]}
							onclick={() => setDirection(i, false)}
							title="Ascending"
							aria-pressed={!safeConfig.descending[i]}
							aria-label={`Sort ${column} ascending`}
						>
							<span class="text-sm leading-none" aria-hidden="true">▲</span>
						</button>
						<button
							id={`sort-btn-desc-${i}`}
							data-testid={`sort-descending-rule-${i}`}
							type="button"
							class="flex items-center justify-center w-7 h-7 p-0 bg-transparent rounded-sm cursor-pointer transition-all text-[var(--fg-secondary)] border border-transparent hover:bg-[var(--bg-tertiary)] hover:text-[var(--fg-primary)]"
							class:!bg-[var(--accent-primary)]={safeConfig.descending[i]}
							class:!text-[var(--bg-primary)]={safeConfig.descending[i]}
							onclick={() => setDirection(i, true)}
							title="Descending"
							aria-pressed={safeConfig.descending[i]}
							aria-label={`Sort ${column} descending`}
						>
							<span class="text-sm leading-none" aria-hidden="true">▼</span>
						</button>
						<button
							id={`sort-btn-remove-${i}`}
							data-testid={`sort-remove-rule-${i}`}
							type="button"
							class="flex items-center justify-center w-7 h-7 p-0 bg-transparent rounded-sm cursor-pointer transition-all text-[var(--fg-secondary)] border border-transparent hover:!bg-[var(--error-bg)] hover:!text-[var(--error-fg)] hover:!border-[var(--error-border)]"
							onclick={() => removeSortRule(i)}
							title="Remove"
							aria-label={`Remove sort rule for ${column}`}
						>
							<X size={14} aria-hidden="true" />
						</button>
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<p
			id="sort-empty-state"
			class="py-8 text-center rounded-md mb-4 text-[var(--fg-muted)] bg-[var(--panel-muted-bg)] border border-[var(--panel-muted-border)]"
			role="status"
		>
			No sort rules configured. Add a column to sort by.
		</p>
	{/if}
</div>
