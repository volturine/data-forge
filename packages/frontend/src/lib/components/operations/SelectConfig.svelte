<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import ColumnTypeDropdown from '$lib/components/common/ColumnTypeDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, stepConfig } from '$lib/styles/panda';
	import { ArrowRight } from 'lucide-svelte';

	interface SelectConfigData {
		columns: string[];
		cast_map?: Record<string, string>;
	}

	interface Props {
		schema: Schema;
		config?: SelectConfigData;
	}

	const CAST_TYPES = ['Int64', 'Float64', 'Boolean', 'String', 'Utf8', 'Date', 'Datetime'];

	let { schema, config = $bindable({ columns: [], cast_map: {} }) }: Props = $props();

	const safeColumns = $derived(Array.isArray(config.columns) ? config.columns : []);
	const safeCasts = $derived(config.cast_map ?? {});

	const selectedColumnInfo = $derived(
		safeColumns
			.map((name) => schema.columns.find((col) => col.name === name))
			.filter((col): col is NonNullable<typeof col> => col !== undefined)
	);

	function onColumnsChange(next: string[]): void {
		const nextCasts: Record<string, string> = {};
		for (const name of next) {
			if (safeCasts[name]) {
				nextCasts[name] = safeCasts[name];
			}
		}
		config.columns = next;
		config.cast_map = nextCasts;
	}

	function setCast(column: string, dtype: string): void {
		const next = { ...safeCasts };
		if (dtype) {
			next[column] = dtype;
		} else {
			delete next[column];
		}
		config.cast_map = next;
	}
</script>

<div class={stepConfig()} role="region" aria-label="Select columns configuration">
	<div class={css({ marginBottom: '0', paddingBottom: '5' })}>
		<SectionHeader>Columns to keep</SectionHeader>
		<div class={css({ marginTop: '1.5' })}>
			<MultiSelectColumnDropdown
				{schema}
				value={safeColumns}
				onChange={onColumnsChange}
				placeholder="Select columns to keep..."
			/>
		</div>
	</div>

	{#if selectedColumnInfo.length > 0}
		<div class={css({ marginBottom: '4' })}>
			<SectionHeader>Cast types (optional)</SectionHeader>
			<div
				class={css({
					display: 'flex',
					flexDirection: 'column',
					gap: '2',
					marginTop: '1.5'
				})}
			>
				{#each selectedColumnInfo as col (col.name)}
					<div
						class={css({
							display: 'grid',
							gridTemplateColumns: '1fr auto 1fr',
							gap: '2',
							alignItems: 'center',
							paddingX: '2',
							paddingY: '1.5',
							borderRadius: 'md',
							backgroundColor: 'bg.tertiary'
						})}
					>
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '2',
								minWidth: '0'
							})}
						>
							<ColumnTypeBadge columnType={col.dtype} size="xs" variant="compact" />
							<span
								class={css({
									fontSize: 'sm',
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap'
								})}>{col.name}</span
							>
						</div>
						{#if safeCasts[col.name]}
							<ArrowRight size={14} />
						{:else}
							<span></span>
						{/if}
						<ColumnTypeDropdown
							value={safeCasts[col.name] ?? ''}
							onChange={(val) => setCast(col.name, val)}
							placeholder="No cast"
							allowed={CAST_TYPES}
						/>
					</div>
				{/each}
			</div>
		</div>

		<Callout tone="info">
			<strong
				>Selected {safeColumns.length} column{safeColumns.length !== 1 ? 's' : ''}{Object.keys(
					safeCasts
				).length > 0
					? `, ${Object.keys(safeCasts).length} cast${Object.keys(safeCasts).length !== 1 ? 's' : ''}`
					: ''}</strong
			>
		</Callout>
	{/if}
</div>
