import json
from datetime import datetime

from core.logging import get_log_writer
from modules.logs.schemas import ClientLogItem


def save_client_logs(items: list[ClientLogItem]) -> int:
    if not items:
        return 0
    writer = get_log_writer()
    payloads = [
        {
            'ts': datetime.utcnow(),
            'event': item.event,
            'action': item.action,
            'page': item.page,
            'target': item.target,
            'form_id': item.form_id,
            'fields_json': json.dumps([field.model_dump() for field in item.fields]),
            'client_id': item.client_id,
            'session_id': item.session_id,
            'meta_json': json.dumps(item.meta) if item.meta else None,
        }
        for item in items
    ]
    writer.write_client_logs(payloads)
    return len(payloads)
