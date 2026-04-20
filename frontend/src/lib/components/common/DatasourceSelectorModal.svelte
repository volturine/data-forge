<script lang="ts">
	import { Debounced } from 'runed';
	import { X } from 'lucide-svelte';
	import type { DataSource } from '$lib/types/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import type { SourceType } from '$lib/utils/file-types';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import { css } from '$lib/styles/panda';

	interface Props {
		show: boolean;
		datasources: DataSource[];
		isLoading?: boolean;
		mode?: 'add' | 'change';
		sourceType?: 'datasource' | 'analysis';
		allowAnalysis?: boolean;
		analysisTabs?: Array<{ id: string; name: string }>;
		excludeTabId?: string | null;
		onSelect: (id: string, name: string, sourceType: 'datasource' | 'analysis') => void;
		onClose: () => void;
	}

	let {
		show,
		datasources,
		isLoading = false,
		mode = 'add',
		sourceType = 'datasource',
		allowAnalysis = true,
		analysisTabs = [],
		excludeTabId = null,
		onSelect,
		onClose
	}: Props = $props();

	let searchQuery = $state('');
	const debouncedSearch = new Debounced(() => searchQuery, 200);
	let searchInput = $state<HTMLInputElement>();
	let activeOverride = $state<'datasource' | 'analysis' | null>(null);
	const activeSource = $derived(activeOverride ?? (allowAnalysis ? sourceType : 'datasource'));

	const filteredDatasources = $derived(
		datasources.filter((ds) => {
			const query = debouncedSearch.current.toLowerCase().trim();
			if (!query) return true;
			return ds.name.toLowerCase().includes(query);
		})
	);
	const filteredTabs = $derived(
		analysisTabs.filter((tab) => {
			if (mode === 'change' && excludeTabId && tab.id === excludeTabId) return false;
			const query = debouncedSearch.current.toLowerCase().trim();
			if (!query) return true;
			return tab.name.toLowerCase().includes(query);
		})
	);

	function handleClose() {
		activeOverride = null;
		onClose();
		searchQuery = '';
	}

	function handleSelect(datasourceId: string, name: string) {
		onSelect(datasourceId, name, activeSource);
		handleClose();
	}

	function handleAnalysisTabSelect(entry: { id: string; name: string }) {
		onSelect(entry.id, entry.name, 'analysis');
		handleClose();
	}

	// DOM: $derived can't focus the search input.
	$effect(() => {
		if (show && searchInput) {
			searchInput.focus();
		}
	});
</script>

<BaseModal
	open={show}
	onClose={handleClose}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass={css({
		display: 'flex',
		maxHeight: '80vh',
		width: '100%',
		maxWidth: 'modalSm',
		flexDirection: 'column',
		borderWidth: '1',
		backgroundColor: 'bg.primary',
		outline: 'none'
	})}
	ariaLabelledby="modal-title"
	{content}
/>

{#snippet content()}
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'space-between',
			padding: '4'
		})}
	>
		<h2 id="modal-title" class={css({ margin: '0', fontSize: 'sm', fontWeight: 'semibold' })}>
			{mode === 'change' ? 'Change Datasource' : 'Add Datasource'}
		</h2>
		<button
			class={css({
				display: 'flex',
				cursor: 'pointer',
				alignItems: 'center',
				justifyContent: 'center',
				border: 'none',
				backgroundColor: 'transparent',
				padding: '1',
				color: 'fg.muted',
				_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
			})}
			onclick={handleClose}
			aria-label="Close"
			type="button"
		>
			<X size={20} />
		</button>
	</div>
	<div
		class={css({
			display: 'flex',
			flexDirection: 'column',
			gap: '4',
			overflowY: 'auto',
			padding: '4'
		})}
	>
		{#if allowAnalysis}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '1',
					borderWidth: '1',
					backgroundColor: 'bg.tertiary',
					padding: '1'
				})}
			>
				<button
					class={css({
						flex: '1',
						border: 'none',
						paddingX: '3',
						paddingY: '2',
						fontSize: 'xs',
						fontWeight: 'semibold',
						textTransform: 'uppercase',
						letterSpacing: 'wide3',
						color: activeSource === 'datasource' ? 'fg.primary' : 'fg.muted',
						backgroundColor: activeSource === 'datasource' ? 'bg.primary' : 'transparent'
					})}
					onclick={() => (activeOverride = 'datasource')}
					type="button"
				>
					Datasources
				</button>
				<button
					class={css({
						flex: '1',
						border: 'none',
						paddingX: '3',
						paddingY: '2',
						fontSize: 'xs',
						fontWeight: 'semibold',
						textTransform: 'uppercase',
						letterSpacing: 'wide3',
						color: activeSource === 'analysis' ? 'fg.primary' : 'fg.muted',
						backgroundColor: activeSource === 'analysis' ? 'bg.primary' : 'transparent'
					})}
					onclick={() => (activeOverride = 'analysis')}
					type="button"
				>
					Analyses
				</button>
			</div>
		{/if}
		<input
			class={css({
				width: 'full',
				color: 'fg.primary',
				backgroundColor: 'bg.primary',
				borderWidth: '1',
				borderRadius: '0',
				transitionProperty: 'border-color',
				transitionDuration: '160ms',
				transitionTimingFunction: 'ease',
				_focusVisible: { borderColor: 'border.accent' },
				_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
				_placeholder: { color: 'fg.muted' },
				paddingX: '3',
				paddingY: '3',
				fontSize: 'sm',
				_focus: { borderColor: 'border.accent' }
			})}
			type="text"
			bind:this={searchInput}
			id="dsm-search"
			aria-label="Search datasources"
			bind:value={searchQuery}
			placeholder={activeSource === 'analysis' ? 'Search analyses...' : 'Search datasources...'}
		/>
		<div
			class={css({
				display: 'flex',
				maxHeight: 'dropdownTall',
				flexDirection: 'column',
				gap: '1',
				overflowY: 'auto'
			})}
		>
			{#if isLoading}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						padding: '8',
						fontSize: 'sm',
						color: 'fg.muted'
					})}
				>
					Loading...
				</div>
			{:else if activeSource === 'analysis' && allowAnalysis && filteredTabs.length === 0}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						padding: '8',
						fontSize: 'sm',
						color: 'fg.muted'
					})}
				>
					{searchQuery ? 'No matching analysis tabs' : 'No analysis tabs available'}
				</div>
			{:else if activeSource === 'datasource' && filteredDatasources.length === 0}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						padding: '8',
						fontSize: 'sm',
						color: 'fg.muted'
					})}
				>
					{searchQuery ? 'No matching datasources' : 'No datasources available'}
				</div>
			{:else if activeSource === 'analysis' && allowAnalysis}
				{#each filteredTabs as entry (entry.id)}
					<button
						data-analysis-tab-option={entry.name}
						class={css({
							display: 'flex',
							cursor: 'pointer',
							alignItems: 'center',
							justifyContent: 'space-between',
							borderWidth: '1',
							borderColor: 'transparent',
							backgroundColor: 'transparent',
							padding: '3',
							textAlign: 'left',
							_hover: { backgroundColor: 'bg.hover' }
						})}
						onclick={() => handleAnalysisTabSelect(entry)}
						type="button"
					>
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>
							{entry.name}
						</span>
						<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>analysis tab</span>
					</button>
				{/each}
			{:else}
				{#each filteredDatasources as ds (ds.id)}
					<button
						data-datasource-option={ds.name}
						class={css({
							display: 'flex',
							cursor: 'pointer',
							alignItems: 'center',
							justifyContent: 'space-between',
							borderWidth: '1',
							borderColor: 'transparent',
							backgroundColor: 'transparent',
							padding: '3',
							textAlign: 'left',
							_hover: { backgroundColor: 'bg.hover' }
						})}
						onclick={() => handleSelect(ds.id, ds.name)}
						type="button"
					>
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>
							{ds.name}
						</span>
						<span
							class={css({ display: 'flex', alignItems: 'center', gap: '1', color: 'fg.muted' })}
						>
							{#if ds.source_type === 'file'}
								<FileTypeBadge path={ds.config.file_path as string} size="sm" showIcon={true} />
							{:else}
								<FileTypeBadge
									sourceType={ds.source_type as SourceType}
									size="sm"
									showIcon={true}
								/>
							{/if}
						</span>
					</button>
				{/each}
			{/if}
		</div>
	</div>
{/snippet}
