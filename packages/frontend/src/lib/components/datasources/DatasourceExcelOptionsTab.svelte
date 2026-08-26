<script lang="ts" module>
	export type ExcelConfig = {
		sheet_name: string;
		table_name: string;
		named_range: string;
		cell_range: string;
		start_row: number;
		start_col: number;
		end_col: number;
		end_row: number | null;
		has_header: boolean;
	};
</script>

<script lang="ts">
	import { Loader, Save } from '@lucide/svelte';
	import ExcelTableSelector from '$lib/components/common/ExcelTableSelector.svelte';
	import { css } from '$lib/styles/panda';

	interface Props {
		filePath: string | null;
		config?: ExcelConfig;
		pending: boolean;
		hasChanges: boolean;
		onDirty: () => void;
		onSave: () => Promise<void> | void;
	}

	let {
		filePath,
		config = $bindable({
			sheet_name: '',
			table_name: '',
			named_range: '',
			cell_range: '',
			start_row: 0,
			start_col: 0,
			end_col: 0,
			end_row: null,
			has_header: true
		}),
		pending,
		hasChanges,
		onDirty,
		onSave
	}: Props = $props();

	function isExcelConfigEqual(a: ExcelConfig, b: ExcelConfig): boolean {
		return (
			a.sheet_name === b.sheet_name &&
			a.table_name === b.table_name &&
			a.named_range === b.named_range &&
			a.cell_range === b.cell_range &&
			a.start_row === b.start_row &&
			a.start_col === b.start_col &&
			a.end_col === b.end_col &&
			a.end_row === b.end_row &&
			a.has_header === b.has_header
		);
	}

	function handleConfigUpdate(value: ExcelConfig) {
		if (isExcelConfigEqual(value, config)) return;
		config = value;
		onDirty();
	}
</script>

<div class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
	{#key filePath}
		<ExcelTableSelector
			mode="config"
			{filePath}
			initialConfig={config}
			disabled={pending}
			onConfigChange={handleConfigUpdate}
		/>
		{#if hasChanges}
			<button
				class={css({
					borderWidth: '1',
					backgroundColor: 'accent.primary',
					color: 'fg.inverse',
					'&:hover:not(:disabled)': { opacity: '0.9' },
					display: 'flex',
					alignItems: 'center',
					width: '100%',
					justifyContent: 'center',
					gap: '2'
				})}
				onclick={onSave}
				disabled={pending}
			>
				{#if pending}
					<Loader size={16} class={css({ animation: 'spin 1s linear infinite' })} />
					Saving...
				{:else}
					<Save size={16} />
					Save Changes
				{/if}
			</button>
		{/if}
		{#if !filePath}
			<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.muted' })}>
				No original file path available for Excel preview.
			</p>
		{/if}
	{/key}
</div>
