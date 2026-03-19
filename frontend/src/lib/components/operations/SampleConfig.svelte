<script lang="ts">
	import { css, input, label, stepConfig } from '$lib/styles/panda';

	interface Props {
		config?: {
			fraction?: number;
			seed?: number;
		};
	}

	let { config = $bindable({ fraction: 0.5, seed: 42 }) }: Props = $props();
</script>

<div class={stepConfig()} role="region" aria-label="Sample configuration">
	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="sample-input-fraction">Fraction</label>
		<input
			id="sample-input-fraction"
			data-testid="sample-fraction-input"
			type="number"
			class={input()}
			bind:value={config.fraction}
			min="0"
			max="1"
			step="0.01"
			placeholder="e.g., 0.5"
		/>
	</div>

	<div class={css({ marginBottom: '0' })}>
		<label class={label()} for="sample-input-seed">Random seed (optional)</label>
		<input
			id="sample-input-seed"
			data-testid="sample-seed-input"
			type="number"
			class={input()}
			bind:value={config.seed}
			min="0"
			placeholder="e.g., 42"
		/>
	</div>
</div>
