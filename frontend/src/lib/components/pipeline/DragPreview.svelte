<script lang="ts">
	import { drag } from '$lib/stores/drag.svelte';
	import {
		ArrowUpDown,
		BarChart3,
		BarChart4,
		Bomb,
		Brush,
		Calculator,
		Calendar,
		CircleHelp,
		Dices,
		Eye,
		Filter,
		Link,
		Pencil,
		Repeat,
		Repeat2,
		Scissors,
		Sparkles,
		Trophy,
		Type,
		Wrench,
		ListChecks,
		Trash2,
		Bell
	} from 'lucide-svelte';

	// Step type metadata with icons and labels
	const stepTypeInfo: Record<string, { label: string; icon: typeof Filter }> = {
		filter: { label: 'Filter', icon: Filter },
		select: { label: 'Select', icon: ListChecks },
		groupby: { label: 'Group By', icon: BarChart3 },
		sort: { label: 'Sort', icon: ArrowUpDown },
		rename: { label: 'Rename', icon: Pencil },
		drop: { label: 'Drop', icon: Trash2 },
		join: { label: 'Join', icon: Link },
		expression: { label: 'Expression', icon: Calculator },
		with_columns: { label: 'With Columns', icon: Calculator },
		pivot: { label: 'Pivot', icon: Repeat },
		unpivot: { label: 'Unpivot', icon: Repeat2 },
		fill_null: { label: 'Fill Null', icon: Wrench },
		deduplicate: { label: 'Deduplicate', icon: Brush },
		explode: { label: 'Explode', icon: Bomb },
		timeseries: { label: 'Time Series', icon: Calendar },
		string_transform: { label: 'String Transform', icon: Type },
		sample: { label: 'Sample', icon: Dices },
		limit: { label: 'Limit', icon: Scissors },
		topk: { label: 'Top K', icon: Trophy },
		null_count: { label: 'Null Count', icon: CircleHelp },
		value_counts: { label: 'Value Counts', icon: BarChart3 },
		chart: { label: 'Chart', icon: BarChart4 },
		notification: { label: 'Notify', icon: Bell },
		ai: { label: 'AI', icon: Sparkles },
		view: { label: 'View', icon: Eye }
	};

	// Derive reactive values from drag store
	const active = $derived(drag.active);
	const type = $derived(drag.type);
	const info = $derived(type ? stepTypeInfo[type] : null);
	const Icon = $derived(info?.icon ?? Filter);
	const isReorder = $derived(drag.isReorder);

	// Local reactive state for pointer position (drag store uses non-reactive getters)
	let pointerX = $state<number | null>(null);
	let pointerY = $state<number | null>(null);

	// Sync with drag store - needed because pointerX/Y are non-reactive getters
	// DOM: $derived can't sync pointer coordinates from store getters.
	$effect(() => {
		pointerX = drag.pointerX;
		pointerY = drag.pointerY;
	});

	// Position is simply the tracked pointer coordinates
	const position = $derived(
		active && pointerX !== null && pointerY !== null ? { x: pointerX, y: pointerY } : null
	);
</script>

{#if active && info && position}
	<div
		class="drag-preview pointer-events-none fixed z-9999 flex items-center gap-2 whitespace-nowrap border-2 px-3 py-2 text-sm"
		class:reorder={isReorder}
		style="left: {position.x + 12}px; top: {position.y + 12}px;"
	>
		<Icon size={16} class="text-base" />
		<span class="font-semibold text-fg-primary">{info.label}</span>
		{#if isReorder}
			<span
				class="px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide bg-warning-fg text-warning-contrast"
				>Move</span
			>
		{/if}
	</div>
{/if}
