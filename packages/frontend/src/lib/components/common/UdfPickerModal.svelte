<script lang="ts">
	import type { Udf } from '$lib/types/udf';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import { X } from 'lucide-svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import PanelFooter from '$lib/components/ui/PanelFooter.svelte';
	import { css, button, input } from '$lib/styles/panda';

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
	{onClose}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass={css({
		width: 'full',
		maxWidth: 'modalSm',
		maxHeight: 'screenTall',
		overflowY: 'auto',
		borderWidth: '1',
		backgroundColor: 'bg.primary'
	})}
	ariaLabelledby="udf-modal-title"
	{content}
/>

{#snippet content()}
	<PanelHeader>
		{#snippet title()}
			<h2 id="udf-modal-title" class={css({ margin: '0', fontSize: 'md' })}>Select UDF</h2>
		{/snippet}
		{#snippet actions()}
			<button
				class={css({
					background: 'transparent',
					border: 'none',
					color: 'fg.muted',
					cursor: 'pointer',
					padding: '1',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
				})}
				onclick={onClose}
				aria-label="Close"
				type="button"
			>
				<X size={16} />
			</button>
		{/snippet}
	</PanelHeader>
	<div
		class={css({
			padding: '4',
			overflowY: 'auto',
			display: 'flex',
			flexDirection: 'column',
			gap: '3'
		})}
	>
		<input
			name="search"
			type="text"
			placeholder="Search UDFs..."
			bind:value={search}
			class={input()}
		/>
		<div
			class={css({
				display: 'flex',
				flexDirection: 'column',
				gap: '2',
				maxHeight: 'popover',
				overflow: 'auto'
			})}
		>
			{#if filtered.length === 0}
				<p class={css({ margin: '0', color: 'fg.muted' })}>No matching UDFs.</p>
			{:else}
				{#each filtered as udf (udf.id)}
					<button
						class={css({
							textAlign: 'left',
							padding: '3',
							borderWidth: '1',

							backgroundColor: 'bg.secondary',
							cursor: 'pointer',
							_hover: { backgroundColor: 'bg.hover' }
						})}
						type="button"
						onclick={() => onSelect(udf)}
					>
						<div
							class={css({
								display: 'flex',
								justifyContent: 'space-between',
								gap: '3',
								fontWeight: 'medium'
							})}
						>
							<span>{udf.name}</span>
							<div
								class={css({
									display: 'flex',
									alignItems: 'center',
									gap: '1',
									flexWrap: 'wrap'
								})}
							>
								{#if udf.signature?.inputs?.length}
									{#each udf.signature.inputs as input, i (i)}
										<ColumnTypeBadge columnType={input.dtype} size="xs" showIcon={false} />
										{#if i < udf.signature.inputs.length - 1}
											<span class={css({ fontSize: 'xs', marginX: '0.5', color: 'fg.muted' })}
												>,</span
											>
										{/if}
									{/each}
								{:else}
									<span
										class={css({
											fontSize: 'xs',
											textTransform: 'uppercase',
											letterSpacing: 'wide',
											color: 'fg.muted'
										})}>No inputs</span
									>
								{/if}
							</div>
						</div>
						{#if udf.description}
							<p
								class={css({
									marginTop: '2',
									marginBottom: '0',
									fontSize: 'sm',
									color: 'fg.secondary'
								})}
							>
								{udf.description}
							</p>
						{/if}
					</button>
				{/each}
			{/if}
		</div>
	</div>
	<PanelFooter>
		<button class={button({ variant: 'secondary' })} onclick={onClose} type="button">Close</button>
	</PanelFooter>
{/snippet}
