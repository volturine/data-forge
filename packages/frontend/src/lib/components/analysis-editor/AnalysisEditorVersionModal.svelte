<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import { Pencil, Trash2, X } from '@lucide/svelte';
	import { css, button } from '$lib/styles/panda';
	import {
		listAnalysisVersions,
		restoreAnalysisVersion,
		renameAnalysisVersion,
		deleteAnalysisVersion
	} from '$lib/api/analysis';
	import { formatDateTimeDisplay, toEpochDisplay } from '$lib/utils/datetime';
	import type { Analysis } from '$lib/types/analysis';

	interface Props {
		open: boolean;
		analysisId: string | null;
		validAnalysisId: string | null;
		currentRevision: string | null;
		editorReadOnly: boolean;
		onRestored: (restored: { analysis: Analysis; version: string }) => void;
		onClose: () => void;
	}

	let {
		open,
		analysisId,
		validAnalysisId,
		currentRevision,
		editorReadOnly,
		onRestored,
		onClose
	}: Props = $props();

	let versionError = $state<string | null>(null);
	let editingVersionId = $state<string | null>(null);
	let editingVersionName = $state('');

	const versionsQuery = createQuery(() => ({
		queryKey: ['analysis-versions', analysisId],
		enabled: open,
		staleTime: 0,
		queryFn: async () => {
			if (!analysisId) throw new Error('Analysis ID is required');
			if (!validAnalysisId) throw new Error('Invalid analysis ID format');
			const result = await listAnalysisVersions(validAnalysisId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	function closeVersionModal() {
		onClose();
		versionError = null;
	}

	function formatVersionDate(value: string | null | undefined): string {
		if (!value) return 'Unknown';
		if (Number.isNaN(toEpochDisplay(value))) return 'Unknown';
		return formatDateTimeDisplay(value);
	}

	async function handleRestoreVersion(version: number) {
		if (!analysisId || editorReadOnly) return;
		if (!currentRevision) {
			versionError = 'Analysis response is missing its revision';
			return;
		}
		versionError = null;
		const result = await restoreAnalysisVersion(analysisId, version, currentRevision);
		if (result.isErr()) {
			versionError = result.error.message;
			return;
		}
		onRestored(result.value);
		closeVersionModal();
	}

	function startRenameVersion(id: string, name: string) {
		if (editorReadOnly) return;
		editingVersionId = id;
		editingVersionName = name;
	}

	async function commitRenameVersion(version: number) {
		if (!analysisId || !editingVersionId || editorReadOnly) return;
		const trimmed = editingVersionName.trim();
		if (!trimmed) {
			editingVersionId = null;
			return;
		}
		if (!currentRevision) {
			versionError = 'Analysis response is missing its revision';
			editingVersionId = null;
			return;
		}
		const result = await renameAnalysisVersion(analysisId, version, trimmed, currentRevision);
		if (result.isErr()) {
			versionError = result.error.message;
			editingVersionId = null;
			return;
		}
		void versionsQuery.refetch();
		editingVersionId = null;
	}

	async function handleDeleteVersion(version: number) {
		if (!analysisId || editorReadOnly) return;
		if (!currentRevision) {
			versionError = 'Analysis response is missing its revision';
			return;
		}
		versionError = null;
		const result = await deleteAnalysisVersion(analysisId, version, currentRevision);
		if (result.isErr()) {
			versionError = result.error.message;
			return;
		}
		void versionsQuery.refetch();
	}
</script>

{#snippet versionModalContent()}
	<div
		class={css({
			display: 'flex',
			justifyContent: 'space-between',
			alignItems: 'center',
			paddingX: '4',
			paddingY: '3',
			borderBottomWidth: '1',
			'& h2': { margin: '0', fontSize: 'md', color: 'fg.primary' }
		})}
	>
		<h2 id="analysis-version-title">Version history</h2>
		<button
			class={css({
				background: 'transparent',
				border: 'none',
				color: 'fg.muted',
				cursor: 'pointer',
				fontSize: 'xl',
				padding: '1',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				transitionProperty: 'color, background-color',
				transitionDuration: 'normal',
				_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
			})}
			onclick={closeVersionModal}
			aria-label="Close version history"
		>
			<X size={16} />
		</button>
	</div>
	<div
		class={css({
			padding: '4',
			overflowY: 'auto',
			display: 'flex',
			flexDirection: 'column',
			gap: '3'
		})}
	>
		{#if versionError}
			<div
				data-testid="version-error"
				class={css({
					paddingX: '2.5',
					paddingY: '3',
					border: 'none',
					borderLeftWidth: '2',

					marginTop: '3',
					marginBottom: '0',
					fontSize: 'xs',
					lineHeight: '1.5',
					backgroundColor: 'transparent',
					borderLeftColor: 'border.error',
					color: 'fg.error',
					margin: '0'
				})}
			>
				{versionError}
			</div>
		{/if}
		{#if versionsQuery.isLoading}
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
		{:else if versionsQuery.isError}
			<div
				data-testid="version-load-error"
				class={css({
					paddingX: '2.5',
					paddingY: '3',
					border: 'none',
					borderLeftWidth: '2',

					marginTop: '3',
					marginBottom: '0',
					fontSize: 'xs',
					lineHeight: '1.5',
					backgroundColor: 'transparent',
					borderLeftColor: 'border.error',
					color: 'fg.error',
					margin: '0'
				})}
			>
				Failed to load version history.
			</div>
		{:else if !versionsQuery.data?.length}
			<p
				class={css({
					color: 'fg.muted',
					fontStyle: 'italic',
					textAlign: 'center',
					padding: '4',
					margin: '0'
				})}
			>
				No versions available.
			</p>
		{:else}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
				{#each versionsQuery.data as version (version.id)}
					<div
						data-testid="version-row-{version.version}"
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'space-between',
							gap: '4',
							borderWidth: '1',
							backgroundColor: 'bg.tertiary',
							padding: '3'
						})}
					>
						<div class={css({ display: 'flex', minWidth: '0', flexDirection: 'column' })}>
							<div
								class={css({
									fontSize: '2xs2',
									textTransform: 'uppercase',
									letterSpacing: 'widest',
									color: 'fg.muted'
								})}
							>
								Version {version.version} · {formatVersionDate(version.created_at)}
							</div>
							{#if editingVersionId === version.id}
								<input
									type="text"
									class={css({
										width: 'full',
										color: 'fg.primary',
										borderWidth: '1',
										borderRadius: '0',
										transitionProperty: 'border-color',
										transitionDuration: '160ms',
										transitionTimingFunction: 'ease',
										_focus: { outline: 'none' },
										_focusVisible: { borderColor: 'border.accent' },
										_disabled: {
											opacity: '0.5',
											cursor: 'not-allowed'
										},
										_placeholder: { color: 'fg.muted' },
										fontSize: 'sm',
										fontWeight: 'semibold',
										backgroundColor: 'transparent',
										paddingX: '1',
										paddingY: '0.5'
									})}
									id="version-name-{version.id}"
									aria-label="Version name"
									bind:value={editingVersionName}
									disabled={editorReadOnly}
									onblur={() => commitRenameVersion(version.version)}
									onkeydown={(e) => {
										if (e.key === 'Enter') commitRenameVersion(version.version);
										else if (e.key === 'Escape') editingVersionId = null;
									}}
								/>
							{:else}
								<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
									<span class={css({ fontSize: 'sm', fontWeight: 'semibold' })}>
										{version.name}
									</span>
									<button
										class={css({
											padding: '0.5',
											backgroundColor: 'transparent',
											borderColor: 'transparent',
											color: 'fg.muted',
											_hover: { color: 'fg.primary' }
										})}
										title="Rename version"
										data-testid="version-rename-{version.version}"
										onclick={() => startRenameVersion(version.id, version.name)}
										disabled={editorReadOnly}
									>
										<Pencil size={12} />
									</button>
								</div>
							{/if}
							{#if version.description}
								<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>
									{version.description}
								</div>
							{/if}
						</div>
						<div class={css({ display: 'flex', gap: '1', flexShrink: '0', alignItems: 'center' })}>
							<button
								class={css({
									padding: '0.5',
									backgroundColor: 'transparent',
									border: 'none',
									color: 'fg.muted',
									cursor: 'pointer',
									_hover: { color: 'fg.error' }
								})}
								title="Delete version"
								data-testid="version-delete-{version.version}"
								onclick={() => handleDeleteVersion(version.version)}
								disabled={editorReadOnly}
							>
								<Trash2 size={14} />
							</button>
							<button
								class={button({ variant: 'secondary', size: 'sm' })}
								data-testid="version-restore-{version.version}"
								onclick={() => handleRestoreVersion(version.version)}
								type="button"
								disabled={editorReadOnly}
							>
								Restore
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
	<div
		class={css({
			paddingX: '4',
			paddingY: '3',
			borderTopWidth: '1',
			display: 'flex',
			justifyContent: 'flex-end',
			gap: '2'
		})}
	>
		<button class={button({ variant: 'secondary' })} onclick={closeVersionModal} type="button"
			>Close</button
		>
	</div>
{/snippet}

<BaseModal
	{open}
	onClose={closeVersionModal}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass={css({
		width: 'min(720px, 92vw)',
		maxHeight: '80vh',
		backgroundColor: 'bg.primary',
		borderWidth: '1',
		display: 'flex',
		flexDirection: 'column',
		_focus: { outline: 'none' }
	})}
	ariaLabelledby="analysis-version-title"
	content={versionModalContent}
/>
