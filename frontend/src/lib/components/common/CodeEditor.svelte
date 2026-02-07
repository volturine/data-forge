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
			'.cm-cursor': { borderLeftColor: 'var(--border-primary)' },
			'.cm-scroller': { fontFamily: 'var(--font-mono)' },
			'.cm-gutters': {
				backgroundColor: 'var(--bg-tertiary)',
				color: 'var(--fg-muted)',
				borderRight: '1px solid var(--border-primary)'
			},
			'.cm-activeLineGutter': { backgroundColor: 'var(--bg-hover)' },
			'.cm-activeLine': { backgroundColor: 'var(--bg-hover)' },
			'.cm-selectionMatch': {
				backgroundColor: 'var(--editor-selection-match)'
			},
			'&.cm-focused .cm-selectionBackground': {
				backgroundColor: 'var(--editor-selection)'
			},
			'.cm-selectionBackground': {
				backgroundColor: 'var(--editor-selection-passive)'
			}
		},
		{ dark: true }
	);

	const highlight = HighlightStyle.define([
		{ tag: tags.keyword, color: 'var(--editor-syntax-keyword)' },
		{ tag: tags.operator, color: 'var(--editor-syntax-operator)' },
		{ tag: tags.variableName, color: 'var(--editor-syntax-variable)' },
		{ tag: tags.function(tags.variableName), color: 'var(--editor-syntax-function)' },
		{ tag: tags.definition(tags.variableName), color: 'var(--editor-syntax-definition)' },
		{ tag: tags.string, color: 'var(--editor-syntax-string)' },
		{ tag: tags.number, color: 'var(--editor-syntax-number)' },
		{ tag: tags.bool, color: 'var(--editor-syntax-boolean)' },
		{ tag: tags.null, color: 'var(--editor-syntax-null)' },
		{ tag: tags.comment, color: 'var(--editor-syntax-comment)', fontStyle: 'italic' },
		{ tag: tags.className, color: 'var(--editor-syntax-class)' },
		{
			tag: tags.definition(tags.function(tags.variableName)),
			color: 'var(--editor-syntax-function)'
		},
		{ tag: tags.propertyName, color: 'var(--editor-syntax-property)' }
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

<div class="overflow-hidden border bg-tertiary border-primary" style:height>
	<div class="h-full" use:init></div>
</div>

<style>
	:global(.cm-editor) {
		height: 100%;
		font-size: 0.85rem;
	}
	:global(.cm-focused) {
		outline: none;
	}
</style>
