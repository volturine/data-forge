from runtime.domain.enums import DataForgeStrEnum


class ComputeRequestKind(DataForgeStrEnum):
    PREVIEW = "preview"
    SCHEMA = "schema"
    ROW_COUNT = "row_count"
    DOWNLOAD = "download"
    EXPORT = "export"
    CREATE_FILE_DATASOURCE = "create_file_datasource"
    CREATE_DATABASE_DATASOURCE = "create_database_datasource"
    CREATE_ICEBERG_DATASOURCE = "create_iceberg_datasource"
    INGEST_DATASOURCE = "ingest_datasource"
    DATASOURCE_SCHEMA = "datasource_schema"
    DATASOURCE_COLUMN_STATS = "datasource_column_stats"
    COMPARE_ICEBERG_SNAPSHOTS = "compare_iceberg_snapshots"
    SPAWN_ENGINE = "spawn_engine"
    CONFIGURE_ENGINE = "configure_engine"
    SHUTDOWN_ENGINE = "shutdown_engine"


class ComputeRequestStatus(DataForgeStrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
