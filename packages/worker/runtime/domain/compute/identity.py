from __future__ import annotations

from dataforge_protocol import compute_pb2, enums_pb2


def datasource_compute_worker_identity(datasource_id: str) -> compute_pb2.ComputeWorkerIdentity:
    return compute_pb2.ComputeWorkerIdentity(
        scope=enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
        datasource_id=datasource_id,
        resource_id=datasource_id,
    )
