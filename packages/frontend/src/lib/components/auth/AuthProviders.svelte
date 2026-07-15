<script lang="ts">
	import { GitBranch } from '@lucide/svelte';
	import { button, css } from '$lib/styles/panda';
</script>

<div class={css({ display: 'flex', alignItems: 'center', gap: '3' })}>
	<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.primary' })}></div>
	<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>or continue with</span>
	<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.primary' })}></div>
</div>

<div class={css({ display: 'flex', gap: '3' })}>
	<a
		href="/api/v1/auth/google"
		rel="external"
		class={button({ variant: 'secondary', width: 'grow' })}
	>
		Google
	</a>
	<a
		href="/api/v1/auth/github"
		rel="external"
		class={button({ variant: 'secondary', width: 'grow' })}
	>
		<GitBranch size={16} />
		GitHub
	</a>
</div>
