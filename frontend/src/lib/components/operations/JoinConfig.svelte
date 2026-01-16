<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface JoinConfigData {
		how: 'inner' | 'left' | 'right' | 'outer';
		left_on: string[];
		right_on: string[];
	}

	interface Props {
		schema: Schema;
		config?: JoinConfigData;
	}

	let { schema, config = $bindable({ how: 'inner', left_on: [], right_on: [] }) }: Props = $props();

	let newLeftKey = $state('');
	let newRightKey = $state('');

	const joinTypes: Array<{ value: 'inner' | 'left' | 'right' | 'outer'; label: string }> = [
		{ value: 'inner', label: 'Inner Join' },
		{ value: 'left', label: 'Left Join' },
		{ value: 'right', label: 'Right Join' },
		{ value: 'outer', label: 'Outer Join' }
	];

	function addJoinKey() {
		if (!newLeftKey || !newRightKey) return;

		config.left_on.push(newLeftKey);
		config.right_on.push(newRightKey);

		newLeftKey = '';
		newRightKey = '';
	}

	function removeJoinKey(index: number) {
		config.left_on.splice(index, 1);
		config.right_on.splice(index, 1);
	}
</script>

<div class="join-config">
	<h3>Join Configuration</h3>

	<div class="section">
		<h4>Join Type</h4>
		<select bind:value={config.how}>
			{#each joinTypes as joinType (joinType.value)}
				<option value={joinType.value}>{joinType.label}</option>
			{/each}
		</select>
		<div class="help-text">
			<strong>Inner:</strong> Returns only matching rows from both datasets.<br />
			<strong>Left:</strong> Returns all rows from left dataset and matching rows from right.<br />
			<strong>Right:</strong> Returns all rows from right dataset and matching rows from left.<br />
			<strong>Outer:</strong> Returns all rows from both datasets.
		</div>
	</div>

	<div class="section">
		<h4>Join Keys</h4>

		<div class="add-key">
			<div class="key-inputs">
				<div class="key-input-group">
					<label for="left-key-select">Left Column</label>
					<select id="left-key-select" bind:value={newLeftKey}>
						<option value="">Select column...</option>
						{#each schema.columns as column (column.name)}
							<option value={column.name}>{column.name} ({column.dtype})</option>
						{/each}
					</select>
				</div>

				<div class="key-input-group">
					<label for="right-key-input">Right Column</label>
					<input
						id="right-key-input"
						type="text"
						bind:value={newRightKey}
						placeholder="Right dataset column name"
					/>
				</div>
			</div>

			<button type="button" onclick={addJoinKey} disabled={!newLeftKey || !newRightKey}>
				Add Join Key
			</button>
		</div>

		{#if config.left_on.length > 0}
			<div class="keys-list">
				{#each config.left_on as leftKey, i (leftKey + '-' + i)}
					<div class="key-item">
						<span class="key-details">
							<span class="key-column">{leftKey}</span>
							<span class="key-separator">=</span>
							<span class="key-column">{config.right_on[i]}</span>
						</span>
						<button type="button" onclick={() => removeJoinKey(i)}>Remove</button>
					</div>
				{/each}
			</div>
		{:else}
			<div class="empty-state">No join keys configured. Add at least one join key.</div>
		{/if}
	</div>
</div>

<style>
	.join-config {
		padding: 1rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	h4 {
		margin-top: 0;
		margin-bottom: 0.75rem;
		font-size: 1rem;
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: var(--bg-tertiary);
		border-radius: 4px;
	}

	.section select {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
		margin-bottom: 0.5rem;
	}

	.help-text {
		font-size: 0.875rem;
		color: var(--fg-muted);
		line-height: 1.5;
		padding: 0.75rem;
		background-color: var(--bg-primary);
		border-left: 3px solid var(--accent-primary);
		border-radius: 4px;
		margin-top: 0.5rem;
	}

	.add-key {
		margin-bottom: 1rem;
	}

	.key-inputs {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
		margin-bottom: 0.5rem;
	}

	.key-input-group {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.key-input-group label {
		font-size: 0.875rem;
		font-weight: 500;
		color: var(--fg-primary);
	}

	.key-input-group select,
	.key-input-group input {
		padding: 0.5rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	.add-key > button {
		width: 100%;
		padding: 0.5rem 1rem;
		background-color: var(--success-fg);
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.add-key > button:disabled {
		background-color: var(--border-primary);
		cursor: not-allowed;
	}

	.keys-list {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.key-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem;
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	.key-details {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		font-family: monospace;
		font-size: 0.875rem;
	}

	.key-column {
		padding: 0.25rem 0.5rem;
		background-color: var(--accent-bg);
		border-radius: 4px;
		font-weight: 500;
	}

	.key-separator {
		color: var(--fg-muted);
		font-weight: bold;
	}

	.key-item button {
		padding: 0.25rem 0.75rem;
		background-color: var(--error-fg);
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.875rem;
	}

	.empty-state {
		padding: 1rem;
		text-align: center;
		color: var(--fg-muted);
		background-color: var(--bg-primary);
		border: 1px dashed var(--border-primary);
		border-radius: 4px;
		font-size: 0.875rem;
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
