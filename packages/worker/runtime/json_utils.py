from typing import Any


def copy_json_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
