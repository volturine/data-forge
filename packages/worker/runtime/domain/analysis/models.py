from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.domain_enums import DomainEnumValue, domain_token


class AnalysisStatus(DomainEnumValue):
    DRAFT: ClassVar[Self]
    RUNNING: ClassVar[Self]
    COMPLETED: ClassVar[Self]
    ERROR: ClassVar[Self]


AnalysisStatus.DRAFT = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_DRAFT, domain_token("AnalysisStatus", enums_pb2.ANALYSIS_STATUS_DRAFT))
AnalysisStatus.RUNNING = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_RUNNING, domain_token("AnalysisStatus", enums_pb2.ANALYSIS_STATUS_RUNNING))
AnalysisStatus.COMPLETED = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_COMPLETED, domain_token("AnalysisStatus", enums_pb2.ANALYSIS_STATUS_COMPLETED))
AnalysisStatus.ERROR = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_ERROR, domain_token("AnalysisStatus", enums_pb2.ANALYSIS_STATUS_ERROR))
