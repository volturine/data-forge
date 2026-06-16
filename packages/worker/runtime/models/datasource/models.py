from runtime.models.enums import DataForgeStrEnum


class DataSourceCreatedBy(DataForgeStrEnum):
    IMPORT = "import"
    ANALYSIS = "analysis"


class DataSourceTargetKind(DataForgeStrEnum):
    ANALYSIS = "analysis"
    RAW = "raw"
    DATASOURCE = "datasource"
