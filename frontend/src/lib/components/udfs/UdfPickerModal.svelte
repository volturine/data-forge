<script lang="ts">
	import type { Udf } from '$lib/types/udf';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';

	interface Props {
		show: boolean;
		udfs: Udf[];
		onSelect: (udf: Udf) => void;
		onClose: () => void;
	}

	let { show, udfs, onSelect, onClose }: Props = $props();
	let search = $state('');

	const filtered = $derived.by(() => {
		if (!search.trim()) return udfs;
		const q = search.trim().toLowerCase();
		return udfs.filter((udf) => udf.name.toLowerCase().includes(q));
	});
</script>

{#if show}
	<div class="modal-backdrop" aria-hidden="true"></div>
	<div class="modal" role="dialog" aria-modal="true">
		<div class="modal-header">
			<h2>Select UDF</h2>
			<button class="modal-close" onclick={onClose} aria-label="Close">×</button>
		</div>
		<div class="modal-body">
			<input type="text" placeholder="Search UDFs..." bind:value={search} />
			<div class="list">
				{#if filtered.length === 0}
					<p class="empty">No matching UDFs.</p>
				{:else}
					{#each filtered as udf (udf.id)}
						<button class="row" type="button" onclick={() => onSelect(udf)}>
							<div class="title">
								<span>{udf.name}</span>
								<div class="signature">
									{#if udf.signature?.inputs?.length}
										{#each udf.signature.inputs as input, i (i)}
											<ColumnTypeBadge columnType={input.dtype} size="xs" showIcon={false} />
											{#if i < udf.signature.inputs.length - 1}
												<span class="signature-separator">,</span>
											{/if}
										{/each}
									{:else}
										<span class="no-inputs">No inputs</span>
									{/if}
								</div>
							</div>
							{#if udf.description}
								<p class="desc">{udf.description}</p>
							{/if}
						</button>
					{/each}
				{/if}
			</div>
		</div>
		<div class="modal-footer">
			<button class="btn-secondary" onclick={onClose}>Close</button>
		</div>
	</div>
{/if}

<style>
	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: var(--overlay-bg);
		z-index: var(--z-modal);
	}
	.modal {
		position: fixed;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		width: min(700px, 92vw);
		background-color: var(--dialog-bg);
		border: 1px solid var(--dialog-border);
		border-radius: var(--radius-lg);
		box-shadow: var(--dialog-shadow);
		z-index: calc(var(--z-modal) + 1);
		display: flex;
		flex-direction: column;
	}
	.modal-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-3) var(--space-4);
		border-bottom: 1px solid var(--border-primary);
	}
	.modal-header h2 {
		margin: 0;
		font-size: var(--text-base);
	}
	.modal-close {
		background: transparent;
		border: none;
		color: var(--fg-muted);
		font-size: 1.25rem;
		cursor: pointer;
	}
	.modal-body {
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		max-height: 360px;
		overflow: auto;
	}
	.row {
		text-align: left;
		padding: var(--space-3);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-secondary);
		color: var(--fg-primary);
		cursor: pointer;
	}
	.row:hover {
		background-color: var(--bg-hover);
	}
	.title {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		font-weight: var(--font-medium);
	}
	.signature {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		flex-wrap: wrap;
	}
	.signature-separator {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		margin: 0 0.125rem;
	}
	.no-inputs {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.desc {
		margin: var(--space-2) 0 0 0;
		color: var(--fg-secondary);
		font-size: var(--text-sm);
	}
	.empty {
		margin: 0;
		color: var(--fg-muted);
	}
	.modal-footer {
		padding: var(--space-3) var(--space-4);
		border-top: 1px solid var(--border-primary);
		display: flex;
		justify-content: flex-end;
	}
</style>
