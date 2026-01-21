<script lang="ts">
	import { drag } from '$lib/stores/drag.svelte';
	import { useEventListener } from 'runed';

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

	let position = $state<{ x: number; y: number } | null>(null);

	// Derive local reactive values from drag store
	let active = $derived(drag.active);
	let type = $derived(drag.type);
	let info = $derived(type ? stepTypeInfo[type] : null);
	let isReorder = $derived(drag.isReorder);

	$effect(() => {
		if (!active) {
			position = null;
			return;
		}

		const state = drag as typeof drag & {
			touchActive: boolean;
			pointerX: number | null;
			pointerY: number | null;
		};
		if (state.touchActive) {
			position =
				state.pointerX !== null && state.pointerY !== null
					? { x: state.pointerX, y: state.pointerY }
					: null;
			return;
		}
	});

	useEventListener(
		() => document,
		'dragover',
		(event: DragEvent) => {
			if (!active) return;
			position = { x: event.clientX, y: event.clientY };
		},
		{ passive: true }
	);
</script>

{#if active && info && position}
	<div
		class="drag-preview"
		class:reorder={isReorder}
		style="left: {position.x + 12}px; top: {position.y + 12}px;"
	>
		<span class="preview-icon">{info.icon}</span>
		<span class="preview-label">{info.label}</span>
		{#if isReorder}
			<span class="preview-badge">Move</span>
		{/if}
	</div>
{/if}

<style>
	.drag-preview {
		position: fixed;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background: var(--bg-primary);
		border: 2px solid var(--accent-primary);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-drag);
		pointer-events: none;
		z-index: 9999;
		font-size: var(--text-sm);
		white-space: nowrap;
		transform: translate(0, 0);
	}

	.drag-preview.reorder {
		border-color: var(--warning-border, #f59e0b);
		background: var(--warning-bg, #fef3c7);
	}

	.preview-icon {
		font-size: var(--text-base);
	}

	.preview-label {
		font-weight: 600;
		color: var(--fg-primary);
	}

	.preview-badge {
		padding: 0.125rem 0.375rem;
		font-size: var(--text-xs);
		font-weight: 500;
		background: var(--warning-fg, #92400e);
		color: white;
		border-radius: var(--radius-sm);
		text-transform: uppercase;
		letter-spacing: 0.02em;
	}
</style>
