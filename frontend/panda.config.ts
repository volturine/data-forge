import { defineConfig } from '@pandacss/dev';
import {
	navLink,
	iconButton,
	button,
	spinner,
	sectionHeader,
	panelHeader,
	panelFooter,
	menuItem,
	toggleButton,
	callout,
	tabButton,
	chip,
	emptyText,
	badge,
	input,
	label,
	stepConfig
} from './src/lib/styles/recipes';

export default defineConfig({
	preflight: false,
	include: ['./src/**/*.{js,ts,svelte}'],
	exclude: [],
	outdir: 'styled-system',
	globalCss: {
		'*, *::before, *::after': {
			boxSizing: 'border-box',
			borderWidth: '0',
			borderStyle: 'solid',
			borderColor: 'var(--colors-border-primary)',
			borderTopColor: 'var(--colors-border-primary)',
			borderRightColor: 'var(--colors-border-primary)',
			borderBottomColor: 'var(--colors-border-primary)',
			borderLeftColor: 'var(--colors-border-primary)'
		},
		html: {
			fontSize: '16px',
			fontSmoothing: 'antialiased',
			height: '100%',
			overflow: 'hidden'
		},
		body: {
			margin: '0',
			fontFamily: 'var(--fonts-mono)',
			fontSize: '0.875rem',
			lineHeight: '1.5',
			color: 'var(--colors-fg-primary)',
			backgroundColor: 'var(--colors-bg-secondary)',
			height: '100%',
			overflow: 'hidden'
		},
		'body[data-theme=dark]': {
			colorScheme: 'dark'
		},
		'body[data-theme=light]': {
			colorScheme: 'light'
		},
		'body *': {
			transition: 'none',
			scrollbarWidth: 'none',
			font: 'inherit'
		},
		'body :focus-visible': {
			outlineWidth: '2px',
			outlineStyle: 'solid',
			outlineColor: 'var(--colors-border-primary)',
			outlineOffset: '2px'
		},
		'body button, body input, body optgroup, body select, body textarea': {
			margin: '0',
			font: 'inherit'
		},
		"body input[type='checkbox'], body input[type='radio']": {
			width: 'auto',
			cursor: 'pointer'
		},
		'body button': {
			fontFamily: 'var(--fonts-mono)',
			fontSize: '0.875rem',
			fontWeight: '500',
			cursor: 'pointer',
			border: '1px solid transparent',
			borderRadius: '0',
			padding: '0.5rem 1rem',
			transition:
				'color 160ms ease, background-color 160ms ease, border-color 160ms ease, opacity 160ms ease',
			display: 'inline-flex',
			alignItems: 'center',
			justifyContent: 'center',
			gap: '0.5rem'
		},
		'body button:disabled': {
			opacity: '0.5',
			cursor: 'not-allowed'
		},
		'body.touch-dragging': {
			userSelect: 'none',
			WebkitUserSelect: 'none',
			WebkitTouchCallout: 'none'
		},
		'body.touch-dragging .pipeline-canvas': {
			overflow: 'hidden',
			touchAction: 'none'
		}
	},
	staticCss: {
		recipes: {
			callout: [{ tone: ['info', 'warn', 'error'] }],
			chip: [{ tone: ['accent', 'neutral', 'warning', 'success', 'error'] }],
			button: [{ variant: ['primary', 'secondary', 'ghost', 'danger'], size: ['default', 'sm'] }],
			spinner: [{ size: ['default', 'sm', 'md'] }],
			badge: [{ tone: ['type', 'file'], size: ['sm', 'md', 'lg'] }],
			tabButton: [{ active: ['true', 'false'], size: ['default', 'lg'] }],
			emptyText: [{ size: ['compact', 'panel', 'inline'] }],
			toggleButton: [{ active: ['true', 'false'], radius: ['left', 'right'] }],
			input: [{ variant: ['default', 'compact', 'search', 'searchCompact', 'menu', 'searchWide'] }],
			label: [
				{ variant: ['default', 'field', 'compact', 'checkbox', 'inline', 'wrapper', 'hidden'] }
			]
		}
	},
	importMap: {
		css: ['styled-system/css', '$lib/styles/panda'],
		recipes: ['styled-system/recipes', '$lib/styles/panda']
	},
	conditions: {
		extend: {
			dark: '&[data-theme=dark], [data-theme=dark] &'
		}
	},
	theme: {
		extend: {
			keyframes: {
				'slide-up': {
					from: { opacity: '0', transform: 'translateY(10px)' },
					to: { opacity: '1', transform: 'translateY(0)' }
				}
			},
			recipes: {
				navLink,
				iconButton,
				button,
				spinner,
				sectionHeader,
				panelHeader,
				panelFooter,
				menuItem,
				toggleButton,
				callout,
				tabButton,
				chip,
				emptyText,
				badge,
				input,
				label,
				stepConfig
			},
			tokens: {
				fonts: {
					mono: {
						value: "'JetBrains Mono', 'Fira Code', 'SF Mono', 'Consolas', 'Monaco', monospace"
					}
				},
				fontSizes: {
					'2xs': { value: '0.625rem' },
					'2xs2': { value: '0.65rem' },
					xs2: { value: '0.6875rem' },
					sm2: { value: '0.8125rem' },
					'3xs': { value: '0.5625rem' }
				},
				letterSpacings: {
					tight2: { value: '0.02em' },
					wide2: { value: '0.04em' },
					wide3: { value: '0.08em' }
				},
				lineHeights: {
					base: { value: '1.6' }
				},
				borderWidths: {
					'1': { value: '1px' },
					'2': { value: '2px' },
					'3': { value: '3px' },
					'4': { value: '4px' }
				},
				spacing: {
					1: { value: '0.25rem' },
					2: { value: '0.5rem' },
					'2.25': { value: '0.5625rem' },
					3: { value: '0.75rem' },
					px: { value: '1px' },
					tight: { value: '0.15rem' }
				},
				radii: {
					sm: { value: '0px' },
					xxs: { value: '1px' },
					xs: { value: '2px' },
					md: { value: '3px' },
					sm2: { value: '6px' },
					pill: { value: '20px' },
					full: { value: '9999px' }
				},
				shadows: {
					drag: { value: '0 4px 12px rgba(0, 0, 0, 0.15)' },
					menu: { value: '0 6px 16px rgba(0, 0, 0, 0.12)' },
					popup: { value: '0 2px 8px rgba(0, 0, 0, 0.15)' },
					panel: { value: '0 10px 24px rgba(0, 0, 0, 0.2)' },
					popover: { value: '0 10px 30px rgba(0, 0, 0, 0.08)' }
				},
				sizes: {
					operationsPanel: { value: '460px' },
					datasourcePanel: { value: '520px' },
					pipelineConnection: { value: '18px' },
					px: { value: '1px' },
					page: { value: '75rem' },
					pageWide: { value: '68.75rem' },
					pageNarrow: { value: '50rem' },
					modal: { value: '45rem' },
					modalSm: { value: '30rem' },
					modalLg: { value: '60rem' },
					popover: { value: '22.5rem' },
					list: { value: '15rem' },
					listLg: { value: '20rem' },
					listTall: { value: '31.25rem' },
					panel: { value: '25rem' },
					dropdownTall: { value: '18.75rem' },
					dropdown: { value: '13.75rem' },
					listSm: { value: '12.5rem' },
					inputSm: { value: '7.5rem' },
					fieldMd: { value: '7.5rem' },
					fieldSm: { value: '6.25rem' },
					labelSm: { value: '3.75rem' },
					labelXs: { value: '3.125rem' },
					icon: { value: '1.125rem' },
					screenTall: { value: '90vh' },
					bar: { value: '0.25rem' },
					barTall: { value: '0.375rem' },
					dot: { value: '0.5rem' },
					dotLg: { value: '0.625rem' },
					iconTiny: { value: '0.75rem' },
					iconXs: { value: '0.875rem' },
					iconSm: { value: '1rem' },
					iconMd: { value: '1.25rem' },
					iconLg: { value: '1.5rem' },
					row: { value: '1.75rem' },
					rowLg: { value: '2rem' },
					rowXl: { value: '2.25rem' },
					spinner: { value: '2.5rem' },
					headerSm: { value: '2.75rem' },
					logo: { value: '3rem' },
					logoLg: { value: '3.5rem' },
					logoXl: { value: '4rem' },
					colNarrow: { value: '6rem' },
					colMd: { value: '8rem' },
					colWide: { value: '9rem' },
					colXl: { value: '12rem' },
					previewMd: { value: '14rem' },
					previewLg: { value: '16rem' },
					previewXl: { value: '18rem' }
				},
				zIndex: {
					header: { value: '100' },
					dropdown: { value: '101' },
					engine: { value: '200' },
					modal: { value: '1000' },
					tooltip: { value: '1100' },
					popover: { value: '2200' },
					overlay: { value: '2500' }
				}
			}
		},
		semanticTokens: {
			colors: {
				bg: {
					primary: { value: { base: '#ffffff', _dark: '#0e0e0e' } },
					secondary: { value: { base: '#fafafa', _dark: '#111111' } },
					tertiary: { value: { base: '#f5f5f5', _dark: '#171717' } },
					muted: { value: { base: '#e5e5e5', _dark: '#1f1f1f' } },
					hover: { value: { base: '#e5e5e5', _dark: '#262626' } },
					panel: { value: { base: '#ffffff', _dark: '#0e0e0e' } },
					overlay: { value: { base: 'rgba(0, 0, 0, 0.55)', _dark: 'rgba(0, 0, 0, 0.55)' } },
					overlaySoft: { value: { base: 'rgba(0, 0, 0, 0.4)', _dark: 'rgba(0, 0, 0, 0.4)' } },
					indicator: { value: { base: '#71717a', _dark: '#737373' } }
				},
				fg: {
					primary: { value: { base: '#09090b', _dark: '#fafafa' } },
					secondary: { value: { base: '#27272a', _dark: '#d4d4d4' } },
					tertiary: { value: { base: '#52525b', _dark: '#a3a3a3' } },
					muted: { value: { base: '#71717a', _dark: '#737373' } },
					faint: { value: { base: '#a1a1aa', _dark: '#525252' } },
					inverse: { value: { base: '#ffffff', _dark: '#0e0e0e' } }
				},
				accent: {
					primary: { value: { base: '#09090b', _dark: '#fafafa' } },
					secondary: { value: { base: '#27272a', _dark: '#d4d4d4' } },
					bg: { value: { base: '#f4f4f5', _dark: '#1f1f1f' } }
				},
				border: {
					primary: { value: { base: '#e0e0e0', _dark: 'rgba(43, 43, 43, 0.663)' } }
				},
				success: {
					fg: { value: { base: '#86efac', _dark: '#86efac' } },
					bg: { value: { base: '#14532d', _dark: '#14532d' } },
					border: { value: { base: '#86efac', _dark: '#86efac' } }
				},
				warning: {
					fg: { value: { base: '#fde047', _dark: '#fde047' } },
					bg: { value: { base: '#713f12', _dark: '#713f12' } },
					border: { value: { base: '#854d0e', _dark: '#854d0e' } },
					contrast: { value: { base: '#ffffff', _dark: '#ffffff' } }
				},
				error: {
					fg: { value: { base: '#fca5a5', _dark: '#fca5a5' } },
					bg: { value: { base: '#7f1d1d', _dark: '#7f1d1d' } },
					border: { value: { base: '#991b1b', _dark: '#991b1b' } }
				},
				canvas: {
					gridLine: {
						value: {
							base: 'color-mix(in srgb, #09090b 6%, transparent)',
							_dark: 'color-mix(in srgb, #fafafa 14%, transparent)'
						}
					},
					lineageNode: { value: { base: '#ffffff', _dark: '#111111' } },
					lineageNodeBorder: { value: { base: '#e0e0e0', _dark: '#2b2b2b' } },
					lineageEdge: { value: { base: '#c4c4c4', _dark: '#3a3a3a' } },
					lineageEdgeActive: { value: { base: '#09090b', _dark: '#fafafa' } }
				}
			}
		}
	}
});
