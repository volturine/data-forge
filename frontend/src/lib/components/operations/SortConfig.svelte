<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { X, Plus, ArrowUp, ArrowDown } from 'lucide-svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import ToggleButton from '$lib/components/ui/ToggleButton.svelte';
	import { css, emptyText, stepConfig } from '$lib/styles/panda';

	const uid = $props.id();

	interface Props {
		schema: Schema;
		config?: { columns: string[]; descending: boolean[] | boolean };
	}

	let { schema, config = $bindable({ columns: [], descending: [] }) }: Props = $props();

	const safeConfig: { columns: string[]; descending: boolean[] } = $derived({
		columns: config?.columns ?? [],
		descending: Array.isArray(config?.descending)
			? config.descending
			: (config?.columns ?? []).map(() => (config?.descending as boolean) ?? false)
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

	const availableColumns = $derived(
		schema.columns.filter((col) => !safeConfig.columns.includes(col.name))
	);
</script>

<div class={stepConfig()} role="region" aria-label="Sort configuration">
	<div
		class={css({
			display: 'flex',
			gap: '2',
			alignItems: 'center',
			marginBottom: '8',
			flexWrap: 'wrap'
		})}
		role="group"
		aria-label="Add sort rule form"
	>
		<div class={css({ flex: '2', minWidth: 'listSm' })}>
			<span
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
				})}>Select column to sort</span
			>
			<ColumnDropdown
				{schema}
				value={newColumn}
				onChange={(val) => (newColumn = val)}
				placeholder="Select column..."
				filter={(col) => availableColumns.some((c) => c.name === col.name)}
			/>
		</div>

		<div
			class={css({
				display: 'flex',
				gap: 'px',
				backgroundColor: 'bg.muted',
				padding: 'px'
			})}
			role="group"
			aria-label="Sort direction"
		>
			<ToggleButton
				active={!newDescending}
				radius="left"
				onclick={() => (newDescending = false)}
				ariaLabel="Sort ascending"
				ariaPressed={!newDescending}
			>
				<ArrowUp size={14} aria-hidden="true" />
			</ToggleButton>
			<ToggleButton
				active={newDescending}
				radius="right"
				onclick={() => (newDescending = true)}
				ariaLabel="Sort descending"
				ariaPressed={newDescending}
			>
				<ArrowDown size={14} aria-hidden="true" />
			</ToggleButton>
		</div>

		<button
			id="{uid}-add"
			data-testid="sort-add-button"
			type="button"
			class={css({
				display: 'flex',
				alignItems: 'center',
				gap: '1',
				paddingY: '2',
				paddingX: '4',
				border: 'none',
				cursor: 'pointer',
				whiteSpace: 'nowrap',
				backgroundColor: 'bg.accent',
				color: 'accent.primary',
				_disabled: { backgroundColor: 'bg.muted', cursor: 'not-allowed', color: 'fg.muted' }
			})}
			onclick={addSortRule}
			disabled={!newColumn}
			aria-label="Add sort rule"
		>
			<Plus size={16} aria-hidden="true" />
			Add
		</button>
	</div>

	{#if safeConfig.columns.length > 0}
		<div id="sort-rules-list" role="region" aria-labelledby="sort-order-heading">
			<span id="sort-order-heading"><SectionHeader>Sort Order</SectionHeader></span>
			{#each safeConfig.columns as column, i (column)}
				<div
					class={css({
						display: 'flex',
						justifyContent: 'space-between',
						alignItems: 'center',
						paddingY: '2',
						borderBottomWidth: '1',
						'&:last-child': { borderBottomWidth: '0' }
					})}
					role="group"
					aria-label={`Sort rule ${i + 1}: ${column}`}
				>
					<span class={css({ fontWeight: 'medium' })}>{column}</span>

					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: 'px',
							backgroundColor: 'bg.muted',
							padding: 'px'
						})}
						role="group"
						aria-label={`Sort direction for ${column}`}
					>
						<ToggleButton
							active={!safeConfig.descending[i]}
							radius="left"
							onclick={() => setDirection(i, false)}
							ariaLabel={`Sort ${column} ascending`}
							ariaPressed={!safeConfig.descending[i]}
						>
							<ArrowUp size={12} aria-hidden="true" />
						</ToggleButton>
						<ToggleButton
							active={safeConfig.descending[i]}
							radius="right"
							onclick={() => setDirection(i, true)}
							ariaLabel={`Sort ${column} descending`}
							ariaPressed={safeConfig.descending[i]}
						>
							<ArrowDown size={12} aria-hidden="true" />
						</ToggleButton>
						<button
							id={`sort-btn-remove-${i}`}
							data-testid={`sort-remove-rule-${i}`}
							type="button"
							class={css({
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								width: 'row',
								height: 'row',
								padding: '0',
								cursor: 'pointer',
								borderWidth: '1',
								_hover: {
									backgroundColor: 'bg.error!',
									color: 'fg.error!',
									borderColor: 'border.error'
								}
							})}
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
		<p id="sort-empty-state" class={emptyText()} role="status">
			No sort rules configured. Add a column to sort by.
		</p>
	{/if}
</div>
