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
			<div class="flex flex-col gap-2 max-h-[360px] overflow-auto">
				{#if filtered.length === 0}
					<p class="m-0" style="color: var(--fg-muted);">No matching UDFs.</p>
				{:else}
					{#each filtered as udf (udf.id)}
						<button class="row" type="button" onclick={() => onSelect(udf)}>
							<div class="flex justify-between gap-3 font-medium">
								<span>{udf.name}</span>
								<div class="flex items-center gap-1 flex-wrap">
									{#if udf.signature?.inputs?.length}
										{#each udf.signature.inputs as input, i (i)}
											<ColumnTypeBadge columnType={input.dtype} size="xs" showIcon={false} />
											{#if i < udf.signature.inputs.length - 1}
												<span class="text-xs mx-0.5" style="color: var(--fg-muted);">,</span>
											{/if}
										{/each}
									{:else}
										<span class="text-xs uppercase tracking-wide" style="color: var(--fg-muted);"
											>No inputs</span
										>
									{/if}
								</div>
							</div>
							{#if udf.description}
								<p class="mt-2 mb-0 text-sm" style="color: var(--fg-secondary);">
									{udf.description}
								</p>
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
	/* modal-backdrop, modal, modal-header, modal-close, modal-body, modal-footer — global in app.css */
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
</style>
