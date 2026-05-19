<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import { CheckCircle, XCircle, Save, Loader2, Database, ChevronDown } from 'lucide-svelte';
	import { getSettings, updateSettings } from '$lib/api/settings';
	import type { AppSettings } from '$lib/api/settings';
	import {
		listInternalPostgresTables,
		toggleInternalPostgresTable,
		type InternalPostgresTable
	} from '$lib/api/datasource';
	import { useNamespace } from '$lib/stores/namespace.svelte';
	import { css } from '$lib/styles/panda';

	let loading = $state(true);
	let saving = $state(false);
	let feedback = $state<{ type: 'success' | 'error'; message: string } | null>(null);
	let internalTables = $state<InternalPostgresTable[]>([]);
	let internalTablesLoading = $state(true);
	let internalTablesError = $state<string | null>(null);
	let togglingKey = $state<string | null>(null);
	const collapsedSchemas = new SvelteSet<string>();
	const initializedSchemaNames = new SvelteSet<string>();

	const ns = useNamespace();
	let idb = $state(false);

	// Network: load global system settings on mount.
	$effect(() => {
		loading = true;
		feedback = null;
		let aborted = false;
		getSettings().match(
			(s) => {
				if (aborted) return;
				idb = s.public_idb_debug;
				loading = false;
			},
			() => {
				if (aborted) return;
				loading = false;
			}
		);
		return () => {
			aborted = true;
		};
	});

	// Network: internal onboard state is namespace-scoped, so reload when namespace changes.
	$effect(() => {
		const currentNamespace = ns.value;
		internalTablesLoading = true;
		internalTablesError = null;
		togglingKey = null;
		feedback = null;
		let aborted = false;
		listInternalPostgresTables().match(
			(tables) => {
				if (aborted || ns.value !== currentNamespace) return;
				internalTables = tables;
				internalTablesLoading = false;
			},
			(error) => {
				if (aborted || ns.value !== currentNamespace) return;
				internalTablesError = error.message;
				internalTablesLoading = false;
			}
		);
		return () => {
			aborted = true;
		};
	});

	function internalTableKey(table: InternalPostgresTable) {
		return `${table.schema_name}.${table.table_name}`;
	}

	function internalTableLabel(table: InternalPostgresTable) {
		return table.table_name;
	}

	function schemaGroupLabel(schemaName: string) {
		return `Database schema: ${schemaName}`;
	}

	const groupedInternalTables = $derived.by(() => {
		const groups: Array<{ schemaName: string; tables: InternalPostgresTable[] }> = [];
		for (const table of internalTables) {
			const existing = groups.find((group) => group.schemaName === table.schema_name);
			if (existing) {
				existing.tables.push(table);
				continue;
			}
			groups.push({ schemaName: table.schema_name, tables: [table] });
		}
		return groups;
	});

	$effect(() => {
		const currentSchemaNames = new Set(groupedInternalTables.map((group) => group.schemaName));
		for (const schemaName of currentSchemaNames) {
			if (initializedSchemaNames.has(schemaName)) continue;
			initializedSchemaNames.add(schemaName);
			collapsedSchemas.add(schemaName);
		}
		for (const schemaName of initializedSchemaNames) {
			if (currentSchemaNames.has(schemaName)) continue;
			initializedSchemaNames.delete(schemaName);
			collapsedSchemas.delete(schemaName);
		}
	});

	function toggleSchemaGroup(schemaName: string) {
		if (collapsedSchemas.has(schemaName)) {
			collapsedSchemas.delete(schemaName);
			return;
		}
		collapsedSchemas.add(schemaName);
	}

	async function toggleTable(table: InternalPostgresTable) {
		const key = internalTableKey(table);
		const nextEnabled = !table.is_onboarded;
		togglingKey = key;
		feedback = null;
		const result = await toggleInternalPostgresTable(
			table.schema_name,
			table.table_name,
			nextEnabled
		);
		result.match(
			(updated) => {
				internalTables = internalTables.map((item) =>
					internalTableKey(item) === key ? updated : item
				);
			},
			(error) => {
				feedback = { type: 'error', message: error.message };
			}
		);
		togglingKey = null;
	}

	async function save() {
		saving = true;
		feedback = null;
		const payload: Partial<AppSettings> = {
			public_idb_debug: idb
		};
		const result = await updateSettings(payload);
		result.match(
			() => {
				feedback = { type: 'success', message: 'System settings saved' };
			},
			(err) => {
				feedback = { type: 'error', message: err.message };
			}
		);
		saving = false;
	}

	const feedbackStyle = (type: 'success' | 'error') =>
		css({
			display: 'flex',
			alignItems: 'center',
			gap: '2',
			borderWidth: '1',
			padding: '2',
			fontSize: 'sm',
			...(type === 'success'
				? {
						borderColor: 'border.success',
						backgroundColor: 'bg.success',
						color: 'fg.success'
					}
				: { borderColor: 'border.error', backgroundColor: 'bg.error', color: 'fg.error' })
		});
</script>

{#if loading}
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			gap: '2',
			padding: '8',
			fontSize: 'sm',
			color: 'fg.muted'
		})}
	>
		<Loader2 size={14} class={css({ animation: 'spin 1s linear infinite' })} />
		Loading system settings…
	</div>
{:else}
	<div class={css({ display: 'flex', flexDirection: 'column', gap: '6' })}>
		{#if feedback}
			<div class={feedbackStyle(feedback.type)}>
				{#if feedback.type === 'success'}
					<CheckCircle size={14} />
				{:else}
					<XCircle size={14} />
				{/if}
				{feedback.message}
			</div>
		{/if}

		<div
			class={css({
				backgroundColor: 'bg.panel',
				borderWidth: '1',
				padding: '6',
				display: 'flex',
				flexDirection: 'column',
				gap: '5'
			})}
		>
			<h2
				class={css({
					fontSize: 'md',
					fontWeight: 'semibold',
					color: 'fg.primary',
					display: 'flex',
					alignItems: 'center',
					gap: '2'
				})}
			>
				<Database size={16} />
				Debug
			</h2>

			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'space-between'
				})}
			>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '0.5' })}>
					<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>IndexedDB Inspector</span>
					<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
						Show cache debug button in header
					</span>
				</div>
				<button
					class={css({
						position: 'relative',
						height: 'iconMd',
						width: 'rowXl',
						cursor: 'pointer',
						border: 'none',
						transition: 'background-color 150ms',
						backgroundColor: idb ? 'accent.primary' : 'bg.tertiary'
					})}
					onclick={() => (idb = !idb)}
					type="button"
					role="switch"
					aria-checked={idb}
					aria-label="Toggle IndexedDB inspector"
				>
					<span
						class={css({
							position: 'absolute',
							top: '0.5',
							left: '0.5',
							height: 'iconSm',
							width: 'iconSm',
							backgroundColor: 'accent.primary',
							transition: 'transform 150ms',
							...(idb ? { transform: 'translateX(1rem)' } : {})
						})}
					></span>
				</button>
			</div>
		</div>

		<div
			class={css({
				backgroundColor: 'bg.panel',
				borderWidth: '1',
				padding: '6',
				display: 'flex',
				flexDirection: 'column',
				gap: '4'
			})}
		>
			<h2
				class={css({
					fontSize: 'md',
					fontWeight: 'semibold',
					color: 'fg.primary',
					display: 'flex',
					alignItems: 'center',
					gap: '2'
				})}
			>
				<Database size={16} />
				What you can export
			</h2>

			<p class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
				Choose which internal PostgreSQL tables should be onboarded as datasources.
			</p>

			{#if internalTablesLoading}
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2', color: 'fg.muted' })}>
					<Loader2 size={14} class={css({ animation: 'spin 1s linear infinite' })} />
					Loading internal tables…
				</div>
			{:else if internalTablesError}
				<div class={feedbackStyle('error')}>
					<XCircle size={14} />
					{internalTablesError}
				</div>
			{:else if internalTables.length === 0}
				<p class={css({ fontSize: 'sm', color: 'fg.muted' })}>No internal tables found.</p>
			{:else}
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
					{#each groupedInternalTables as group (group.schemaName)}
						{@const groupCollapsed = collapsedSchemas.has(group.schemaName)}
						<div class={css({ borderWidth: '1', backgroundColor: 'bg.secondary', padding: '3' })}>
							<button
								class={css({
									display: 'flex',
									width: '100%',
									alignItems: 'center',
									justifyContent: 'space-between',
									gap: '3',
									cursor: 'pointer',
									border: 'none',
									backgroundColor: 'transparent',
									padding: '0',
									textAlign: 'left',
									transition: 'color 150ms',
									_hover: { color: 'fg.primary' }
								})}
								type="button"
								aria-expanded={!groupCollapsed}
								aria-controls={`internal-postgres-schema-${group.schemaName}`}
								data-testid="system-export-group-toggle"
								data-schema-name={group.schemaName}
								onclick={() => toggleSchemaGroup(group.schemaName)}
							>
								<span
									class={css({ fontSize: 'sm', fontWeight: 'semibold', textTransform: 'none' })}
								>
									{schemaGroupLabel(group.schemaName)}
								</span>
								<ChevronDown
									size={16}
									class={css(
										{ color: 'fg.muted', transition: 'transform 150ms' },
										groupCollapsed && { transform: 'rotate(-90deg)' }
									)}
								/>
							</button>

							<div
								id={`internal-postgres-schema-${group.schemaName}`}
								hidden={groupCollapsed}
								aria-hidden={groupCollapsed}
								class={css(
									{ display: 'flex', flexDirection: 'column', gap: '2', paddingTop: '3' },
									groupCollapsed && { display: 'none' }
								)}
							>
								{#each group.tables as table (internalTableKey(table))}
									{@const key = internalTableKey(table)}
									<div
										class={css({
											display: 'flex',
											alignItems: 'center',
											justifyContent: 'space-between',
											gap: '4',
											borderWidth: '1',
											backgroundColor: 'bg.panel',
											padding: '3'
										})}
									>
										<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>
											{internalTableLabel(table)}
										</span>
										<div
											class={css({
												display: 'flex',
												alignItems: 'center',
												gap: '3',
												flexShrink: '0'
											})}
										>
											<span class={css({ fontSize: 'xs', color: 'fg.tertiary', minWidth: '16' })}>
												{#if togglingKey === key}
													Toggling…
												{:else if table.is_onboarded}
													On
												{:else}
													Off
												{/if}
											</span>
											<button
												class={css({
													position: 'relative',
													height: 'iconMd',
													width: 'rowXl',
													cursor: togglingKey !== null ? 'default' : 'pointer',
													border: 'none',
													transition: 'background-color 150ms',
													backgroundColor:
														table.is_onboarded || togglingKey === key
															? 'accent.primary'
															: 'bg.tertiary',
													_disabled: { opacity: 0.7 }
												})}
												type="button"
												role="switch"
												aria-checked={table.is_onboarded || togglingKey === key}
												aria-label={`Onboard table ${key}`}
												data-testid="internal-table-onboard-switch"
												data-internal-table-key={key}
												disabled={togglingKey !== null}
												onclick={() => toggleTable(table)}
											>
												<span
													class={css({
														position: 'absolute',
														top: '0.5',
														left: '0.5',
														height: 'iconSm',
														width: 'iconSm',
														backgroundColor: 'accent.primary',
														transition: 'transform 150ms',
														...(table.is_onboarded || togglingKey === key
															? { transform: 'translateX(1rem)' }
															: {})
													})}
												>
													{#if togglingKey === key}
														<Loader2
															size={12}
															class={css({ animation: 'spin 1s linear infinite' })}
														/>
													{:else if table.is_onboarded}
														<CheckCircle size={12} />
													{/if}
												</span>
											</button>
										</div>
									</div>
								{/each}
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<div class={css({ display: 'flex', justifyContent: 'flex-end' })}>
			<button
				class={css({
					display: 'flex',
					cursor: 'pointer',
					alignItems: 'center',
					gap: '1.5',
					border: 'none',
					paddingX: '4',
					paddingY: '2',
					fontSize: 'sm',
					fontWeight: 'medium',
					backgroundColor: 'accent.primary',
					color: 'fg.inverse',
					_hover: { opacity: 0.9 },
					_disabled: { cursor: 'not-allowed', opacity: 0.5 }
				})}
				onclick={save}
				disabled={saving}
				type="button"
			>
				{#if saving}
					<Loader2 size={14} class={css({ animation: 'spin 1s linear infinite' })} />
				{:else}
					<Save size={14} />
				{/if}
				Save
			</button>
		</div>
	</div>
{/if}
