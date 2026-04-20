<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { X, Plus } from 'lucide-svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import DateTimeInput from '$lib/components/common/DateTimeInput.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import ToggleButton from '$lib/components/ui/ToggleButton.svelte';
	import { css, input } from '$lib/styles/panda';

	const uid = $props.id();

	type ValueType = 'string' | 'number' | 'date' | 'datetime' | 'column' | 'boolean';

	interface Condition {
		column: string;
		operator: string;
		value: string | number | boolean | string[] | null;
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
	const LIST_OPS = ['in', 'not_in'];
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
		in: 'in',
		not_in: 'not in',
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
		if (type === 'string') return [...COMPARISON_OPS, ...LIST_OPS, ...STRING_OPS, ...NULL_OPS];
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

	function updateCondition(idx: number, updates: Partial<Condition>, coerce = true) {
		const next = { ...conditions[idx], ...updates } as Condition;
		if (coerce && next.value_type === 'number' && typeof next.value === 'string') {
			const trimmed = next.value.trim();
			next.value = trimmed === '' ? '' : Number(trimmed);
		}
		config.conditions = conditions.map((c, i) => (i === idx ? next : c));
	}

	function isMultiLiteralOperator(op: string): boolean {
		return op !== 'regex' && op !== 'is_null' && op !== 'is_not_null';
	}

	function getLiteralList(value: string | number | boolean | string[] | null): string[] {
		if (Array.isArray(value)) return value;
		if (value === null || value === undefined) return [];
		if (value === '') return [];
		return [String(value)];
	}

	function setLiteralList(idx: number, values: string[]) {
		const next = values.length === 0 ? '' : values;
		updateCondition(idx, { value: next });
	}

	function appendLiteralToken(idx: number, token: string) {
		const trimmed = token.trim();
		if (!trimmed) return;
		const next = [...getLiteralList(conditions[idx].value), trimmed];
		setLiteralList(idx, next);
	}

	function removeLiteralToken(idx: number, tokenIndex: number) {
		const next = getLiteralList(conditions[idx].value).filter((_, i) => i !== tokenIndex);
		setLiteralList(idx, next);
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
			updateCondition(idx, { value_type: 'column', compare_column: '', operator: op, value: '' });
			return;
		}
		updateCondition(idx, {
			value_type: colType,
			compare_column: undefined,
			operator: op,
			value: ''
		});
	}

	function handleOperatorChange(idx: number, op: string) {
		const updates: Partial<Condition> = { operator: op };
		if (isNullOperator(op)) {
			updates.value = '';
			updates.compare_column = undefined;
		}
		if (op === 'regex' && Array.isArray(conditions[idx].value)) {
			updates.value = '';
		}
		updateCondition(idx, updates);
	}

	function formatDatetimeForInput(val: string | number | boolean | string[] | null): string {
		if (!val) return '';
		if (Array.isArray(val)) return '';
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

	function formatDateForInput(val: string | number | boolean | string[] | null): string {
		if (!val) return '';
		if (Array.isArray(val)) return '';
		const str = String(val);
		// If already in date format (YYYY-MM-DD), return as-is
		if (/^\d{4}-\d{2}-\d{2}$/.test(str)) return str;
		// Extract date part from ISO string
		const match = /^(\d{4}-\d{2}-\d{2})/.exec(str);
		if (match) return match[1];
		return '';
	}
</script>

<div
	class={css({ padding: '0', border: 'none', backgroundColor: 'bg.primary' })}
	role="region"
	aria-label="Filter configuration"
>
	<div role="group" aria-labelledby="{uid}-conditions-heading">
		<div
			class={css({
				marginBottom: '5',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between'
			})}
		>
			<SectionHeader>
				<span id="{uid}-conditions-heading">Conditions</span>
			</SectionHeader>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<div class={css({ display: 'flex' })} role="radiogroup" aria-label="Condition logic">
					<ToggleButton
						active={config.logic === 'AND'}
						radius="left"
						onclick={() => (config.logic = 'AND')}
						ariaPressed={config.logic === 'AND'}>AND</ToggleButton
					>
					<ToggleButton
						active={config.logic === 'OR'}
						radius="right"
						onclick={() => (config.logic = 'OR')}
						ariaPressed={config.logic === 'OR'}>OR</ToggleButton
					>
				</div>
				<button
					type="button"
					class={css({
						display: 'flex',
						height: 'row',
						width: 'row',
						cursor: 'pointer',
						alignItems: 'center',
						justifyContent: 'center',
						borderWidth: '1',
						backgroundColor: 'bg.tertiary',
						padding: '0',
						color: 'fg.secondary',
						_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
					})}
					onclick={addCondition}
					aria-label="Add filter condition"
				>
					<Plus size={16} aria-hidden="true" />
				</button>
			</div>
		</div>

		{#if conditions.length === 0}
			<p
				class={css({
					color: 'fg.muted',
					fontStyle: 'italic',
					textAlign: 'center',
					padding: '4',
					margin: '0'
				})}
				role="status"
			>
				No conditions configured. Click "+ Add" to create one.
			</p>
		{:else}
			<div
				class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}
				role="list"
				aria-label="Filter conditions"
				aria-live="polite"
			>
				{#each conditions as cond, i (i)}
					{@const colType = getColumnType(cond.column)}
					{@const isColumn = cond.value_type === 'column'}
					{@const isNull = isNullOperator(cond.operator)}
					{@const multiLiteral =
						!isColumn && !isNull && colType === 'string' && isMultiLiteralOperator(cond.operator)}
					{@const ops = getOperatorsForType(colType, isColumn)}

					<div
						class={css({
							borderLeftWidth: '2',
							paddingLeft: '4',
							paddingBottom: '2'
						})}
						role="listitem"
					>
						<div
							class={css({
								marginBottom: '3',
								display: 'flex',
								alignItems: 'center',
								gap: '2',
								paddingBottom: '2'
							})}
						>
							<span
								class={css({
									display: 'block',
									fontSize: 'xs2',
									fontWeight: 'semibold',
									color: 'fg.muted',
									marginBottom: '1.5',
									textTransform: 'uppercase',
									letterSpacing: 'wider'
								})}>#{i + 1}</span
							>
							{#if cond.column}
								<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>{cond.column}</span>
							{/if}
							<button
								type="button"
								class={css({
									marginLeft: 'auto',
									display: 'flex',
									height: 'iconLg',
									width: 'iconLg',
									cursor: 'pointer',
									alignItems: 'center',
									justifyContent: 'center',
									borderWidth: '1',
									padding: '0',
									_hover: {
										borderColor: 'border.error',
										backgroundColor: 'bg.error',
										color: 'fg.error'
									},
									_disabled: { cursor: 'not-allowed', opacity: '0.3' }
								})}
								onclick={() => removeCondition(i)}
								disabled={conditions.length === 1}
								aria-label={`Remove condition ${i + 1}`}
							>
								<X size={14} aria-hidden="true" />
							</button>
						</div>

						<div
							class={css({
								position: 'relative',
								display: 'flex',
								flexWrap: 'wrap',
								alignItems: 'start',
								gap: '4'
							})}
						>
							<div
								class={css({
									display: 'flex',
									flex: '2',
									flexDirection: 'column',
									gap: '1',
									minWidth: 'dropdown'
								})}
							>
								<span
									class={css({
										marginBottom: '0',
										fontSize: 'xs',
										fontWeight: 'normal',
										color: 'fg.muted'
									})}>Column</span
								>
								<ColumnDropdown
									{schema}
									value={cond.column}
									onChange={(val) => handleColumnChange(i, val)}
									placeholder="Select..."
									triggerClass={css({ width: '100%' })}
									menuClass={css({ top: '100%' })}
								/>
							</div>

							<div
								class={css({
									display: 'flex',
									flex: '1',
									flexDirection: 'column',
									gap: '1',
									minWidth: 'inputSm'
								})}
							>
								<label
									class={css({
										fontSize: 'xs',
										fontWeight: 'normal',
										marginBottom: '0',
										color: 'fg.muted'
									})}
									for="{uid}-operator-{i}">Operator</label
								>
								<select
									id="{uid}-operator-{i}"
									data-testid={`filter-operator-select-${i}`}
									class={input()}
									value={cond.operator}
									onchange={(e) => handleOperatorChange(i, e.currentTarget.value)}
								>
									{#each ops as op (op)}
										<option value={op}>{OPERATOR_LABELS[op]}</option>
									{/each}
								</select>
							</div>

							{#if !isNull}
								<div
									class={css({
										display: 'flex',
										flex: '2',
										flexDirection: 'column',
										gap: '1',
										minWidth: 'list'
									})}
								>
									<div
										class={css({
											display: 'flex',
											alignItems: 'center',
											justifyContent: 'space-between',
											gap: '2'
										})}
									>
										<span
											class={css({
												display: 'block',
												fontSize: 'xs2',
												fontWeight: 'normal',
												color: 'fg.muted',
												marginBottom: '1.5',
												textTransform: 'uppercase',
												letterSpacing: 'wider'
											})}>Compare to</span
										>
										<div class={css({ display: 'flex' })} role="radiogroup" aria-label="Value mode">
											<ToggleButton
												active={!isColumn}
												radius="left"
												onclick={() => handleModeChange(i, 'value')}
												ariaPressed={!isColumn}>Value</ToggleButton
											>
											<ToggleButton
												active={isColumn}
												radius="right"
												onclick={() => handleModeChange(i, 'column')}
												ariaPressed={isColumn}>Column</ToggleButton
											>
										</div>
									</div>

									{#if isColumn}
										<ColumnDropdown
											{schema}
											value={cond.compare_column ?? ''}
											onChange={(val) => updateCondition(i, { compare_column: val })}
											placeholder="Select..."
											triggerClass={css({ width: '100%' })}
											menuClass={css({ top: '100%' })}
										/>
									{:else if colType === 'number'}
										<input
											id="{uid}-value-{i}"
											data-testid={`filter-value-input-${i}`}
											type="number"
											class={input()}
											step="any"
											value={typeof cond.value === 'number'
												? String(cond.value)
												: (cond.value ?? '')}
											oninput={(e) => updateCondition(i, { value: e.currentTarget.value }, false)}
											onblur={(e) => updateCondition(i, { value: e.currentTarget.value })}
											placeholder="0"
										/>
									{:else if colType === 'datetime'}
										<DateTimeInput
											id="{uid}-value-{i}"
											value={formatDatetimeForInput(cond.value)}
											onChange={(val) => updateCondition(i, { value: val })}
										/>
									{:else if colType === 'date'}
										<DateTimeInput
											id="{uid}-value-{i}"
											value={formatDateForInput(cond.value)}
											onChange={(val) => updateCondition(i, { value: val })}
											withTime={false}
										/>
									{:else if colType === 'boolean'}
										<select
											id="{uid}-value-{i}"
											data-testid={`filter-value-input-${i}`}
											class={input()}
											value={String(cond.value ?? 'true')}
											onchange={(e) =>
												updateCondition(i, { value: e.currentTarget.value === 'true' })}
										>
											<option value="true">true</option>
											<option value="false">false</option>
										</select>
									{:else if multiLiteral}
										{@const tokens = getLiteralList(cond.value)}
										<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
											<input
												id="{uid}-value-{i}"
												data-testid={`filter-value-input-${i}`}
												type="text"
												class={input()}
												value=""
												onkeydown={(e) => {
													if (e.key !== 'Enter') return;
													e.preventDefault();
													const target = e.currentTarget as HTMLInputElement;
													appendLiteralToken(i, target.value);
													target.value = '';
												}}
												placeholder="Type value and press Enter"
											/>
											{#if tokens.length > 0}
												<div
													class={css({ display: 'flex', flexWrap: 'wrap', gap: '2' })}
													role="list"
													aria-label="Filter values"
												>
													{#each tokens as token, tokenIndex (tokenIndex)}
														<span
															class={css({
																display: 'inline-flex',
																alignItems: 'center',
																gap: '1',
																borderWidth: '1',
																backgroundColor: 'bg.tertiary',
																fontSize: 'xs',
																paddingY: '1',
																paddingX: '2'
															})}
															role="listitem"
														>
															<span
																class={css({
																	maxWidth: 'dropdown',
																	overflow: 'hidden',
																	textOverflow: 'ellipsis',
																	whiteSpace: 'nowrap'
																})}>{token}</span
															>
															<button
																class={css({
																	display: 'inline-flex',
																	alignItems: 'center',
																	justifyContent: 'center',
																	padding: '0',
																	border: 'none',
																	background: 'transparent',
																	color: 'fg.muted',
																	cursor: 'pointer',
																	_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
																})}
																onclick={() => removeLiteralToken(i, tokenIndex)}
																aria-label={`Remove ${token}`}
																type="button"
															>
																<X size={12} />
															</button>
														</span>
													{/each}
												</div>
											{/if}
										</div>
									{:else}
										<input
											id="{uid}-value-{i}"
											data-testid={`filter-value-input-${i}`}
											type="text"
											class={input()}
											value={cond.value ?? ''}
											oninput={(e) => updateCondition(i, { value: e.currentTarget.value })}
											placeholder={cond.operator === 'regex' ? 'pattern' : 'value'}
										/>
									{/if}
								</div>
							{:else}
								<div
									class={css({
										display: 'flex',
										flex: '2',
										flexDirection: 'column',
										gap: '1',
										minWidth: 'list'
									})}
								>
									<span
										class={css({
											display: 'block',
											fontSize: 'xs2',
											fontWeight: 'normal',
											color: 'fg.muted',
											marginBottom: '1.5',
											textTransform: 'uppercase',
											letterSpacing: 'wider'
										})}>Value</span
									>
									<div
										class={css({
											display: 'flex',
											alignItems: 'center',
											height: 'rowXl',
											paddingX: '3',
											fontSize: 'xs',
											fontStyle: 'italic',
											color: 'fg.muted'
										})}
									>
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
