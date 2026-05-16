from __future__ import annotations

from contracts.enums import DataForgeStrEnum


class CodeExportFormat(DataForgeStrEnum):
    POLARS = "polars"
    SQL = "sql"

    @property
    def file_extension(self) -> str:
        match self:
            case CodeExportFormat.POLARS:
                return "py"
            case CodeExportFormat.SQL:
                return "sql"
