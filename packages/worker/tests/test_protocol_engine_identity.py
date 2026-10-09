from __future__ import annotations

import pytest
from protovalidate import ValidationError, Validator

from dataforge_protocol import analysis_pb2, compute_pb2, enums_pb2
from runtime import compute_request_runtime, compute_service


def test_step_preview_request_uses_generated_compute_worker_identity() -> None:
    identity = compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        datasource_id="datasource-1",
        resource_id="datasource-1",
    )
    request = compute_pb2.StepPreviewCommand(engine_identity=identity)

    assert isinstance(request.engine_identity, compute_pb2.ComputeWorkerIdentity)
    assert request.engine_identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW
    assert request.engine_identity.reuse_policy == enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED
    assert request.engine_identity.datasource_id == "datasource-1"
    assert request.engine_identity.resource_id == "datasource-1"


def test_step_preview_request_rejects_invalid_compute_worker_identity_payload() -> None:
    identity = compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        datasource_id="datasource-1",
        resource_id="",
    )

    with pytest.raises(ValidationError):
        Validator().validate(identity)


def _pipeline(datasource_id: str, analysis_id: str) -> analysis_pb2.AnalysisPipelinePayload:
    pipeline = analysis_pb2.AnalysisPipelinePayload(analysis_id=analysis_id)
    tab = pipeline.tabs.add(id="tab-1")
    tab.datasource.id = datasource_id
    tab.output.result_id = "output-1"
    tab.output.filename = "output.parquet"
    tab.output.format = enums_pb2.EXPORT_FORMAT_PARQUET
    return pipeline


def _claimed_request(kind: int, command: compute_pb2.ComputeCommand) -> compute_request_runtime.ClaimedComputeRequest:
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


@pytest.mark.parametrize(
    ("kind", "field_name", "command_type"),
    [
        (enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA, "schema", compute_pb2.StepSchemaCommand),
        (enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT, "row_count", compute_pb2.StepRowCountCommand),
        (enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD, "download", compute_pb2.DownloadCommand),
        (enums_pb2.COMPUTE_REQUEST_KIND_EXPORT, "export", compute_pb2.ExportCommand),
    ],
)
def test_analysis_requests_share_analysis_compute_worker_identity(kind, field_name, command_type) -> None:
    pipeline = _pipeline("dataset-1", "analysis-1")
    request = command_type(
        analysis_id="analysis-1",
        target_step_id="source",
        analysis_pipeline=pipeline,
    )
    command = compute_pb2.ComputeCommand()
    getattr(command, field_name).CopyFrom(request)

    identity = compute_request_runtime._compute_worker_identity_for_claimed(_claimed_request(kind, command))

    assert identity == compute_service.default_stateless_compute_worker_identity(
        {
            "analysis_id": "analysis-1",
            "tabs": [{"id": "tab-1", "datasource": {"id": "dataset-1"}, "steps": []}],
        },
        "source",
    )
    assert identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE
    assert identity.analysis_id == "analysis-1"


def test_distinct_transforms_share_only_the_exact_analysis_engine() -> None:
    identities = []
    for analysis_id, target_step_id in [
        ("analysis-1", "step-a"),
        ("analysis-1", "step-b"),
        ("analysis-2", "step-a"),
    ]:
        request = compute_pb2.StepPreviewCommand(
            analysis_id=analysis_id,
            target_step_id=target_step_id,
            analysis_pipeline=_pipeline("dataset-1", analysis_id),
        )
        command = compute_pb2.ComputeCommand(preview=request)
        identities.append(compute_request_runtime._compute_worker_identity_for_claimed(_claimed_request(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, command)))

    assert identities[0] == identities[1]
    assert identities[0].resource_id == "analysis-1"
    assert identities[0] != identities[2]


@pytest.mark.parametrize(
    "identity",
    [
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            datasource_id="datasource-1",
            resource_id="other",
        ),
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE,
            analysis_id="analysis-1",
            resource_id="analysis-1",
        ),
        compute_pb2.ComputeWorkerIdentity(
            scope=enums_pb2.COMPUTE_WORKER_SCOPE_BUILD,
            reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE,
            analysis_id="analysis-1",
            build_id="build-1",
            resource_id="build-1",
        ),
    ],
    ids=["mismatched-resource-id", "invalid-reuse-policy", "multiple-scoped-ids"],
)
def test_compute_worker_identity_rejects_scope_invariant_violations(identity: compute_pb2.ComputeWorkerIdentity) -> None:
    with pytest.raises(ValidationError):
        Validator().validate(identity)
