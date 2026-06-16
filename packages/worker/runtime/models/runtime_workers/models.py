from runtime.models.enums import DataForgeStrEnum


class RuntimeWorkerKind(DataForgeStrEnum):
    API = "api"
    BUILD_MANAGER = "build_manager"
    BUILD_WORKER = "build_worker"
    SCHEDULER = "scheduler"
