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
	class="file-type-badge"
	class:minimal={variant === 'minimal'}
	class:outline={variant === 'outline'}
	style:font-size={styles.fontSize}
	style:padding={styles.padding}
	style:color={styles.color}
	style:border-color={styles.borderColor}
	style:background-color={styles.backgroundColor}
	role="img"
	aria-label="{config.label} file type"
	title={config.description}
>
	{#if showIcon}
		<Icon size={sizeConfig[size].iconSize} />
	{/if}
	{config.label}
</span>

<style>
	.file-type-badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-family: var(--font-mono);
		font-weight: var(--font-medium);
		border-radius: var(--radius-sm);
		border-width: 1px;
		border-style: solid;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		flex-shrink: 0;
		white-space: nowrap;
		transition: all var(--transition);
	}

	.file-type-badge.minimal {
		border: none;
		padding: 0;
	}

	.file-type-badge.outline {
		border-width: 1px;
	}
</style>
