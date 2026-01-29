"""Rename columns operation."""

from modules.compute.operations.base import OperationParams, make_handler


class RenameParams(OperationParams):
    mapping: dict[str, str]


RenameHandler = make_handler('rename', RenameParams, lambda lf, p: lf.rename(p.mapping))
