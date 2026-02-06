<script lang="ts">
	import { drag } from '$lib/stores/drag.svelte';

	// Step type metadata with icons and labels
	const stepTypeInfo: Record<string, { label: string; icon: string }> = {
		filter: { label: 'Filter', icon: '🔍' },
		select: { label: 'Select', icon: '📋' },
		groupby: { label: 'Group By', icon: '📊' },
		sort: { label: 'Sort', icon: '↕️' },
		rename: { label: 'Rename', icon: '✏️' },
		drop: { label: 'Drop', icon: '🗑️' },
		join: { label: 'Join', icon: '🔗' },
		expression: { label: 'Expression', icon: '🧮' },
		with_columns: { label: 'With Columns', icon: '🧮' },
		pivot: { label: 'Pivot', icon: '🔄' },
		unpivot: { label: 'Unpivot', icon: '🔃' },
		fill_null: { label: 'Fill Null', icon: '🔧' },
		deduplicate: { label: 'Deduplicate', icon: '🧹' },
		explode: { label: 'Explode', icon: '💥' },
		timeseries: { label: 'Time Series', icon: '📅' },
		string_transform: { label: 'String Transform', icon: '📝' },
		sample: { label: 'Sample', icon: '🎲' },
		limit: { label: 'Limit', icon: '✂️' },
		topk: { label: 'Top K', icon: '🏆' },
		null_count: { label: 'Null Count', icon: '❓' },
		value_counts: { label: 'Value Counts', icon: '📊' },
		view: { label: 'View', icon: '👁️' },
		export: { label: 'Export', icon: '📤' }
	};

	// Derive reactive values from drag store
	let active = $derived(drag.active);
	let type = $derived(drag.type);
	let info = $derived(type ? stepTypeInfo[type] : null);
	let isReorder = $derived(drag.isReorder);
	let pointerX = $derived(drag.pointerX);
	let pointerY = $derived(drag.pointerY);

	// Position is simply the tracked pointer coordinates
	let position = $derived(
		active && pointerX !== null && pointerY !== null ? { x: pointerX, y: pointerY } : null
	);
</script>

{#if active && info && position}
	<div
		class="pointer-events-none fixed z-[9999] flex items-center gap-2 whitespace-nowrap rounded-md border-2 px-3 py-2 text-sm"
		class:reorder={isReorder}
		style="left: {position.x + 12}px; top: {position.y +
			12}px; background: var(--bg-primary); border-color: {isReorder
			? 'var(--warning-border, #f59e0b)'
			: 'var(--accent-primary)'}; box-shadow: var(--shadow-drag); {isReorder
			? 'background: var(--warning-bg, #fef3c7);'
			: ''}"
	>
		<span class="text-base">{info.icon}</span>
		<span class="font-semibold" style="color: var(--fg-primary);">{info.label}</span>
		{#if isReorder}
			<span
				class="rounded-sm px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide text-white"
				style="background: var(--warning-fg);">Move</span
			>
		{/if}
	</div>
{/if}
