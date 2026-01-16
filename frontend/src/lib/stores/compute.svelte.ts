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
		const job = await executeAnalysisApi(id);
		this.jobs.set(job.id, job);
		this.jobs = new Map(this.jobs);

		// Start polling if job is pending or running
		if (job.status === 'pending' || job.status === 'running') {
			this.startPolling(job.id);
		}

		return job;
	}

	async pollJobStatus(jobId: string): Promise<ComputeJob> {
		const job = await getComputeStatus(jobId);
		this.jobs.set(jobId, job);
		this.jobs = new Map(this.jobs);

		// Stop polling if job is completed or failed
		if (job.status === 'completed' || job.status === 'failed') {
			this.stopPolling(jobId);
		}

		return job;
	}

	async cancelJob(jobId: string): Promise<void> {
		await cancelJobApi(jobId);
		this.stopPolling(jobId);

		// Update job status
		const job = this.jobs.get(jobId);
		if (job) {
			this.jobs.set(jobId, { ...job, status: 'failed', error: 'Cancelled by user' });
			this.jobs = new Map(this.jobs);
		}
	}

	getJob(jobId: string): ComputeJob | undefined {
		return this.jobs.get(jobId);
	}

	private startPolling(jobId: string): void {
		// Don't start if already polling
		if (this.polling.has(jobId)) return;

		const intervalId = window.setInterval(() => {
			this.pollJobStatus(jobId).catch(() => {
				this.stopPolling(jobId);
			});
		}, 2000); // Poll every 2 seconds

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
		// Stop all polling
		for (const jobId of this.polling.keys()) {
			this.stopPolling(jobId);
		}

		// Clear all jobs
		this.jobs.clear();
		this.jobs = new Map();
	}
}

export const computeStore = new ComputeStore();
