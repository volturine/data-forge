<script lang="ts">
	import { untrack } from 'svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { Copy, Download, X } from '@lucide/svelte';
	import { css, button, spinner } from '$lib/styles/panda';
	import {
		exportAnalysisCode,
		type CodeExportFormat,
		type CodeExportResponse
	} from '$lib/api/analysis';
	import { downloadBlob } from '$lib/api/compute';

	interface Props {
		open: boolean;
		validAnalysisId: string | null;
		scopeTabId: string | null;
		tabs: { id: string; name: string }[];
		onClose: () => void;
	}

	let { open, validAnalysisId, scopeTabId, tabs, onClose }: Props = $props();

	let exportScopeTabId = $state<string | null>(null);
	let exportFormat = $state<CodeExportFormat>('polars');
	let exportCopied = $state(false);
	let exportError = $state<string | null>(null);
	let exportByFormat = $state<Record<CodeExportFormat, CodeExportResponse | null>>({
		polars: null,
		sql: null
	});
	let exportLoadingByFormat = $state<Record<CodeExportFormat, boolean>>({
		polars: false,
		sql: false
	});

	const exportResponse = $derived(exportByFormat[exportFormat]);
	const exportWarnings = $derived(exportResponse?.warnings ?? []);
	const exportCode = $derived(exportResponse?.code ?? '');
	const exportFilename = $derived(exportResponse?.filename ?? '');
	const exportLoading = $derived(exportLoadingByFormat[exportFormat]);
	const exportScopeTabName = $derived.by(() => {
		const id = exportScopeTabId;
		if (!id) return null;
		const tab = tabs.find((item) => item.id === id);
		return tab?.name ?? null;
	});

	function resetExportState() {
		exportByFormat = { polars: null, sql: null };
		exportLoadingByFormat = { polars: false, sql: false };
		exportError = null;
		exportCopied = false;
	}

	async function loadExportCode(format: CodeExportFormat) {
		if (!validAnalysisId) return;
		if (exportLoadingByFormat[format]) return;
		exportLoadingByFormat = { ...exportLoadingByFormat, [format]: true };
		exportError = null;
		const result = await exportAnalysisCode(validAnalysisId, {
			format,
			tab_id: exportScopeTabId
		});
		if (result.isErr()) {
			exportError = result.error.message;
			exportLoadingByFormat = { ...exportLoadingByFormat, [format]: false };
			return;
		}
		exportByFormat = { ...exportByFormat, [format]: result.value };
		exportLoadingByFormat = { ...exportLoadingByFormat, [format]: false };
	}

	function selectExportFormat(format: CodeExportFormat) {
		exportFormat = format;
		exportError = null;
		if (!exportByFormat[format]) {
			void loadExportCode(format);
		}
	}

	async function copyExportCode() {
		if (!exportCode) return;
		try {
			await navigator.clipboard.writeText(exportCode);
			exportCopied = true;
		} catch {
			exportError = 'Clipboard write failed. Copy manually from the code block.';
		}
	}

	function downloadExportCodeFile() {
		if (!exportCode || !exportFilename) return;
		const type = exportFormat === 'sql' ? 'text/sql;charset=utf-8' : 'text/x-python;charset=utf-8';
		downloadBlob(new Blob([exportCode], { type }), exportFilename);
	}

	function closeExportModal() {
		onClose();
		exportScopeTabId = null;
		exportError = null;
		exportCopied = false;
	}

	$effect(() => {
		if (!open) return;
		// Run the open transition imperatively: loadExportCode reads and writes
		// reactive state, so tracking it here would re-trigger this effect and
		// reset the response it just loaded.
		untrack(() => {
			exportScopeTabId = scopeTabId;
			exportFormat = 'polars';
			resetExportState();
			void loadExportCode('polars');
		});
	});

	// Timer: copied state is transient UI feedback.
	$effect(() => {
		if (!exportCopied) return;
		const timer = window.setTimeout(() => {
			exportCopied = false;
		}, 1200);
		return () => window.clearTimeout(timer);
	});
</script>

{#snippet exportModalContent()}
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
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
			<h2 id="analysis-export-title">Export Code</h2>
			<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>
				{exportScopeTabName ? `Tab: ${exportScopeTabName}` : 'Scope: Full pipeline'}
			</span>
		</div>
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
			onclick={closeExportModal}
			aria-label="Close export modal"
		>
			<X size={16} />
		</button>
	</div>
	<div
		class={css({
			display: 'flex',
			flexDirection: 'column',
			gap: '3',
			padding: '4',
			minHeight: '0',
			overflow: 'auto'
		})}
	>
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between',
				gap: '2',
				flexWrap: 'wrap'
			})}
		>
			<div role="tablist" aria-label="Export format" class={css({ display: 'flex', gap: '1' })}>
				<button
					class={button({
						variant: exportFormat === 'polars' ? 'primary' : 'secondary',
						size: 'sm'
					})}
					type="button"
					role="tab"
					aria-selected={exportFormat === 'polars'}
					onclick={() => selectExportFormat('polars')}
					data-testid="analysis-export-format-polars"
				>
					Polars (Python)
				</button>
				<button
					class={button({ variant: exportFormat === 'sql' ? 'primary' : 'secondary', size: 'sm' })}
					type="button"
					role="tab"
					aria-selected={exportFormat === 'sql'}
					onclick={() => selectExportFormat('sql')}
					data-testid="analysis-export-format-sql"
				>
					SQL
				</button>
			</div>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<button
					class={button({ variant: 'secondary', size: 'sm' })}
					type="button"
					onclick={copyExportCode}
					disabled={!exportCode || exportLoading}
					data-testid="analysis-export-copy"
				>
					<Copy size={13} />
					{exportCopied ? 'Copied' : 'Copy to Clipboard'}
				</button>
				<button
					class={button({ variant: 'secondary', size: 'sm' })}
					type="button"
					onclick={downloadExportCodeFile}
					disabled={!exportCode || exportLoading}
					data-testid="analysis-export-download"
				>
					<Download size={13} />
					Download
				</button>
			</div>
		</div>

		{#if exportFilename}
			<div
				class={css({ fontSize: 'xs', color: 'fg.muted' })}
				data-testid="analysis-export-filename"
			>
				{exportFilename}
			</div>
		{/if}

		{#if exportError}
			<div data-testid="analysis-export-error">
				<Callout tone="error">{exportError}</Callout>
			</div>
		{/if}

		{#if exportWarnings.length > 0}
			<div data-testid="analysis-export-warnings">
				<Callout tone="warn">
					{#each exportWarnings as warning, idx (idx)}
						<div>{warning}</div>
					{/each}
				</Callout>
			</div>
		{/if}

		{#if exportLoading}
			<div class={css({ display: 'flex', justifyContent: 'center', paddingY: '8' })}>
				<div class={spinner()}></div>
			</div>
		{:else}
			<pre
				class={css({
					fontFamily: 'mono',
					fontSize: 'xs',
					lineHeight: '1.45',
					backgroundColor: 'bg.secondary',
					borderWidth: '1',
					padding: '3',
					overflowX: 'auto',
					whiteSpace: 'pre'
				})}
				data-testid="analysis-export-code"
				data-language={exportFormat}><code>{exportCode}</code></pre>
		{/if}
	</div>
	<div
		class={css({
			paddingX: '4',
			paddingY: '3',
			borderTopWidth: '1',
			display: 'flex',
			justifyContent: 'flex-end'
		})}
	>
		<button class={button({ variant: 'secondary' })} onclick={closeExportModal} type="button"
			>Close</button
		>
	</div>
{/snippet}

<BaseModal
	{open}
	onClose={closeExportModal}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass={css({
		width: 'min(960px, 96vw)',
		maxHeight: '86vh',
		backgroundColor: 'bg.primary',
		borderWidth: '1',
		display: 'flex',
		flexDirection: 'column',
		_focus: { outline: 'none' }
	})}
	ariaLabelledby="analysis-export-title"
	content={exportModalContent}
/>
