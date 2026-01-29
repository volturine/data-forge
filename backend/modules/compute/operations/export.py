"""Export passthrough operation."""

from modules.compute.operations.base import OperationParams, make_handler


class ExportParams(OperationParams):
    format: str = 'csv'
    filename: str = 'export'
    destination: str = 'download'


ExportHandler = make_handler('export', ExportParams, lambda lf, _: lf)
