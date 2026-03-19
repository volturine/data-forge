<script lang="ts">
	import { css, stepConfig } from '$lib/styles/panda';

	interface Props {
		config?: Record<string, never>;
	}

	let { config = $bindable({} as Record<string, never>) }: Props = $props();
	void config;
</script>

<div class={stepConfig()}>
	<h3 class={css({ marginBottom: '2' })}>Null Count</h3>
	<p
		class={css({
			marginTop: '0',
			marginBottom: '2',
			color: 'fg.tertiary',
			fontSize: 'xs',
			lineHeight: '1.6'
		})}
	>
		Count null values for each column in the dataset.
	</p>
	<p
		class={css({
			paddingX: '3',
			paddingY: '2.5',
			border: 'none',
			borderLeftWidth: '2',
			borderLeftColor: 'accent.secondary',

			marginTop: '3',
			marginBottom: '0',
			fontSize: 'xs',
			lineHeight: '1.5',
			backgroundColor: 'transparent',
			color: 'fg.tertiary'
		})}
	>
		This operation will return a single row with the count of null values for each column.
	</p>
</div>
