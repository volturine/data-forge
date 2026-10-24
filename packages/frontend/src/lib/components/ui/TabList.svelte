<script lang="ts" generics="K extends string">
	import { css, tabButton } from '#lib/styles/panda.js';

	interface Props {
		tabs: readonly { key: K; label: string }[];
		active: K;
		onSelect: (key: K) => void;
		label: string;
		size?: 'default' | 'lg';
	}

	let { tabs, active, onSelect, label, size = 'default' }: Props = $props();

	function handleKeydown(event: KeyboardEvent, index: number) {
		const count = tabs.length;
		let next = -1;
		if (event.key === 'ArrowRight') next = (index + 1) % count;
		if (event.key === 'ArrowLeft') next = (index - 1 + count) % count;
		if (event.key === 'Home') next = 0;
		if (event.key === 'End') next = count - 1;
		if (next < 0) return;
		event.preventDefault();
		onSelect(tabs[next].key);
		document.getElementById(`tab-${tabs[next].key}`)?.focus();
	}
</script>

<div
	class={css({
		display: 'flex',
		gap: '0',
		borderBottomWidth: '1'
	})}
	role="tablist"
	aria-label={label}
>
	{#each tabs as tab, i (tab.key)}
		<button
			id={`tab-${tab.key}`}
			class={tabButton({ active: active === tab.key, size })}
			onclick={() => onSelect(tab.key)}
			onkeydown={(e) => handleKeydown(e, i)}
			role="tab"
			aria-selected={active === tab.key}
			aria-controls={`panel-${tab.key}`}
			tabindex={active === tab.key ? 0 : -1}
			type="button"
		>
			{tab.label}
		</button>
	{/each}
</div>
