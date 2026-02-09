<script lang="ts">
	import { EditorView, basicSetup } from 'codemirror';
	import { EditorState } from '@codemirror/state';
	import { python } from '@codemirror/lang-python';

	interface Props {
		value?: string;
		height?: string;
		onEdit?: () => void;
	}

	let { value = $bindable(''), height = '360px', onEdit }: Props = $props();
	let view: EditorView | null = null;
	let skipUpdate = false;
	let programmatic = false;

	const theme = EditorView.theme(
		{
			'&': { backgroundColor: '#1f232b', color: '#e6edf3' },
			'.cm-content': { caretColor: '#e6edf3' },
			'.cm-cursor': { borderLeftColor: '#2f333b' },
			'.cm-scroller': {
				fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace'
			},
			'.cm-gutters': {
				backgroundColor: '#1f232b',
				color: '#9aa4b2',
				borderRight: '1px solid #2f333b'
			},
			'.cm-activeLineGutter': { backgroundColor: '#2a2f3a' },
			'.cm-activeLine': { backgroundColor: '#2a2f3a' },
			'.cm-selectionMatch': {
				backgroundColor: '#394052'
			},
			'&.cm-focused .cm-selectionBackground': {
				backgroundColor: '#2f3b52'
			},
			'.cm-selectionBackground': {
				backgroundColor: '#2a3346'
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

<div class="overflow-hidden border bg-tertiary border-tertiary" style:height>
	<div class="h-full" use:init></div>
</div>
