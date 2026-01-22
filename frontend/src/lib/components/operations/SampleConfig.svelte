<script lang="ts">
	interface Props {
		config?: {
			mode?: 'n' | 'fraction';
			n?: number;
			fraction?: number;
			shuffle?: boolean;
			seed?: number;
		};
	}

	let { config = $bindable({}) }: Props = $props();

	let n = $state(config.n ?? null);
	let fraction = $state(config.fraction ?? null);
	const initialMode: 'n' | 'fraction' =
		config.mode === 'fraction'
			? 'fraction'
			: config.mode === 'n'
				? 'n'
				: config.n !== null && config.n !== undefined
					? 'n'
					: config.fraction !== null && config.fraction !== undefined
						? 'fraction'
						: 'n';
	let mode = $state<'n' | 'fraction'>(initialMode);
	let shuffle = $state(config.shuffle ?? false);
	let seed = $state(config.seed ?? null);

	$effect(() => {
		if (mode === 'n' && fraction !== null) {
			fraction = null;
		}
		if (mode === 'fraction' && n !== null) {
			n = null;
		}
	});

	$effect(() => {
		config = {
			mode,
			...(mode === 'n' && n !== null && n !== undefined ? { n } : {}),
			...(mode === 'fraction' && fraction !== null && fraction !== undefined ? { fraction } : {}),
			...(shuffle ? { shuffle } : {}),
			...(seed !== null && seed !== undefined ? { seed } : {})
		};
	});
</script>

<div class="sample-config">
	<h3>Sample Configuration</h3>

	<div class="form-group">
		<label>
			<input type="radio" name="sample-mode" checked={mode === 'n'} onchange={() => (mode = 'n')} />
			Fixed number (n)
		</label>
		<label>
			<input
				type="radio"
				name="sample-mode"
				checked={mode === 'fraction'}
				onchange={() => (mode = 'fraction')}
			/>
			Fraction (0-1)
		</label>
	</div>

	<div class="form-group">
		{#if mode === 'n'}
			<label for="n">Number of rows</label>
			<input id="n" type="number" bind:value={n} min="1" placeholder="e.g., 100" />
		{:else}
			<label for="fraction">Fraction</label>
			<input
				id="fraction"
				type="number"
				bind:value={fraction}
				min="0"
				max="1"
				step="0.01"
				placeholder="e.g., 0.5"
			/>
		{/if}
	</div>

	<div class="form-group">
		<label class="checkbox-label">
			<input id="shuffle" type="checkbox" bind:checked={shuffle} />
			<span>Shuffle rows</span>
		</label>
	</div>

	<div class="form-group">
		<label for="seed">Random seed (optional)</label>
		<input id="seed" type="number" bind:value={seed} min="0" placeholder="e.g., 42" />
	</div>
</div>

<style>
	.sample-config {
		padding: 1rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
		color: var(--panel-header-fg);
	}

	.form-group {
		margin-bottom: 1rem;
	}

	.form-group:last-child {
		margin-bottom: 0;
	}

	label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		color: var(--fg-secondary);
	}

	input[type='number'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.checkbox-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
</style>
