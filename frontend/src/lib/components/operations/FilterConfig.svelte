<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { X, Plus } from 'lucide-svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import DateTimeInput from '$lib/components/common/DateTimeInput.svelte';

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

	const defaultCondition: Condition = {
		column: '',
		operator: '=',
		value: '',
		value_type: 'string'
	};

	let { schema, config = $bindable({ conditions: [defaultCondition], logic: 'AND' }) }: Props =
		$props();

	const conditions = $derived(config.conditions ?? [defaultCondition]);
	const logic = $derived(config.logic ?? 'AND');

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
		if (dtype.includes('int') || dtype.includes('float') || dtype.includes('decimal'))
			return 'number';
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
		const ops = getOperatorsForType(type, isColumn);
		const op = ops.includes(cond.operator) ? cond.operator : '=';
		updateCondition(idx, {
			column: col,
			operator: op,
			value_type: isColumn ? 'column' : type,
			value: isColumn ? cond.value : ''
		});
	}

	function handleModeChange(idx: number, mode: 'value' | 'column') {
		const cond = conditions[idx];
		const colType = getColumnType(cond.column);
		const isColumn = mode === 'column';
		const ops = getOperatorsForType(colType, isColumn);
		const op = ops.includes(cond.operator) ? cond.operator : '=';

		if (isColumn) {
			updateCondition(idx, { value_type: 'column', compare_column: '', operator: op, value: null });
		} else {
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

	function formatDatetimeForInput(val: string | number | boolean | null): string {
		if (!val) return '';
		const str = String(val);
		// If already in datetime-local format (YYYY-MM-DDTHH:MM), return as-is
		if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(str)) return str.slice(0, 16);
		// If ISO format with Z or offset, parse and format without TZ conversion
		const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(str);
		if (match) return `${match[1]}T${match[2]}`;
		// If date-only format (YYYY-MM-DD), return as-is (no time component)
		if (/^\d{4}-\d{2}-\d{2}$/.test(str)) return str;
		return '';
	}

	function formatDateForInput(val: string | number | boolean | null): string {
		if (!val) return '';
		const str = String(val);
		// If already in date format (YYYY-MM-DD), return as-is
		if (/^\d{4}-\d{2}-\d{2}$/.test(str)) return str;
		// Extract date part from ISO string
		const match = /^(\d{4}-\d{2}-\d{2})/.exec(str);
		if (match) return match[1];
		return '';
	}
</script>

<div class="config-panel" role="region" aria-label="Filter configuration">
	<h3>Filter Configuration</h3>

	<div class="form-section" role="group" aria-labelledby="{uid}-conditions-heading">
		<div class="section-header">
			<h4 id="{uid}-conditions-heading">Conditions</h4>
			<div class="header-actions">
				<div class="logic-toggle" role="radiogroup" aria-label="Condition logic">
					<button
						type="button"
						class="logic-btn"
						class:active={config.logic === 'AND'}
						onclick={() => (config.logic = 'AND')}
						aria-pressed={config.logic === 'AND'}
					>
						AND
					</button>
					<button
						type="button"
						class="logic-btn"
						class:active={config.logic === 'OR'}
						onclick={() => (config.logic = 'OR')}
						aria-pressed={config.logic === 'OR'}
					>
						OR
					</button>
				</div>
				<button
					type="button"
					class="btn-add"
					onclick={addCondition}
					aria-label="Add filter condition"
				>
					<Plus size={16} aria-hidden="true" />
				</button>
			</div>
		</div>

		{#if conditions.length === 0}
			<p class="empty-message" role="status">
				No conditions configured. Click "+ Add" to create one.
			</p>
		{:else}
			<div class="conditions-list" role="list" aria-label="Filter conditions" aria-live="polite">
				{#each conditions as cond, i (i)}
					{@const colType = getColumnType(cond.column)}
					{@const isColumn = cond.value_type === 'column'}
					{@const isNull = isNullOperator(cond.operator)}
					{@const ops = getOperatorsForType(colType, isColumn)}

					<div class="condition-card" role="listitem">
						<div class="condition-header">
							<span class="condition-number">#{i + 1}</span>
							{#if cond.column}
								<span class="condition-column">{cond.column}</span>
							{/if}
							<button
								type="button"
								class="btn-remove"
								onclick={() => removeCondition(i)}
								disabled={conditions.length === 1}
								aria-label={`Remove condition ${i + 1}`}
							>
								<X size={14} aria-hidden="true" />
							</button>
						</div>

						<div class="condition-row">
							<div class="field-group">
								<label class="field-label" for="{uid}-column-{i}">Column</label>
								<ColumnDropdown
									{schema}
									value={cond.column}
									onChange={(val) => handleColumnChange(i, val)}
									placeholder="Select..."
								/>
							</div>

							<div class="field-group operator-group">
								<label class="field-label" for="{uid}-operator-{i}">Operator</label>
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

							{#if !isNull}
								<div class="field-group value-group">
									<div class="value-header">
										<span class="field-label">Compare to</span>
										<div class="mode-toggle" role="radiogroup" aria-label="Value mode">
											<button
												type="button"
												class="mode-btn"
												class:active={!isColumn}
												onclick={() => handleModeChange(i, 'value')}
												aria-pressed={!isColumn}
											>
												Value
											</button>
											<button
												type="button"
												class="mode-btn"
												class:active={isColumn}
												onclick={() => handleModeChange(i, 'column')}
												aria-pressed={isColumn}
											>
												Column
											</button>
										</div>
									</div>

									{#if isColumn}
										<ColumnDropdown
											{schema}
											value={cond.compare_column ?? ''}
											onChange={(val) => updateCondition(i, { compare_column: val })}
											placeholder="Select..."
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
												updateCondition(i, { value: raw === '' ? '' : Number(raw) });
											}}
											placeholder="0"
										/>
									{:else if colType === 'datetime'}
										<DateTimeInput
											id="{uid}-value-{i}"
											value={formatDatetimeForInput(cond.value)}
											onChange={(val) => updateCondition(i, { value: val })}
										/>
									{:else if colType === 'date'}
										<input
											id="{uid}-value-{i}"
											data-testid={`filter-value-input-${i}`}
											type="date"
											value={formatDateForInput(cond.value)}
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
										<input
											id="{uid}-value-{i}"
											data-testid={`filter-value-input-${i}`}
											type="text"
											value={cond.value ?? ''}
											oninput={(e) => updateCondition(i, { value: e.currentTarget.value })}
											placeholder={cond.operator === 'regex' ? 'pattern' : 'value'}
										/>
									{/if}
								</div>
							{:else}
								<div class="field-group value-group">
									<span class="field-label">Value</span>
									<div class="null-indicator">
										<span>No value needed</span>
									</div>
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.section-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-4);
	}
	.section-header h4 {
		margin-bottom: 0;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.logic-toggle,
	.mode-toggle {
		display: flex;
	}

	.logic-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--space-1) var(--space-2);
		background-color: transparent;
		color: var(--fg-muted);
		border: 1px solid var(--border-primary);
		cursor: pointer;
		transition: all var(--transition);
		font-size: var(--text-xs);
	}
	.logic-btn:first-child {
		border-radius: var(--radius-sm) 0 0 var(--radius-sm);
		border-right: none;
	}
	.logic-btn:last-child {
		border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
	}
	.logic-btn:hover:not(.active) {
		background-color: var(--bg-hover);
		color: var(--fg-secondary);
	}
	.logic-btn.active {
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border-color: var(--accent-primary);
	}

	.mode-toggle {
		display: flex;
	}

	.mode-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--space-1) var(--space-2);
		background-color: transparent;
		color: var(--fg-muted);
		border: 1px solid var(--border-primary);
		cursor: pointer;
		transition: all var(--transition);
		font-size: var(--text-xs);
	}
	.mode-btn:first-child {
		border-radius: var(--radius-sm) 0 0 var(--radius-sm);
		border-right: none;
	}
	.mode-btn:last-child {
		border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
	}
	.mode-btn:hover:not(.active) {
		background-color: var(--bg-hover);
		color: var(--fg-secondary);
	}
	.mode-btn.active {
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border-color: var(--accent-primary);
	}

	.btn-add {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		padding: 0;
		background-color: var(--bg-tertiary);
		color: var(--fg-secondary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}
	.btn-add:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.empty-message {
		color: var(--fg-muted);
		font-style: italic;
		text-align: center;
		padding: var(--space-6);
	}

	.conditions-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.condition-card {
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		padding: var(--space-3);
	}

	.condition-header {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
		padding-bottom: var(--space-2);
		border-bottom: 1px solid var(--border-primary);
	}

	.condition-number {
		font-size: var(--text-xs);
		font-weight: var(--font-semibold);
		color: var(--fg-muted);
	}

	.condition-column {
		font-size: var(--text-sm);
		font-weight: var(--font-medium);
		color: var(--fg-primary);
	}

	.btn-remove {
		margin-left: auto;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		padding: 0;
		background-color: transparent;
		color: var(--fg-muted);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition);
	}
	.btn-remove:hover:not(:disabled) {
		background-color: var(--error-bg);
		color: var(--error-fg);
		border-color: var(--error-border);
	}
	.btn-remove:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}

	.condition-row {
		display: flex;
		gap: var(--space-3);
		align-items: flex-start;
		flex-wrap: wrap;
		position: relative;
	}

	.field-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		flex: 1;
		min-width: 120px;
	}

	.operator-group {
		flex: 0.8;
		min-width: 100px;
	}

	.value-group {
		flex: 1.5;
		min-width: 150px;
	}

	.field-label {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		margin-bottom: 0;
		font-weight: var(--font-normal);
	}

	.value-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: var(--space-2);
	}

	.null-indicator {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 34px;
		background-color: var(--bg-tertiary);
		border: 1px dashed var(--border-secondary);
		border-radius: var(--radius-sm);
		color: var(--fg-muted);
		font-size: var(--text-sm);
		font-style: italic;
	}

	.condition-card :global(.column-select) {
		position: static;
	}
	.condition-card :global(.column-menu) {
		top: inherit;
		margin-top: 48px;
	}
</style>
