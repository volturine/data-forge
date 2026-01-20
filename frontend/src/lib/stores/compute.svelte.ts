import type { ComputeJob } from '$lib/types/compute';
import {
	executeAnalysis as executeAnalysisApi,
	getComputeStatus,
	cancelJob as cancelJobApi
} from '$lib/api/compute';

class ComputeStore {
	jobs = $state(new Map<string, ComputeJob>());
	polling = $state(new Map<string, number>());

	async executeAnalysis(id: string): Promise<ComputeJob> {
		return executeAnalysisApi(id).match(
			(job) => {
				this.jobs.set(job.id, job);
				this.jobs = new Map(this.jobs);

				if (job.status === 'pending' || job.status === 'running') {
					this.startPolling(job.id);
				}

				return job;
			},
			(_error) => {
				const failedJob: ComputeJob = {
					id,
					status: 'failed',
					progress: 0,
					error: 'Failed to execute analysis',
					created_at: new Date().toISOString(),
					updated_at: new Date().toISOString()
				};
				this.jobs.set(id, failedJob);
				this.jobs = new Map(this.jobs);
				return failedJob;
			}
		);
	}

	async pollJobStatus(jobId: string): Promise<ComputeJob> {
		return getComputeStatus(jobId).match(
			(job) => {
				this.jobs.set(jobId, job);
				this.jobs = new Map(this.jobs);

				if (job.status === 'completed' || job.status === 'failed') {
					this.stopPolling(jobId);
				}

				return job;
			},
			(_error) => {
				const job = this.jobs.get(jobId);
				if (job) {
					const failedJob = {
						...job,
						status: 'failed' as const,
						error: 'Failed to poll job status'
					};
					this.jobs.set(jobId, failedJob);
					this.jobs = new Map(this.jobs);
					this.stopPolling(jobId);
					return failedJob;
				}
				this.stopPolling(jobId);
				throw new Error('Job not found');
			}
		);
	}

	async cancelJob(jobId: string): Promise<void> {
		cancelJobApi(jobId).match(
			() => {
				this.stopPolling(jobId);

				const job = this.jobs.get(jobId);
				if (job) {
					this.jobs.set(jobId, { ...job, status: 'failed', error: 'Cancelled by user' });
					this.jobs = new Map(this.jobs);
				}
			},
			(_error) => {
				this.stopPolling(jobId);

				const job = this.jobs.get(jobId);
				if (job) {
					this.jobs.set(jobId, { ...job, status: 'failed', error: 'Failed to cancel job' });
					this.jobs = new Map(this.jobs);
				}
			}
		);
	}

	getJob(jobId: string): ComputeJob | undefined {
		return this.jobs.get(jobId);
	}

	private startPolling(jobId: string): void {
		if (this.polling.has(jobId)) return;

		const intervalId = window.setInterval(() => {
			this.pollJobStatus(jobId).catch(() => {
				this.stopPolling(jobId);
			});
		}, 2000);

		this.polling.set(jobId, intervalId);
		this.polling = new Map(this.polling);
	}

	private stopPolling(jobId: string): void {
		const intervalId = this.polling.get(jobId);
		if (intervalId) {
			window.clearInterval(intervalId);
			this.polling.delete(jobId);
			this.polling = new Map(this.polling);
		}
	}

	clearJob(jobId: string): void {
		this.stopPolling(jobId);
		this.jobs.delete(jobId);
		this.jobs = new Map(this.jobs);
	}

	clearAll(): void {
		for (const jobId of this.polling.keys()) {
			this.stopPolling(jobId);
		}

		this.jobs.clear();
		this.jobs = new Map();
	}
}

export const computeStore = new ComputeStore();
