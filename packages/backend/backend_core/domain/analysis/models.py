from __future__ import annotations

from typing import ClassVar, Self

from backend_core.domain.api_enums import ApiEnumValue, api_token
from dataforge_protocol import enums_pb2


class AnalysisStatus(ApiEnumValue):
    DRAFT: ClassVar[Self]
    RUNNING: ClassVar[Self]
    COMPLETED: ClassVar[Self]
    ERROR: ClassVar[Self]


AnalysisStatus.DRAFT = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_DRAFT, api_token('AnalysisStatus', enums_pb2.ANALYSIS_STATUS_DRAFT))
AnalysisStatus.RUNNING = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_RUNNING, api_token('AnalysisStatus', enums_pb2.ANALYSIS_STATUS_RUNNING))
AnalysisStatus.COMPLETED = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_COMPLETED, api_token('AnalysisStatus', enums_pb2.ANALYSIS_STATUS_COMPLETED))
AnalysisStatus.ERROR = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_ERROR, api_token('AnalysisStatus', enums_pb2.ANALYSIS_STATUS_ERROR))
