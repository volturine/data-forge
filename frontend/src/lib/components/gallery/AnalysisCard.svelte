<script lang="ts">
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { ChartBar, Copy, Trash2 } from 'lucide-svelte';
	import { formatDateDisplay, getYearDisplay } from '$lib/utils/datetime';
	import { css } from '$lib/styles/panda';

	interface Props {
		analysis: AnalysisGalleryItem;
		selected: boolean;
		onDelete: (id: string) => void;
		onDuplicate?: (analysis: AnalysisGalleryItem) => void;
		onToggleSelect: (id: string) => void;
	}

	let { analysis, selected, onDelete, onDuplicate, onToggleSelect }: Props = $props();

	function handleClick(e: MouseEvent) {
		const target = e.target as HTMLElement;
		if (target.closest('button') || target.closest('input[type=checkbox]')) {
			e.preventDefault();
			return;
		}
		e.preventDefault();
		goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
	}

	function handleKeyPress(e: KeyboardEvent) {
		if (
			(e.key === 'Enter' || e.key === ' ') &&
			!(e.target as HTMLElement).closest('button') &&
			!(e.target as HTMLElement).closest('input[type=checkbox]')
		) {
			e.preventDefault();
			goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
		}
	}

	function formatDate(date: string): string {
		const now = new Date();
		const year = getYearDisplay(date);
		const currentYear = getYearDisplay(now);
		const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' };
		if (year !== null && currentYear !== null && year !== currentYear) {
			opts.year = 'numeric';
		}
		return formatDateDisplay(date, opts);
	}
</script>

<a
	data-analysis-card={analysis.name}
	href={resolve(`/analysis/${analysis.id}`)}
	class={css({
		position: 'relative',
		cursor: 'pointer',
		overflow: 'hidden',
		backgroundColor: 'bg.primary',
		display: 'block',
		textDecoration: 'none',
		color: 'inherit'
	})}
	onclick={handleClick}
	onkeypress={handleKeyPress}
>
	<div
		class={css({
			position: 'relative',
			display: 'flex',
			aspectRatio: '16 / 9',
			width: '100%',
			alignItems: 'center',
			justifyContent: 'center',
			backgroundColor: 'bg.tertiary'
		})}
	>
		<input
			type="checkbox"
			class={css({
				position: 'absolute',
				left: '5',
				top: '5',
				height: 'icon',
				width: 'icon'
			})}
			id="analysis-{analysis.id}-select"
			checked={selected}
			onchange={(e) => {
				e.stopPropagation();
				onToggleSelect(analysis.id);
			}}
			onclick={(e) => e.stopPropagation()}
			aria-label={`Select ${analysis.name}`}
		/>
		{#if analysis.thumbnail}
			<img
				src={analysis.thumbnail}
				alt={analysis.name}
				class={css({ height: '100%', width: '100%', objectFit: 'cover' })}
			/>
		{:else}
			<ChartBar size={32} class={css({ color: 'fg.faint' })} />
		{/if}
	</div>

	<div class={css({ padding: '4' })}>
		<div
			class={css({
				marginBottom: '2',
				display: 'flex',
				alignItems: 'flex-start',
				justifyContent: 'space-between',
				gap: '3'
			})}
		>
			<h3
				class={css({
					margin: '0',
					minWidth: '0',
					flex: '1',
					textOverflow: 'ellipsis',
					overflow: 'hidden',
					whiteSpace: 'nowrap',
					fontSize: 'sm',
					fontWeight: 'semibold',
					color: 'fg.primary'
				})}
			>
				{analysis.name}
			</h3>
			<div class={css({ display: 'inline-flex', alignItems: 'center', gap: '1' })}>
				{#if onDuplicate}
					<button
						type="button"
						class={css({
							display: 'inline-flex',
							flexShrink: '0',
							alignItems: 'center',
							justifyContent: 'center',
							border: 'none',
							backgroundColor: 'transparent',
							padding: '1',
							cursor: 'pointer',
							_hover: { color: 'accent.primary' },
							_focusVisible: {
								color: 'accent.primary',
								outline: '2px solid',
								outlineColor: 'accent.primary',
								outlineOffset: '1px'
							}
						})}
						onclick={(e) => {
							e.preventDefault();
							e.stopPropagation();
							onDuplicate(analysis);
						}}
						aria-label="Duplicate analysis"
					>
						<Copy size={16} />
					</button>
				{/if}
				<button
					type="button"
					class={css({
						display: 'inline-flex',
						flexShrink: '0',
						alignItems: 'center',
						justifyContent: 'center',
						border: 'none',
						backgroundColor: 'transparent',
						padding: '1',
						cursor: 'pointer',
						_hover: { color: 'fg.error' },
						_focusVisible: {
							color: 'fg.error',
							outline: '2px solid',
							outlineColor: 'accent.primary',
							outlineOffset: '1px'
						}
					})}
					onclick={(e) => {
						e.preventDefault();
						e.stopPropagation();
						onDelete(analysis.id);
					}}
					aria-label="Delete analysis"
				>
					<Trash2 size={16} />
				</button>
			</div>
		</div>

		<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>
			<span>{formatDate(analysis.updated_at)}</span>
		</div>
	</div>
</a>
