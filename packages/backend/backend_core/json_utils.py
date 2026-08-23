from copy import deepcopy
from typing import Any


def copy_json_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f'Expected dict, got {type(value).__name__}')
    return deepcopy(value)


def copy_json_object(value: object) -> dict[str, Any] | None:
    return deepcopy(value) if isinstance(value, dict) else None
