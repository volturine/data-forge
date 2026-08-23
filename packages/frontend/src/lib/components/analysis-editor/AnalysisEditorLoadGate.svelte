<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { css, spinner } from '$lib/styles/panda';

	interface Props {
		isLoading: boolean;
		error: unknown;
	}

	let { isLoading, error }: Props = $props();
</script>

{#if isLoading}
	<div
		class={css({ display: 'flex', alignItems: 'center', height: '100%', justifyContent: 'center' })}
	>
		<div class={spinner()}></div>
	</div>
{:else}
	<div
		data-testid="analysis-load-error"
		class={css({
			display: 'flex',
			alignItems: 'center',
			paddingX: '2.5',
			paddingY: '3',
			border: 'none',
			borderLeftWidth: '2',

			fontSize: 'xs',
			lineHeight: '1.5',
			backgroundColor: 'transparent',
			borderLeftColor: 'border.error',
			color: 'fg.error',
			height: '100%',
			flexDirection: 'column',
			justifyContent: 'center',
			textAlign: 'center',
			gap: '4'
		})}
	>
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				fontSize: 'xl',
				fontWeight: 'bold',
				width: 'logoLg',
				height: 'logoLg',
				borderWidth: '1'
			})}
		>
			!
		</div>
		<h2 class={css({ margin: '0' })}>Error loading analysis</h2>
		<p class={css({ margin: '0' })}>
			{error instanceof Error ? error.message : 'Unknown error'}
		</p>
		<button
			class={css({
				borderWidth: '1',
				backgroundColor: 'accent.primary',
				color: 'fg.inverse',
				marginTop: '4',
				'&:hover:not(:disabled)': { opacity: '0.9' }
			})}
			onclick={() => goto(resolve('/analysis/new'))}
			type="button"
		>
			Create analysis
		</button>
	</div>
{/if}
