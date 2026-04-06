<script lang="ts">
	import { EditorView, basicSetup } from 'codemirror';
	import { EditorState } from '@codemirror/state';
	import { python } from '@codemirror/lang-python';
	import { css } from '$lib/styles/panda';

	interface Props {
		value?: string;
		height?: string;
		onEdit?: () => void;
	}

	let { value = $bindable(''), height = '360px', onEdit }: Props = $props();
	let view: EditorView | null = null;
	let skipUpdate = false;
	let programmatic = false;

	const CURSOR_COLOR = 'var(--colors-fg-muted)';
	const SELECTION_COLOR = 'var(--colors-bg-muted)';

	const theme = EditorView.theme(
		{
			'.cm-cursor': { borderLeftColor: CURSOR_COLOR },
			'.cm-scroller': {
				fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace'
			},
			'.cm-selectionMatch': {
				backgroundColor: SELECTION_COLOR
			},
			'&.cm-focused .cm-selectionBackground': {
				backgroundColor: SELECTION_COLOR
			},
			'.cm-selectionBackground': {
				backgroundColor: SELECTION_COLOR
			}
		},
		{ dark: true }
	);

	function init(host: HTMLElement) {
		const state = EditorState.create({
			doc: value,
			extensions: [
				basicSetup,
				python(),
				theme,
				EditorView.updateListener.of((update) => {
					if (!update.docChanged) return;
					if (programmatic) return;
					skipUpdate = true;
					value = update.state.doc.toString();
					onEdit?.();
					queueMicrotask(() => {
						skipUpdate = false;
					});
				})
			]
		});
		view = new EditorView({ state, parent: host });
		return {
			destroy() {
				view?.destroy();
				view = null;
			}
		};
	}

	// DOM: $derived can't update CodeMirror imperatively.
	$effect(() => {
		if (!view) return;
		if (skipUpdate) return;
		const current = view.state.doc.toString();
		if (current === value) return;
		programmatic = true;
		view.dispatch({
			changes: { from: 0, to: current.length, insert: value }
		});
		queueMicrotask(() => {
			programmatic = false;
		});
	});
</script>

<div
	class={css({
		overflow: 'hidden',
		borderWidth: '1',
		backgroundColor: 'bg.tertiary'
	})}
	style:height
>
	<div class={css({ height: 'full' })} use:init></div>
</div>
