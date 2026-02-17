import uuid
from typing import Annotated

from fastapi import HTTPException, Path


def _parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='Invalid UUID') from exc


AnalysisId = Annotated[str, Path(description='Analysis ID', examples=['b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a'], min_length=1)]
DataSourceId = Annotated[str, Path(description='Datasource ID', examples=['b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a'], min_length=1)]
ScheduleId = Annotated[str, Path(description='Schedule ID', examples=['b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a'], min_length=1)]
EngineRunId = Annotated[str, Path(description='Engine run ID', examples=['b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a'], min_length=1)]
HealthcheckId = Annotated[str, Path(description='Healthcheck ID', examples=['b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a'], min_length=1)]
UdfId = Annotated[str, Path(description='UDF ID', examples=['b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a'], min_length=1)]
PreflightId = Annotated[str, Path(description='Preflight ID', examples=['b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a'], min_length=1)]
LockResourceId = Annotated[str, Path(description='Lock resource ID', examples=['b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a'], min_length=1)]


def parse_analysis_id(value: str) -> str:
    return _parse_uuid(value)


def parse_datasource_id(value: str) -> str:
    return _parse_uuid(value)


def parse_schedule_id(value: str) -> str:
    return _parse_uuid(value)


def parse_engine_run_id(value: str) -> str:
    return _parse_uuid(value)


def parse_healthcheck_id(value: str) -> str:
    return _parse_uuid(value)


def parse_udf_id(value: str) -> str:
    return _parse_uuid(value)


def parse_preflight_id(value: str) -> str:
    return _parse_uuid(value)


def parse_lock_resource_id(value: str) -> str:
    return _parse_uuid(value)
