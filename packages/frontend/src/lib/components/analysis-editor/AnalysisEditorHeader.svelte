<script lang="ts">
	import {
		Lock,
		LockOpen,
		Clock,
		ChevronDown,
		ChevronLeft,
		ChevronRight,
		ChevronUp,
		PanelRight,
		PanelBottom,
		Pencil,
		Plus,
		Star,
		X
	} from '@lucide/svelte';
	import { css } from '$lib/styles/panda';
	import type { EditorAccessState } from '$lib/utils/analysis-lock-state';
	import type { AnalysisTab } from '$lib/types/analysis';

	interface Props {
		tabs: AnalysisTab[];
		activeTabId: string | null;
		titleName: string;
		description: string | null;
		favorite: boolean;
		loading: boolean;
		editorReadOnly: boolean;
		editorAccessState: EditorAccessState;
		isDirty: boolean;
		isSaving: boolean;
		saveButtonState: string;
		saveButtonLabel: string;
		lockButtonLabel: string;
		lockButtonDisabled: boolean;
		leftPaneCollapsed: boolean;
		rightPaneCollapsed: boolean;
		configPosition: 'right' | 'bottom';
		onToggleFavorite: () => void;
		onEditDescription: () => void;
		onCommitTitle: (name: string) => void;
		onSelectTab: (tabId: string) => void;
		onTabContextMenu: (event: MouseEvent, tabId: string) => void;
		onRemoveTab: (tabId: string) => void;
		onAddDatasourceTab: () => void;
		onToggleLock: () => void;
		onExport: () => void;
		onDiscard: () => void;
		onSave: () => void;
		onOpenVersions: () => void;
	}

	let {
		tabs,
		activeTabId,
		titleName,
		description,
		favorite,
		loading,
		editorReadOnly,
		editorAccessState,
		isDirty,
		isSaving,
		saveButtonState,
		saveButtonLabel,
		lockButtonLabel,
		lockButtonDisabled,
		leftPaneCollapsed = $bindable(false),
		rightPaneCollapsed = $bindable(false),
		configPosition = $bindable('right'),
		onToggleFavorite,
		onEditDescription,
		onCommitTitle,
		onSelectTab,
		onTabContextMenu,
		onRemoveTab,
		onAddDatasourceTab,
		onToggleLock,
		onExport,
		onDiscard,
		onSave,
		onOpenVersions
	}: Props = $props();
</script>

<header
	class={css({
		display: 'flex',
		alignItems: 'stretch',
		position: 'sticky',
		top: '0',
		height: 'headerSm',
		backgroundColor: 'bg.primary',
		zIndex: 'header'
	})}
>
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			height: '100%',
			boxSizing: 'border-box',
			borderRightWidth: '1',
			width: 'operationsPanel',
			transitionProperty: 'width, visibility',
			transitionDuration: 'normal'
		})}
	>
		<div
			class={css({
				flex: '1',
				display: 'flex',
				flexDirection: 'column',
				minWidth: '0',
				overflow: 'hidden',
				paddingX: '5',
				gap: '1'
			})}
		>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2', minWidth: '0' })}>
				<h1
					contenteditable={!editorReadOnly}
					class={css({
						margin: '0',
						flex: '1',
						minWidth: '0',
						fontSize: 'xs',
						fontWeight: 'semibold',
						textTransform: 'uppercase',
						whiteSpace: 'nowrap',
						overflow: 'hidden',
						textOverflow: 'ellipsis',
						outline: 'none',
						letterSpacing: 'wide2',
						cursor: editorReadOnly ? 'default' : 'text',
						_focus: {
							backgroundColor: 'bg.hover',
							paddingX: '1',
							marginX: 'calc({spacing.1} * -1)'
						}
					})}
					onblur={(e) => {
						if (editorReadOnly) {
							e.currentTarget.textContent = titleName;
							return;
						}
						const newName = e.currentTarget.textContent?.trim();
						if (newName && newName !== titleName) {
							onCommitTitle(newName);
							return;
						}
						e.currentTarget.textContent = titleName;
					}}
				>
					{titleName}
				</h1>
				<button
					class={css({
						display: 'inline-flex',
						alignItems: 'center',
						justifyContent: 'center',
						width: '6',
						height: '6',
						flexShrink: '0',
						backgroundColor: 'transparent',
						border: 'none',
						cursor: 'pointer',
						color: favorite ? 'accent.primary' : 'fg.muted',
						_hover: { color: 'accent.primary', backgroundColor: 'bg.hover' }
					})}
					type="button"
					onclick={onToggleFavorite}
					aria-label={favorite ? 'Remove analysis from favorites' : 'Add analysis to favorites'}
					data-testid="analysis-favorite-toggle"
				>
					<Star size={14} fill={favorite ? 'currentColor' : 'none'} />
				</button>
			</div>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2', minWidth: '0' })}>
				{#if description}
					<span
						class={css({
							fontSize: '2xs',
							whiteSpace: 'nowrap',
							overflow: 'hidden',
							textOverflow: 'ellipsis',
							color: 'fg.faint',
							letterSpacing: 'tight2',
							minWidth: '0',
							flex: '1'
						})}
					>
						{description}
					</span>
				{:else if !editorReadOnly}
					<span class={css({ fontSize: '2xs', color: 'fg.muted', flex: '1' })}>
						No description
					</span>
				{/if}
				{#if !editorReadOnly}
					<button
						class={css({
							display: 'inline-flex',
							alignItems: 'center',
							gap: '1',
							flexShrink: '0',
							backgroundColor: 'transparent',
							border: 'none',
							padding: '0',
							fontSize: '2xs',
							color: 'fg.muted',
							cursor: 'pointer',
							_hover: { color: 'fg.primary' }
						})}
						type="button"
						onclick={onEditDescription}
						aria-label={description ? 'Edit description' : 'Add description'}
						data-testid="analysis-description-trigger"
					>
						<Pencil size={12} />
						<span>{description ? 'Edit' : 'Add description'}</span>
					</button>
				{/if}
			</div>
		</div>
	</div>
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			flex: '1',
			minWidth: '0',
			overflow: 'hidden',
			justifyContent: 'center',
			gap: '0'
		})}
	>
		<button
			class={css({
				height: '100%',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				paddingX: '2',
				backgroundColor: 'bg.primary',
				border: 'none',
				cursor: 'pointer',
				flexShrink: '0',
				color: 'fg.faint',
				_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
			})}
			onclick={() => {
				leftPaneCollapsed = !leftPaneCollapsed;
				rightPaneCollapsed = !rightPaneCollapsed;
			}}
			type="button"
			title={leftPaneCollapsed ? 'Expand panels' : 'Collapse panels'}
		>
			{#if leftPaneCollapsed}
				<ChevronRight size={12} />
			{:else}
				<ChevronLeft size={12} />
			{/if}
		</button>
		<div class={css({ display: 'flex', alignItems: 'center', flex: '1', overflow: 'hidden' })}>
			<div class={css({ display: 'flex', alignItems: 'center', overflowX: 'auto', gap: '0' })}>
				{#each tabs as tab (tab.id)}
					<div
						class={css({
							display: 'inline-flex',
							alignItems: 'center',
							backgroundColor: 'transparent',
							border: 'none',
							fontSize: 'xs',
							fontWeight: 'medium',
							textTransform: 'uppercase',
							color: 'fg.muted',
							letterSpacing: 'wide',
							...(activeTabId === tab.id
								? { color: 'fg.primary', backgroundColor: 'bg.secondary' }
								: {})
						})}
					>
						<button
							class={css({
								display: 'inline-flex',
								alignItems: 'center',
								minWidth: '0',
								backgroundColor: 'transparent',
								border: 'none',
								cursor: 'pointer'
							})}
							onclick={() => onSelectTab(tab.id)}
							oncontextmenu={(event) => onTabContextMenu(event, tab.id)}
							type="button"
							data-testid={`tab-button-${tab.id}`}
							data-tab-name={tab.name}
						>
							<span
								class={css({
									whiteSpace: 'nowrap',
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									maxWidth: 'inputSm'
								})}
							>
								{tab.name}
							</span>
						</button>
						{#if tabs.length > 1}
							<button
								class={css({
									fontSize: 'md',
									lineHeight: '1',
									marginLeft: '1',
									backgroundColor: 'transparent',
									opacity: '0.4',
									_hover: { opacity: '1', color: 'fg.error' }
								})}
								onclick={() => onRemoveTab(tab.id)}
								type="button"
								aria-label="Remove tab"
								disabled={editorReadOnly}
							>
								<X size={10} />
							</button>
						{/if}
					</div>
				{/each}
				<div class={css({ display: 'flex', alignItems: 'center' })}>
					<button
						class={css({
							display: 'inline-flex',
							alignItems: 'center',
							backgroundColor: 'transparent',
							border: 'none',
							cursor: 'pointer',
							fontSize: 'xs',
							textTransform: 'uppercase',
							color: 'fg.faint',
							_hover: { color: 'fg.primary' }
						})}
						onclick={onAddDatasourceTab}
						type="button"
						title="Add datasource tab"
						disabled={editorReadOnly}
					>
						<Plus size={12} />
					</button>
				</div>
			</div>
		</div>
	</div>
	<button
		class={css({
			flexShrink: '0',
			height: '100%',
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			paddingX: '2',
			backgroundColor: 'bg.primary',
			border: 'none',
			cursor: 'pointer',
			color: 'fg.faint',
			_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
		})}
		onclick={() => {
			configPosition = configPosition === 'right' ? 'bottom' : 'right';
		}}
		type="button"
		title={configPosition === 'right' ? 'Move config to bottom' : 'Move config to side'}
	>
		{#if configPosition === 'right'}
			<PanelBottom size={13} />
		{:else}
			<PanelRight size={13} />
		{/if}
	</button>
	<button
		class={css({
			display: 'flex',
			alignItems: 'center',
			paddingX: '2',
			backgroundColor: 'bg.primary',
			border: 'none',
			color: 'fg.faint',
			_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
		})}
		onclick={() => {
			rightPaneCollapsed = !rightPaneCollapsed;
			leftPaneCollapsed = !leftPaneCollapsed;
		}}
		type="button"
		title={rightPaneCollapsed ? 'Expand panels' : 'Collapse panels'}
	>
		{#if configPosition === 'bottom'}
			{#if leftPaneCollapsed}
				<ChevronUp size={12} />
			{:else}
				<ChevronDown size={12} />
			{/if}
		{:else if leftPaneCollapsed}
			<ChevronLeft size={12} />
		{:else}
			<ChevronRight size={12} />
		{/if}
	</button>
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'flex-end',
			height: '100%',
			boxSizing: 'border-box',
			borderLeftWidth: '1',
			width: 'operationsPanel',
			transitionProperty: 'width, visibility',
			transitionDuration: 'normal'
		})}
	>
		<div class={css({ display: 'flex', height: '100%', flex: '1', padding: '1', gap: '1' })}>
			<button
				class={css({
					display: 'flex',
					flexShrink: '0',
					alignItems: 'center',
					justifyContent: 'center',
					width: '8',
					height: '100%',
					padding: '0',
					backgroundColor: 'transparent',
					border: 'none',
					cursor: 'pointer',
					color: editorAccessState === 'editable' ? 'fg.warning' : 'fg.muted',
					_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' },
					_disabled: { opacity: '0.5', cursor: 'not-allowed' }
				})}
				onclick={onToggleLock}
				disabled={lockButtonDisabled}
				type="button"
				aria-label={lockButtonLabel}
				title={lockButtonLabel}
				data-testid="lock-toggle-button"
			>
				{#if editorAccessState === 'editable'}
					<LockOpen size={14} />
				{:else}
					<Lock size={14} />
				{/if}
			</button>
			<button
				class={css({
					flex: '1 1 0',
					minWidth: '0',
					height: '100%',
					backgroundColor: 'bg.tertiary',
					border: 'none',
					fontSize: 'xs',
					fontWeight: 'medium',
					cursor: 'pointer',
					color: 'fg.faint',
					borderRadius: 'xs',
					paddingX: '2.5',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
				})}
				onclick={onExport}
				type="button"
				title="Export pipeline as code"
				data-testid="analysis-export-toolbar-button"
			>
				Export
			</button>
			<button
				class={css({
					flex: '1 1 0',
					minWidth: '0',
					height: '100%',
					backgroundColor: 'bg.tertiary',
					border: 'none',
					fontSize: 'xs',
					fontWeight: 'medium',
					cursor: 'pointer',
					color: isDirty ? 'fg.primary' : 'fg.muted',
					borderRadius: 'xs',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
					_disabled: { opacity: '1', color: 'fg.muted', cursor: 'not-allowed' }
				})}
				onclick={onDiscard}
				disabled={!isDirty || isSaving || loading || editorReadOnly}
				type="button"
			>
				Discard
			</button>
			<button
				class={css({
					flex: '1 1 0',
					minWidth: '0',
					height: '100%',
					border: 'none',
					borderRadius: 'xs',
					backgroundColor: 'bg.tertiary',
					fontSize: 'xs',
					fontWeight: 'medium',
					cursor: 'pointer',
					color: 'fg.success',
					_disabled: { opacity: '1', color: 'fg.success', cursor: 'not-allowed' }
				})}
				onclick={onSave}
				disabled={isSaving || loading || editorReadOnly}
				type="button"
				data-save-state={saveButtonState}
			>
				{saveButtonLabel}
			</button>
			<button
				class={css({
					display: 'flex',
					flexShrink: '0',
					alignItems: 'center',
					justifyContent: 'center',
					width: '8',
					height: '100%',
					backgroundColor: 'transparent',
					border: 'none',
					borderRadius: 'xs',
					cursor: 'pointer',
					padding: '0',
					color: 'fg.warning',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.warning' }
				})}
				onclick={onOpenVersions}
				type="button"
				title="Version history"
				data-testid="version-history-trigger"
			>
				<Clock size={14} />
			</button>
		</div>
	</div>
</header>
