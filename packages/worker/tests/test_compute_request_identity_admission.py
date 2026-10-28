from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from dataforge_protocol import analysis_pb2, compute_pb2, enums_pb2
from runtime import compute_request_runtime, compute_service


def _pipeline(analysis_id: str = "analysis-1") -> analysis_pb2.AnalysisPipelinePayload:
    pipeline = analysis_pb2.AnalysisPipelinePayload(analysis_id=analysis_id)
    tab = pipeline.tabs.add(id="tab-1")
    tab.datasource.id = "datasource-1"
    tab.output.result_id = "output-1"
    tab.output.filename = "output.parquet"
    tab.output.format = enums_pb2.EXPORT_FORMAT_PARQUET
    return pipeline


def _claimed(kind: int, command: compute_pb2.ComputeCommand) -> compute_request_runtime.ClaimedComputeRequest:
    return compute_request_runtime.ClaimedComputeRequest(
        id="request-1",
        namespace="default",
        kind=kind,
        command_envelope=compute_pb2.ComputeCommandEnvelope(command=command),
        worker_id="worker-1",
        claim_token="claim-1",
        lease_generation=1,
        lease_ttl_seconds=300,
    )


def test_preview_identity_preserves_explicit_identity_before_pipeline_fallback() -> None:
    explicit = compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        datasource_id="datasource-1",
        resource_id="datasource-1",
    )
    preview = compute_pb2.StepPreviewCommand(
        target_step_id="source",
        analysis_pipeline=_pipeline(),
        engine_identity=explicit,
    )

    identity = compute_request_runtime._compute_worker_identity_for_claimed(
        _claimed(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, compute_pb2.ComputeCommand(preview=preview))
    )

    assert identity == explicit


@pytest.mark.asyncio
async def test_pipeline_only_download_admission_cancels_its_exact_job_on_lease_loss(monkeypatch) -> None:
    admission_identities: list[compute_pb2.ComputeWorkerIdentity] = []
    job_slot_identities: list[compute_pb2.ComputeWorkerIdentity] = []
    cancellations: list[tuple[compute_pb2.ComputeWorkerIdentity, str]] = []
    execution_started = asyncio.Event()
    lease_lost = asyncio.Event()
    execution_released = asyncio.Event()

    class Manager:
        async def await_engine_request_admission(self, identity, *, namespace: str, priority: int) -> bool:
            assert namespace == "default"
            admission_identities.append(identity)
            return False

        async def await_engine_job_slot(self, identity, *, namespace: str) -> None:
            assert namespace == "default"
            job_slot_identities.append(identity)

        def release_engine_job_slot(self, identity, *, namespace: str) -> None:
            assert namespace == "default"
            assert identity == job_slot_identities[0]

        def release_engine_request(self, identity, *, namespace: str) -> None:
            assert namespace == "default"
            assert identity == admission_identities[0]

        def release_spawn_admission(self, identity, *, namespace: str, owned: bool) -> None:
            assert namespace == "default"
            assert owned is False

        def cancel_engine_job(self, identity, *, namespace: str, job_id: str) -> bool:
            assert namespace == "default"
            cancellations.append((identity, job_id))
            execution_released.set()
            return True

        def shutdown_compute_worker_after_request_lease_loss(self, identity, *, namespace: str) -> bool:
            assert namespace == "default"
            return False

    async def renew_lease(_claimed, *, stop_event: asyncio.Event, lease_confirmed: asyncio.Event) -> None:
        lease_confirmed.set()
        await lease_lost.wait()
        raise compute_request_runtime.ComputeRequestLeaseLost("request lease expired")

    async def run_compute_in_thread(function, *args, **kwargs) -> None:
        del function, args, kwargs
        execution_started.set()
        await execution_released.wait()

    async def run_control_in_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(compute_request_runtime, "_renew_compute_lease", renew_lease)
    monkeypatch.setattr(compute_request_runtime, "run_compute_in_thread", run_compute_in_thread)
    monkeypatch.setattr(compute_request_runtime, "run_control_in_thread", run_control_in_thread)
    monkeypatch.setattr(compute_request_runtime, "run_shutdown_in_thread", run_control_in_thread)

    download = compute_pb2.DownloadCommand(target_step_id="source", analysis_pipeline=_pipeline())
    claimed = _claimed(
        enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD,
        compute_pb2.ComputeCommand(download=download),
    )
    expected_identity = compute_service.default_stateless_compute_worker_identity(download.analysis_pipeline.analysis_id)

    task = asyncio.create_task(compute_request_runtime._execute_request(claimed, cast(Any, Manager())))
    await asyncio.wait_for(execution_started.wait(), timeout=1)
    lease_lost.set()
    with pytest.raises(compute_request_runtime.ComputeRequestLeaseLost, match="request lease expired"):
        await asyncio.wait_for(task, timeout=1)

    assert admission_identities == [expected_identity]
    assert job_slot_identities == [expected_identity]
    assert cancellations == [(expected_identity, claimed.id)]
