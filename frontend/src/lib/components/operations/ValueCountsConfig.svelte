<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

	interface Props {
		schema: Schema;
		config?: { column?: string; normalize?: boolean; sort?: boolean };
	}

	let { schema, config = $bindable({}) }: Props = $props();

	// Helper to get config value with default
	const get = <T,>(key: keyof typeof config, defaultValue: T): T =>
		(config[key] as T) ?? defaultValue;
</script>

<div class="config-panel">
	<div class="form-group mb-5">
		<div class="form-label">Column to count</div>
		<ColumnDropdown
			{schema}
			value={config.column ?? ''}
			onChange={(val) => (config.column = val)}
			placeholder="Select column..."
		/>
	</div>

	<div class="form-group mb-5">
		<label class="flex cursor-pointer items-center gap-3">
			<input id="normalize" type="checkbox" bind:checked={config.normalize} />
			<span>Normalize (show proportions instead of counts)</span>
		</label>
	</div>

	<div class="form-group mb-0">
		<label class="flex cursor-pointer items-center gap-3">
			<input
				id="sort"
				type="checkbox"
				checked={get('sort', true)}
				onchange={(e) => (config.sort = e.currentTarget.checked)}
			/>
			<span>Sort by count</span>
		</label>
	</div>
</div>
