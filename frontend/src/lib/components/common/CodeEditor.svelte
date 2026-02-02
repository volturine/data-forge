<script lang="ts">
	import { EditorView, basicSetup } from 'codemirror';
	import { EditorState } from '@codemirror/state';
	import { python } from '@codemirror/lang-python';
	import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
	import { tags } from '@lezer/highlight';

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
			'&': { backgroundColor: 'var(--bg-tertiary)', color: 'var(--fg-primary)' },
			'.cm-content': { caretColor: 'var(--fg-primary)' },
			'.cm-cursor': { borderLeftColor: 'var(--fg-primary)' },
			'.cm-scroller': { fontFamily: 'var(--font-mono)' },
			'.cm-gutters': {
				backgroundColor: 'var(--bg-tertiary)',
				color: 'var(--fg-muted)',
				borderRight: '1px solid var(--border-primary)'
			},
			'.cm-activeLineGutter': { backgroundColor: 'var(--bg-hover)' },
			'.cm-activeLine': { backgroundColor: 'var(--bg-hover)' },
			'.cm-selectionMatch': {
				backgroundColor: 'color-mix(in srgb, var(--accent-primary) 50%, transparent)'
			},
			'&.cm-focused .cm-selectionBackground': {
				backgroundColor: 'color-mix(in srgb, var(--accent-primary) 70%, transparent)'
			},
			'.cm-selectionBackground': {
				backgroundColor: 'color-mix(in srgb, var(--accent-primary) 30%, transparent)'
			}
		},
		{ dark: true }
	);

	const highlight = HighlightStyle.define([
		{ tag: tags.keyword, color: '#c586c0' },
		{ tag: tags.operator, color: '#d4d4d4' },
		{ tag: tags.variableName, color: '#9cdcfe' },
		{ tag: tags.function(tags.variableName), color: '#dcdcaa' },
		{ tag: tags.definition(tags.variableName), color: '#4fc1ff' },
		{ tag: tags.string, color: '#ce9178' },
		{ tag: tags.number, color: '#b5cea8' },
		{ tag: tags.bool, color: '#569cd6' },
		{ tag: tags.null, color: '#569cd6' },
		{ tag: tags.comment, color: '#6a9955', fontStyle: 'italic' },
		{ tag: tags.className, color: '#4ec9b0' },
		{ tag: tags.definition(tags.function(tags.variableName)), color: '#dcdcaa' },
		{ tag: tags.propertyName, color: '#9cdcfe' }
	]);

	function init(host: HTMLElement) {
		const state = EditorState.create({
			doc: value,
			extensions: [
				basicSetup,
				python(),
				theme,
				syntaxHighlighting(highlight),
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

<div class="code-editor" style:height>
	<div class="editor-host" use:init></div>
</div>

<style>
	.code-editor {
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-md);
		overflow: hidden;
		background-color: var(--bg-tertiary);
	}
	.editor-host {
		height: 100%;
	}
	:global(.cm-editor) {
		height: 100%;
		font-size: 0.85rem;
	}
	:global(.cm-focused) {
		outline: none;
	}
</style>
