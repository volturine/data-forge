<script lang="ts">
	import { drag } from '$lib/stores/drag.svelte';
	import { css } from '$lib/styles/panda';
	import {
		ArrowUpDown,
		ChartColumn,
		ChartColumnIncreasing,
		Bomb,
		Brush,
		Calculator,
		Calendar,
		Dices,
		Download,
		Eye,
		Funnel,
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
	const stepTypeInfo: Record<string, { label: string; icon: typeof Funnel }> = {
		filter: { label: 'Filter', icon: Funnel },
		select: { label: 'Select', icon: ListChecks },
		groupby: { label: 'Group By', icon: ChartColumn },
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
		chart: { label: 'Chart', icon: ChartColumnIncreasing },
		notification: { label: 'Notify', icon: Bell },
		ai: { label: 'AI', icon: Sparkles },
		view: { label: 'View', icon: Eye },
		download: { label: 'Download', icon: Download }
	};

	// Derive reactive values from drag store
	const active = $derived(drag.active);
	const type = $derived(drag.type);
	const info = $derived(type ? stepTypeInfo[type] : null);
	const Icon = $derived(info?.icon ?? Funnel);
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
		class={css({
			pointerEvents: 'none',
			position: 'fixed',
			zIndex: '9999',
			display: 'flex',
			alignItems: 'center',
			gap: '2',
			whiteSpace: 'nowrap',
			borderWidth: '2',
			paddingX: '3',
			paddingY: '2',
			fontSize: 'sm',
			backgroundColor: isReorder ? 'bg.warning' : 'bg.primary',
			borderColor: isReorder ? 'border.warning' : 'border.primary',
			boxShadow: 'drag'
		})}
		style:left="{position.x + 12}px"
		style:top="{position.y + 12}px"
	>
		<Icon size={16} class={css({ fontSize: 'md' })} />
		<span class={css({ fontWeight: 'semibold', color: 'fg.primary' })}>{info.label}</span>
		{#if isReorder}
			<span
				class={css({
					paddingX: '1.5',
					paddingY: '0.5',
					fontSize: 'xs',
					fontWeight: 'medium',
					textTransform: 'uppercase',
					letterSpacing: 'wide',
					backgroundColor: 'fg.warning',
					color: 'fg.inverse'
				})}>Move</span
			>
		{/if}
	</div>
{/if}
