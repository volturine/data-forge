<script lang="ts">
	import type { Udf } from '$lib/types/udf';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import { X } from 'lucide-svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';

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

<BaseModal
	open={show}
	onClose={onClose}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass="w-full max-w-120 max-h-[90vh] overflow-y-auto border bg-dialog border-tertiary"
	ariaLabelledby="udf-modal-title"
	content={content}
/>

{#snippet content()}
	<div class="modal-header">
		<h2 id="udf-modal-title">Select UDF</h2>
		<button class="modal-close" onclick={onClose} aria-label="Close" type="button">
			<X size={16} />
		</button>
	</div>
	<div class="modal-body">
		<input type="text" placeholder="Search UDFs..." bind:value={search} />
		<div class="flex flex-col gap-2 max-h-90 overflow-auto">
			{#if filtered.length === 0}
				<p class="m-0 text-fg-muted">No matching UDFs.</p>
			{:else}
				{#each filtered as udf (udf.id)}
					<button class="row udf-row" type="button" onclick={() => onSelect(udf)}>
						<div class="flex justify-between gap-3 font-medium">
							<span>{udf.name}</span>
							<div class="flex items-center gap-1 flex-wrap">
								{#if udf.signature?.inputs?.length}
									{#each udf.signature.inputs as input, i (i)}
										<ColumnTypeBadge columnType={input.dtype} size="xs" showIcon={false} />
										{#if i < udf.signature.inputs.length - 1}
											<span class="text-xs mx-0.5 text-fg-muted">,</span>
										{/if}
									{/each}
								{:else}
									<span class="text-xs uppercase tracking-wide text-fg-muted">No inputs</span>
								{/if}
							</div>
						</div>
						{#if udf.description}
							<p class="mt-2 mb-0 text-sm text-fg-secondary">
								{udf.description}
							</p>
						{/if}
					</button>
				{/each}
			{/if}
		</div>
	</div>
	<div class="modal-footer">
		<button class="btn-secondary" onclick={onClose} type="button">Close</button>
	</div>
{/snippet}
