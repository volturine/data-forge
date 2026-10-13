from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]

STAGED_NOTIFICATION_PREFIX = "__dataforge_notification_"


def staged_column_name(step_id: str) -> str:
    return f"{STAGED_NOTIFICATION_PREFIX}{step_id.replace('-', '_')}"


def encode_staged_deliveries(deliveries: list[dict[str, object]]) -> str:
    return json.dumps(deliveries, separators=(",", ":"), sort_keys=True)


def extract_staged_deliveries(table: pa.Table) -> tuple[pa.Table, list[dict[str, object]]]:
    staged_columns = [name for name in table.column_names if name.startswith(STAGED_NOTIFICATION_PREFIX)]
    if not staged_columns:
        return table, []
    deliveries: list[dict[str, object]] = []
    for column_name in staged_columns:
        for raw in table[column_name].to_pylist():
            if raw is None:
                continue
            parsed = json.loads(str(raw))
            if not isinstance(parsed, list):
                raise ValueError(f"Staged notification column {column_name} must contain JSON arrays")
            for delivery in parsed:
                if not isinstance(delivery, dict):
                    raise ValueError(f"Staged notification column {column_name} contains an invalid delivery")
                deliveries.append({str(key): value for key, value in delivery.items()})
    return table.drop(staged_columns), deliveries


def strip_staged_preview(data: Mapping[str, object]) -> dict[str, Any]:
    result = dict(data)
    raw_schema = result.get("schema")
    if isinstance(raw_schema, Mapping):
        result["schema"] = {str(key): value for key, value in raw_schema.items() if not str(key).startswith(STAGED_NOTIFICATION_PREFIX)}
    raw_rows = result.get("data")
    if isinstance(raw_rows, list):
        result["data"] = [
            {str(key): value for key, value in row.items() if not str(key).startswith(STAGED_NOTIFICATION_PREFIX)}
            for row in raw_rows
            if isinstance(row, Mapping)
        ]
    return result


def render_template(template: str, context: dict[str, object]) -> str:
    for key, value in context.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template
