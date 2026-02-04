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

<div class="datetime-input">
	<input type="date" id={id ? `${id}-date` : undefined} value={dateValue} onchange={handleDateChange} />
	<div class="time-wrapper">
		<input
			type="time"
			id={id ? `${id}-time` : undefined}
			value={timeValue}
			onchange={handleTimeChange}
			disabled={!dateValue}
		/>
		{#if timeValue}
			<button type="button" class="clear-btn" onclick={clearTime} title="Clear time">
				<X size={12} />
			</button>
		{/if}
	</div>
</div>

<style>
	.datetime-input {
		display: flex;
		gap: var(--space-2);
	}

	.datetime-input > input {
		flex: 1;
		min-width: 0;
	}

	.time-wrapper {
		position: relative;
		flex: 1;
		min-width: 0;
	}

	.time-wrapper input {
		width: 100%;
		padding-right: var(--space-6);
	}

	.time-wrapper input:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.clear-btn {
		position: absolute;
		right: var(--space-1);
		top: 50%;
		transform: translateY(-50%);
		display: flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		padding: 0;
		background: transparent;
		border: none;
		border-radius: var(--radius-sm);
		color: var(--fg-muted);
		cursor: pointer;
		transition: all var(--transition);
	}

	.clear-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.clear-btn:active {
		background-color: var(--bg-tertiary);
	}
</style>
