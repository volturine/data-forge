<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { LayoutGrid, Plus } from 'lucide-svelte';
	import { css } from '$lib/styles/panda';

	function createNew() {
		goto(resolve('/analysis/new'), { invalidateAll: true });
	}
</script>

<div
	class={css({
		display: 'flex',
		minHeight: 'panel',
		flexDirection: 'column',
		alignItems: 'center',
		justifyContent: 'center',
		borderWidth: '1',
		borderStyle: 'dashed',
		paddingX: '6',
		paddingY: '12',
		textAlign: 'center'
	})}
>
	<div
		class={css({
			marginBottom: '6',
			display: 'flex',
			height: 'logoXl',
			width: 'logoXl',
			alignItems: 'center',
			justifyContent: 'center',
			color: 'fg.faint'
		})}
	>
		<LayoutGrid size={32} strokeWidth={1.5} />
	</div>

	<h2 class={css({ margin: '0', marginBottom: '2', fontWeight: 'semibold' })}>No analyses yet</h2>
	<p
		class={css({
			margin: '0',
			marginBottom: '6',
			maxWidth: 'dropdownTall',
			fontSize: 'sm',
			color: 'fg.tertiary'
		})}
	>
		Create your first analysis to get started with data exploration.
	</p>

	<button
		class={css({
			backgroundColor: 'accent.primary',
			color: 'fg.inverse',
			borderWidth: '1',
			paddingX: '4',
			paddingY: '2',
			display: 'inline-flex',
			alignItems: 'center',
			gap: '2'
		})}
		onclick={createNew}
	>
		<Plus size={16} />
		Create Analysis
	</button>
</div>
