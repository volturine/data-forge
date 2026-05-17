<script lang="ts">
	import HealthChecksManager from '$lib/components/common/HealthChecksManager.svelte';

	interface Props {
		datasourceId: string;
	}

	let { datasourceId }: Props = $props();
</script>

<HealthChecksManager {datasourceId} />
