import uuid

from persistence.engine_runs.models import EngineRun
from sqlmodel import select

from runtime import compute_service
from runtime.compute_manager import ProcessManager


def _pipeline(datasource_id: str, analysis_id: str) -> dict[str, object]:
    return {
        "analysis_id": analysis_id,
        "tabs": [
            {
                "id": "tab1",
                "datasource": {
                    "id": datasource_id,
                    "analysis_tab_id": None,
                    "config": {"branch": "master"},
                },
                "output": {
                    "result_id": "out-1",
                    "format": "parquet",
                    "filename": "preview_out",
                },
                "steps": [],
            }
        ],
    }


def _preview_request(analysis_id: str, pipeline: dict[str, object]) -> dict[str, object]:
    return {
        "analysis_id": analysis_id,
        "analysis_pipeline": pipeline,
        "target_step_id": "source",
    }


def test_preview_step_persists_engine_run_by_default(test_db_session, sample_datasource, monkeypatch) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", True)
    analysis_id = f"preview-log-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource.id, analysis_id)
    manager = ProcessManager()
    try:
        result = compute_service.preview_step(
            session=test_db_session,
            manager=manager,
            target_step_id="source",
            analysis_pipeline=pipeline,
            row_limit=100,
            page=1,
            analysis_id=analysis_id,
            request_json=_preview_request(analysis_id, pipeline),
        )
    finally:
        if manager.get_engine(analysis_id):
            manager.shutdown_engine(analysis_id)

    runs = list(
        test_db_session.execute(
            select(EngineRun).where(EngineRun.datasource_id == sample_datasource.id)  # type: ignore[arg-type]
        )
        .scalars()
        .all()
    )

    assert result.total_rows == 5
    assert len(runs) == 1
    assert runs[0].kind == "preview"
    assert runs[0].status == "success"


def test_preview_step_skips_engine_run_persistence_when_disabled(test_db_session, sample_datasource, monkeypatch) -> None:
    monkeypatch.setattr(compute_service.settings, "persist_preview_runs", False)
    analysis_id = f"preview-no-log-{uuid.uuid4()}"
    pipeline = _pipeline(sample_datasource.id, analysis_id)
    manager = ProcessManager()
    try:
        result = compute_service.preview_step(
            session=test_db_session,
            manager=manager,
            target_step_id="source",
            analysis_pipeline=pipeline,
            row_limit=100,
            page=1,
            analysis_id=analysis_id,
            request_json=_preview_request(analysis_id, pipeline),
        )
    finally:
        if manager.get_engine(analysis_id):
            manager.shutdown_engine(analysis_id)

    runs = list(
        test_db_session.execute(
            select(EngineRun).where(EngineRun.datasource_id == sample_datasource.id)  # type: ignore[arg-type]
        )
        .scalars()
        .all()
    )

    assert result.total_rows == 5
    assert runs == []
