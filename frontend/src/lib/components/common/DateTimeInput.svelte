<script lang="ts">
	import {
		ChevronsLeft,
		ChevronLeft,
		ChevronRight,
		ChevronsRight,
		Calendar,
		X,
		Clock
	} from 'lucide-svelte';
	import { css, cx, input } from '$lib/styles/panda';

	interface Props {
		value: string;
		onChange: (value: string) => void;
		id?: string;
		withTime?: boolean;
	}

	type Cell = { key: string; day: number } | { key: string; empty: true };

	const MONTHS = [
		'Jan',
		'Feb',
		'Mar',
		'Apr',
		'May',
		'Jun',
		'Jul',
		'Aug',
		'Sep',
		'Oct',
		'Nov',
		'Dec'
	] as const;
	const MONTHS_FULL = [
		'January',
		'February',
		'March',
		'April',
		'May',
		'June',
		'July',
		'August',
		'September',
		'October',
		'November',
		'December'
	] as const;

	const navBtn = css({
		display: 'flex',
		alignItems: 'center',
		justifyContent: 'center',
		height: 'row',
		width: 'row',
		padding: '0',
		cursor: 'pointer',
		border: 'none',
		background: 'transparent',
		color: 'fg.secondary',
		_hover: { backgroundColor: 'bg.tertiary' }
	});

	const headerBtn = css({
		fontSize: 'xs',
		fontWeight: 'semibold',
		cursor: 'pointer',
		border: 'none',
		background: 'transparent',
		padding: '0',
		_hover: { color: 'fg.muted' }
	});

	const gridCell = css({
		height: 'rowXl',
		display: 'flex',
		alignItems: 'center',
		justifyContent: 'center',
		fontSize: 'xs',
		cursor: 'pointer',
		_hover: { backgroundColor: 'bg.tertiary' }
	});

	let { value, onChange, id, withTime = true }: Props = $props();

	let open = $state(false);
	let month = $state('');
	let hour = $state('');
	let minute = $state('');
	let containerRef = $state<HTMLDivElement>();
	let mode = $state<'date' | 'month' | 'year'>('date');
	let yearBase = $state(0);

	const date = $derived.by(() => {
		if (!value) return '';
		const match = /^(\d{4}-\d{2}-\d{2})/.exec(value);
		return match ? match[1] : '';
	});

	const time = $derived.by(() => {
		if (!value) return '';
		const match = /T(\d{2}:\d{2})/.exec(value);
		return match ? match[1] : '';
	});

	const formatted = $derived.by(() => {
		if (!date) return 'Select date...';
		const [y, m, d] = date.split('-').map(Number);
		const text = `${MONTHS[m - 1]} ${String(d).padStart(2, '0')}, ${y}`;
		if (!withTime || !time) return text;
		return `${text} ${time}`;
	});

	const currentYear = $derived(month ? Number(month.split('-')[0]) : 0);
	const currentMonth = $derived(month ? Number(month.split('-')[1]) : 0);

	const days = $derived.by(() => {
		if (!month) return [] as Cell[];
		const [y, m] = month.split('-').map(Number);
		const first = new Date(y, m - 1, 1);
		const count = new Date(y, m, 0).getDate();
		const offset = (first.getDay() + 6) % 7;
		const result: Cell[] = [];
		for (let i = 0; i < offset; i++) result.push({ key: `empty-${i}`, empty: true });
		for (let d = 1; d <= count; d++) {
			const key = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
			result.push({ key, day: d });
		}
		while (result.length < 42) result.push({ key: `pad-${result.length}`, empty: true });
		return result;
	});

	const years = $derived(Array.from({ length: 28 }, (_, i) => yearBase + i));
	const yearLabel = $derived(`${yearBase}\u2009\u2014\u2009${yearBase + 27}`);

	function toggle() {
		if (open) {
			open = false;
			mode = 'date';
			return;
		}
		const today = new Date();
		const target = date
			? date
			: `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
		month = target.slice(0, 7);
		mode = 'date';
		if (time) {
			const [h, m] = time.split(':');
			hour = h;
			minute = m;
		}
		open = true;
	}

	function shift(delta: number) {
		const [y, m] = month.split('-').map(Number);
		const next = new Date(y, m - 1 + delta, 1);
		month = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`;
	}

	function shiftYear(delta: number) {
		month = `${currentYear + delta}-${String(currentMonth).padStart(2, '0')}`;
	}

	function enterYear() {
		yearBase = currentYear - (currentYear % 28);
		mode = 'year';
	}

	function enterMonth() {
		mode = 'month';
	}

	function pickYear(y: number) {
		month = `${y}-${String(currentMonth).padStart(2, '0')}`;
		mode = 'date';
	}

	function pickMonth(m: number) {
		month = `${currentYear}-${String(m).padStart(2, '0')}`;
		mode = 'date';
	}

	function shiftPage(delta: number) {
		yearBase += delta * 28;
	}

	function pick(key: string) {
		if (!withTime) {
			onChange(key);
			open = false;
			return;
		}
		if (hour && minute) {
			onChange(`${key}T${hour}:${minute}`);
			return;
		}
		onChange(key);
	}

	function now() {
		const d = new Date();
		const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
		if (!withTime) {
			onChange(key);
			open = false;
			return;
		}
		const h = String(d.getHours()).padStart(2, '0');
		const m = String(d.getMinutes()).padStart(2, '0');
		hour = h;
		minute = m;
		month = key.slice(0, 7);
		onChange(`${key}T${h}:${m}`);
	}

	function clear() {
		onChange('');
		open = false;
	}

	function handleHour(e: Event) {
		const raw = (e.target as HTMLInputElement).value.replace(/\D/g, '');
		const n = Math.min(23, Math.max(0, Number(raw) || 0));
		hour = String(n).padStart(2, '0');
		if (!date) return;
		if (!minute) {
			minute = '00';
		}
		onChange(`${date}T${hour}:${minute}`);
	}

	function handleMinute(e: Event) {
		const raw = (e.target as HTMLInputElement).value.replace(/\D/g, '');
		const n = Math.min(59, Math.max(0, Number(raw) || 0));
		minute = String(n).padStart(2, '0');
		if (!date) return;
		if (!hour) {
			hour = '00';
		}
		onChange(`${date}T${hour}:${minute}`);
	}

	// $derived can't register DOM event listeners
	$effect(() => {
		if (!open) return;
		function handler(e: MouseEvent) {
			if (containerRef && !containerRef.contains(e.target as Node)) open = false;
		}
		window.addEventListener('mousedown', handler, true);
		return () => window.removeEventListener('mousedown', handler, true);
	});

	// $derived can't handle conditional write-back to mutable state
	$effect(() => {
		if (open) return;
		if (time) {
			const [h, m] = time.split(':');
			hour = h;
			minute = m;
		}
	});
</script>

<div bind:this={containerRef} class={css({ position: 'relative' })}>
	<div class={css({ display: 'flex', gap: '1' })}>
		<button
			type="button"
			onclick={toggle}
			{id}
			class={cx(
				input(),
				css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					cursor: 'pointer',
					flex: '1',
					minWidth: '0',
					textAlign: 'left'
				})
			)}
		>
			<Calendar size={14} />
			<span
				class={css({
					flex: '1',
					overflow: 'hidden',
					textOverflow: 'ellipsis',
					whiteSpace: 'nowrap',
					color: date ? 'fg.primary' : 'fg.muted'
				})}
			>
				{formatted}
			</span>
		</button>
		{#if value}
			<button
				type="button"
				onclick={clear}
				class={cx(
					input(),
					css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						cursor: 'pointer',
						width: 'auto',
						paddingX: '2',
						flexShrink: '0'
					})
				)}
			>
				<X size={14} />
			</button>
		{/if}
	</div>

	{#if open}
		<div
			class={css({
				position: 'absolute',
				zIndex: 'dropdown',
				top: '100%',
				left: '0',
				marginTop: '1',
				backgroundColor: 'bg.primary',
				borderWidth: '1',
				boxShadow: 'menu',
				padding: '2',
				display: 'flex',
				flexDirection: 'column',
				gap: '2',
				width: 'popover'
			})}
		>
			<div class={css({ display: 'flex', alignItems: 'center', justifyContent: 'space-between' })}>
				<div class={css({ display: 'flex', alignItems: 'center' })}>
					{#if mode === 'date'}
						<button type="button" onclick={() => shiftYear(-1)} class={navBtn}>
							<ChevronsLeft size={16} />
						</button>
						<button type="button" onclick={() => shift(-1)} class={navBtn}>
							<ChevronLeft size={16} />
						</button>
					{:else if mode === 'month'}
						<button type="button" onclick={() => shiftYear(-1)} class={navBtn}>
							<ChevronLeft size={16} />
						</button>
					{:else}
						<button type="button" onclick={() => shiftPage(-1)} class={navBtn}>
							<ChevronLeft size={16} />
						</button>
					{/if}
				</div>
				{#if mode === 'date'}
					<span class={css({ display: 'flex', gap: '1' })}>
						<button type="button" onclick={enterMonth} class={headerBtn}>
							{MONTHS_FULL[currentMonth - 1]}
						</button>
						<button type="button" onclick={enterYear} class={headerBtn}>
							{currentYear}
						</button>
					</span>
				{:else if mode === 'month'}
					<span class={css({ fontSize: 'xs', fontWeight: 'semibold' })}>{currentYear}</span>
				{:else}
					<span class={css({ fontSize: 'xs', fontWeight: 'semibold' })}>{yearLabel}</span>
				{/if}
				<div class={css({ display: 'flex', alignItems: 'center' })}>
					{#if mode === 'date'}
						<button type="button" onclick={() => shift(1)} class={navBtn}>
							<ChevronRight size={16} />
						</button>
						<button type="button" onclick={() => shiftYear(1)} class={navBtn}>
							<ChevronsRight size={16} />
						</button>
					{:else if mode === 'month'}
						<button type="button" onclick={() => shiftYear(1)} class={navBtn}>
							<ChevronRight size={16} />
						</button>
					{:else}
						<button type="button" onclick={() => shiftPage(1)} class={navBtn}>
							<ChevronRight size={16} />
						</button>
					{/if}
				</div>
			</div>

			<div class={css({ height: '17.25rem' })}>
				{#if mode === 'year'}
					<div
						class={css({
							display: 'grid',
							gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
							gap: '1'
						})}
					>
						{#each years as y (y)}
							<button
								type="button"
								onclick={() => pickYear(y)}
								class={cx(
									gridCell,
									css({
										borderWidth: currentYear === y ? '1' : '0',
										borderColor: currentYear === y ? 'border.primary' : 'transparent',
										backgroundColor: currentYear === y ? 'bg.tertiary' : 'transparent'
									})
								)}
							>
								{y}
							</button>
						{/each}
					</div>
				{:else if mode === 'month'}
					<div
						class={css({
							display: 'grid',
							gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
							gap: '1',
							height: '100%',
							alignContent: 'center'
						})}
					>
						{#each MONTHS as m, i (m)}
							<button
								type="button"
								onclick={() => pickMonth(i + 1)}
								class={cx(
									gridCell,
									css({
										borderWidth: currentMonth === i + 1 ? '1' : '0',
										borderColor: currentMonth === i + 1 ? 'border.primary' : 'transparent',
										backgroundColor: currentMonth === i + 1 ? 'bg.tertiary' : 'transparent'
									})
								)}
							>
								{m}
							</button>
						{/each}
					</div>
				{:else}
					<div
						class={css({
							display: 'grid',
							gridTemplateColumns: 'repeat(7, minmax(0, 1fr))',
							gap: '1'
						})}
					>
						{#each ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'] as d (d)}
							<div
								class={css({
									height: 'rowXl',
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									fontSize: '2xs',
									color: 'fg.tertiary'
								})}
							>
								{d}
							</div>
						{/each}
						{#each days as cell (cell.key)}
							{#if 'day' in cell}
								<button
									type="button"
									onclick={() => pick(cell.key)}
									class={cx(
										gridCell,
										css({
											borderWidth: date === cell.key ? '1' : '0',
											borderColor: date === cell.key ? 'border.primary' : 'transparent',
											backgroundColor: date === cell.key ? 'bg.tertiary' : 'transparent'
										})
									)}
								>
									{cell.day}
								</button>
							{:else}
								<div class={css({ height: 'rowXl' })}></div>
							{/if}
						{/each}
					</div>
				{/if}
			</div>

			{#if mode === 'date' && !withTime}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						borderTopWidth: '1',
						paddingTop: '2'
					})}
				>
					<button
						type="button"
						onclick={now}
						class={css({
							marginLeft: 'auto',
							fontSize: 'xs',
							color: 'fg.muted',
							cursor: 'pointer',
							border: 'none',
							background: 'transparent',
							paddingX: '1',
							paddingY: '0.5',
							_hover: { color: 'fg.primary' }
						})}
					>
						Today
					</button>
				</div>
			{/if}

			{#if mode === 'date' && withTime}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '1',
						borderTopWidth: '1',
						paddingTop: '2'
					})}
				>
					<Clock size={14} class={css({ color: 'fg.muted', flexShrink: '0' })} />
					<input
						type="text"
						inputmode="numeric"
						maxlength={2}
						placeholder="HH"
						value={hour}
						onfocus={(e) => (e.target as HTMLInputElement).select()}
						onchange={handleHour}
						class={cx(input(), css({ width: '2.5rem', textAlign: 'center', paddingX: '1' }))}
					/>
					<span class={css({ color: 'fg.muted', fontSize: 'sm2' })}>:</span>
					<input
						type="text"
						inputmode="numeric"
						maxlength={2}
						placeholder="MM"
						value={minute}
						onfocus={(e) => (e.target as HTMLInputElement).select()}
						onchange={handleMinute}
						class={cx(input(), css({ width: '2.5rem', textAlign: 'center', paddingX: '1' }))}
					/>
					<button
						type="button"
						onclick={now}
						class={css({
							marginLeft: 'auto',
							fontSize: 'xs',
							color: 'fg.muted',
							cursor: 'pointer',
							border: 'none',
							background: 'transparent',
							paddingX: '1',
							paddingY: '0.5',
							_hover: { color: 'fg.primary' }
						})}
					>
						Now
					</button>
				</div>
			{/if}
		</div>
	{/if}
</div>
