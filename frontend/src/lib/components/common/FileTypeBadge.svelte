<script lang="ts">
	import {
		detectFileType,
		getFileTypeConfig,
		getSourceTypeConfig,
		type FileType,
		type SourceType
	} from '$lib/utils/fileTypes';

	interface Props {
		/** File type (if known) */
		fileType?: FileType;
		/** Source type for non-file datasources (database, api, iceberg, etc.) */
		sourceType?: SourceType;
		/** File path (for auto-detection) */
		path?: string;
		/** Whether the path is a folder */
		isFolder?: boolean;
		/** Badge size */
		size?: 'sm' | 'md' | 'lg';
		/** Whether to show the icon */
		showIcon?: boolean;
		/** Visual variant */
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

	// Get configuration based on priority: sourceType > fileType > auto-detect from path
	let config = $derived.by(() => {
		if (sourceType) {
			return getSourceTypeConfig(sourceType);
		}
		if (fileType) {
			return getFileTypeConfig(fileType);
		}
		if (path) {
			const detectedType = detectFileType(path, isFolder);
			return getFileTypeConfig(detectedType);
		}
		return getFileTypeConfig('unknown');
	});
	let Icon = $derived(config.icon);

	// Size configurations
	const sizeConfig = {
		sm: { fontSize: '10px', padding: '2px 6px', iconSize: 12 },
		md: { fontSize: '11px', padding: '2px 8px', iconSize: 14 },
		lg: { fontSize: '12px', padding: '3px 10px', iconSize: 16 }
	};

	let styles = $derived({
		fontSize: sizeConfig[size].fontSize,
		padding: sizeConfig[size].padding,
		color: variant === 'minimal' ? config.colors.color : config.colors.color,
		borderColor: variant === 'outline' ? config.colors.color : config.colors.borderColor,
		backgroundColor:
			variant === 'outline'
				? 'transparent'
				: variant === 'minimal'
					? 'transparent'
					: config.colors.backgroundColor
	});
</script>

<span
	class="inline-flex flex-shrink-0 items-center gap-1 whitespace-nowrap rounded-sm border font-medium uppercase tracking-wide transition-all {variant ===
	'minimal'
		? 'border-none p-0'
		: ''}"
	style:font-size={styles.fontSize}
	style:padding={variant === 'minimal' ? '0' : styles.padding}
	style:color={styles.color}
	style:border-color={styles.borderColor}
	style:background-color={styles.backgroundColor}
	style="font-family: var(--font-mono);"
	role="img"
	aria-label="{config.label} file type"
	title={config.description}
>
	{#if showIcon}
		<Icon size={sizeConfig[size].iconSize} />
	{/if}
	{config.label}
</span>
