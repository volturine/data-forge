from backend_core.domain.enums import DataForgeStrEnum


class AnalysisStatus(DataForgeStrEnum):
    DRAFT = 'draft'
    RUNNING = 'running'
    COMPLETED = 'completed'
    ERROR = 'error'
