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
		<div class="mb-4 flex items-center justify-between">
			<h4 id="{uid}-conditions-heading" class="mb-0">Conditions</h4>
			<div class="flex items-center gap-2">
				<div class="flex" role="radiogroup" aria-label="Condition logic">
					<button
						type="button"
						class="logic-btn flex cursor-pointer items-center justify-center border border-tertiary bg-transparent px-2 py-1 text-xs text-fg-muted transition-all hover:bg-hover hover:text-fg-secondary"
						class:active={config.logic === 'AND'}
						onclick={() => (config.logic = 'AND')}
						aria-pressed={config.logic === 'AND'}
					>
						AND
					</button>
					<button
						type="button"
						class="logic-btn flex cursor-pointer items-center justify-center border border-tertiary bg-transparent px-2 py-1 text-xs text-fg-muted transition-all hover:bg-hover hover:text-fg-secondary"
						class:active={config.logic === 'OR'}
						onclick={() => (config.logic = 'OR')}
						aria-pressed={config.logic === 'OR'}
					>
						OR
					</button>
				</div>
				<button
					type="button"
					class="btn-add flex h-7 w-7 cursor-pointer items-center justify-center border border-tertiary bg-tertiary p-0 text-fg-secondary hover:bg-hover hover:text-fg-primary"
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
			<div
				class="flex flex-col gap-3"
				role="list"
				aria-label="Filter conditions"
				aria-live="polite"
			>
				{#each conditions as cond, i (i)}
					{@const colType = getColumnType(cond.column)}
					{@const isColumn = cond.value_type === 'column'}
					{@const isNull = isNullOperator(cond.operator)}
					{@const ops = getOperatorsForType(colType, isColumn)}

					<div
						class="condition-card filter-config border border-tertiary bg-panel p-3"
						role="listitem"
					>
						<div class="mb-3 flex items-center gap-2 border-b border-tertiary pb-2">
							<span class="text-xs font-semibold text-fg-muted">#{i + 1}</span>
							{#if cond.column}
								<span class="text-sm font-medium text-fg-primary">{cond.column}</span>
							{/if}
							<button
								type="button"
								class="btn-remove ml-auto flex h-6 w-6 cursor-pointer items-center justify-center border border-transparent bg-transparent p-0 text-fg-muted transition-all hover:border-error hover:bg-error hover:text-error disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-transparent disabled:hover:bg-transparent disabled:hover:text-fg-muted"
								onclick={() => removeCondition(i)}
								disabled={conditions.length === 1}
								aria-label={`Remove condition ${i + 1}`}
							>
								<X size={14} aria-hidden="true" />
							</button>
						</div>

						<div class="relative flex flex-wrap items-start gap-3">
							<div class="flex min-w-30 flex-1 flex-col gap-1">
								<label class="mb-0 text-xs font-normal text-fg-muted" for="{uid}-column-{i}"
									>Column</label
								>
								<ColumnDropdown
									{schema}
									value={cond.column}
									onChange={(val) => handleColumnChange(i, val)}
									placeholder="Select..."
								/>
							</div>

							<div class="flex flex-col gap-1 min-w-25 flex-1">
								<label class="text-xs font-normal mb-0 text-fg-muted" for="{uid}-operator-{i}"
									>Operator</label
								>
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
								<div class="flex flex-col gap-1 min-w-35 flex-2">
									<div class="flex items-center justify-between gap-2">
										<span class="text-xs font-normal text-fg-muted">Compare to</span>
										<div class="flex" role="radiogroup" aria-label="Value mode">
											<button
												type="button"
												class="mode-btn flex items-center justify-center px-2 py-1 text-xs cursor-pointer transition-all border border-tertiary bg-transparent text-fg-muted hover:bg-hover hover:text-fg-secondary"
												class:active={!isColumn}
												onclick={() => handleModeChange(i, 'value')}
												aria-pressed={!isColumn}
											>
												Value
											</button>
											<button
												type="button"
												class="mode-btn flex items-center justify-center px-2 py-1 text-xs cursor-pointer transition-all border border-tertiary bg-transparent text-fg-muted hover:bg-hover hover:text-fg-secondary"
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
								<div class="flex flex-col gap-1 min-w-35 flex-2">
									<span class="text-xs font-normal text-fg-muted">Value</span>
									<div class="flex items-center h-9 px-3 text-sm italic bg-tertiary text-fg-muted">
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
