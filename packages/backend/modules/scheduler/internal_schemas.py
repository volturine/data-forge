from __future__ import annotations

from pydantic import BaseModel, Field


class SchedulerRegisterRequest(BaseModel):
    worker_id: str = Field(min_length=1)
    hostname: str = Field(min_length=1)
    pid: int = Field(ge=1)
    capacity: int = Field(ge=1)


class SchedulerWorkerRequest(BaseModel):
    worker_id: str = Field(min_length=1)


class SchedulerEnqueuedRun(BaseModel):
    namespace: str
    schedule_id: str
    datasource_id: str
    build_id: str


class SchedulerRunFailure(BaseModel):
    namespace: str
    schedule_id: str
    datasource_id: str
    error: str


class SchedulerRunDueResponse(BaseModel):
    handled: bool
    enqueued: list[SchedulerEnqueuedRun]
    failures: list[SchedulerRunFailure]


class SchedulerWorkerResponse(BaseModel):
    worker_id: str
