<script lang="ts">
	import { drag } from '#lib/stores/drag.svelte.js';
	import { css } from '#lib/styles/panda.js';
	import { getStepTypeConfig } from './utils';

	// Derive reactive values from drag store
	const active = $derived(drag.active);
	const info = $derived(drag.type ? getStepTypeConfig(drag.type) : null);
	const isReorder = $derived(drag.isReorder);

	const position = $derived(
		active && drag.pointerX !== null && drag.pointerY !== null
			? { x: drag.pointerX, y: drag.pointerY }
			: null
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
		<info.icon size={16} class={css({ fontSize: 'md' })} />
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
