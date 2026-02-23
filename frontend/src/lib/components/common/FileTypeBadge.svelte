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
		/** Source type for non-file datasources (database, iceberg, etc.) */
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
	const config = $derived.by(() => {
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
	const Icon = $derived(config.icon);

	// Size configurations
	const sizeConfig = {
		sm: { iconSize: 12 },
		md: { iconSize: 14 },
		lg: { iconSize: 16 }
	};

	const sizeClass = $derived(`size-${size}`);
	const variantClass = $derived(variant === 'default' ? '' : `variant-${variant}`);
	const typeClass = $derived.by(() => {
		if (sourceType) return `source-${sourceType}`;
		const typed = config.type;
		return `file-${typed}`;
	});
</script>

<span
	class="file-badge {typeClass} {sizeClass} {variantClass}"
	role="img"
	aria-label="{config.label} file type"
	title={config.description}
>
	{#if showIcon}
		<Icon size={sizeConfig[size].iconSize} />
	{/if}
	{config.label}
</span>
