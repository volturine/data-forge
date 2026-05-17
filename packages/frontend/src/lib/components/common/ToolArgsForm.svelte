<script lang="ts">
	import { SvelteMap } from 'svelte/reactivity';
	import { css, input, label, button } from '$lib/styles/panda';
	import ToolArgsForm from './ToolArgsForm.svelte';

	interface Props {
		schema: Record<string, unknown>;
		value: Record<string, unknown>;
		errors?: { path: string; message: string }[];
		pathPrefix?: string;
		onchange?: (updated: Record<string, unknown>) => void;
		onunsupported?: (path: string, message: string) => void;
	}

	let {
		schema,
		value = $bindable(),
		errors = [],
		pathPrefix = '',
		onchange,
		onunsupported
	}: Props = $props();

	type PropSchema = {
		type?: string | string[];
		title?: string;
		description?: string;
		default?: unknown;
		const?: unknown;
		properties?: Record<string, PropSchema>;
		patternProperties?: Record<string, PropSchema>;
		additionalProperties?: boolean | PropSchema;
		items?: PropSchema;
		enum?: unknown[];
		anyOf?: PropSchema[];
		oneOf?: PropSchema[];
		allOf?: PropSchema[];
		if?: PropSchema;
		then?: PropSchema;
		else?: PropSchema;
		not?: PropSchema;
		required?: string[];
		minimum?: number;
		maximum?: number;
		minLength?: number;
		maxLength?: number;
		pattern?: string;
		format?: string;
		dependentRequired?: Record<string, string[]>;
		dependencies?: Record<string, string[] | PropSchema>;
	};

	const properties = $derived((schema.properties as Record<string, PropSchema> | undefined) ?? {});
	const required = $derived((schema.required as string[] | undefined) ?? []);
	const schemaDependentRequired = $derived(
		(schema.dependentRequired as Record<string, string[]> | undefined) ?? {}
	);

	const variantMap = new SvelteMap<string, number>();

	function errorFor(key: string): string | undefined {
		const path = pathPrefix ? `${pathPrefix}.${key}` : key;
		return errors.find((e) => e.path === path || e.path === `$.${path}`)?.message;
	}

	function resolveSchema(prop: PropSchema): { schema: PropSchema; nullable: boolean } {
		if (!prop.anyOf) return { schema: prop, nullable: false };
		const nonNull = prop.anyOf.find((s) => s.type !== 'null');
		const hasNull = prop.anyOf.some((s) => s.type === 'null');
		return { schema: nonNull ?? prop, nullable: hasNull };
	}

	function effectiveType(prop: PropSchema): string {
		const { schema: s } = resolveSchema(prop);
		if (Array.isArray(s.type)) return s.type.find((t) => t !== 'null') ?? 'string';
		return s.type ?? 'string';
	}

	function mergeAllOf(schemas: PropSchema[]): PropSchema {
		const merged: PropSchema = { type: 'object', properties: {}, required: [] };
		for (const s of schemas) {
			if (s.properties) merged.properties = { ...merged.properties, ...s.properties };
			if (s.required) merged.required = [...(merged.required ?? []), ...s.required];
		}
		return merged;
	}

	function getVariants(prop: PropSchema): PropSchema[] {
		return prop.oneOf ?? prop.anyOf ?? [];
	}

	function nonNullVariants(variants: PropSchema[]): PropSchema[] {
		return variants.filter((v) => v.type !== 'null');
	}

	function defaultVariantIndex(variants: PropSchema[]): number {
		const idx = variants.findIndex((v) => v.type !== 'null');
		return idx >= 0 ? idx : 0;
	}

	function getVariantIndex(key: string, variants: PropSchema[]): number {
		const stored = variantMap.get(key);
		if (stored !== undefined && stored >= 0 && stored < variants.length) return stored;
		return defaultVariantIndex(variants);
	}

	function setVariantIndex(key: string, idx: number): void {
		variantMap.set(key, idx);
		const next = { ...value };
		delete next[key];
		value = next;
		onchange?.(next);
	}

	function isSchemaSupported(prop: PropSchema): boolean {
		if (prop.oneOf || prop.anyOf || prop.allOf) return true;
		if (prop.patternProperties) return true;
		if (prop.const !== undefined) return true;
		const t = effectiveType(prop);
		return ['string', 'number', 'integer', 'boolean', 'array', 'object'].includes(t);
	}

	function update(next: Record<string, unknown>): void {
		value = next;
		onchange?.(next);
	}

	function getString(key: string): string {
		const v = value[key];
		if (v === undefined || v === null) return '';
		if (typeof v === 'object') return JSON.stringify(v);
		return String(v);
	}

	function setString(key: string, raw: string, prop: PropSchema): void {
		const t = effectiveType(prop);
		if (t === 'integer') {
			const n = parseInt(raw, 10);
			update({ ...value, [key]: isNaN(n) ? raw : n });
			return;
		}
		if (t === 'number') {
			const n = parseFloat(raw);
			update({ ...value, [key]: isNaN(n) ? raw : n });
			return;
		}
		update({ ...value, [key]: raw });
	}

	function getBoolean(key: string): boolean {
		return value[key] === true;
	}

	function setBoolean(key: string, checked: boolean): void {
		update({ ...value, [key]: checked });
	}

	function getArray(key: string): string {
		const v = value[key];
		if (!Array.isArray(v)) return '';
		return v.join(', ');
	}

	function setArray(key: string, raw: string): void {
		update({
			...value,
			[key]: raw
				.split(',')
				.map((s) => s.trim())
				.filter((s) => s.length > 0)
		});
	}

	function getEnumArray(key: string): string[] {
		const v = value[key];
		if (!Array.isArray(v)) return [];
		return v.map(String);
	}

	function setEnumArrayItem(key: string, idx: number, val: string): void {
		const arr = [...getEnumArray(key)];
		arr[idx] = val;
		update({ ...value, [key]: arr });
	}

	function addEnumArrayItem(key: string, firstOpt: string): void {
		const arr = [...getEnumArray(key), firstOpt];
		update({ ...value, [key]: arr });
	}

	function removeEnumArrayItem(key: string, idx: number): void {
		const arr = [...getEnumArray(key)];
		arr.splice(idx, 1);
		update({ ...value, [key]: arr });
	}

	function getNestedArrays(key: string): string[] {
		const v = value[key];
		if (!Array.isArray(v)) return [];
		return v.map((sub) => (Array.isArray(sub) ? sub.join(', ') : String(sub ?? '')));
	}

	function setNestedArrayItem(key: string, idx: number, raw: string): void {
		const arr = getNestedArrays(key).map((s, i) =>
			(i === idx ? raw : s)
				.split(',')
				.map((x) => x.trim())
				.filter((x) => x.length > 0)
		);
		update({ ...value, [key]: arr });
	}

	function addNestedArrayItem(key: string): void {
		const arr = getNestedArrays(key).map((s) =>
			s
				.split(',')
				.map((x) => x.trim())
				.filter((x) => x.length > 0)
		);
		update({ ...value, [key]: [...arr, []] });
	}

	function removeNestedArrayItem(key: string, idx: number): void {
		const arr = getNestedArrays(key).map((s) =>
			s
				.split(',')
				.map((x) => x.trim())
				.filter((x) => x.length > 0)
		);
		arr.splice(idx, 1);
		update({ ...value, [key]: arr });
	}

	function getObjectArray(key: string): Record<string, unknown>[] {
		const v = value[key];
		if (!Array.isArray(v)) return [];
		return v.filter(
			(item): item is Record<string, unknown> => typeof item === 'object' && item !== null
		);
	}

	function setObjectArrayRow(key: string, idx: number, row: Record<string, unknown>): void {
		const arr = [...getObjectArray(key)];
		arr[idx] = row;
		update({ ...value, [key]: arr });
	}

	function addObjectArrayRow(key: string, itemSchema: PropSchema): void {
		const arr = [...getObjectArray(key)];
		arr.push(buildBlank(itemSchema));
		update({ ...value, [key]: arr });
	}

	function removeObjectArrayRow(key: string, idx: number): void {
		const arr = [...getObjectArray(key)];
		arr.splice(idx, 1);
		update({ ...value, [key]: arr });
	}

	function buildBlank(s: PropSchema): Record<string, unknown> {
		const blank: Record<string, unknown> = {};
		for (const [k, p] of Object.entries(s.properties ?? {})) {
			if (p.const !== undefined) {
				blank[k] = p.const;
				continue;
			}
			if (p.default !== undefined) {
				blank[k] = p.default;
				continue;
			}
			const t = effectiveType(p);
			if (t === 'boolean') blank[k] = false;
			else if (t === 'integer' || t === 'number') blank[k] = 0;
			else if (t === 'array') blank[k] = [];
			else if (t === 'object') blank[k] = {};
			else blank[k] = '';
		}
		return blank;
	}

	function getNestedObject(key: string): Record<string, unknown> {
		const v = value[key];
		if (typeof v === 'object' && v !== null && !Array.isArray(v))
			return v as Record<string, unknown>;
		return {};
	}

	function getNullable(key: string): boolean {
		return value[key] === null || value[key] === undefined;
	}

	function setNullable(key: string, checked: boolean): void {
		if (checked) update({ ...value, [key]: null });
	}

	function getPatternRows(key: string): [string, string][] {
		const v = value[key];
		if (typeof v !== 'object' || v === null || Array.isArray(v)) return [];
		return Object.entries(v as Record<string, unknown>).map(([k, val]) => [k, String(val ?? '')]);
	}

	function setPatternRow(key: string, idx: number, rowKey: string, rowVal: string): void {
		const rows = getPatternRows(key);
		rows[idx] = [rowKey, rowVal];
		const obj: Record<string, string> = {};
		for (const [k, v] of rows) obj[k] = v;
		update({ ...value, [key]: obj });
	}

	function addPatternRow(key: string): void {
		const rows = getPatternRows(key);
		rows.push(['', '']);
		const obj: Record<string, string> = {};
		for (const [k, v] of rows) obj[k] = v;
		update({ ...value, [key]: obj });
	}

	function removePatternRow(key: string, idx: number): void {
		const rows = getPatternRows(key);
		rows.splice(idx, 1);
		const obj: Record<string, string> = {};
		for (const [k, v] of rows) obj[k] = v;
		update({ ...value, [key]: obj });
	}

	function patternValueEnums(prop: PropSchema): unknown[] | null {
		const schemas = Object.values(prop.patternProperties ?? {});
		if (schemas.length > 0 && schemas[0].enum) return schemas[0].enum;
		return null;
	}

	function getAdditionalRows(key: string): [string, unknown][] {
		const v = value[key];
		if (typeof v !== 'object' || v === null || Array.isArray(v)) return [];
		const knownKeys = Object.keys((properties[key] as PropSchema | undefined)?.properties ?? {});
		return Object.entries(v as Record<string, unknown>).filter(([k]) => !knownKeys.includes(k));
	}

	function setAdditionalRow(key: string, idx: number, rowKey: string, rowVal: unknown): void {
		const existing = getNestedObject(key);
		const rows = getAdditionalRows(key);
		rows[idx] = [rowKey, rowVal];
		const next = { ...existing };
		for (const [k] of getAdditionalRows(key)) delete next[k];
		for (const [k, v] of rows) next[k] = v;
		update({ ...value, [key]: next });
	}

	function addAdditionalRow(key: string): void {
		const existing = getNestedObject(key);
		update({ ...value, [key]: { ...existing, '': '' } });
	}

	function removeAdditionalRow(key: string, idx: number): void {
		const existing = getNestedObject(key);
		const rows = getAdditionalRows(key);
		rows.splice(idx, 1);
		const next = { ...existing };
		for (const [k] of getAdditionalRows(key)) delete next[k];
		for (const [k, v] of rows) next[k] = v;
		update({ ...value, [key]: next });
	}

	function formatInputType(format: string | undefined, baseType: string): string {
		if (format === 'date') return 'date';
		if (format === 'date-time') return 'datetime-local';
		if (format === 'email') return 'email';
		if (format === 'uri' || format === 'url') return 'url';
		if (baseType === 'integer' || baseType === 'number') return 'number';
		return 'text';
	}

	function formatHelperText(prop: PropSchema): string | null {
		const parts: string[] = [];
		if (prop.pattern) parts.push(`Pattern: ${prop.pattern}`);
		if (prop.format && !['date', 'date-time', 'email', 'uri', 'url'].includes(prop.format)) {
			parts.push(`Format: ${prop.format}`);
		}
		if (prop.minimum !== undefined) parts.push(`Min: ${prop.minimum}`);
		if (prop.maximum !== undefined) parts.push(`Max: ${prop.maximum}`);
		if (prop.minLength !== undefined) parts.push(`Min length: ${prop.minLength}`);
		if (prop.maxLength !== undefined) parts.push(`Max length: ${prop.maxLength}`);
		return parts.length > 0 ? parts.join(' · ') : null;
	}

	function matchesSchema(schema: PropSchema, val: unknown): boolean {
		if (schema.const !== undefined) return val === schema.const;
		if (schema.enum) return schema.enum.includes(val);
		if (schema.properties) {
			if (typeof val !== 'object' || val === null) return false;
			const obj = val as Record<string, unknown>;
			for (const [k, sub] of Object.entries(schema.properties)) {
				if (!matchesSchema(sub, obj[k])) return false;
			}
			return true;
		}
		return true;
	}

	function resolveIfBranch(prop: PropSchema, currentVal: unknown): PropSchema | null {
		if (!prop.if) return null;
		const cond = matchesSchema(prop.if, currentVal);
		if (cond && prop.then) return prop.then;
		if (!cond && prop.else) return prop.else;
		return null;
	}

	function matchesNot(prop: PropSchema, currentVal: unknown): boolean {
		if (!prop.not) return false;
		return matchesSchema(prop.not, currentVal);
	}

	function isDependentRequired(key: string): boolean {
		for (const [dep, deps] of Object.entries(schemaDependentRequired)) {
			if (
				deps.includes(key) &&
				value[dep] !== undefined &&
				value[dep] !== null &&
				value[dep] !== ''
			) {
				return true;
			}
		}
		const schemaDeps =
			(schema.dependencies as Record<string, string[] | PropSchema> | undefined) ?? {};
		for (const [dep, depSpec] of Object.entries(schemaDeps)) {
			if (Array.isArray(depSpec) && depSpec.includes(key)) {
				if (value[dep] !== undefined && value[dep] !== null && value[dep] !== '') return true;
			}
		}
		return false;
	}

	function dependentHint(key: string): string | null {
		for (const [dep, deps] of Object.entries(schemaDependentRequired)) {
			if (
				deps.includes(key) &&
				value[dep] !== undefined &&
				value[dep] !== null &&
				value[dep] !== ''
			) {
				return `Required when "${dep}" is set`;
			}
		}
		return null;
	}

	// DOM-independent side effect: fills missing const/default into value on mount/change
	$effect(() => {
		let changed = false;
		const next = { ...value };
		for (const [key, rawProp] of Object.entries(properties)) {
			const { schema: prop } = resolveSchema(rawProp);
			if (prop.const !== undefined && next[key] === undefined) {
				next[key] = prop.const;
				changed = true;
			} else if (prop.default !== undefined && next[key] === undefined) {
				next[key] = prop.default;
				changed = true;
			}
		}
		if (changed) {
			value = next;
			onchange?.(next);
		}
	});

	const entries = $derived(Object.entries(properties));

	const unsupportedPaths = $derived(
		entries
			.filter(([, rawProp]) => {
				const { schema: prop } = resolveSchema(rawProp);
				const etype = effectiveType(rawProp);
				return (
					!isSchemaSupported(rawProp) ||
					(etype === 'object' &&
						!prop.properties &&
						!prop.patternProperties &&
						prop.additionalProperties === false)
				);
			})
			.map(([key]) => (pathPrefix ? `${pathPrefix}.${key}` : key))
	);

	// DOM-independent side effect: notifies parent of unsupported schema paths
	$effect(() => {
		for (const path of unsupportedPaths) {
			onunsupported?.(path, 'Unsupported schema — structured input not available');
		}
	});
</script>

<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
	{#each entries as [key, rawProp] (key)}
		{@const { schema: prop, nullable } = resolveSchema(rawProp)}
		{@const isReq = required.includes(key) || isDependentRequired(key)}
		{@const err = errorFor(key)}
		{@const etype = effectiveType(rawProp)}
		{@const hint = dependentHint(key)}
		{@const helper = formatHelperText(prop)}
		{@const notWarning = matchesNot(rawProp, value[key])}
		{@const ifBranch = resolveIfBranch(rawProp, value[key])}
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '0.5' })}>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<label class={label()} for={`tool-arg-${pathPrefix}-${key}`}>
					{key}{isReq ? ' *' : ''}
					{#if prop.description}
						<span class={css({ color: 'fg.muted', fontWeight: 'normal', marginLeft: '1' })}>
							— {prop.description}
						</span>
					{/if}
				</label>
				{#if nullable}
					<label
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '1',
							fontSize: 'xs',
							color: 'fg.muted'
						})}
					>
						<input
							type="checkbox"
							checked={getNullable(key)}
							onchange={(e) => setNullable(key, (e.target as HTMLInputElement).checked)}
							class={css({ width: '12px', height: '12px', cursor: 'pointer' })}
						/>
						null
					</label>
				{/if}
			</div>

			{#if hint}
				<span class={css({ fontSize: 'xs', color: 'fg.warning' })}>{hint}</span>
			{/if}

			{#if nullable && getNullable(key)}
				<span class={css({ fontSize: 'xs', color: 'fg.muted', fontStyle: 'italic' })}>null</span>
			{:else if prop.const !== undefined}
				<input
					id={`tool-arg-${pathPrefix}-${key}`}
					class={input()}
					type="text"
					value={String(prop.const)}
					readonly
					disabled
				/>
				<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Fixed value</span>
			{:else if ifBranch && ifBranch.properties}
				<div
					class={css({
						paddingLeft: '3',
						borderLeftWidth: '2',
						borderColor: err ? 'border.error' : 'border.subtle',
						display: 'flex',
						flexDirection: 'column',
						gap: '1.5'
					})}
				>
					<ToolArgsForm
						schema={{
							type: 'object',
							properties: ifBranch.properties,
							required: ifBranch.required ?? []
						}}
						value={getNestedObject(key)}
						{errors}
						pathPrefix={pathPrefix ? `${pathPrefix}.${key}` : key}
						onchange={(updated) => update({ ...value, [key]: updated })}
						{onunsupported}
					/>
				</div>
			{:else if rawProp.oneOf || (rawProp.anyOf && nonNullVariants(rawProp.anyOf ?? []).length > 1)}
				{@const variants = getVariants(rawProp)}
				{@const nonNull = nonNullVariants(variants)}
				{@const vidx = getVariantIndex(key, variants)}
				{@const activeVariant = variants[vidx] ?? nonNull[0] ?? variants[0]}
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
					<select
						class={input()}
						value={String(vidx)}
						onchange={(e) =>
							setVariantIndex(key, parseInt((e.target as HTMLSelectElement).value, 10))}
					>
						{#each variants as v, i (i)}
							{#if v.type !== 'null'}
								<option value={String(i)}>
									{v.title ?? v.type ?? `Option ${i + 1}`}
								</option>
							{/if}
						{/each}
					</select>
					<div
						class={css({
							paddingLeft: '3',
							borderLeftWidth: '2',

							display: 'flex',
							flexDirection: 'column',
							gap: '1.5'
						})}
					>
						<ToolArgsForm
							schema={{
								type: 'object',
								properties: { [key]: activeVariant },
								required: isReq ? [key] : []
							}}
							value={{ [key]: value[key] }}
							{errors}
							{pathPrefix}
							onchange={(updated) => update({ ...value, [key]: updated[key] })}
							{onunsupported}
						/>
					</div>
				</div>
			{:else if rawProp.allOf}
				{@const merged = mergeAllOf(rawProp.allOf)}
				<div
					class={css({
						paddingLeft: '3',
						borderLeftWidth: '2',
						borderColor: err ? 'border.error' : 'border.subtle',
						display: 'flex',
						flexDirection: 'column',
						gap: '1.5'
					})}
				>
					<ToolArgsForm
						schema={{
							type: 'object',
							properties: merged.properties,
							required: merged.required ?? []
						}}
						value={getNestedObject(key)}
						{errors}
						pathPrefix={pathPrefix ? `${pathPrefix}.${key}` : key}
						onchange={(updated) => update({ ...value, [key]: updated })}
						{onunsupported}
					/>
				</div>
			{:else if prop.patternProperties}
				{@const valEnums = patternValueEnums(prop)}
				<div
					class={css({
						borderWidth: '1',
						borderColor: err ? 'border.error' : 'border.primary',
						borderRadius: 'sm',
						overflow: 'hidden'
					})}
				>
					{#each getPatternRows(key) as [rowKey, rowVal], idx (idx)}
						<div
							class={css({
								display: 'flex',
								gap: '1',
								padding: '2',
								alignItems: 'center',
								borderBottomWidth: '1'
							})}
						>
							<input
								class={css({
									flex: '1',
									fontSize: 'xs',
									padding: '1',
									borderWidth: '1',
									borderRadius: 'sm',
									backgroundColor: 'bg.secondary',
									color: 'fg.primary'
								})}
								type="text"
								value={rowKey}
								oninput={(e) =>
									setPatternRow(key, idx, (e.target as HTMLInputElement).value, rowVal)}
								placeholder="key"
							/>
							<span class={css({ color: 'fg.muted', fontSize: 'xs', flexShrink: '0' })}>:</span>
							{#if valEnums}
								<select
									class={css({ flex: '1', fontSize: 'xs' })}
									value={rowVal}
									onchange={(e) =>
										setPatternRow(key, idx, rowKey, (e.target as HTMLSelectElement).value)}
								>
									{#each valEnums as opt (opt)}
										<option value={String(opt)}>{String(opt)}</option>
									{/each}
								</select>
							{:else}
								<input
									class={css({
										flex: '1',
										fontSize: 'xs',
										padding: '1',
										borderWidth: '1',
										borderRadius: 'sm',
										backgroundColor: 'bg.secondary',
										color: 'fg.primary'
									})}
									type="text"
									value={rowVal}
									oninput={(e) =>
										setPatternRow(key, idx, rowKey, (e.target as HTMLInputElement).value)}
									placeholder="value"
								/>
							{/if}
							<button
								class={button({ variant: 'ghost', size: 'sm' })}
								type="button"
								onclick={() => removePatternRow(key, idx)}
							>
								-
							</button>
						</div>
					{/each}
					<div class={css({ padding: '2' })}>
						<button
							class={button({ variant: 'ghost', size: 'sm' })}
							type="button"
							onclick={() => addPatternRow(key)}
						>
							+ Add entry
						</button>
					</div>
				</div>
			{:else if etype === 'boolean'}
				<input
					id={`tool-arg-${pathPrefix}-${key}`}
					type="checkbox"
					checked={getBoolean(key)}
					onchange={(e) => setBoolean(key, (e.target as HTMLInputElement).checked)}
					class={css({ width: '16px', height: '16px', cursor: 'pointer' })}
				/>
			{:else if prop.enum}
				<select
					id={`tool-arg-${pathPrefix}-${key}`}
					class={input()}
					value={getString(key)}
					onchange={(e) => setString(key, (e.target as HTMLSelectElement).value, rawProp)}
				>
					{#each prop.enum as opt (opt)}
						<option value={String(opt)}>{String(opt)}</option>
					{/each}
				</select>
			{:else if etype === 'array' && prop.items?.type === 'object' && prop.items.properties}
				<div
					class={css({
						borderWidth: '1',
						borderColor: err ? 'border.error' : 'border.primary',
						borderRadius: 'sm',
						overflow: 'hidden'
					})}
				>
					{#each getObjectArray(key) as row, idx (idx)}
						<div
							class={css({
								padding: '2',
								borderBottomWidth: '1',

								backgroundColor: 'bg.tertiary'
							})}
						>
							<div
								class={css({
									display: 'flex',
									justifyContent: 'space-between',
									alignItems: 'center',
									marginBottom: '1.5'
								})}
							>
								<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>#{idx + 1}</span>
								<button
									class={button({ variant: 'ghost', size: 'sm' })}
									type="button"
									onclick={() => removeObjectArrayRow(key, idx)}
								>
									Remove
								</button>
							</div>
							<ToolArgsForm
								schema={{
									type: 'object',
									properties: prop.items?.properties,
									required: prop.items?.required ?? []
								}}
								value={row}
								{errors}
								pathPrefix={pathPrefix ? `${pathPrefix}.${key}.${idx}` : `${key}.${idx}`}
								onchange={(updated) => setObjectArrayRow(key, idx, updated)}
								{onunsupported}
							/>
						</div>
					{/each}
					<div class={css({ padding: '2' })}>
						<button
							class={button({ variant: 'ghost', size: 'sm' })}
							type="button"
							onclick={() => addObjectArrayRow(key, prop.items!)}
						>
							+ Add row
						</button>
					</div>
				</div>
			{:else if etype === 'array' && prop.items?.enum}
				{@const opts = prop.items.enum ?? []}
				<div
					class={css({
						borderWidth: '1',
						borderColor: err ? 'border.error' : 'border.primary',
						borderRadius: 'sm',
						overflow: 'hidden'
					})}
				>
					{#each getEnumArray(key) as item, idx (idx)}
						<div
							class={css({
								display: 'flex',
								gap: '1',
								padding: '2',
								alignItems: 'center',
								borderBottomWidth: '1'
							})}
						>
							<select
								class={css({ flex: '1', fontSize: 'xs' })}
								value={item}
								onchange={(e) => setEnumArrayItem(key, idx, (e.target as HTMLSelectElement).value)}
							>
								{#each opts as opt (opt)}
									<option value={String(opt)}>{String(opt)}</option>
								{/each}
							</select>
							<button
								class={button({ variant: 'ghost', size: 'sm' })}
								type="button"
								onclick={() => removeEnumArrayItem(key, idx)}
							>
								−
							</button>
						</div>
					{/each}
					<div class={css({ padding: '2' })}>
						<button
							class={button({ variant: 'ghost', size: 'sm' })}
							type="button"
							onclick={() => addEnumArrayItem(key, String(opts[0] ?? ''))}
						>
							+ Add item
						</button>
					</div>
				</div>
			{:else if etype === 'array' && prop.items?.type === 'array'}
				<div
					class={css({
						borderWidth: '1',
						borderColor: err ? 'border.error' : 'border.primary',
						borderRadius: 'sm',
						overflow: 'hidden'
					})}
				>
					{#each getNestedArrays(key) as subraw, idx (idx)}
						<div
							class={css({
								display: 'flex',
								gap: '1',
								padding: '2',
								alignItems: 'center',
								borderBottomWidth: '1'
							})}
						>
							<span class={css({ fontSize: 'xs', color: 'fg.muted', flexShrink: '0' })}
								>[{idx}]</span
							>
							<input
								class={css({
									flex: '1',
									fontSize: 'xs',
									padding: '1',
									borderWidth: '1',
									borderRadius: 'sm',
									backgroundColor: 'bg.secondary',
									color: 'fg.primary'
								})}
								type="text"
								value={subraw}
								oninput={(e) => setNestedArrayItem(key, idx, (e.target as HTMLInputElement).value)}
								placeholder="Comma-separated values"
							/>
							<button
								class={button({ variant: 'ghost', size: 'sm' })}
								type="button"
								onclick={() => removeNestedArrayItem(key, idx)}
							>
								−
							</button>
						</div>
					{/each}
					<div class={css({ padding: '2' })}>
						<button
							class={button({ variant: 'ghost', size: 'sm' })}
							type="button"
							onclick={() => addNestedArrayItem(key)}
						>
							+ Add sub-array
						</button>
					</div>
				</div>
			{:else if etype === 'array'}
				<input
					id={`tool-arg-${pathPrefix}-${key}`}
					class={input()}
					type="text"
					value={getArray(key)}
					oninput={(e) => setArray(key, (e.target as HTMLInputElement).value)}
					placeholder="Comma-separated values"
				/>
			{:else if etype === 'object' && prop.properties}
				<div
					class={css({
						paddingLeft: '3',
						borderLeftWidth: '2',
						borderColor: err ? 'border.error' : 'border.subtle',
						display: 'flex',
						flexDirection: 'column',
						gap: '1.5'
					})}
				>
					<ToolArgsForm
						schema={{
							type: 'object',
							properties: prop.properties,
							required: prop.required ?? [],
							dependentRequired: prop.dependentRequired
						}}
						value={getNestedObject(key)}
						{errors}
						pathPrefix={pathPrefix ? `${pathPrefix}.${key}` : key}
						onchange={(updated) => update({ ...value, [key]: updated })}
						{onunsupported}
					/>
					{#if prop.additionalProperties !== false}
						{@const addRows = getAdditionalRows(key)}
						{@const addSchema =
							typeof prop.additionalProperties === 'object' ? prop.additionalProperties : null}
						<div class={css({ marginTop: '1' })}>
							<span class={css({ fontSize: 'xs', color: 'fg.muted', fontWeight: 'medium' })}>
								Additional fields
							</span>
							{#each addRows as [rk, rv], idx (idx)}
								<div
									class={css({
										display: 'flex',
										gap: '1',
										marginTop: '1',
										alignItems: 'center'
									})}
								>
									<input
										class={css({
											flex: '1',
											fontSize: 'xs',
											padding: '1',
											borderWidth: '1',
											borderRadius: 'sm',
											backgroundColor: 'bg.secondary',
											color: 'fg.primary'
										})}
										type="text"
										value={rk}
										oninput={(e) =>
											setAdditionalRow(key, idx, (e.target as HTMLInputElement).value, rv)}
										placeholder="key"
									/>
									<span class={css({ color: 'fg.muted', fontSize: 'xs' })}>:</span>
									{#if addSchema?.enum}
										<select
											class={css({ flex: '1', fontSize: 'xs' })}
											value={String(rv ?? '')}
											onchange={(e) =>
												setAdditionalRow(key, idx, rk, (e.target as HTMLSelectElement).value)}
										>
											{#each addSchema.enum as opt (opt)}
												<option value={String(opt)}>{String(opt)}</option>
											{/each}
										</select>
									{:else}
										<input
											class={css({
												flex: '1',
												fontSize: 'xs',
												padding: '1',
												borderWidth: '1',
												borderRadius: 'sm',
												backgroundColor: 'bg.secondary',
												color: 'fg.primary'
											})}
											type="text"
											value={String(rv ?? '')}
											oninput={(e) =>
												setAdditionalRow(key, idx, rk, (e.target as HTMLInputElement).value)}
											placeholder="value"
										/>
									{/if}
									<button
										class={button({ variant: 'ghost', size: 'sm' })}
										type="button"
										onclick={() => removeAdditionalRow(key, idx)}
									>
										−
									</button>
								</div>
							{/each}
							<button
								class={button({ variant: 'ghost', size: 'sm' })}
								type="button"
								onclick={() => addAdditionalRow(key)}
							>
								+ Add field
							</button>
						</div>
					{:else}
						<span class={css({ fontSize: 'xs', color: 'fg.muted', fontStyle: 'italic' })}>
							No additional fields allowed
						</span>
					{/if}
				</div>
			{:else if etype === 'object' && prop.additionalProperties !== false}
				{@const addRows = getAdditionalRows(key)}
				{@const addSchema =
					typeof prop.additionalProperties === 'object' ? prop.additionalProperties : null}
				<div
					class={css({
						borderWidth: '1',
						borderColor: err ? 'border.error' : 'border.primary',
						borderRadius: 'sm',
						overflow: 'hidden'
					})}
				>
					{#each addRows as [rk, rv], idx (idx)}
						<div
							class={css({
								display: 'flex',
								gap: '1',
								padding: '2',
								alignItems: 'center',
								borderBottomWidth: '1'
							})}
						>
							<input
								class={css({
									flex: '1',
									fontSize: 'xs',
									padding: '1',
									borderWidth: '1',
									borderRadius: 'sm',
									backgroundColor: 'bg.secondary',
									color: 'fg.primary'
								})}
								type="text"
								value={rk}
								oninput={(e) =>
									setAdditionalRow(key, idx, (e.target as HTMLInputElement).value, rv)}
								placeholder="key"
							/>
							<span class={css({ color: 'fg.muted', fontSize: 'xs' })}>:</span>
							{#if addSchema?.enum}
								<select
									class={css({ flex: '1', fontSize: 'xs' })}
									value={String(rv ?? '')}
									onchange={(e) =>
										setAdditionalRow(key, idx, rk, (e.target as HTMLSelectElement).value)}
								>
									{#each addSchema.enum as opt (opt)}
										<option value={String(opt)}>{String(opt)}</option>
									{/each}
								</select>
							{:else}
								<input
									class={css({
										flex: '1',
										fontSize: 'xs',
										padding: '1',
										borderWidth: '1',
										borderRadius: 'sm',
										backgroundColor: 'bg.secondary',
										color: 'fg.primary'
									})}
									type="text"
									value={String(rv ?? '')}
									oninput={(e) =>
										setAdditionalRow(key, idx, rk, (e.target as HTMLInputElement).value)}
									placeholder="value"
								/>
							{/if}
							<button
								class={button({ variant: 'ghost', size: 'sm' })}
								type="button"
								onclick={() => removeAdditionalRow(key, idx)}
							>
								−
							</button>
						</div>
					{/each}
					<div class={css({ padding: '2' })}>
						<button
							class={button({ variant: 'ghost', size: 'sm' })}
							type="button"
							onclick={() => addAdditionalRow(key)}
						>
							+ Add field
						</button>
					</div>
				</div>
			{:else if !isSchemaSupported(rawProp)}
				<div
					class={css({
						padding: '2',
						borderWidth: '1',
						borderColor: 'border.error',
						borderRadius: 'sm',
						backgroundColor: 'bg.errorSubtle',
						fontSize: 'xs',
						color: 'fg.error'
					})}
				>
					Unsupported schema — editing not available.
				</div>
			{:else if etype === 'object'}
				<div
					class={css({
						padding: '2',
						borderWidth: '1',
						borderColor: 'border.error',
						borderRadius: 'sm',
						backgroundColor: 'bg.errorSubtle',
						fontSize: 'xs',
						color: 'fg.error'
					})}
				>
					Unsupported object — no schema properties defined.
				</div>
			{:else}
				{@const inputType = formatInputType(prop.format, etype)}
				<input
					id={`tool-arg-${pathPrefix}-${key}`}
					class={input()}
					type={inputType}
					value={getString(key)}
					oninput={(e) => setString(key, (e.target as HTMLInputElement).value, rawProp)}
					placeholder={prop.default !== undefined ? String(prop.default) : ''}
					min={prop.minimum !== undefined ? prop.minimum : undefined}
					max={prop.maximum !== undefined ? prop.maximum : undefined}
					minlength={prop.minLength !== undefined ? prop.minLength : undefined}
					maxlength={prop.maxLength !== undefined ? prop.maxLength : undefined}
					pattern={prop.pattern ?? undefined}
				/>
				{#if helper}
					<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>{helper}</span>
				{/if}
			{/if}

			{#if notWarning}
				<span class={css({ fontSize: 'xs', color: 'fg.warning' })}>
					Warning: current value matches a forbidden schema.
				</span>
			{/if}

			{#if err}
				<span class={css({ fontSize: 'xs', color: 'fg.error' })}>{err}</span>
			{/if}
		</div>
	{/each}

	{#if entries.length === 0}
		<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>No arguments</span>
	{/if}
</div>
