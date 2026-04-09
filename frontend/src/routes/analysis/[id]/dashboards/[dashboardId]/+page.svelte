<script lang="ts">
	import { page } from '$app/stores';
	import DashboardRuntime from '$lib/components/analysis/DashboardRuntime.svelte';

	const analysisId = $derived($page.params.id ?? '');
	const dashboardId = $derived($page.params.dashboardId ?? '');
</script>

<DashboardRuntime {analysisId} {dashboardId} />
