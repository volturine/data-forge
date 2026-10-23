"""Analysis API payload builders shared by the analysis test modules."""

import uuid
from typing import Any


def tab_payload(
    datasource_id: str,
    *,
    tab_id: str = 'tab1',
    name: str = 'Source',
    parent_id: str | None = None,
    analysis_tab_id: str | None = None,
    datasource_config: dict[str, object] | None = None,
    result_id: str | None = None,
    filename: str = 'source',
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one pipeline tab; output.result_id is a fresh uuid4 unless given."""
    return {
        'id': tab_id,
        'name': name,
        'parent_id': parent_id,
        'datasource': {
            'id': datasource_id,
            'analysis_tab_id': analysis_tab_id,
            'config': {'branch': 'master'} if datasource_config is None else datasource_config,
        },
        'output': {
            'result_id': result_id or str(uuid.uuid4()),
            'datasource_type': 'iceberg',
            'format': 'parquet',
            'filename': filename,
        },
        'steps': steps or [],
    }
