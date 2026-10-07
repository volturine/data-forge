<script lang="ts">
	import { EditorView, basicSetup } from 'codemirror';
	import { EditorState } from '@codemirror/state';
	import { python } from '@codemirror/lang-python';
	import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
	import { tags } from '@lezer/highlight';
	import { fromAction } from 'svelte/attachments';
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
	const codeHighlight = HighlightStyle.define([
		{ tag: tags.keyword, class: 'cm-code-keyword' },
		{ tag: tags.definition(tags.variableName), class: 'cm-code-definition' },
		{ tag: tags.function(tags.variableName), class: 'cm-code-function' },
		{ tag: tags.variableName, class: 'cm-code-variable' },
		{ tag: [tags.string, tags.character], class: 'cm-code-string' },
		{ tag: [tags.number, tags.bool, tags.literal], class: 'cm-code-number' },
		{ tag: [tags.typeName, tags.className, tags.namespace], class: 'cm-code-type' },
		{ tag: [tags.propertyName, tags.attributeName], class: 'cm-code-property' },
		{ tag: tags.operator, class: 'cm-code-operator' },
		{ tag: tags.punctuation, class: 'cm-code-punctuation' },
		{ tag: tags.comment, class: 'cm-code-comment' },
		{ tag: tags.invalid, class: 'cm-code-invalid' }
	]);

	const theme = EditorView.theme({
		'&': {
			height: '100%',
			backgroundColor: 'var(--colors-bg-tertiary)',
			color: 'var(--colors-fg-primary)',
			fontSize: '14px'
		},
		'.cm-scroller': {
			fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
			lineHeight: '1.55'
		},
		'.cm-content': { caretColor: 'var(--colors-accent-primary)', padding: '8px 0' },
		'.cm-line': { padding: '0 12px' },
		'.cm-gutters': {
			backgroundColor: 'var(--colors-bg-tertiary)',
			color: 'var(--colors-fg-muted)',
			border: 'none',
			borderRight: '1px solid var(--colors-border-primary)'
		},
		'.cm-gutterElement': { paddingLeft: '12px', paddingRight: '10px' },
		'.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'var(--colors-bg-muted)' },
		'.cm-activeLineGutter': { color: 'var(--colors-fg-secondary)' },
		'.cm-code-keyword': { color: 'var(--colors-fg-error)', fontWeight: '600' },
		'.cm-code-definition': { color: 'var(--colors-accent-primary)', fontWeight: '600' },
		'.cm-code-function': { color: 'var(--colors-accent-secondary)' },
		'.cm-code-variable': { color: 'var(--colors-fg-primary)' },
		'.cm-code-string': { color: 'var(--colors-fg-success)' },
		'.cm-code-number': { color: 'var(--colors-fg-warning)' },
		'.cm-code-type': { color: 'var(--colors-fg-warning)', fontWeight: '600' },
		'.cm-code-property': { color: 'var(--colors-fg-secondary)' },
		'.cm-code-operator': { color: 'var(--colors-fg-secondary)' },
		'.cm-code-punctuation': { color: 'var(--colors-fg-tertiary)' },
		'.cm-code-comment': { color: 'var(--colors-fg-muted)', fontStyle: 'italic' },
		'.cm-code-invalid': { color: 'var(--colors-fg-error)', textDecoration: 'underline' },
		'.cm-cursor': { borderLeftColor: CURSOR_COLOR },
		'.cm-selectionMatch': {
			backgroundColor: SELECTION_COLOR
		},
		'&.cm-focused .cm-selectionBackground': {
			backgroundColor: SELECTION_COLOR
		},
		'.cm-selectionBackground': {
			backgroundColor: SELECTION_COLOR
		}
	});

	function init(host: HTMLElement, doc: string) {
		const state = EditorState.create({
			doc,
			extensions: [
				basicSetup,
				python(),
				syntaxHighlighting(codeHighlight),
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
			update(next: string) {
				if (!view || skipUpdate) return;
				const current = view.state.doc.toString();
				if (current === next) return;
				programmatic = true;
				view.dispatch({
					changes: { from: 0, to: current.length, insert: next }
				});
				queueMicrotask(() => {
					programmatic = false;
				});
			},
			destroy() {
				view?.destroy();
				view = null;
			}
		};
	}

	const attachEditor = fromAction(init, () => value);
</script>

<div
	class={css({
		overflow: 'hidden',
		borderWidth: '1',
		backgroundColor: 'bg.tertiary'
	})}
	style:height
>
	<div class={css({ height: 'full' })} {@attach attachEditor}></div>
</div>
