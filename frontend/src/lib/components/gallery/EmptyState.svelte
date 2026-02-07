<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { LayoutGrid, Plus } from 'lucide-svelte';

	function createNew() {
		goto(resolve('/analysis/new'), { invalidateAll: true });
	}
</script>

<div
	class="flex min-h-[400px] flex-col items-center justify-center border border-dashed px-6 py-12 text-center input-styled"
>
	<div class="mb-6 flex h-16 w-16 items-center justify-center" style="color: var(--fg-faint);">
		<LayoutGrid size={32} strokeWidth={1.5} />
	</div>

	<h2 class="m-0 mb-2 font-semibold">No analyses yet</h2>
	<p class="m-0 mb-6 max-w-[300px] text-sm" style="color: var(--fg-tertiary);">
		Create your first analysis to get started with data exploration.
	</p>

	<button class="btn-primary" onclick={createNew}>
		<Plus size={16} />
		Create Analysis
	</button>
</div>
