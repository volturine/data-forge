<script lang="ts">
	import { css, input, label, stepConfig } from '$lib/styles/panda';

	interface Props {
		config?: { n?: number };
	}

	let { config = $bindable({ n: 10 }) }: Props = $props();
</script>

<div class={stepConfig()} role="region" aria-label="Limit configuration">
	<div class={css({ marginBottom: '0' })}>
		<label class={label()} for="limit-input-n">Number of rows to keep</label>
		<input
			id="limit-input-n"
			data-testid="limit-rows-input"
			type="number"
			class={input()}
			bind:value={config.n}
			min="1"
			placeholder="e.g., 10"
			aria-describedby="limit-n-help"
		/>
		<span
			id="limit-n-help"
			class={css({ marginTop: '1', display: 'block', fontSize: 'xs', color: 'fg.muted' })}
			>Enter the maximum number of rows to keep in the dataset</span
		>
	</div>
</div>
