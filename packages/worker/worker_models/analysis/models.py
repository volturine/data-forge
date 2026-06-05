from worker_models.enums import DataForgeStrEnum


class AnalysisStatus(DataForgeStrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
