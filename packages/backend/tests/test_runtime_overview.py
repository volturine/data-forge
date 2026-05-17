from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.build_jobs.models import BuildJobStatus
from contracts.compute.base import EngineStatusInfo
from contracts.runtime_workers.models import RuntimeWorkerKind
from core import (
    build_jobs_service as build_job_service,
)
from core import (
    engine_instances_service as engine_instance_service,
)
from core import (
    runtime_workers_service as runtime_worker_service,
)
from core.database import run_db, run_settings_db
from core.namespace import namespace_paths


def test_runtime_overview_reports_runtime_state(client, monkeypatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "distributed_runtime_enabled", True, raising=False)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://user:pass@host:5432/db",
        raising=False,
    )

    run_settings_db(
        runtime_worker_service.register_worker,
        worker_id="build-manager-1",
        kind=RuntimeWorkerKind.BUILD_MANAGER,
        hostname="manager-host",
        pid=111,
        capacity=4,
        active_jobs=0,
    )
    run_settings_db(
        runtime_worker_service.register_worker,
        worker_id="build-worker-1",
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname="worker-host",
        pid=222,
        capacity=1,
        active_jobs=1,
    )
    run_settings_db(
        engine_instance_service.upsert_engine_status,
        worker_id="build-worker-1",
        namespace="default",
        status=EngineStatusInfo(
            analysis_id="analysis-live",
            status="healthy",
            process_id=4321,
            last_activity=datetime.now(UTC).isoformat(),
            current_job_id="job-live",
            resource_config={"max_threads": 2},
            effective_resources={"max_threads": 2},
            defaults={"max_threads": 2},
        ),
    )

    queued_id = str(uuid.uuid4())
    run_db(build_job_service.create_job, build_id=queued_id, namespace="default")
    running_id = str(uuid.uuid4())
    run_db(build_job_service.create_job, build_id=running_id, namespace="default")
    run_db(_set_running_job_owner, running_id, "build-worker-1")

    orphaned_id = str(uuid.uuid4())
    run_db(build_job_service.create_job, build_id=orphaned_id, namespace="default")
    run_db(_set_running_job_owner, orphaned_id, "dead-worker")
    run_settings_db(
        runtime_worker_service.register_worker,
        worker_id="dead-worker",
        kind=RuntimeWorkerKind.BUILD_WORKER,
        hostname="worker-host",
        pid=333,
        capacity=1,
        now=datetime.now(UTC).replace(year=2024),
    )

    response = client.get("/api/v1/runtime/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "distributed"
    assert body["api"]["worker_id"].startswith("api:")
    assert body["api"]["version"] == settings.app_version
    assert any(item["id"] == "build-manager-1" and item["kind"] == "build_manager" for item in body["workers"])
    assert any(item["id"] == "build-worker-1" for item in body["workers"])
    assert any(item["analysis_id"] == "analysis-live" for item in body["engines"])
    assert body["queue"]["totals"]["queued"] == 1
    assert body["queue"]["totals"]["running"] == 1
    assert body["queue"]["totals"]["orphaned"] == 1
    assert body["queue"]["totals"]["oldest_queued_age_seconds"] is not None


def test_runtime_overview_reports_single_process_mode(client, monkeypatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "distributed_runtime_enabled", False, raising=False)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://user:pass@host:5432/db",
        raising=False,
    )
    monkeypatch.setattr(settings, "embedded_build_worker_enabled", True, raising=False)

    response = client.get("/api/v1/runtime/overview")

    assert response.status_code == 200
    assert response.json()["mode"] == "single_process"


def _set_running_job_owner(session, build_id: str, worker_id: str) -> None:
    job = build_job_service.get_job_by_build_id(session, build_id)
    assert job is not None
    job.status = BuildJobStatus.RUNNING
    job.lease_owner = worker_id
    session.add(job)
    session.commit()


def test_runtime_overview_includes_filesystem_namespaces(client, monkeypatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "embedded_build_worker_enabled", False, raising=False)
    monkeypatch.setattr(settings, "distributed_runtime_enabled", False, raising=False)
    namespace_paths("beta")

    response = client.get("/api/v1/runtime/overview")

    assert response.status_code == 200
    namespaces = [item["namespace"] for item in response.json()["queue"]["namespaces"]]
    assert namespaces == ["default", "beta"]
