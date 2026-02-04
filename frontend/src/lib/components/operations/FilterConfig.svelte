<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import {
		formatDateInput,
		formatDateTimeInput,
		parseDateTimeInputValue
	} from '$lib/utils/datetime';

	const uid = $props.id();

	type ValueType = 'string' | 'number' | 'date' | 'datetime' | 'column' | 'boolean';

	interface Condition {
		column: string;
		operator: string;
		value: string | number | boolean | null;
		value_type: ValueType;
		compare_column?: string;
	}

	interface FilterConfigData {
		conditions: Condition[];
		logic: 'AND' | 'OR';
	}

	interface Props {
		schema: Schema;
		config?: FilterConfigData;
	}

	let {
		schema,
		config = $bindable({
			conditions: [{ column: '', operator: '=', value: '', value_type: 'string' as ValueType }],
			logic: 'AND'
		})
	}: Props = $props();

	let conditions = $derived(config.conditions);

	// Operator groups by category
	const COMPARISON_OPS = ['=', '!=', '>', '<', '>=', '<='];
	const STRING_OPS = ['contains', 'not_contains', 'starts_with', 'ends_with', 'regex'];
	const NULL_OPS = ['is_null', 'is_not_null'];

	const OPERATOR_LABELS: Record<string, string> = {
		'=': '=',
		'!=': '!=',
		'>': '>',
		'<': '<',
		'>=': '>=',
		'<=': '<=',
		contains: 'contains',
		not_contains: 'not contains',
		starts_with: 'starts with',
		ends_with: 'ends with',
		regex: 'regex',
		is_null: 'is null',
		is_not_null: 'is not null'
	};

	function getColumnType(name: string): 'string' | 'number' | 'datetime' | 'date' | 'boolean' {
		const col = schema.columns.find((c) => c.name === name);
		if (!col) return 'string';
		const dtype = col.dtype.toLowerCase();

		if (dtype.includes('int') || dtype.includes('float') || dtype.includes('decimal')) {
			return 'number';
		}
		if (dtype.includes('datetime')) return 'datetime';
		if (dtype.includes('date')) return 'date';
		if (dtype.includes('bool')) return 'boolean';
		return 'string';
	}

	function getOperatorsForType(type: string, isColumnMode: boolean): string[] {
		if (isColumnMode) return COMPARISON_OPS;
		if (type === 'string') return [...COMPARISON_OPS, ...STRING_OPS, ...NULL_OPS];
		return [...COMPARISON_OPS, ...NULL_OPS];
	}

	function isNullOperator(op: string): boolean {
		return NULL_OPS.includes(op);
	}

	function addCondition() {
		config.conditions = [
			...conditions,
			{ column: '', operator: '=', value: '', value_type: 'string' as ValueType }
		];
	}

	function updateCondition(idx: number, updates: Partial<Condition>) {
		config.conditions = conditions.map((c, i) => (i === idx ? { ...c, ...updates } : c));
	}

	function removeCondition(idx: number) {
		config.conditions = conditions.filter((_, i) => i !== idx);
	}

	function handleColumnChange(idx: number, col: string) {
		const type = getColumnType(col);
		const cond = conditions[idx];
		const isColumn = cond.value_type === 'column';

		// Reset operator if incompatible with new type
		const ops = getOperatorsForType(type, isColumn);
		const op = ops.includes(cond.operator) ? cond.operator : '=';

		updateCondition(idx, {
			column: col,
			operator: op,
			value_type: isColumn ? 'column' : type,
			value: isColumn ? cond.value : ''
		});
	}

	function handleValueTypeChange(idx: number, isColumn: boolean) {
		const cond = conditions[idx];
		const colType = getColumnType(cond.column);

		if (isColumn) {
			const ops = getOperatorsForType(colType, true);
			const op = ops.includes(cond.operator) ? cond.operator : '=';
			updateCondition(idx, {
				value_type: 'column',
				compare_column: '',
				operator: op,
				value: null
			});
		} else {
			const ops = getOperatorsForType(colType, false);
			const op = ops.includes(cond.operator) ? cond.operator : '=';
			updateCondition(idx, {
				value_type: colType,
				compare_column: undefined,
				operator: op,
				value: ''
			});
		}
	}

	function handleOperatorChange(idx: number, op: string) {
		const updates: Partial<Condition> = { operator: op };
		if (isNullOperator(op)) {
			updates.value = null;
			updates.compare_column = undefined;
		}
		updateCondition(idx, updates);
	}

	function formatDatetime(val: string | number | boolean | null): string {
		if (!val) return '';
		return formatDateTimeInput(String(val));
	}

	function formatDate(val: string | number | boolean | null): string {
		if (!val) return '';
		return formatDateInput(String(val));
	}
</script>

<div class="config-panel" role="region" aria-label="Filter configuration">
	<h3>Filter Configuration</h3>

	<div class="logic-selector">
		<label for="{uid}-logic">
			Combine conditions with:
			<select id="{uid}-logic" data-testid="filter-logic-select" bind:value={config.logic}>
				<option value="AND">AND</option>
				<option value="OR">OR</option>
			</select>
		</label>
	</div>

	<div class="conditions" role="group" aria-label="Filter conditions">
		{#each conditions as cond, i (i)}
			{@const colType = getColumnType(cond.column)}
			{@const isColumn = cond.value_type === 'column'}
			{@const isNull = isNullOperator(cond.operator)}
			{@const ops = getOperatorsForType(colType, isColumn)}

			<div class="condition-row" role="group" aria-label={`Condition ${i + 1}`}>
				<!-- Column selector -->
				<div class="field column-field">
					<label for="{uid}-column-{i}" class="sr-only">Column</label>
					<ColumnDropdown
						{schema}
						value={cond.column}
						onChange={(val) => handleColumnChange(i, val)}
						placeholder="Select column..."
					/>
				</div>

				<!-- Operator -->
				<div class="field operator-field">
					<label for="{uid}-operator-{i}" class="sr-only">Operator</label>
					<select
						id="{uid}-operator-{i}"
						data-testid={`filter-operator-select-${i}`}
						value={cond.operator}
						onchange={(e) => handleOperatorChange(i, e.currentTarget.value)}
					>
						{#each ops as op (op)}
							<option value={op}>{OPERATOR_LABELS[op]}</option>
						{/each}
					</select>
				</div>

				<!-- Value input - varies by type -->
				{#if !isNull}
					<div class="field value-field">
						<!-- Mode toggle: literal vs column -->
						<div class="mode-toggle">
							<label class="toggle-label">
								<input
									type="checkbox"
									checked={isColumn}
									onchange={(e) => handleValueTypeChange(i, e.currentTarget.checked)}
								/>
								<span>Compare to column</span>
							</label>
						</div>

						{#if isColumn}
							<!-- Column-to-column comparison -->
							<ColumnDropdown
								{schema}
								value={cond.compare_column ?? ''}
								onChange={(val) => updateCondition(i, { compare_column: val })}
								placeholder="Select column..."
							/>
						{:else if colType === 'number'}
							<input
								id="{uid}-value-{i}"
								data-testid={`filter-value-input-${i}`}
								type="number"
								step="any"
								value={cond.value ?? ''}
								oninput={(e) => {
									const raw = e.currentTarget.value;
									const val = raw === '' ? '' : Number(raw);
									updateCondition(i, { value: val });
								}}
								placeholder="Enter number"
							/>
						{:else if colType === 'datetime'}
							<input
								id="{uid}-value-{i}"
								data-testid={`filter-value-input-${i}`}
								type="datetime-local"
								value={formatDatetime(cond.value)}
								onchange={(e) => {
									const val = e.currentTarget.value;
									if (!val) {
										updateCondition(i, { value: '' });
										return;
									}
									const iso = parseDateTimeInputValue(val);
									updateCondition(i, { value: iso });
								}}
							/>
						{:else if colType === 'date'}
							<input
								id="{uid}-value-{i}"
								data-testid={`filter-value-input-${i}`}
								type="date"
								value={formatDate(cond.value)}
								onchange={(e) => updateCondition(i, { value: e.currentTarget.value })}
							/>
						{:else if colType === 'boolean'}
							<select
								id="{uid}-value-{i}"
								data-testid={`filter-value-input-${i}`}
								value={String(cond.value ?? 'true')}
								onchange={(e) =>
									updateCondition(i, { value: e.currentTarget.value === 'true' })}
							>
								<option value="true">true</option>
								<option value="false">false</option>
							</select>
						{:else}
							<!-- String input -->
							<input
								id="{uid}-value-{i}"
								data-testid={`filter-value-input-${i}`}
								type="text"
								value={cond.value ?? ''}
								oninput={(e) => updateCondition(i, { value: e.currentTarget.value })}
								placeholder={cond.operator === 'regex' ? 'Enter regex pattern' : 'Enter value'}
							/>
						{/if}
					</div>
				{:else}
					<div class="field value-field null-placeholder">
						<span class="null-hint">No value needed</span>
					</div>
				{/if}

				<!-- Remove button -->
				<button
					type="button"
					class="remove-btn"
					onclick={() => removeCondition(i)}
					disabled={conditions.length === 1}
					aria-label={`Remove condition ${i + 1}`}
				>
					Remove
				</button>
			</div>
		{/each}
	</div>

	<button type="button" onclick={addCondition} class="add-btn" aria-label="Add new filter condition">
		Add Condition
	</button>
</div>

<style>
	.logic-selector {
		margin-bottom: var(--space-4);
		color: var(--fg-secondary);
	}

	.logic-selector select {
		margin-left: var(--space-2);
		padding: var(--space-1) var(--space-2);
	}

	.conditions {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}

	.condition-row {
		display: flex;
		gap: var(--space-2);
		align-items: flex-start;
		flex-wrap: wrap;
		padding: var(--space-3);
		background: var(--bg-secondary);
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-primary);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.column-field {
		flex: 2;
		min-width: 150px;
	}

	.operator-field {
		flex: 1;
		min-width: 120px;
	}

	.value-field {
		flex: 2;
		min-width: 180px;
	}

	.mode-toggle {
		margin-bottom: var(--space-1);
	}

	.toggle-label {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-sm);
		color: var(--fg-secondary);
		cursor: pointer;
	}

	.toggle-label input {
		margin: 0;
	}

	.null-placeholder {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.null-hint {
		color: var(--fg-muted);
		font-style: italic;
		font-size: var(--text-sm);
	}

	.condition-row select,
	.condition-row input[type='text'],
	.condition-row input[type='number'],
	.condition-row input[type='date'],
	.condition-row input[type='datetime-local'] {
		width: 100%;
		padding: var(--space-2);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		background: var(--bg-primary);
		color: var(--fg-primary);
	}

	.remove-btn {
		padding: var(--space-2) var(--space-4);
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		align-self: flex-end;
	}

	.remove-btn:disabled {
		background-color: var(--bg-muted);
		cursor: not-allowed;
		color: var(--fg-muted);
		border-color: var(--border-secondary);
	}

	.add-btn {
		padding: var(--space-2) var(--space-4);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		margin-bottom: var(--space-4);
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
