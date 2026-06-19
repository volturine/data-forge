from __future__ import annotations

from typing import ClassVar, Self

from dataforge_protocol import enums_pb2
from runtime.domain.protocol_enums import ProtocolEnumValue, protocol_token


class AnalysisStatus(ProtocolEnumValue):
    DRAFT: ClassVar[Self]
    RUNNING: ClassVar[Self]
    COMPLETED: ClassVar[Self]
    ERROR: ClassVar[Self]


AnalysisStatus.DRAFT = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_DRAFT, protocol_token("AnalysisStatus", enums_pb2.ANALYSIS_STATUS_DRAFT))
AnalysisStatus.RUNNING = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_RUNNING, protocol_token("AnalysisStatus", enums_pb2.ANALYSIS_STATUS_RUNNING))
AnalysisStatus.COMPLETED = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_COMPLETED, protocol_token("AnalysisStatus", enums_pb2.ANALYSIS_STATUS_COMPLETED))
AnalysisStatus.ERROR = AnalysisStatus(enums_pb2.ANALYSIS_STATUS_ERROR, protocol_token("AnalysisStatus", enums_pb2.ANALYSIS_STATUS_ERROR))
