<script lang="ts">
	import {
		detectFileType,
		getFileTypeConfig,
		getSourceTypeConfig,
		type FileType,
		type SourceType
	} from '$lib/utils/file-types';
	import { css, cx, badge } from '$lib/styles/panda';

	interface Props {
		fileType?: FileType;
		sourceType?: SourceType;
		path?: string;
		isFolder?: boolean;
		size?: 'sm' | 'md' | 'lg';
		showIcon?: boolean;
		variant?: 'default' | 'minimal' | 'outline';
	}

	let {
		fileType,
		sourceType,
		path,
		isFolder = false,
		size = 'md',
		showIcon = false,
		variant = 'default'
	}: Props = $props();

	const config = $derived.by(() => {
		if (sourceType) return getSourceTypeConfig(sourceType);
		if (fileType) return getFileTypeConfig(fileType);
		if (path) {
			const detected = detectFileType(path, isFolder);
			return getFileTypeConfig(detected);
		}
		return getFileTypeConfig('unknown');
	});
	const Icon = $derived(config.icon);

	const sizes: Record<
		string,
		{ iconSize: number; fontSize: string; paddingX: string; paddingY: string }
	> = {
		sm: { iconSize: 12, fontSize: '2xs', paddingX: '1.5', paddingY: '0.5' },
		md: { iconSize: 14, fontSize: 'xs', paddingX: '2', paddingY: '0.5' },
		lg: { iconSize: 16, fontSize: 'xs', paddingX: '2.5', paddingY: '0.5' }
	};

	const variants: Record<string, Record<string, string>> = {
		default: {},
		minimal: { border: 'none', padding: '0', backgroundColor: 'transparent' },
		outline: { backgroundColor: 'transparent' }
	};
</script>

<span
	class={cx(
		badge({ tone: 'file' }),
		css({
			flexShrink: '0',
			gap: '1',
			whiteSpace: 'nowrap',
			fontWeight: 'semibold',
			transition: 'color 150ms, background-color 150ms, border-color 150ms',
			fontSize: sizes[size].fontSize,
			paddingX: sizes[size].paddingX,
			paddingY: sizes[size].paddingY,
			...variants[variant]
		})
	)}
	role="img"
	aria-label="{config.label} file type"
	title={config.description}
>
	{#if showIcon}
		<Icon size={sizes[size].iconSize} />
	{/if}
	{config.label}
</span>
