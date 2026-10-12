<script lang="ts">
	import { LoaderCircle, Power, Search, X } from '@lucide/svelte';
	import type { SvelteSet } from 'svelte/reactivity';
	import BaseModal from '#lib/components/ui/BaseModal.svelte';
	import ConfirmDialog from '#lib/components/common/ConfirmDialog.svelte';
	import PanelHeader from '#lib/components/ui/PanelHeader.svelte';
	import { computeWorkersStore } from '#lib/stores/compute-workers.svelte.js';
	import type { ComputeWorkerStatusResponse } from '#lib/types/compute.js';
	import {
		computeWorkerActivityLabel,
		computeWorkerHasActiveJob,
		computeWorkerIdentityKey,
		computeWorkerShutdownConfirmText,
		computeWorkerShutdownHeading,
		computeWorkerShutdownMessage,
		computeWorkerStatusColor
	} from '#lib/nxt/compute-worker.js';
	import { css, iconButton, input, label } from '#lib/styles/panda.js';

	interface Props {
		onClose: () => void;
		shuttingDown: SvelteSet<string>;
	}

	type ActivityFilter = 'all' | 'busy' | 'idle';

	let { onClose, shuttingDown }: Props = $props();

	let searchQuery = $state('');
	let activityFilter = $state<ActivityFilter>('all');
	let confirmOpen = $state(false);
	let pendingComputeWorker = $state<ComputeWorkerStatusResponse | null>(null);

	function computeWorkerIsIdle(computeWorker: ComputeWorkerStatusResponse): boolean {
		return computeWorker.status === 'healthy' && !computeWorkerHasActiveJob(computeWorker);
	}

	const busyWorkerCount = $derived(
		computeWorkersStore.computeWorkers.filter(computeWorkerHasActiveJob).length
	);
	const idleWorkerCount = $derived(
		computeWorkersStore.computeWorkers.filter(computeWorkerIsIdle).length
	);
	const filteredWorkers = $derived.by((): ComputeWorkerStatusResponse[] => {
		const normalizedQuery = searchQuery.trim().toLowerCase();
		return computeWorkersStore.computeWorkers.filter((computeWorker) => {
			if (activityFilter === 'busy' && !computeWorkerHasActiveJob(computeWorker)) return false;
			if (activityFilter === 'idle' && !computeWorkerIsIdle(computeWorker)) return false;
			if (!normalizedQuery) return true;

			return [
				computeWorker.resource_id,
				computeWorker.scope,
				computeWorker.container_id,
				computeWorker.docker_host,
				computeWorker.current_job_id,
				computeWorker.current_build_id,
				computeWorker.build_id
			].some((value) => value?.toLowerCase().includes(normalizedQuery));
		});
	});
	const connectionStatusLabel = $derived(
		{
			connecting: 'Connecting to live worker updates',
			connected: 'Live worker updates connected',
			disconnected: 'Live worker updates disconnected',
			error: 'Live worker updates unavailable'
		}[computeWorkersStore.status]
	);
	const confirmHeading = $derived(
		pendingComputeWorker
			? computeWorkerShutdownHeading(pendingComputeWorker)
			: 'Shut down compute worker?'
	);
	const confirmMessage = $derived(
		pendingComputeWorker
			? computeWorkerShutdownMessage(pendingComputeWorker)
			: 'This will stop and remove the compute worker container.'
	);
	const confirmText = $derived(
		pendingComputeWorker ? computeWorkerShutdownConfirmText(pendingComputeWorker) : 'Shut down'
	);

	function requestShutdown(computeWorker: ComputeWorkerStatusResponse): void {
		pendingComputeWorker = computeWorker;
		confirmOpen = true;
	}

	function cancelConfirm(): void {
		confirmOpen = false;
		pendingComputeWorker = null;
	}

	async function confirmShutdown(): Promise<void> {
		const computeWorker = pendingComputeWorker;
		confirmOpen = false;
		pendingComputeWorker = null;
		if (!computeWorker) return;

		const key = computeWorkerIdentityKey(computeWorker);
		shuttingDown.add(key);
		try {
			await computeWorkersStore.shutdownComputeWorker(computeWorker);
		} catch (error) {
			computeWorkersStore.error =
				error instanceof Error ? error.message : 'Could not shut down compute worker.';
		} finally {
			shuttingDown.delete(key);
		}
	}

	function handleClose(): void {
		if (confirmOpen) return;
		onClose();
	}
</script>

<BaseModal
	open={true}
	size="large"
	initialFocus="#compute-workers-search"
	onClose={handleClose}
	ariaLabelledby="compute-workers-title"
>
	{#snippet content()}
		<div
			data-compute-workers-popup="true"
			class={css({
				display: 'flex',
				flexDirection: 'column',
				width: 'full',
				height: 'full',
				minHeight: '0',
				overflow: 'hidden',
				backgroundColor: 'bg.primary'
			})}
		>
			<PanelHeader>
				{#snippet title()}
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<h2
							id="compute-workers-title"
							class={css({ margin: '0', fontSize: 'md', fontWeight: 'semibold' })}
						>
							Compute workers
						</h2>
						<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.muted' })}>
							Compute workers start automatically for analyses and data sources.
						</p>
					</div>
				{/snippet}
				{#snippet actions()}
					<button
						class={iconButton({ variant: 'ghost' })}
						onclick={handleClose}
						aria-label="Close compute workers"
						type="button"
					>
						<X size={16} />
					</button>
				{/snippet}
			</PanelHeader>

			<div
				class={css({
					display: 'flex',
					flexDirection: 'column',
					gap: '5',
					borderBottomWidth: '1',
					paddingX: '6',
					paddingY: '5',
					flexShrink: '0'
				})}
			>
				<div
					class={css({
						display: 'grid',
						gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
						gap: '3'
					})}
				>
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '1',
							borderWidth: '1',
							paddingX: '4',
							paddingY: '3',
							backgroundColor: 'bg.secondary'
						})}
					>
						<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Total workers</span>
						<span class={css({ fontSize: 'xl', fontWeight: 'semibold', lineHeight: 'tight' })}>
							{computeWorkersStore.computeWorkers.length}
						</span>
					</div>
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '1',
							borderWidth: '1',
							paddingX: '4',
							paddingY: '3',
							backgroundColor: 'bg.secondary'
						})}
					>
						<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Busy workers</span>
						<span class={css({ fontSize: 'xl', fontWeight: 'semibold', lineHeight: 'tight' })}>
							{busyWorkerCount}
						</span>
					</div>
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '1',
							borderWidth: '1',
							paddingX: '4',
							paddingY: '3',
							backgroundColor: 'bg.secondary'
						})}
					>
						<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Idle workers</span>
						<span class={css({ fontSize: 'xl', fontWeight: 'semibold', lineHeight: 'tight' })}>
							{idleWorkerCount}
						</span>
					</div>
				</div>

				<div
					class={css({
						display: 'grid',
						gridTemplateColumns: 'minmax(0, 1fr) 220px',
						alignItems: 'end',
						gap: '4',
						smDown: { gridTemplateColumns: 'minmax(0, 1fr)' }
					})}
				>
					<div class={css({ position: 'relative', minWidth: '0' })}>
						<Search
							size={16}
							aria-hidden="true"
							class={css({
								position: 'absolute',
								left: '3',
								top: '50%',
								transform: 'translateY(-50%)',
								color: 'fg.muted'
							})}
						/>
						<input
							id="compute-workers-search"
							class={input({ variant: 'search' })}
							type="search"
							aria-label="Search compute workers"
							placeholder="Search resource, container, host, or job ID"
							bind:value={searchQuery}
						/>
					</div>
					<div>
						<label for="compute-workers-activity" class={label({ variant: 'compact' })}
							>Activity</label
						>
						<select
							id="compute-workers-activity"
							class={input({ variant: 'panelSelect' })}
							bind:value={activityFilter}
						>
							<option value="all">All workers</option>
							<option value="busy">Busy workers</option>
							<option value="idle">Idle workers</option>
						</select>
					</div>
				</div>
			</div>

			{#if computeWorkersStore.error}
				<div
					role="alert"
					class={css({
						marginX: '6',
						marginTop: '4',
						borderWidth: '1',
						borderColor: 'border.error',
						backgroundColor: 'bg.error',
						paddingX: '4',
						paddingY: '3',
						fontSize: 'sm',
						color: 'fg.error'
					})}
				>
					{computeWorkersStore.error}
				</div>
			{/if}

			<div
				class={css({
					display: 'flex',
					flexDirection: 'column',
					flex: '1',
					minHeight: '0',
					overflowY: 'auto',
					padding: '6'
				})}
			>
				{#if computeWorkersStore.loading && computeWorkersStore.computeWorkers.length === 0}
					<div
						class={css({
							display: 'flex',
							flex: '1',
							alignItems: 'center',
							justifyContent: 'center',
							gap: '2',
							fontSize: 'sm',
							color: 'fg.muted'
						})}
					>
						<LoaderCircle size={16} class={css({ animation: 'spin 1s linear infinite' })} />
						Loading compute workers...
					</div>
				{:else if computeWorkersStore.computeWorkers.length === 0}
					<div
						class={css({
							display: 'flex',
							flex: '1',
							alignItems: 'center',
							justifyContent: 'center',
							fontSize: 'sm',
							color: 'fg.muted'
						})}
					>
						No compute workers running
					</div>
				{:else if filteredWorkers.length === 0}
					<div
						class={css({
							display: 'flex',
							flex: '1',
							alignItems: 'center',
							justifyContent: 'center',
							fontSize: 'sm',
							color: 'fg.muted'
						})}
					>
						No compute workers match your filters
					</div>
				{:else}
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
						{#each filteredWorkers as computeWorker (computeWorkerIdentityKey(computeWorker))}
							{@const busy = computeWorkerHasActiveJob(computeWorker)}
							{@const workerKey = computeWorkerIdentityKey(computeWorker)}
							{@const jobId = computeWorker.current_job_id}
							{@const buildId = computeWorker.current_build_id ?? computeWorker.build_id}
							<div
								data-compute-worker-row={workerKey}
								data-compute-worker-busy={busy ? 'true' : 'false'}
								class={css({
									display: 'flex',
									flexDirection: 'column',
									gap: '4',
									borderWidth: '1',
									padding: '5',
									backgroundColor: 'bg.primary'
								})}
							>
								<div
									class={css({
										display: 'flex',
										alignItems: 'flex-start',
										justifyContent: 'space-between',
										gap: '4'
									})}
								>
									<div
										class={css({
											display: 'flex',
											flexDirection: 'column',
											gap: '2',
											minWidth: '0'
										})}
									>
										<div
											class={css({
												display: 'flex',
												alignItems: 'center',
												flexWrap: 'wrap',
												gap: '3'
											})}
										>
											<span
												class={css({ fontSize: 'xs', fontWeight: 'semibold', color: 'fg.muted' })}
											>
												Resource ID
											</span>
											<span
												class={css({
													fontSize: 'sm',
													fontWeight: 'medium',
													fontFamily: 'mono',
													wordBreak: 'break-all'
												})}
												title={computeWorker.resource_id}
											>
												{computeWorker.resource_id}
											</span>
										</div>
										<span
											class={css({
												display: 'inline-flex',
												alignItems: 'center',
												alignSelf: 'flex-start',
												borderWidth: '1',
												borderColor: 'border.primary',
												paddingX: '2',
												paddingY: '1',
												fontSize: 'xs',
												fontWeight: 'medium',
												color: busy ? 'fg.warning' : computeWorkerStatusColor(computeWorker.status)
											})}
											data-compute-worker-activity={busy
												? 'busy'
												: computeWorker.status === 'healthy'
													? 'idle'
													: 'terminated'}
										>
											{computeWorkerActivityLabel(computeWorker)}
										</span>
									</div>
									<button
										data-compute-worker-shutdown={workerKey}
										class={css({
											display: 'flex',
											cursor: 'pointer',
											alignItems: 'center',
											justifyContent: 'center',
											borderWidth: '1',
											backgroundColor: 'transparent',
											padding: '2',
											color: 'fg.tertiary',
											transition: 'color 150ms',
											_hover: { color: 'fg.error' },
											_disabled: { cursor: 'not-allowed', opacity: 0.5 }
										})}
										onclick={() => requestShutdown(computeWorker)}
										disabled={shuttingDown.has(workerKey)}
										type="button"
										title={busy
											? 'Cancel job and shut down compute worker'
											: 'Shut down idle compute worker'}
										aria-label={`${busy ? 'Cancel job and shut down' : 'Shut down idle'} compute worker ${computeWorker.resource_id}`}
									>
										{#if shuttingDown.has(workerKey)}
											<LoaderCircle
												size={16}
												class={css({ animation: 'spin 1s linear infinite' })}
											/>
										{:else}
											<Power size={16} />
										{/if}
									</button>
								</div>

								<div
									class={css({
										display: 'grid',
										gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
										gap: '4',
										smDown: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }
									})}
								>
									{#each [{ label: 'Scope', value: computeWorker.scope }, { label: 'Container', value: computeWorker.container_id }, { label: 'Docker host', value: computeWorker.docker_host }, { label: 'Current job', value: jobId }, { label: 'Current build', value: buildId }] as detail (detail.label)}
										{#if detail.value}
											<div
												class={css({
													display: 'flex',
													flexDirection: 'column',
													gap: '1',
													minWidth: '0'
												})}
											>
												<span class={css({ fontSize: 'xs', color: 'fg.muted' })}
													>{detail.label}</span
												>
												<span
													class={css({
														fontSize: 'sm',
														fontFamily: 'mono',
														wordBreak: 'break-all'
													})}
												>
													{detail.value}
												</span>
											</div>
										{/if}
									{/each}
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<footer
				class={css({
					borderTopWidth: '1',
					paddingX: '6',
					paddingY: '3',
					fontSize: 'xs',
					color: 'fg.muted',
					flexShrink: '0'
				})}
				aria-live="polite"
			>
				{connectionStatusLabel}
			</footer>
		</div>
	{/snippet}
</BaseModal>

<ConfirmDialog
	show={confirmOpen}
	heading={confirmHeading}
	message={confirmMessage}
	{confirmText}
	cancelText="Keep running"
	onConfirm={confirmShutdown}
	onCancel={cancelConfirm}
/>
