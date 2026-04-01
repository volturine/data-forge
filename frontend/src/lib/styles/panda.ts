import { css, cx } from '../../../styled-system/css';

export { css, cx };
export {
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
} from '../../../styled-system/recipes';

export const muted = css({ color: 'fg.muted' });
export const row = css({ display: 'flex', alignItems: 'center' });
export const rowBetween = css({
	display: 'flex',
	alignItems: 'center',
	justifyContent: 'space-between'
});
export const divider = css({
	borderTopWidth: '1'
});
