import { defineRecipe } from '@pandacss/dev';

export const stepConfig = defineRecipe({
	className: 'step-config-panel',
	base: {
		padding: '0',
		border: 'none',
		backgroundColor: 'bg.primary',
		'& .description': {
			marginTop: '0',
			marginBottom: '3',
			color: 'fg.tertiary',
			fontSize: 'xs',
			lineHeight: 'base'
		},
		'& h4': {
			marginTop: '0',
			marginBottom: '3',
			fontSize: 'xs2',
			fontWeight: 'semibold',
			color: 'fg.muted',
			textTransform: 'uppercase',
			letterSpacing: 'wide3'
		}
	}
});

export const sectionHeader = defineRecipe({
	className: 'section-header',
	base: {
		fontSize: 'xs',
		fontWeight: 'semibold',
		textTransform: 'uppercase',
		letterSpacing: 'wider',
		color: 'fg.tertiary'
	}
});

export const panelHeader = defineRecipe({
	className: 'panel-header',
	base: {
		display: 'flex',
		flexDirection: 'row',
		alignItems: 'center',
		justifyContent: 'space-between',
		borderBottomWidth: '1',
		padding: '4'
	}
});

export const panelFooter = defineRecipe({
	className: 'panel-footer',
	base: {
		display: 'flex',
		justifyContent: 'flex-end',
		gap: '3',
		borderTopWidth: '1',
		padding: '4'
	}
});

export const menuItem = defineRecipe({
	className: 'menu-item',
	base: {
		border: 'none',
		background: 'transparent',
		color: 'fg.primary',
		width: 'full',
		paddingX: '3',
		paddingY: '2',
		fontSize: 'xs',
		textAlign: 'left',
		cursor: 'pointer',
		borderBottomWidth: '1',
		_last: { borderBottomWidth: '0' },
		_hover: { backgroundColor: 'bg.hover' }
	}
});

export const toggleButton = defineRecipe({
	className: 'toggle-btn',
	base: {
		display: 'flex',
		alignItems: 'center',
		justifyContent: 'center',
		cursor: 'pointer',
		borderWidth: '1',
		paddingX: '2',
		paddingY: '1',
		fontSize: 'xs'
	},
	variants: {
		active: {
			true: {
				backgroundColor: 'bg.accent',
				color: 'accent.primary',
				boxShadow: 'inset 0 0 0 1px {colors.accent.primary}',
				position: 'relative',
				zIndex: '1'
			},
			false: {
				backgroundColor: 'transparent',
				color: 'fg.muted',
				_hover: { backgroundColor: 'bg.hover', color: 'fg.secondary' }
			}
		},
		radius: {
			left: {
				borderTopLeftRadius: 'sm',
				borderBottomLeftRadius: 'sm',
				borderTopRightRadius: '0',
				borderBottomRightRadius: '0'
			},
			right: {
				borderTopLeftRadius: '0',
				borderBottomLeftRadius: '0',
				borderTopRightRadius: 'sm',
				borderBottomRightRadius: 'sm'
			}
		}
	},
	defaultVariants: { active: false }
});

export const callout = defineRecipe({
	className: 'callout',
	base: {
		paddingX: '3',
		paddingY: '2.5',
		borderLeftWidth: '2',
		fontSize: 'xs',
		lineHeight: '1.5',
		color: 'fg.tertiary'
	},
	variants: {
		tone: {
			info: { borderLeftColor: 'border.accent', backgroundColor: 'transparent' },
			warn: { borderLeftColor: 'border.warning', backgroundColor: 'bg.warning' },
			error: { borderLeftColor: 'border.error', backgroundColor: 'bg.error', color: 'fg.error' }
		}
	},
	defaultVariants: { tone: 'info' }
});

export const button = defineRecipe({
	className: 'btn',
	base: {
		// display, alignItems, justifyContent, gap, cursor, fontFamily, fontSize,
		// fontWeight, transition, and _disabled are all set by globalCss body button
		borderWidth: '1'
	},
	variants: {
		variant: {
			primary: {
				backgroundColor: 'accent.primary',
				color: 'fg.inverse',
				_hover: { _notDisabled: { opacity: '0.9' } }
			},
			secondary: {
				backgroundColor: 'transparent',
				color: 'fg.primary',
				_hover: { _notDisabled: { backgroundColor: 'bg.hover', color: 'fg.secondary' } }
			},
			ghost: {
				backgroundColor: 'transparent',
				color: 'fg.secondary',
				borderColor: 'transparent',
				_hover: { _notDisabled: { backgroundColor: 'bg.hover', color: 'fg.primary' } }
			},
			danger: {
				backgroundColor: 'bg.error',
				color: 'fg.error',
				borderColor: 'border.error',
				_hover: { _notDisabled: { opacity: '0.85' } }
			}
		},
		size: {
			default: {},
			sm: { fontSize: 'xs', paddingX: '2', paddingY: '1' }
		}
	},
	defaultVariants: { variant: 'secondary', size: 'default' }
});

export const spinner = defineRecipe({
	className: 'spinner',
	base: {
		borderRadius: 'full',
		borderTopColor: 'border.accent',
		animation: 'spin 0.8s linear infinite',
		flexShrink: '0'
	},
	variants: {
		size: {
			default: { width: 'spinner', height: 'spinner', borderWidth: '4' },
			sm: { width: 'iconXs', height: 'iconXs', borderWidth: '2' },
			md: { width: 'iconLg', height: 'iconLg', borderWidth: '3' }
		}
	},
	defaultVariants: { size: 'default' }
});

export const iconButton = defineRecipe({
	className: 'icon-button',
	base: {
		display: 'inline-flex',
		alignItems: 'center',
		justifyContent: 'center',
		borderWidth: '1',
		backgroundColor: 'bg.primary',
		padding: '2',
		color: 'fg.secondary',
		transitionProperty: 'color, background-color, border-color, opacity',
		transitionDuration: '160ms',
		transitionTimingFunction: 'ease',
		_hover: {
			backgroundColor: 'bg.hover',
			color: 'fg.primary'
		}
	}
});

export const tabButton = defineRecipe({
	className: 'tab-button',
	base: {
		backgroundColor: 'transparent',
		borderBottomWidth: '2',
		borderBottomColor: 'transparent',
		marginBottom: '-1px',
		fontWeight: 'medium',
		color: 'fg.muted',
		_hover: { color: 'fg.secondary' }
	},
	variants: {
		active: {
			true: { color: 'accent.primary', borderBottomColor: 'border.accent' }
		},
		size: {
			default: { paddingX: '3', paddingY: '1.5', fontSize: 'xs' },
			lg: { paddingX: '6', paddingY: '3', fontSize: 'sm' }
		}
	},
	defaultVariants: { active: false, size: 'default' }
});

export const chip = defineRecipe({
	className: 'chip',
	base: {
		display: 'inline-flex',
		alignItems: 'center',
		paddingX: '1.5',
		paddingY: '0.5',
		fontSize: '2xs',
		fontWeight: 'medium',
		textTransform: 'uppercase',
		letterSpacing: 'wider'
	},
	variants: {
		tone: {
			accent: { backgroundColor: 'bg.accent', color: 'accent.primary' },
			neutral: { backgroundColor: 'bg.tertiary', color: 'fg.muted' },
			warning: { backgroundColor: 'bg.warning', color: 'fg.warning' },
			success: { backgroundColor: 'bg.success', color: 'fg.success' },
			error: { backgroundColor: 'bg.error', color: 'fg.error' }
		}
	},
	defaultVariants: { tone: 'neutral' }
});

export const emptyText = defineRecipe({
	className: 'empty-text',
	base: {
		color: 'fg.muted',
		textAlign: 'center'
	},
	variants: {
		size: {
			compact: { paddingY: '8', fontSize: 'xs' },
			panel: { padding: '6', fontSize: 'sm' },
			inline: { padding: '0', fontSize: 'sm' }
		}
	},
	defaultVariants: { size: 'compact' }
});

export const input = defineRecipe({
	className: 'input',
	base: {
		width: 'full',
		fontSize: 'sm2',
		color: 'fg.primary',
		backgroundColor: 'bg.primary',
		borderWidth: '1',
		borderRadius: '0',
		paddingX: '3.5',
		paddingY: '2.25',
		transitionProperty: 'border-color',
		transitionDuration: '160ms',
		transitionTimingFunction: 'ease',
		_focus: { outline: 'none' },
		_focusVisible: { borderColor: 'border.accent' },
		_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
		_placeholder: { color: 'fg.muted' }
	},
	variants: {
		variant: {
			default: {},
			compact: {
				fontSize: 'xs',
				backgroundColor: 'transparent',
				paddingX: '2',
				paddingY: '1.5'
			},
			search: {
				paddingLeft: '8',
				paddingRight: '2',
				paddingY: '1.5',
				fontSize: 'sm',
				backgroundColor: 'transparent'
			},
			searchCompact: {
				paddingLeft: '8',
				paddingRight: '2',
				paddingY: '1',
				fontSize: 'xs',
				backgroundColor: 'bg.secondary'
			},
			menu: {
				backgroundColor: 'bg.secondary',
				paddingX: '3',
				paddingY: '2',
				fontSize: 'sm',
				_focus: { outline: 'none', backgroundColor: 'bg.primary', borderColor: 'border.accent' },
				_placeholder: { color: 'fg.muted' }
			},
			searchWide: {
				paddingY: '3',
				paddingLeft: '10',
				paddingRight: '10',
				backgroundColor: 'bg.primary',
				fontSize: 'sm'
			}
		}
	},
	defaultVariants: { variant: 'default' }
});

export const label = defineRecipe({
	className: 'label',
	base: {
		display: 'block',
		fontSize: 'xs2',
		fontWeight: 'semibold',
		color: 'fg.muted',
		marginBottom: '1.5',
		textTransform: 'uppercase',
		letterSpacing: 'wider'
	},
	variants: {
		variant: {
			default: {},
			field: {
				fontSize: 'sm',
				fontWeight: 'medium',
				color: 'fg.secondary',
				textTransform: 'none',
				letterSpacing: 'normal'
			},
			compact: {
				fontSize: '2xs',
				fontWeight: 'medium',
				color: 'fg.secondary'
			},
			checkbox: {
				display: 'flex',
				cursor: 'pointer',
				alignItems: 'center',
				gap: '3',
				fontSize: 'sm',
				fontWeight: 'normal',
				color: 'fg.secondary',
				textTransform: 'none',
				letterSpacing: 'normal',
				marginBottom: '0'
			},
			inline: {
				display: 'inline-flex',
				alignItems: 'center',
				gap: '2',
				fontSize: 'sm',
				fontWeight: 'normal',
				color: 'fg.secondary',
				textTransform: 'none',
				letterSpacing: 'normal',
				marginBottom: '0'
			},
			wrapper: {
				display: 'flex',
				flexDirection: 'column',
				gap: '1',
				textTransform: 'none',
				letterSpacing: 'normal',
				marginBottom: '0'
			},
			hidden: {
				position: 'absolute',
				width: 'px',
				height: 'px',
				padding: '0',
				margin: '-1px',
				overflow: 'hidden',
				clip: 'rect(0, 0, 0, 0)',
				whiteSpace: 'nowrap',
				borderWidth: '0'
			}
		}
	},
	defaultVariants: { variant: 'default' }
});

export const badge = defineRecipe({
	className: 'badge',
	base: {
		display: 'inline-flex',
		alignItems: 'center',
		borderWidth: '1',
		backgroundColor: 'bg.accent',
		color: 'accent.primary'
	},
	variants: {
		tone: {
			type: {},
			file: { textTransform: 'uppercase', letterSpacing: 'wider' }
		},
		size: {
			sm: { paddingX: '1.5', paddingY: '0.5', fontSize: '2xs' },
			md: { paddingX: '2', paddingY: '0.5', fontSize: 'xs' },
			lg: { paddingX: '2.5', paddingY: '0.5', fontSize: 'xs' }
		}
	},
	defaultVariants: { tone: 'type', size: 'md' }
});
