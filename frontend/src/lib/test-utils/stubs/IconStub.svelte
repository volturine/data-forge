<script lang="ts">
	let { class: className = '', size = 24 }: { class?: string; size?: number } = $props();
</script>

<svg class={className} width={size} height={size}></svg>
