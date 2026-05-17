import uuid
from typing import Annotated

from core.exceptions import InvalidIdError
from fastapi import Path


def _parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError) as exc:
        raise InvalidIdError(message=f"Invalid UUID: {value}", details={"value": value}) from exc


AnalysisId = Annotated[
    str,
    Path(
        description="Analysis ID",
        examples=["b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a"],
        min_length=1,
    ),
]
DataSourceId = Annotated[
    str,
    Path(
        description="Datasource ID",
        examples=["b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a", "ds-lineage-output"],
        min_length=1,
    ),
]
ScheduleId = Annotated[
    str,
    Path(
        description="Schedule ID",
        examples=["b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a"],
        min_length=1,
    ),
]
EngineRunId = Annotated[
    str,
    Path(
        description="Engine run ID",
        examples=["b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a"],
        min_length=1,
    ),
]
HealthcheckId = Annotated[
    str,
    Path(
        description="Healthcheck ID",
        examples=["b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a"],
        min_length=1,
    ),
]
UdfId = Annotated[
    str,
    Path(
        description="UDF ID",
        examples=["b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a"],
        min_length=1,
    ),
]
PreflightId = Annotated[
    str,
    Path(
        description="Preflight ID",
        examples=["b3b1a08a-6a30-4f06-8c8a-9c1f1c8a4c2a"],
        min_length=1,
    ),
]


parse_analysis_id = _parse_uuid


def parse_datasource_id(value: str) -> str:
    """Datasource IDs may be UUIDs or slug strings — accept both."""
    return value.strip()


parse_schedule_id = _parse_uuid
parse_engine_run_id = _parse_uuid
parse_healthcheck_id = _parse_uuid
parse_udf_id = _parse_uuid
parse_preflight_id = _parse_uuid
