<script lang="ts">
	import { X } from 'lucide-svelte';

	interface Props {
		value: string;
		onChange: (value: string) => void;
		id?: string;
	}

	let { value, onChange, id }: Props = $props();

	const dateValue = $derived.by(() => {
		if (!value) return '';
		const match = /^(\d{4}-\d{2}-\d{2})/.exec(value);
		return match ? match[1] : '';
	});

	const timeValue = $derived.by(() => {
		if (!value) return '';
		const match = /T(\d{2}:\d{2})/.exec(value);
		return match ? match[1] : '';
	});

	function handleDateChange(e: Event) {
		const date = (e.target as HTMLInputElement).value;
		if (!date) {
			onChange('');
			return;
		}
		onChange(timeValue ? `${date}T${timeValue}` : date);
	}

	function handleTimeChange(e: Event) {
		const time = (e.target as HTMLInputElement).value;
		if (!dateValue) return;
		onChange(time ? `${dateValue}T${time}` : dateValue);
	}

	function clearTime() {
		if (dateValue) onChange(dateValue);
	}
</script>

<div class="flex gap-2">
	<input
		type="date"
		id={id ? `${id}-date` : undefined}
		value={dateValue}
		onchange={handleDateChange}
		class="min-w-0 flex-1"
	/>
	<div class="relative min-w-0 flex-1">
		<input
			type="time"
			id={id ? `${id}-time` : undefined}
			value={timeValue}
			onchange={handleTimeChange}
			disabled={!dateValue}
			class="w-full pr-6 disabled:cursor-not-allowed disabled:opacity-50"
		/>
		{#if timeValue}
			<button
				type="button"
				class="clear-btn absolute right-1 top-1/2 -translate-y-1/2 flex h-[18px] w-[18px] cursor-pointer items-center justify-center rounded-sm border-none bg-transparent p-0 transition-all"
				onclick={clearTime}
				title="Clear time"
				style="color: var(--fg-muted);"
			>
				<X size={12} />
			</button>
		{/if}
	</div>
</div>

<style>
	.clear-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.clear-btn:active {
		background-color: var(--bg-tertiary);
	}
</style>
